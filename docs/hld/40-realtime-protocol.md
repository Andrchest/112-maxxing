# HLD 40 — Realtime protocol (WebSocket, Redis, reconnect)

Elaborates `docs/hld/00-decisions.md` D8 (commands API and realtime channel), D5 (event sourcing),
D3 (structural visibility) and D9 (voice path) against `docs/SPEC.md` §8, §31, §34, §39. Nothing here
re-decides the frame.

Two realtime planes exist and they never mix (SPEC §34):

| Plane | Carries | Transport | Owner |
|:--|:--|:--|:--|
| **Media** | microphone and caller audio | LiveKit WebRTC (SIP later) | `CallTransport` port, `LiveKitCallTransport` (D9) |
| **Application events** | `SessionEvent` envelopes | this document's WebSocket | backend FastAPI, `SimulationRunner` |

Raw PCM never travels over REST or over this WebSocket (SPEC §34). Application events never travel
over LiveKit data channels: the audit source is PostgreSQL and the fan-out is Redis (SPEC §31).

Companion documents: the REST contract is `docs/hld/openapi.yaml`; every event name, payload key and
per-role visibility is copied from the `EVENT PAYLOAD CATALOG` of `docs/hld/10-domain-model.md`
§10.13 and must stay identical to it.

---

## 40.1 Endpoint and authentication

```
GET /api/v1/ws/sessions/{session_id}?token=<JWT>
Upgrade: websocket
```

- One connection per (session, participant, browser tab). A second connection from the same user is
  allowed and receives the same stream; the server keeps no per-user singleton.
- **Auth** is the same HS256 JWT the REST API uses (D8), passed as the `token` query parameter
  because a browser `WebSocket` constructor cannot set an `Authorization` header. The token is
  validated **before** the upgrade completes. The token is never logged.
- Authorisation on connect, in this order:
  1. token valid and not expired → else close `4401 UNAUTHENTICATED`;
  2. the session exists → else close `4404 NOT_FOUND`;
  3. the user is a participant of the session, or has user role `INSTRUCTOR` / `ADMIN` → else close
     `4403 FORBIDDEN_FOR_ROLE`.
- The connection's **effective realtime role** is fixed at connect time and never renegotiated:
  - a participant assigned to a stage → that stage's `RoleType` (`OPERATOR_112` or `DDS`);
  - a participant of a `FULL_CYCLE_SINGLE_TRAINEE` session assigned to every stage → the `RoleType`
    of the **currently active** `RoleStage`, re-derived on every push, so that the role transition
    changes what the same socket may see without a reconnect;
  - user role `INSTRUCTOR` or `ADMIN` → `INSTRUCTOR` (the instructor console, not a `RoleType`).
- Token expiry during a live session does **not** drop the socket: the session outlives the token and
  dropping it would violate SPEC §39's "never silently reset the simulation". The client refreshes
  its token for REST separately.

### Close codes

| Code | Meaning |
|:--|:--|
| `1000` | normal close (the client navigated away) |
| `1001` | server going away (graceful backend shutdown) |
| `4400` | malformed client frame (not JSON, unknown `type`, missing field) |
| `4401` | `UNAUTHENTICATED` — token missing, malformed or invalid |
| `4403` | `FORBIDDEN_FOR_ROLE` — not a participant and not an instructor |
| `4404` | `NOT_FOUND` — no such session |
| `4409` | resume cursor is ahead of the log (`after_seq_no > last_seq_no`) |
| `4429` | client frame rate limit exceeded (more than 10 frames/s) |

A close is never a state reset. Everything the client needs is re-derivable from
`GET /api/v1/sessions/{session_id}/snapshot` plus a resume (§40.5).

---

## 40.2 Envelope schema

Every server→client message is one JSON object with a `type` discriminator.

### `event` — the only frame that carries simulation data

```json
{
  "type": "event",
  "seq_no": 412,
  "event_type": "CARD_FIELD_CHANGED",
  "timestamp_utc": "2026-09-19T10:04:17.221Z",
  "monotonic_offset_ms": 137221,
  "payload": { "...": "per EVENT_PAYLOAD_CATALOG, after role redaction" },
  "actor_type": "TRAINEE",
  "correlation_id": "0f5a…",
  "redacted_keys": []
}
```

- `seq_no`, `event_type`, `timestamp_utc`, `monotonic_offset_ms`, `payload` are the five fields D8
  mandates; `actor_type`, `correlation_id` and `redacted_keys` are additive and always present.
- `payload` keys are exactly the catalog's `payload_keys` for that `event_type`, minus the keys the
  redaction table of §40.4 removes for this role.
- `redacted_keys` lists what was removed, so the UI can render "скрыто" instead of implying absence.
  It is always `[]` for the `INSTRUCTOR` role.
- The envelope is byte-identical to what `GET /api/v1/sessions/{id}/events` returns
  (`SessionEventEnvelope` in `openapi.yaml`): one schema, two delivery mechanisms.

### `resume_complete`

```json
{ "type": "resume_complete", "replayed_count": 37, "last_seq_no": 412, "live": true }
```

Sent once, after the PostgreSQL replay finishes and before the first live event. `live: true` means
the socket is now tailing Redis.

### `heartbeat`

```json
{ "type": "heartbeat", "server_time_utc": "2026-09-19T10:04:20.000Z", "last_seq_no": 412 }
```

Every 15 seconds when no event was pushed. It is also a cheap gap detector: a client whose
`last_seq_no` is behind the heartbeat's knows it missed something and re-sends `resume`.

### `error`

```json
{ "type": "error", "code": "INVALID_RESUME_CURSOR", "detail": "after_seq_no 900 > last_seq_no 412" }
```

`code` values: `INVALID_FRAME`, `INVALID_RESUME_CURSOR`, `RATE_LIMITED`, `REPLAY_FAILED`. An `error`
frame does not necessarily close the socket; a close always carries one of §40.1's codes.

### Client→server frames

The client sends **one** frame type (D8):

```json
{ "type": "resume", "after_seq_no": 412 }
```

`after_seq_no` is exclusive and may be `0` (replay everything the role may see). Any other `type`,
any non-JSON payload, or more than 10 frames per second closes the socket (`4400` / `4429`). **The
client can never send a command over this socket**: commands are REST (SPEC §34, D12) so that every
state change passes the same authorisation and Unit-of-Work path.

---

## 40.3 Resume, replay and ordering guarantees

### The mechanism

1. On connect the server sends nothing until it receives `resume`. (A client that wants only live
   events sends `{"type":"resume","after_seq_no": <last_seq_no from the REST snapshot>}`.)
2. The server subscribes to the Redis channel `session:{session_id}:events` **first** and buffers
   incoming messages in memory.
3. It then reads `session_events WHERE session_id = ? AND seq_no > after_seq_no ORDER BY seq_no`
   from PostgreSQL in pages, filters each row by role (§40.4) and pushes it.
4. It drains the buffer, discarding any buffered message whose `seq_no` was already covered by the
   PostgreSQL read, and sends `resume_complete`.
5. It then tails Redis live.

Subscribing before reading is what makes the handover lossless: an event appended during step 3
arrives on the buffer, not into a gap.

### Guarantees

| Guarantee | How it holds |
|:--|:--|
| **Total order per session** | `seq_no` is allocated under a row lock on `simulation_sessions.next_seq_no` with `SELECT … FOR UPDATE` in the same transaction as the insert (D5). Several processes (backend, voice-agent) append safely and no two events share a `seq_no`. |
| **No gaps** | `UNIQUE(session_id, seq_no)` plus dense allocation. A client that sees `seq_no` jump re-sends `resume` from its last contiguous value. |
| **At-least-once delivery** | A duplicate is possible at the replay/live seam (an event both read from PostgreSQL and buffered from Redis). The server de-duplicates by `seq_no`; clients must additionally treat `seq_no` as idempotent, because a reconnect replays. |
| **Publish-after-commit** | Envelopes are published to Redis only **after** the Unit of Work commits (D5). A subscriber therefore never sees an event that a later PostgreSQL read would not return. |
| **Replay equals live** | Both paths build the envelope from the same `session_events` row through the same role filter. A replayed stream and a live stream are indistinguishable except for timing. |
| **PostgreSQL is authoritative** | Redis is a fan-out bus only. If Redis is flushed, restarted or lost entirely, every client recovers completely by resuming from PostgreSQL (SPEC §31). |

`monotonic_offset_ms` is ms since `SESSION_STARTED` from the injected `Clock` port (D5); it is
monotonic per session and survives restarts because sim time is recomputed from the persisted
`started_at` plus paused intervals (D7).

### Replay bounds

A resume replays at most `WS_REPLAY_MAX_EVENTS` (default 5000) rows per page, pausing between pages
so a long session does not block the event loop. There is no upper bound on total replayed events: a
client that was away for the whole session gets the whole session.

---

## 40.4 Per-event-type visibility and payload redaction

The authority is `DataVisibilityPolicy.visible_event_types` per `RoleModule`
(`10-domain-model.md` §10.9) and the **Visible to** column of the `EVENT PAYLOAD CATALOG` (§10.13).
This table copies that catalog; it is a whitelist, never a blacklist (D3). An event type absent from
a role's set is not merely unrendered — the push loop never serialises it for that connection.

Legend: `✔` push in full · `—` never pushed to this role · `▲` pushed with the payload redaction
named in the last column · `◆` pushed only when `SessionPolicy.show_asr_partials` is true for the
session mode (`ASSESSMENT` sets it false, §10.10).

### SPEC §8 event types (28)

| # | Event type | OPERATOR_112 | DDS | INSTRUCTOR | Redaction for trainee roles |
|:--|:--|:--:|:--:|:--:|:--|
| 1 | `SESSION_CREATED` | — | — | ✔ | contains `session_seed`, `time_scale` (additive, E5) and `scenario_version_id`; instructor-only |
| 2 | `SESSION_STARTED` | ✔ | ✔ | ✔ | — |
| 3 | `ROLE_STAGE_STARTED` | ✔ | ✔ | ✔ | — |
| 4 | `CALL_RINGING` | ✔ | — | ✔ | — |
| 5 | `CALL_ANSWERED` | ✔ | — | ✔ | — |
| 6 | `USER_SPEECH_STARTED` | ✔ | — | ✔ | — |
| 7 | `USER_SPEECH_ENDED` | ✔ | — | ✔ | — |
| 8 | `ASR_PARTIAL` | ◆ | — | ✔ | `vad_provider`/`asr_model` kept; nothing hidden — the whole event is withheld in `ASSESSMENT` |
| 9 | `ASR_FINAL` | ▲ | — | ✔ | drop `asr_provider`, `asr_model`, `confidence`: provider internals are not trainee data |
| 10 | `CALLER_RESPONSE_PLANNED` | — | — | ✔ | names `allowed_fact_ids`, `unavailable_fact_ids`, `withheld_count` — gate internals (D3) |
| 11 | `CALLER_RESPONSE_GENERATED` | — | — | ✔ | model internals and the validator verdict |
| 12 | `CALLER_TTS_STARTED` | ▲ | — | ✔ | trainee receives only `{call_id, turn_index, at_offset_ms}` — enough to animate the phone widget; `text_sent_to_tts`, `tts_provider`, `tts_model`, `voice_id`, `voice_id_native` dropped (the last is a caller detail, same rule as `planned_text` on row 14, E20-G) |
| 13 | `CALLER_TTS_ENDED` | ▲ | — | ✔ | trainee receives only `{call_id, turn_index, at_offset_ms, completed}`; `total_audio_ms` and `audio_segment_id` dropped |
| 14 | `CALLER_UTTERANCE_INTERRUPTED` | ▲ | — | ✔ | drop `planned_text` — what the caller *would* have said is unrevealed information (SPEC §21); keep `delivered_text`, `delivered_audio_ms`, `cutoff_latency_ms` |
| 15 | `CARD_FIELD_CHANGED` | ✔ | — | ✔ | never pushed to DDS: the live card is outside `DDSModule`'s sources (SPEC §10) |
| 16 | `SERVICE_SELECTED` | ✔ | — | ✔ | — |
| 17 | `HANDOFF_CREATED` | ✔ | — | ✔ | DDS learns of the handoff through `HANDOFF_RECEIVED`, whose payload is snapshot-scoped |
| 18 | `HANDOFF_RECEIVED` | — | ✔ | ✔ | — |
| 19 | `DDS_ACKNOWLEDGED` | — | ✔ | ✔ | — |
| 20 | `RESOURCE_SELECTED` | — | ✔ | ✔ | — |
| 21 | `RESOURCE_DISPATCHED` | — | ✔ | ✔ | — |
| 22 | `RESOURCE_STATUS_CHANGED` | — | ✔ | ▲/✔ | DDS payload drops `source_world_event_id` — which world event moved a unit is engine internals |
| 23 | `WORLD_EVENT_TRIGGERED` | — | — | ✔ | the world engine is hidden from both trainees (SPEC §12, D3) |
| 24 | `ROLE_STAGE_COMPLETED` | ✔ | ✔ | ✔ | — |
| 25 | `SCORING_RULE_EVALUATED` | — | — | ✔ | scores reach the trainee through the report, after release (D11) |
| 26 | `SESSION_COMPLETED` | ✔ | ✔ | ✔ | — |
| 27 | `MODEL_FALLBACK_USED` | — | — | ✔ | model internals |
| 28 | `MODEL_ERROR` | — | — | ✔ | model internals |

### Additive event types (D5, 21)

| # | Event type | OPERATOR_112 | DDS | INSTRUCTOR | Redaction for trainee roles |
|:--|:--|:--:|:--:|:--:|:--|
| 29 | `SESSION_ABORTED` | ✔ | ✔ | ✔ | — |
| 30 | `STAGE_STATE_CHANGED` | ▲ | ▲ | ✔ | pushed only when `role_type` equals the connection's role ("the stage's own role", §10.13); otherwise not pushed |
| 31 | `ROLE_TRANSITION_STARTED` | ✔ | ✔ | ✔ | — |
| 32 | `ROLE_TRANSITION_COMPLETED` | ✔ | ✔ | ✔ | — |
| 33 | `SERVICE_DESELECTED` | ✔ | — | ✔ | — |
| 34 | `RESOURCE_DESELECTED` | — | ✔ | ✔ | — |
| 35 | `DDS_STATUS_UPDATE_SENT` | — | ✔ | ✔ | — |
| 36 | `DDS_INCIDENT_CLOSED` | — | ✔ | ✔ | — |
| 37 | `NOTIFICATION_CREATED` | ▲ | ▲ | ✔ | pushed only when `audience_role` equals the connection's role; drop `source_world_event_id` for trainees |
| 38 | `NOTIFICATION_ACKNOWLEDGED` | ▲ | ▲ | ✔ | pushed only when `audience_role` equals the connection's role (the key is additive, E9 — §10.13) |
| 39 | `RADIO_MESSAGE_CREATED` | ▲ | ▲ | ✔ | pushed only when `to_role` equals the connection's role; drop `source_world_event_id` for trainees |
| 40 | `WORLD_TRUTH_MUTATED` | — | — | ✔ | **never** to a trainee — this is the WorldTruth boundary (D3, D8, SPEC §42 tests 1 and 3) |
| 41 | `CALLER_BELIEF_MUTATED` | — | — | ✔ | **never** to a trainee — it would disclose what the caller knows without asking |
| 42 | `CALLER_EMOTION_CHANGED` | — | — | ✔ | the trainee perceives emotion through the voice, not through a state feed |
| 43 | `CALL_ENDED` | ✔ | — | ✔ | — |
| 44 | `DIALOGUE_INTERPRETED` | — | — | ✔ | interpreter internals |
| 45 | `FACT_GATE_EVALUATED` | — | — | ✔ | **never** to a trainee — gate internals name withheld facts (D3, D10) |
| 46 | `FACTS_DELIVERED` | — | — | ✔ | naming which facts "counted" would hand the trainee the scoring key (D10, §42 test 10) |
| 47 | `TRANSPORT_DISCONNECTED` | ✔ | — | ✔ | — |
| 48 | `TRANSPORT_RECONNECTED` | ✔ | — | ✔ | — |
| 49 | `INFERENCE_HEALTH_CHANGED` | — | — | ✔ | operational health belongs to the instructor console (SPEC §37) |

Consistency rule for implementers: this table and `EVENT_PAYLOAD_CATALOG` are one fact expressed
twice. A unit test iterates `EventType` and asserts that every member appears in both, with the same
role set — a new event type that is added to one and not the other must fail the gate, not default to
visible.

### How redaction is applied

Redaction happens in exactly one place, `DataVisibilityPolicy` plus a per-event-type key whitelist in
`backend/app/application/realtime/redaction.py`, applied to the envelope **before** it reaches the
socket writer. It is not a frontend concern and not a serialiser flag: a field a role may not see is
absent from the bytes on the wire (D3). The same function serves
`GET /api/v1/sessions/{id}/events` and the report timeline, so the three read paths cannot drift.

---

## 40.5 Reconnect behaviour

### Browser refresh (SPEC §39, §42 test 13)

1. The page loads with no in-memory state; nothing the simulation needs ever lived only in the
   browser (D8).
2. `GET /api/v1/sessions/{session_id}/snapshot` returns the active stage, its stage state,
   `available_actions`, the role's card or work item, the call state and `last_seq_no`.
3. The client opens the WebSocket and sends `{"type":"resume","after_seq_no": last_seq_no}`.
4. The server replays anything appended between the snapshot read and the subscribe, then goes live.
5. If the active stage is `OPERATOR_112` and the call phase is `CONNECTED`, the client calls
   `POST /api/v1/sessions/{session_id}/voice-token` and rejoins the LiveKit room. The voice-agent
   never left it, so the caller's state, emotion and revealed facts are untouched.

The simulation clock does not move backwards: `SimulationRunner` re-adopts ACTIVE sessions on backend
start and derives sim time from the persisted `started_at` plus paused intervals (D7). A refresh
costs the trainee the wall-clock time of the refresh, exactly as a real console would.

### Temporary LiveKit drop (SPEC §39)

The media plane and the event plane fail independently, and the domain follows neither:

1. The transport's `events()` stream reports the participant's disconnect. The voice-agent appends
   `TRANSPORT_DISCONNECTED {call_id, participant_identity, reason, at_offset_ms}`.
2. **Nothing in the domain changes.** The call stays `CONNECTED`, the stage stays in its state, the
   card keeps its values, sim time keeps running. Audio produced during the gap is simply not heard:
   a dropped trainee missed the caller's words, which is a realistic consequence, not a state reset
   (SPEC §39, §42 test 14).
3. An in-flight caller response is cancelled if the drop lasts past `TRANSPORT_GRACE_MS` (default
   2000): the backend publishes `voice:cancel:{session_id}` and the pipeline stops generating rather
   than speaking to nobody.
4. On rejoin — the LiveKit client SDK reconnects by itself, or the user refreshes and mints a new
   token — the agent appends `TRANSPORT_RECONNECTED {call_id, participant_identity, downtime_ms,
   at_offset_ms}`.
5. Both events are pushed to `OPERATOR_112` and `INSTRUCTOR`, so the phone widget can show
   "соединение восстановлено" and the instructor sees the gap in the timeline.

If the **event** WebSocket drops while LiveKit stays up, the client reconnects with exponential
backoff (0.5 s, 1 s, 2 s, 4 s, capped at 10 s, with jitter) and resumes from its last `seq_no`. The
call continues throughout: audio does not depend on the event socket.

### Backend restart

Sockets close with `1001`. Clients reconnect on the same backoff and resume. On start the backend
re-adopts every ACTIVE session, re-acquires `lock:session:{id}:runner` and resumes ticking. No event
is lost, because every event was committed to PostgreSQL before it was ever published.

---

## 40.6 Redis inventory

**No key or channel in this table is a source of truth.** Redis carries pub/sub, transient realtime
state, locks, cancellation signals and LiveKit-related state only; PostgreSQL remains authoritative
and the system must survive a complete Redis flush with no loss of simulation state (SPEC §31, D5).
Everything below is either re-derivable from PostgreSQL or is a signal whose loss degrades liveness,
never correctness. This is the complete inventory: any key not listed here does not exist.

Placeholder note: `{session_id}` here and `{id}` in D5's `session:{id}:events` and D7's
`lock:session:{id}:runner` are the same placeholder — the session UUID. There is one key space, not
two; implementers substitute the UUID and never emit the braces.

### Pub/sub channels

| Channel | Payload | Publisher | Subscribers | Purpose / loss behaviour |
|:--|:--|:--|:--|:--|
| `session:{session_id}:events` | one JSON envelope per event: `{seq_no, event_type, timestamp_utc, monotonic_offset_ms, actor_type, actor_id, correlation_id, payload}` — **unredacted**; each socket applies its own role filter (§40.4) | backend and voice-agent, **after** the Unit of Work commits (D5) | every WebSocket handler for that session; the `SimulationRunner` tick loop | Live fan-out. Loss ⇒ clients fall back to replay from PostgreSQL on the next heartbeat gap or resume. |
| `voice:join` | `{session_id, room, call_id}` | backend, at `CALL_RINGING` (D9) | the voice-agent process | Tells the agent which room to join. Loss ⇒ the agent never joins; the backend re-publishes every `VOICE_JOIN_RETRY_MS` (default 2000) **while the call phase is `RINGING` or `CONNECTED` and no agent has joined it**, so the signal is self-healing. What ends the retry is the first event the voice agent itself appended for that `call_id` (it appends nothing at the moment it joins, so its first turn/transport event is the ack), or the call reaching `ENDED` — never the trainee's answer: a trainee who answers before the agent has arrived would otherwise leave the call `CONNECTED` with an empty room and no further signal (E20 R2, E19-E3). Re-publishing at an agent that is already in the room is a no-op: `VoiceAgent._on_join` returns early for a session it already serves. |
| `voice:cancel:{session_id}` | `{call_id, reason: "HANGUP" \| "ABORT" \| "TRANSPORT_LOST", at_offset_ms}` | backend, on `endCall`, `abortSession` or a transport grace timeout | the voice-agent's `_control` task (`50-voice-pipeline.md` §6) | Cross-process barge-in/cancellation signal (D9). Loss ⇒ the caller finishes one utterance into a closed call; no state is corrupted. |
| `voice:health` | `{service, from, to, detail, at}` | voice-agent, on every health transition | backend health aggregator | Turned into `INFERENCE_HEALTH_CHANGED` on every ACTIVE session (`60-inference-ops.md` §4.3). Loss ⇒ the next `voice:health:{service}` heartbeat re-establishes the state within 5 s. |

Channel naming is fixed: `session:{session_id}:events` uses the session UUID in canonical lowercase
hyphenated form.

### Keys

| Key | Type | Value | TTL | Writer | Readers | Loss behaviour |
|:--|:--|:--|:--|:--|:--|:--|
| `lock:session:{session_id}:runner` | string | the owning backend instance id | `SIM_RUNNER_LOCK_TTL_S` (default 30), refreshed every 10 s | backend `SimulationRunner` | every backend instance | Guarantees a single runner per session (D7). Loss ⇒ another instance may adopt the session; the runner is idempotent per tick because effects are derived from persisted state, and duplicate appends are prevented by the `seq_no` row lock. |
| `voice:health:{service}` for `service ∈ {llm, asr, tts, vad}` | string (JSON) | `{state, profile, provider, model_version, updated_at, detail, warmup_ms}` | `EX 15`, heartbeat every 5 s | voice-agent | backend `/api/v1/health/ready` | **A missing key is `NOT_READY`, never `READY`** (`60-inference-ops.md` §4.3) — a crashed voice-agent is visible with no extra protocol. Loss ⇒ readiness degrades to NOT_READY and sessions cannot start; correctness is preserved. |
| `voice:health:fatal` | string (JSON) | `{service, detail, at}` | none (deliberately never expires) | voice-agent, on `FATAL` | backend health aggregator | So a restart loop cannot make a fatal condition look transient. Cleared only by `POST /api/v1/admin/inference/clear-fatal` or a clean warm-up after a manual restart. Loss ⇒ a fatal condition is forgotten and re-detected on the next inference attempt. |
| `session:{session_id}:last_seq_no` | string (integer) | the highest published `seq_no` | `SESSION_CACHE_TTL_S` (default 3600), refreshed on publish | backend and voice-agent publishers | WebSocket handlers, heartbeat frames | A read cache so a heartbeat does not hit PostgreSQL. Loss ⇒ the handler reads `MAX(seq_no)` from PostgreSQL instead. |
| `session:{session_id}:call_state` | string (JSON) | `{call_id, room_name, phase, caller_speaking, updated_at}` | `SESSION_CACHE_TTL_S` (default 3600) | backend call use cases, voice-agent TTS boundary | WebSocket handlers, `getSessionSnapshot` | Transient realtime state for the phone widget (SPEC §31). Loss ⇒ rebuilt from `CALL_RINGING` / `CALL_ANSWERED` / `CALL_ENDED` / `CALLER_TTS_*` in `session_events`. |
| `idempotency:{user_id}:{client_command_id}` | string (JSON) | the first response body of that command | `IDEMPOTENCY_TTL_S` (default 300) | backend command handlers | backend command handlers | Makes a retried `setCardField` a no-op rather than a second revision. Loss ⇒ a retried command is re-evaluated; setting a field to its current value is already a no-op, so the worst case is a duplicate revision of a genuinely changed value. |
| `preflight:probe` | string | arbitrary | deleted immediately | the preflight script | the preflight script | SPEC §38 Redis check (`60-inference-ops.md` §8, row 8). Not runtime state. |

LiveKit's own Redis usage (room state, when the SFU is configured with a Redis backend) lives under
LiveKit's own key prefixes inside the same instance. The simulator neither reads nor writes those
keys, and treats them as opaque infrastructure — they too are not a source of truth for anything in
`docs/SPEC.md`.

### The invariant, stated once

> Redis holds nothing that cannot be rebuilt from PostgreSQL, and nothing whose loss changes a
> score, a card value, a stage state, a snapshot or an event. A `FLUSHALL` against a running
> simulation costs: live fan-out until the next resume, the runner lock until the next acquisition,
> readiness until the next heartbeat, and two read caches. It costs no simulation state.
> (SPEC §31, D5.)

This is testable and is asserted in `backend/tests/integration`: flush Redis mid-session, resume, and
compare the client's reconstructed state with the pre-flush state.

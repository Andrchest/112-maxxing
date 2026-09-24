# HLD 80 — I3 H2: telephony (software SIP server, ДДС calls, the AI voice by category)

Elaborates `docs/hld/00-decisions.md` D22–D25 (appended by this epic, H2) against the organizer
material under `requirements/` and the tree as it stands on 2026-09-24. The design follows the
read-only H2 analysis (`/tmp/teamwork-112-maxxing/reports/i3/H2-analysis.md`), which the manager
accepted in full, plus the manager's binding decisions on it. Every place where this document departs
from the analysis's wording is listed in §80.13 with the reason.

Nothing here edits HLD 10/20/30/40/50/60 or `openapi.yaml`. Those documents are parsed by tests
(`test_dds_tables_match_the_hld.py`, `test_visibility_matches_protocol_table.py`,
`tests/api/test_contract.py`, …); **each implementing epic (E6a–E6f) updates them together with its
code**, copying identifiers from this file literally. The contract delta is
`docs/hld/contracts/i3-telephony-openapi-delta.yaml` (items tagged `x-epic: E6b` … `E6e`); the schemes
are `docs/hld/puml/i3-telephony-*.puml`; the epic list is the "I3 TBD epics" section of
`docs/hld/90-tbd-epics.md` (rows E6a–E6f).

Language rule unchanged (header of 00): identifiers English; trainee-facing labels Russian. No
credential appears in this document: the deployment SIP password is `SIM_SIP_PASSWORD` from the
environment, written here as [credential redacted].

## 80.0 The five forks in one table

| Fork | Decision | Decision entry | Section |
|:--|:--|:--|:--|
| F1 | Our own **Python SIP/RTP gateway** (registrar + UAS/UAC + RTP G.711) that registers softphones and bridges each call into the call's LiveKit room as one more participant; own process / compose service `sip-gateway` under `profiles: ["sip"]`; ports 5060 udp+tcp, RTP 20000–20199/udp, health 8114. `SipCallTransport` stays the reserved plan B; Asterisk-AudioSocket is the named fallback. | D22 | §80.2 |
| F2 | An additive **`DdsCall`** keyed by `call_id` with `DDS_CALL_TRANSITIONS`, kinds `SERVICE_HEAD` / `CLAIMANT` / `OPERATOR_112`, the endpoint recorded on the event; events `DDS_CALL_STARTED / ANSWERED / ENDED / STATUS_PROPOSED / ASSERTION`; the per-turn pipeline events reused under `call_id`; the agent keys `_calls` by `(session_id, call_id)`; a claimant call reuses the frozen caller pipeline unchanged. | D23 | §80.3, §80.6 |
| F3 | Persona from the sha-pinned `reference/personas/v1.yaml`, resolved by catalog category (`code` > `kind`); the service head knows only the script plus the snapshot (INV 1/2/3/14 held by constructor and signature tests); template responder by default, LLM paraphrase optional (`Settings.responder_dialogue`); under `ON` the trainee's own leg's script is voiced (heard), not applied, and a heard status is proposed and confirmed by the trainee. | D24 | §80.4 |
| F4 | `dds_brigade_call: ON` = "the ДДС workstation has a phone" (memo mode only, R41; persona override R42). Browser vs SIP is an endpoint per call, not a switch. Default stays `OFF` (C7). | D25 | §80.5 |
| F5 | Gate: a headless Python UA proves REGISTER / INVITE / RTP / BYE against the in-process gateway, and the call use cases run on fakes (GPU-free, no network). Manual: our own `tools/softphone --headset` (sox). `benchmarks/benchmark_voip.py` measures one-way delay (ТЗ ¶161 ≤ 150 ms) and a 1/5/10/20/40 concurrent sweep. | D22 (verification clause) | §80.8 |

## 80.1 Facts the design rests on

**Machine (read-only inspection, 2026-09-24; analysis §1.1).** No SIP server binary or image
(asterisk, freeswitch, kamailio, opensips, rtpengine, `livekit/sip` — none), no CLI softphone, no Python
SIP/RTP library in `.venv` (`pjsua2`, `aiortc`, `pyVoIP`, `aiosip`, `av` all absent); apt lists carry
candidates but the apt cache holds none, so every one would be a download over the slow proxy. Present:
`livekit` 1.1.19 rtc SDK in `.venv`, stdlib `audioop` (Python 3.12: G.711 A/μ-law, `ratecv`), `numpy`,
`/usr/bin/sox`, `livekit-client` in `frontend/node_modules`. Piper has only `ru_RU-irina-medium`
(female) on disk; Qwen3-TTS CustomVoice speakers are reached through `tts.voice_map`
(`backend/app/config/profiles/DEV_3060TI.yaml`). Ports 5060/udp+tcp, 20000–20999/udp and 8114 were free;
none of them is an owner port (8000, 8001, 8011, 8012, 5000) or an existing service port (agent 8113,
TTS 8112, LiveKit 7880–7882, test 55432/56379).

**Code seams (verified).**

- `CallTransport` (`backend/app/application/ports/call_transport.py`) — `LiveKitCallTransport` is the
  only `livekit` importer; `backend/tools/check_imports.py` allows `livekit` (not `livekit.agents`)
  anywhere under `workers/voice_agent/voice_agent/transport/`, so a new `transport/sip/` package needs
  no boundary change. `transport/sip_transport.py` refuses every method and stays so (plan B).
- The 112 call is singular per session: `session:{id}:call_state`, `CallStateView`,
  `VoiceAgent._calls: dict[SessionId, Task]` (`workers/voice_agent/voice_agent/main.py`).
  `RecordingPaths.for_call(session_id, call_id)` already keys by call. `voice:join {session_id, room,
  call_id}` is published after the `CALL_RINGING` commit (`application/operator/call_flow.py`) and
  re-published every `VOICE_JOIN_RETRY_MS`; `voice:cancel:{session_id}` carries `call_id`.
- **No token travels over Redis or to the gateway**: the agent mints its own room token locally with
  the backend's `LiveKitTokenService` (`voice_agent/wiring.py::build_agent_token`, E19-E3). The gateway,
  which lives in the same `workers/voice_agent` package, does the same.
- `guard_call_ended` gates the 112 stage's completion, and in MULTI_TRAINEE the DDS stage can be live
  while the 112 call is still connected — two concurrent calls per session are possible.
- E5b: `domain/dds/responders.py` (`ScriptedStep {after_ms, status, comment_ru, order_number}`,
  `due_scripted_steps` pure and due-offset stamped, `assign_responders`, `plays_leg`); the script reaches
  only stage automation through the probe `app.application.simulation.responder_scripts` (INV 3).
  `IMPLEMENTED_VARIANT_VALUES["dds_brigade_call"] = {OFF}` (`domain/session/variants.py`).
- Catalog: every `phone` in `reference/services/v1.yaml` is `null`; `code` is `101…104` for the four
  emergency services; `kind ∈ {CITY, DISTRICT, PREFECTURE, DEPARTMENT}` (70 §70.6.3). The claimant's
  number is the snapshot's `caller.phone`.
- The per-turn pipeline events (`USER_SPEECH_*`, `ASR_*`, `CALLER_TTS_*`, `CALLER_UTTERANCE_INTERRUPTED`,
  `DIALOGUE_INTERPRETED`, `FACT_GATE_EVALUATED`, `FACTS_DELIVERED`, `TRANSPORT_*`) already carry
  `call_id` (`domain/events/catalog.py`), but their visibility (HLD 40 §40.4) is by event type:
  OPERATOR_112 + INSTRUCTOR, never DDS. `FACT_OBTAINED` (`domain/scoring/evaluators/fact_obtained.py`)
  counts every `FACTS_DELIVERED` of the session, whatever call it came from. Both matter for §80.6.

**Requirements carried.** ТЗ ¶302 local SIP server (REQ-2249), ¶161 VoIP delay ≤ 150 ms (REQ-2139), ¶175
headset / software IP-phone emulation (REQ-2150), ¶199 admin configures telephony (REQ-2168); «аппаратный
телефон не нужен» (REQ-4004), «imitation in the DB is enough for MVP, real virtual telephony would be
great» (REQ-1025); ДДС→service heads over IP telephony (REQ-1028); brigade push/pull by phone
(REQ-1038, REQ-5918 «минуя 112»); ДДС→claimant, number from the card, no card number spoken
(REQ-5917/5919/5920); ДДС→112 script (REQ-5332); «телефон не работает либо не отвечают» (REQ-5325);
male/female voices by category (REQ-4041).

## 80.2 F1 — The SIP gateway

### 80.2.1 Components (`workers/voice_agent/voice_agent/transport/sip/`, new; E6a)

| Module | Responsibility |
|:--|:--|
| `message.py` | RFC 3261 subset: parse / serialise requests and responses; `Via` with `rport`, `branch`, tags, `CSeq`, `Contact`, `Expires`, `Content-Length`; Digest challenge/response (MD5, `realm = SIM_SIP_REALM`, `qop=auth`); SDP offer/answer, audio m-line only. A malformed message is answered `400` and never raises out of the listener. |
| `registrar.py` | In-memory bindings `{aor → (contact, transport, expires_at)}`; `REGISTER → 401 → REGISTER(Digest) → 200`, `Expires: 0` unbinds, wrong password `403`. Credential: any username with the deployment password `SIM_SIP_PASSWORD` ([credential redacted]) in E6a; E6e checks the username against `users.username` at dial time and may switch to per-user HA1 (§80.7, `0015`). E6e mirrors each live binding to Redis (§80.3.7). |
| `dialog.py` | UAS: `INVITE → 100 / 180 / 200`, `ACK`, `BYE`, `CANCEL`, re-INVITE answered with the same SDP, `OPTIONS`. UAC: `INVITE` to a registered contact (click-to-call, inbound brigade call), `BYE`. Dialog state keyed by SIP `Call-ID` + tags, mapped to at most one `DdsCall.call_id`. |
| `rtp.py` | RTP send/receive; PT 8 (PCMA) preferred, PT 0 (PCMU) accepted, PT 101 `telephone-event` ignored; ptime 20 ms; jitter buffer `SIM_SIP_JITTER_MS` (default 40); `audioop.alaw2lin / ulaw2lin ↔ lin2alaw / lin2ulaw`, `audioop.ratecv` 8 kHz ↔ 48 kHz; RTP port pair allocated from `SIM_SIP_RTP_PORT_RANGE`. |
| `bridge.py` | One SIP dialog ↔ one room participant behind a `RoomPort`: `FakeRoomBridge` (gate: loops audio back or records it) and `LiveKitRoomBridge` (rtc SDK: publishes the softphone's audio as its microphone track, plays the first remote audio track back as RTP). The gateway's room identity is `sip-{call_id}`; its token is minted locally (§80.1). |
| `gateway.py` | The process: UDP + TCP listeners on `SIM_SIP_PORT`; dial handling (`999` = gateway-local echo; anything else → `POST /api/v1/telephony/dial` from E6e, `404 Not Found` before); health `GET /health` on `127.0.0.1:SIM_SIP_GATEWAY_HTTP_PORT`; a `BYE` to every live dialog on SIGTERM. From E6e it also subscribes to `voice:join` (acts on `endpoint: SIP` only), `voice:cancel:{session_id}` and `session:{session_id}:events` for the sessions it bridges (§80.2.3). |
| `softphone.py` | The headless UA (tests, load generator, latency probe). CLI `python -m voice_agent.tools.softphone` (`workers/voice_agent/voice_agent/tools/softphone.py`): `--register <user> --dial <number>`, `--headset` bench-only mode through `sox rec -q -r 8000 -c 1 -t raw -` → RTP and RTP → `play`. |

Entry point `python -m voice_agent.sip_gateway`. Compose: an additive service `sip-gateway` under
`profiles: ["sip"]` (a plain `docker compose up` stays SPEC §36's seven services + `tts-qwen3`),
publishing `5060/udp`, `5060/tcp` and `20000-20199/udp` on the host, reaching `livekit:7880`, the backend
and Redis internally, advertising `SIM_SIP_MEDIA_IP` (the host LAN address) in SDP so a softphone on
another workstation can send RTP. `make compose-check` renders the profile.

Settings (all `SIM_`-prefixed, `backend/app/config/settings.py`): `sip_port = 5060`,
`sip_rtp_port_range = "20000-20199"` (100 concurrent calls at 2 ports each), `sip_gateway_http_port =
8114`, `sip_realm`, `sip_password` (env only, never committed), `sip_media_ip`, `sip_jitter_ms = 40`,
`sip_gateway_secret` (E6e: the gateway's service credential towards the backend; env only),
`telephony_endpoints = "browser"` (`"browser,sip"` when the gateway is deployed), `responder_dialogue =
"template"` (§80.4.3).

### 80.2.2 How the gateway joins the existing media plane

The gateway is **another room participant**, exactly like the browser. Every call — the 112 caller, a
brigade head, the claimant, the AI 112 operator; browser or softphone — is one LiveKit room. The agent's
`LiveKitCallTransport` is unchanged: it subscribes to the first remote audio track of the room, which is
the gateway's for a SIP-endpoint call and the browser's otherwise. The recorder, the benchmarks and the
phone widget keep one code path. SPEC §15's ladder (WebRTC → LiveKit SIP → PSTN) is preserved: the day a
`livekit/sip` image is present it can replace `bridge.py` + `dialog.py` for *trunk* calls while the
registrar keeps serving softphones.

### 80.2.3 SIP flows

(Sequence: `puml/i3-telephony-sequence-sip-register-invite.puml`.)

1. **Register.** `REGISTER sip:<realm>` → `401` with a nonce → `REGISTER` with Digest → `200`, binding
   stored until `Expires`; refreshed by the softphone. E6e writes `sip:binding:{username}` with the same
   TTL (§80.3.7).
2. **Softphone dials (E6e).** `INVITE sip:101@<realm>` → `100 Trying` → the gateway calls `POST
   /api/v1/telephony/dial {sip_user, dialed, sip_call_id}` with `SIM_SIP_GATEWAY_SECRET` → the backend
   resolves the dial plan and the session (§80.3.5), appends `DDS_CALL_STARTED {endpoint: SIP}` and
   returns `{call_id, session_id, room}` → the gateway sends `180 Ringing`, allocates RTP, joins `room`
   as `sip-{call_id}`, reports `POST /api/v1/telephony/calls/{call_id}/leg {state: UP}` → the backend
   fires `ring` (transport ready) and publishes `voice:join` → the agent joins → on
   `DDS_CALL_ANSWERED` (read from `session:{session_id}:events`) the gateway sends `200 OK` with its SDP
   answer → `ACK` → RTP both ways. Unknown number / no eligible session: the dial endpoint answers `404
   DIAL_NUMBER_UNKNOWN` / `409 NO_ACTIVE_DDS_SESSION` and the gateway maps them to SIP `404` / `480`.
3. **Click-to-call to a softphone (E6e).** The trainee presses «Позвонить старшему»; the trainee's user
   has a live binding, so the call is `endpoint: SIP`; the backend publishes `voice:join` with the
   additive keys `endpoint: SIP, sip_user`. The gateway (UAC) `INVITE`s the binding's contact; on the
   softphone's `200` it joins the room and reports `leg {state: UP}`; the call proceeds as in 2. A
   softphone that does not answer within 30 s ⇒ `leg {state: FAILED, sip_status}` ⇒ `hang_up` by SYSTEM,
   `end_reason: ABORT`.
4. **Hang-up.** `BYE` from the softphone ⇒ `leg {state: DOWN}` ⇒ `hang_up` by TRAINEE. A hang-up from
   the browser or by the backend ⇒ `voice:cancel:{session_id} {call_id, reason}` ⇒ the agent leaves and
   the gateway sends `BYE`. `CANCEL` before `200` ⇒ `DOWN`.
5. **Inbound brigade call to a softphone (E6c/E6e).** A `report: CALL_IN` step starts an `INBOUND`
   `DdsCall`; with a binding the gateway rings the softphone (UAC); answering it is the trainee's
   `answer`.
6. **Echo `999` (E6a).** Handled inside the gateway, no backend, no room: the RTP payload is sent back.
   It is the interop and latency probe.
7. **INVITE authentication (E6e manager decision 1, D27).** One setting, `SIM_SIP_INVITE_AUTH`. In
   both modes an INVITE is accepted only from a user with a live registration (`403` otherwise).
   `challenge` (the default): every INVITE — and every in-dialog re-INVITE — is answered `407 Proxy
   Authentication Required` with a fresh nonce (the registrar's nonce table); the retried request
   must carry a valid `Proxy-Authorization` Digest for the **same username as the From /
   registration**, else `403` (an expired nonce is challenged again with `stale=true`). Reason: the
   dial plan trusts the SIP username to pick the trainee's session, and source-address trust on UDP
   is spoofable. `registered_only`: E6a's behaviour (the registration's Digest is the only check).
   The headless UA and `tools/softphone` answer the `407` themselves.
8. **Who may register (E6e manager decisions 2 and 3, D27).** A REGISTER's username must be an active
   `users.username` — an unknown or retired one is `403`, asked of the backend
   (`GET /api/v1/telephony/sip-credentials/{username}`: `403` unknown, `404` no own password, `200`
   the HA1). A user with `users.sip_ha1` (migration `0015`, set by `python -m
   app.tools.set_sip_password`) is checked against that HA1, everyone else against the deployment
   password. The backend unreachable ⇒ `503` (never a fallback to "anyone"). The same lookup
   checks the INVITE's `Proxy-Authorization`. Without `SIM_SIP_BACKEND_URL` the gateway runs
   standalone (E6a: any username, echo only).
9. **Readings the implementation fixed (E6e).** (a) `leg UP` for an OUTBOUND call whose transport is
   not ready yet leaves it `DIALING`; the gateway re-reports `UP` every `leg_retry_s` (1 s) for up
   to the ring timeout, then reports `FAILED`. (b) While a softphone-dialled call waits for
   `DDS_CALL_ANSWERED`, the gateway re-reads it (`getTelephonyCall`) every `answer_poll_s` (2 s),
   so a lost Redis event delays the `200 OK` by at most that. (c) A call ended before its answer
   gives the softphone `486` (`BUSY`), `487` (the trainee's `HANGUP` from the browser) or `480`
   (`NO_ANSWER`, `ABORT`, `TRANSPORT_LOST`); a `409 DDS_LINE_BUSY` on dial is `486`, any other `409`
   `480`, a `403` `403`, the backend down `503`. (d) The gateway pattern-subscribes to
   `voice:cancel:*` and `session:*:events` and drops every message not about a call it bridges. (e)
   The session selection's candidates also require `dds_brigade_call = ON` (a session without the
   phone has nobody to ring; D25). (f) A browser-button `SIP` call publishes `voice:join {endpoint:
   SIP, sip_user}` at `DIALING` (re-published every `VOICE_JOIN_RETRY_MS` until the gateway's `leg
   UP` rings it); an INBOUND `SIP` call is rung by the tick as before and the softphone's answer
   (`leg UP`) is the trainee's `answer`. (g) On shutdown the gateway reports `leg FAILED {503}` for
   every ДДС call it carries.

### 80.2.4 Plan B and fallback (named, not built)

- **`SipCallTransport` (direct RTP into the agent, no SFU hop).** Reserved seam. Built only if the
  falsification checkpoint (§80.11) fires on delay. The domain is unaffected because the transport is
  chosen per `DdsCall.endpoint`.
- **Asterisk 20.6 + `chan_audiosocket`.** If a softphone cannot complete a call against our stack,
  Asterisk becomes registrar + PBX and `bridge.py` takes 16 kHz PCM from AudioSocket instead of RTP;
  everything above the bridge (rooms, domain, personas, tests) survives. It is a download plus a root
  install, so it needs the owner's consent at that point.
- **Wideband.** If ASR over 8 kHz G.711 raises WER unacceptably (`benchmark_asr.py` on a resampled
  corpus), G.722 is added before E6e.

## 80.3 F2 — ДДС calls in the domain

### 80.3.1 Types — `backend/app/domain/dds/call.py` (new, E6b)

```python
class DdsCallKind(str, Enum):      SERVICE_HEAD = "SERVICE_HEAD"; CLAIMANT = "CLAIMANT"; OPERATOR_112 = "OPERATOR_112"
class DdsCallDirection(str, Enum): OUTBOUND = "OUTBOUND"; INBOUND = "INBOUND"   # INBOUND = the brigade calls the ДДС (REQ-1038 push)
class CallEndpoint(str, Enum):     BROWSER = "BROWSER"; SIP = "SIP"
class DdsCallState(str, Enum):     DIALING = "DIALING"; RINGING = "RINGING"; CONNECTED = "CONNECTED"; ENDED = "ENDED"
class DdsCallEndReason(str, Enum): HANGUP = "HANGUP"; NO_ANSWER = "NO_ANSWER"; BUSY = "BUSY"; ABORT = "ABORT"; TRANSPORT_LOST = "TRANSPORT_LOST"
class CallAnsweredBy(str, Enum):   AI = "AI"; TRAINEE = "TRAINEE"

class DdsCall(BaseModel):  # frozen, extra="forbid"
    call_id: uuid.UUID
    session_id: SessionId
    kind: DdsCallKind
    direction: DdsCallDirection
    assignment_id: AssignmentId | None   # SERVICE_HEAD: the leg (70 §70.4.5); None otherwise
    service_type: ServiceId | None       # SERVICE_HEAD: the leg's service; None otherwise
    dialed: str                          # "101", "7012", "112", the claimant's digits
    endpoint: CallEndpoint
    room: str                            # "dds-{session_id}-{call_id}"
    persona_id: str | None               # resolved at start (§80.4.1); None for CLAIMANT
    actor_user_id: UserId | None         # the ДДС trainee on the line
    state: DdsCallState
    answered_by: CallAnsweredBy | None
    started_at_offset_ms: int
    answered_at_offset_ms: int | None
    ended_at_offset_ms: int | None
    end_reason: DdsCallEndReason | None
```

`kind = OPERATOR_112` with `answered_by = TRAINEE` is the reserved hook for a human 112 trainee
answering (owner Q1, later sub-epic E6g); in I3 every `OPERATOR_112` call is `answered_by: AI`.

### 80.3.2 `DDS_CALL_TRANSITIONS` (table-driven, INV 8; `puml/i3-telephony-dds-call-state.puml`)

| From | Trigger | To | Actor | Guard / source |
|:--|:--|:--|:--|:--|
| `[*]` | `start` | `DIALING` | TRAINEE (OUTBOUND), SIMULATION (INBOUND `CALL_IN` step) | `guard_dds_call_allowed`: session `ACTIVE`, DDS stage started, `dds_brigade_call = ON`, the action is in the caller's `available_actions`; for `SERVICE_HEAD` `plays_leg(leg, user)`; the user has no other non-`ENDED` `DdsCall` in the session (one line per workstation) |
| `DIALING` | `ring` | `RINGING` | SIMULATION | `guard_dds_call_transport_ready`: LiveKit reachable ∧ agent heartbeat (as the 112 `ring`), and for `endpoint = SIP` the gateway reported `leg UP` |
| `RINGING` | `answer` | `CONNECTED` | SIMULATION (OUTBOUND: AI callee after the persona's `answer_after_ms`), TRAINEE (INBOUND) | the actor matches the direction |
| `RINGING` | `no_answer` | `ENDED` | SIMULATION | persona / script data (`no_answer: true`, REQ-5325 «не отвечают»); an INBOUND call nobody answers within `ring_timeout_ms` |
| `RINGING` | `busy` | `ENDED` | SIMULATION | script data (`busy: true`), or `CLAIMANT` while the session's 112 call is `RINGING`/`CONNECTED` (the claimant's phone is busy) |
| `DIALING`, `RINGING`, `CONNECTED` | `hang_up` | `ENDED` | TRAINEE, SYSTEM | TRAINEE ⇒ `end_reason HANGUP`; SYSTEM ⇒ `ABORT` (session abort, stage completion, softphone leg `FAILED`) or `TRANSPORT_LOST` (transport grace timeout) |

Every accepted transition appends exactly one event (`start` → `DDS_CALL_STARTED`, `answer` →
`DDS_CALL_ANSWERED`, `no_answer` / `busy` / `hang_up` → `DDS_CALL_ENDED`); `ring` appends nothing new
(the `voice:join` publish follows the commit, the 112 call-flow discipline). A call left `DIALING` or
`RINGING` when the DDS stage completes is ended by SYSTEM (`ABORT`) in the same Unit of Work. The leg
machine (`SERVICE_RESPONSE_TRANSITIONS`), `DDS_TRANSITIONS` and the memo closure guard are untouched.

Refusals: a disallowed `start` ⇒ `409 ACTION_NOT_AVAILABLE` (switch `OFF`, wrong stage) or `403
FORBIDDEN_FOR_SERVICE` (leg bound to another participant) or `409 DDS_LINE_BUSY` (the user already has a
live call); any other trigger not in the table ⇒ `409 INVALID_TRANSITION`.

### 80.3.3 Who plays what under `dds_brigade_call: ON` (memo mode only, R41)

- **The trainee's own leg** (`responder = TRAINEE`, i.e. `plays_leg(leg, user)`): the script
  `responders[service_type]` (or `DEFAULT`) is the brigade's timeline and is **voiced, never applied**.
  `due_scripted_steps` stays the source (pure, due-offset stamped); stage automation skips `TRAINEE`
  legs when `SESSION_CREATED.variants.dds_brigade_call = ON`; the persona reads the due steps at call
  time. The trainee learns a status by calling (pull, REQ-1038) or by being called (a step with `report:
  CALL_IN`, additive optional script field, default `ON_REQUEST`) and enters it with the existing
  `set_service_status` — the leg machine, `409 INVALID_TRANSITION`, `422 COMMENT_REQUIRED`, history,
  card status and memo closure unchanged. `set_service_status` gains an optional `proposed_by_call_id`,
  validated to name a `DDS_CALL_STATUS_PROPOSED` of this leg (else `422 PROPOSAL_UNKNOWN`).
- **Other services' `SCRIPTED` legs**: exactly E5b (applied by stage automation); their card-status
  timers keep working.
- **`OFF`**: exactly E5b for every leg; no call action is offered and no `DDS_CALL_*` is ever appended.

(Sequence: `puml/i3-telephony-sequence-service-head-call.puml`.)

### 80.3.4 ДДС → claimant, ДДС → 112

- **Claimant** (`kind = CLAIMANT`, `dialed` = the snapshot's `caller.phone` digits): the callee is the
  scenario's caller — `CallerBelief`, `FactAccessGate`, `CallerProfile`, validator, the whole frozen
  chain — with the ДДС in the operator seat. The one change is a speaker-label parameter on
  `CallerPromptBuilder` («ОПЕРАТОР» today, «ДИСПЕТЧЕР» here). `GENERATED_CARD` sessions still carry
  `caller_profile` / `caller_knowledge`, so the claimant exists without a 112 stage. No card number is
  spoken (REQ-5919); the persona greeting follows the memo's phrasing (REQ-5920). While the session's 112
  call is live the claimant is `busy` (§80.3.2).
- **112** (`kind = OPERATOR_112`, `dialed = "112"`): answered by an **AI 112 operator** (E6d) following
  REQ-5332's checklist — self-identification (ФИО, должность, служба), address, reason, "working a card
  already routed", the change, answering the operator's questions. The persona's knowledge is the
  snapshot and nothing else; each checklist item the trainee covers is a `DDS_CALL_ASSERTION` with a
  memo-item `field_path` (`call.self_identification`, `call.card_reference`, `address.street`,
  `incident.change`, …) so `WORKFLOW_ACTION` rules score the script. The human-112-trainee variant is
  owner question Q1 (§80.10).

### 80.3.5 Dial plan — `backend/app/domain/routing/dial_plan.py` (pure; E6b, used by E6e)

| Dialled | Resolves to |
|:--|:--|
| `112` | `OPERATOR_112` |
| a catalog `code` (`101`, `102`, `103`, `104`) | `SERVICE_HEAD` of that service's leg on the selected card |
| `7` + 3 digits | `SERVICE_HEAD` of the catalog entry at that 1-based position among `display: true` entries in pack order (`7001` …); stable because the pack is sha-pinned — a reorder is a new pack. Shown on the ДДС screen beside each service block («тел. 7012», `DdsLegView.phone_extension`) |
| the snapshot's `caller.phone` (digits only; a leading `8` or `7` of an 11-digit number dropped before comparing the last 10) | `CLAIMANT` |
| `999` | gateway-local echo; never reaches the backend |
| anything else | `404 DIAL_NUMBER_UNKNOWN` (SIP `404`) |

**Session selection for a SIP-dialled number**: the user's `ACTIVE` sessions in which they are a ДДС
participant and the DDS stage has started; the card this user opened last (`DDS_CARD_OPENED`) wins,
else the oldest; none ⇒ `409 NO_ACTIVE_DDS_SESSION` (SIP `480`). A `SERVICE_HEAD` number whose service
has no leg on that card, or whose leg the user does not play ⇒ `404 DIAL_NUMBER_UNKNOWN`. The choice is
recorded as `DDS_CALL_STARTED.selection_reason ∈ {BROWSER_BUTTON, LAST_OPENED_CARD, OLDEST_ACTIVE,
INBOUND_SCRIPT}`. The browser path never needs the dial plan (the button carries `assignment_id` /
`kind`).

### 80.3.6 Concurrency in the agent

`VoiceAgent._calls` is keyed by `(session_id, call_id)`. `voice:join` gains additive keys `call_kind:
CALLER | SERVICE_HEAD | CLAIMANT | OPERATOR_112` (absent ⇒ `CALLER`, today's behaviour), `assignment_id`,
`persona_id`, `endpoint`, `sip_user` (E6e). `call_kind = CLAIMANT` runs today's pipeline;
`SERVICE_HEAD` / `OPERATOR_112` run the responder chain (§80.4). A DDS call **never writes**
`session:{id}:call_state` (that key is the 112 call's; HLD 40 §40.6 unchanged) — the ДДС phone widget
reads `GET …/dds-calls` and the call-scoped events (§80.6.2). `voice:join` for a `DdsCall` is re-published
under the same self-healing rule as the 112 call, per `call_id`. Recordings land under
`RecordingPaths.for_call(session_id, call_id)` with no change.

### 80.3.7 Endpoint choice (E6e)

At `start` of an OUTBOUND call: if `telephony_endpoints` contains `sip` and the Redis key
`sip:binding:{username}` exists for the trainee's user, `endpoint = SIP`; otherwise `BROWSER`. The key is
written by the gateway on every successful `REGISTER` (`{contact, expires_at}`, `EX` = the binding's
`Expires`) and deleted on unregister; it is an additive HLD 40 §40.6 row in E6e. Loss ⇒ the call falls
back to the browser endpoint until the softphone's next refresh; no simulation state is involved. A
softphone-dialled call is `SIP` by construction.

## 80.4 F3 — The AI voice by category

### 80.4.1 Persona source — `reference/personas/v1.yaml` (E6c; sha-pinned in `reference/manifest.json`, pack `v046_24-r1` re-pinned)

```yaml
- id: BRIGADE_101     applies: {code: "101"}         title_ru: "Начальник караула ПСЧ"       gender: MALE   voice_id: ru_male_adult_01
- id: BRIGADE_102     applies: {code: "102"}         title_ru: "Старший наряда"               gender: MALE   voice_id: ru_male_adult_01
- id: BRIGADE_103     applies: {code: "103"}         title_ru: "Старший бригады СМП"          gender: FEMALE voice_id: ru_female_adult_01
- id: BRIGADE_104     applies: {code: "104"}         title_ru: "Дежурный аварийной бригады"   gender: MALE   voice_id: ru_male_adult_02
- id: DDS_DISTRICT    applies: {kind: DISTRICT}      title_ru: "Дежурный ДДС района"          …
- id: DDS_PREFECTURE  applies: {kind: PREFECTURE}    …
- id: DEPARTMENT      applies: {kind: DEPARTMENT}    …
- id: CITY_DEFAULT    applies: {kind: CITY}          …
- id: OPERATOR_112    applies: {kind: OPERATOR_112}  title_ru: "Оператор 112"                 …
```

Each entry also carries `greeting_ru`, `answer_after_ms` (default 4000), `vocabulary` (the memo's phrases
for each status) and optional `no_answer` / `busy` flags. **Resolution** (`domain/dds/personas.py`,
pure): the most specific `applies` wins (`code` > `kind`); `CLAIMANT` has no persona (the scenario's
`CallerProfile` is the persona). A scenario may override per service with the additive optional key
`expected_response.responders[service_id].persona` (schema 2 only; R42). The resolved `persona_id` is
recorded on `DDS_CALL_STARTED` (P4).

**Voices** are logical ids resolved through the existing profile `tts.voice_map`: `ru_male_adult_*` map
to male Qwen3-TTS CustomVoice speakers, verified by E6c against the installed `qwen_tts` package (the
names in the profile come from recon, not from that package). Piper has no male voice on disk, so under
the Piper fallback every male id maps to `ru_RU-irina-medium` and REQ-4041 is reported **partial** under
that fallback. Nothing is downloaded.

### 80.4.2 Knowledge boundary — `ResponderKnowledge`

`ResponderKnowledge {service: catalog entry, persona, snapshot_values (the leg's HandoffSnapshot),
steps_due: [ScriptedStep], steps_pending_count, leg_status_now, call_history (this leg's previous
DDS_CALL_*)}` is built by `ResponderContextLoader` (`application/dialogue/responder_context.py`),
constructed with the snapshot repository, the scenario repository read **only** through the
`responder_scripts` probe E5b binds for stage automation, and the event reader — **and no WorldTruth or
CallerBelief repository**. Held by two tests: a constructor-signature test (the INV 3 pattern) and a
prompt-builder signature test (the `test_r3_*` pattern).

Behaviour: on the **first** call the head knows nothing about the incident beyond the snapshot it was
sent; it asks for what the checklist names (the snapshot's non-empty `required_for_handoff` paths —
address, what happened, victims, access) and the trainee's answers are matched to the snapshot **by
code** (normalised string compare, `ru_numerals`) as `DDS_CALL_ASSERTION`s. On later calls it reports
`steps_due` in the memo's words («Прибыли на место в 14:32», «Наряд 2415») and appends one
`DDS_CALL_STATUS_PROPOSED` per step, carrying the step's due offset. A step not yet due is never
spoken — «Пока в пути, доложу позже» (INV 2 by construction).

### 80.4.3 Dialogue — `Settings.responder_dialogue = template | llm` (`SIM_RESPONDER_DIALOGUE`, default `template`)

- **`template`** (E6c, default): the existing `DialogueInterpreter` with a *responder* slot catalog
  (`status`, `order_number`, `address`, `victims`, `eta`) yields `speech_act`, `requested_facts` and
  `operator_assertions`; a deterministic `ResponderTemplates` maps `(speech_act, requested slot,
  knowledge)` to a Russian line and can emit only knowledge fields. Template lines are pre-synthesised
  at agent warm-up per persona voice (`tts_cache/{voice}/{sha(text)}.wav`, `voice_agent/tts_cache.py`),
  side-stepping Qwen3-TTS's whole-utterance first audio for the lines that matter; dynamic lines (an
  order number) go through streaming TTS as today. An unrecognised question gets «Повторите вопрос».
- **`llm`** (E6c′, optional): `CallerResponseGenerator` + `ResponseValidator` with a
  `ResponderPromptBuilder` (persona block + `KNOWN_FACTS` from `ResponderKnowledge` only); the validator's
  allowed set = knowledge values ∪ the trainee's recent utterances ∪ the persona whitelist; the leak check
  runs against every scenario value outside the knowledge (the validator is code and may see them, D10).
  Any failure falls back to the template line. INV 1/2/14 tests run in both modes.
- **Claimant**: no responder machinery; `DialogueResponder` as built with the speaker label parameter.

## 80.5 F4 — The switch `dds_brigade_call`

`ON` means **the ДДС workstation has a phone and the brigade is reachable on it**.

| Aspect | `OFF` (E5b, default) | `ON` (E6b+) |
|:--|:--|:--|
| `available_actions` (memo mode) | as 70 §70.4.4 | + `call_service_head` «Позвонить старшему» on each leg the user plays; `call_claimant` «Позвонить заявителю» and `call_112` «Позвонить в 112» on the stage; `hang_up` «Положить трубку» and (INBOUND) `answer` «Ответить» on a live `DdsCall` |
| Trainee leg's `responders` script | unused | voiced by the head; `CALL_IN` steps ring the trainee |
| `SCRIPTED` legs | applied by stage automation | applied by stage automation (unchanged) |
| Inbound brigade call | — | `DDS_CALL_STARTED {direction: INBOUND}`, ring/answer on the ДДС console |
| Scoring | call rules non-applicable (`applies_to_variants: {dds_brigade_call: [ON]}`) | call rules apply |
| Validation | — | R41, R42 |

**R41** (HLD 30 §30.8, E6b): a schema-2 scenario whose `variants.supported.dds_brigade_call` contains
`ON` must also support `dds_mode: MEMO_STATUSES` and carry `expected_response.responders`; session
creation resolving to `ON` with `dds_mode: RESOURCE_PICKER` ⇒ `409 VARIANT_NOT_SUPPORTED`.
**R42** (E6c): `expected_response.responders[service_id].persona`, when present, names a persona id of the
scenario's reference pack; a step's `report` is `ON_REQUEST` or `CALL_IN`; and `persona` / `report` appear
only in a schema-2 document whose `variants.supported.dds_brigade_call` contains `ON` (they mean nothing
under `OFF`).

**Browser vs SIP is not a value of this switch and not a `SIM_CALL_TRANSPORT` value.** It is the
endpoint per call (§80.3.7), recorded on `DDS_CALL_STARTED.endpoint` (P4 without a fifth switch). The
112 caller path keeps `SIM_CALL_TRANSPORT = livekit | fake` untouched. 70 §70.2.2's clause "deployment
settings may only remove `dds_brigade_call: ON` when no telephony transport is configured" is satisfied
trivially: the browser endpoint exists wherever LiveKit does.

Default: `OFF` for schema-2 scenarios until the owner answers Q2 (C7). Schema 1: `{OFF}` forever (P5).
Permission addition: `PLACE_DDS_CALL` (DDS module, under `ON`).

## 80.6 Events — new and changed (for HLD 10 §10.13 and HLD 40 §40.4, by the epic named)

### 80.6.1 Payloads

| Event type | Epic | Actor | Payload keys (`name: type`) | Visible to |
|:--|:--|:--|:--|:--|
| `DDS_CALL_STARTED` | E6b | TRAINEE (OUTBOUND), SIMULATION (INBOUND) | `call_id: uuid`, `kind: DdsCallKind`, `direction: DdsCallDirection`, `assignment_id: uuid \| null`, `service_type: ServiceId \| null`, `dialed: str`, `endpoint: CallEndpoint`, `room: str`, `persona_id: str \| null`, `actor_user_id: uuid \| null`, `selection_reason: BROWSER_BUTTON \| LAST_OPENED_CARD \| OLDEST_ACTIVE \| INBOUND_SCRIPT`, `at_offset_ms: int` | DDS, INSTRUCTOR |
| `DDS_CALL_ANSWERED` | E6b | SIMULATION (AI callee), TRAINEE (INBOUND) | `call_id: uuid`, `answered_by: AI \| TRAINEE`, `at_offset_ms: int` | DDS, INSTRUCTOR |
| `DDS_CALL_ENDED` | E6b | TRAINEE, SIMULATION, SYSTEM | `call_id: uuid`, `reason: HANGUP \| NO_ANSWER \| BUSY \| ABORT \| TRANSPORT_LOST`, `duration_ms: int` (0 when never connected), `at_offset_ms: int` | DDS, INSTRUCTOR |
| `DDS_CALL_STATUS_PROPOSED` | E6c | SIMULATION | `call_id: uuid`, `assignment_id: uuid`, `service_type: ServiceId`, `status: ServiceResponseStatus`, `order_number: str \| null`, `comment_ru: str \| null`, `script_after_ms: int`, `due_offset_ms: int` (`received_at_offset_ms + script_after_ms`; the INV 7 key), `at_offset_ms: int` (when the head spoke it) | DDS, INSTRUCTOR |
| `DDS_CALL_ASSERTION` | E6c (E6d field paths) | MODEL | `call_id: uuid`, `turn_id: uuid`, `field_path: str`, `value_ru: str`, `matches_snapshot: bool`, `at_offset_ms: int` — one per card fact / checklist item the trainee stated on the call, matched by code against the handoff snapshot | INSTRUCTOR |
| `DDS_SERVICE_STATUS_SET` (additive key) | E6c | as today | `proposed_by_call_id: uuid \| null` | as today |

**Per-turn events reused under `call_id`.** `USER_SPEECH_STARTED/ENDED`, `ASR_PARTIAL/FINAL`,
`CALLER_TTS_STARTED/ENDED`, `CALLER_UTTERANCE_INTERRUPTED`, `DIALOGUE_INTERPRETED`,
`CALLER_RESPONSE_PLANNED/GENERATED`, `FACT_GATE_EVALUATED`, `FACTS_DELIVERED`, `MODEL_*`,
`TRANSPORT_*` are appended **unchanged** under the call's `call_id`. HLD 10 §10.13 gains the note that
"CALLER" in those names is "the AI party of the call"; the party is read from `DDS_CALL_STARTED.kind` of
the same `call_id`. No `RESPONDER_*` twins. The report and the transcript panel group turns by
`call_id` and label the party from `kind`.

### 80.6.2 Call-scoped visibility and scoring (E6b)

Reusing the per-turn events under a DDS `call_id` has two consequences the event-type-only rules of
today would get wrong; both are closed by one derived fact — **the set of DDS call ids of the session is
the `call_id`s of its `DDS_CALL_STARTED` events** (a pure function of the log, P2/P4; `dds_calls` caches
it):

- **Visibility (HLD 40 §40.4, `▲` rows).** A per-turn event whose `call_id` is a DDS call id is pushed to
  DDS (with the same trainee redaction as OPERATOR_112 gets today) and **not** to OPERATOR_112; one whose
  `call_id` is not is pushed exactly as today. The redaction function takes the DDS call id set as an
  input (`STAGE_STATE_CHANGED`'s "only for the stage's own role" rule is the precedent). The rows for
  `USER_SPEECH_*`, `ASR_*`, `CALLER_TTS_*`, `CALLER_UTTERANCE_INTERRUPTED`, `TRANSPORT_*` gain `▲` in
  the DDS column; the instructor sees everything as today. `DDS_CALL_*` rows are plain (table above).
- **Scoring.** `ScoringContext.deliveries_of` (read by `FACT_OBTAINED` and `CARD_CONTRADICTION`'s
  `require_fact_delivered`) excludes `FACTS_DELIVERED` whose `call_id` is a DDS call id, so a claimant
  call-back never moves a 112 score. `FACT_OBTAINED` gains an additive optional config key `on_call:
  CALLER_112 | DDS_CLAIMANT` (default `CALLER_112`) for ДДС-side claimant rules. Call rules otherwise use
  `WORKFLOW_ACTION` / `DEADLINE` on `DDS_CALL_*` (`payload_match {kind: CLAIMANT}`), with
  `applies_to_variants: {dds_brigade_call: [ON]}`; E6c adds one evaluator `CALL_STATUS_TRANSCRIBED`
  (a `DDS_SERVICE_STATUS_SET` whose `proposed_by_call_id` names a proposal with the same `status`) only if
  `WORKFLOW_ACTION.must_occur_after` cannot express it (SPEC §28 "at least").

## 80.7 Migrations (additive; `0001`…`0012` never move)

| Migration | Epic | Changes |
|:--|:--|:--|
| `0014_dds_calls` | E6b | new table `dds_calls (id uuid PK (= call_id), session_id uuid NOT NULL FK simulation_sessions ON DELETE CASCADE, kind text NOT NULL CHECK IN (SERVICE_HEAD, CLAIMANT, OPERATOR_112), direction text NOT NULL CHECK IN (OUTBOUND, INBOUND), assignment_id uuid NULL FK dds_assignments ON DELETE CASCADE, service_type text NULL, dialed text NOT NULL, endpoint text NOT NULL CHECK IN (BROWSER, SIP), room text NOT NULL UNIQUE, persona_id text NULL, actor_user_id uuid NULL FK users ON DELETE RESTRICT, state text NOT NULL DEFAULT 'DIALING' CHECK IN (DIALING, RINGING, CONNECTED, ENDED), answered_by text NULL CHECK IN (AI, TRAINEE), selection_reason text NOT NULL, started_event_id uuid NOT NULL UNIQUE FK session_events, started_at_offset_ms integer NOT NULL, answered_at_offset_ms integer NULL, ended_at_offset_ms integer NULL, end_reason text NULL CHECK IN (HANGUP, NO_ANSWER, BUSY, ABORT, TRANSPORT_LOST))`; `CHECK ((kind = 'SERVICE_HEAD') = (assignment_id IS NOT NULL))`; `CHECK ((state = 'ENDED') = (ended_at_offset_ms IS NOT NULL))`; `CHECK ((state = 'ENDED') = (end_reason IS NOT NULL))`; index `ix_dds_calls_session (session_id, started_at_offset_ms)`; partial index `ix_dds_calls_live (session_id, actor_user_id) WHERE state <> 'ENDED'`. A read model written in the same Unit of Work as the `DDS_CALL_*` event and rebuildable from them (INV 13); no backfill (no call exists before E6b). |
| `0015_users_sip_ha1` (optional) | E6e | `users.sip_ha1 text NULL` + `CHECK (sip_ha1 IS NULL OR sip_ha1 ~ '^[0-9a-f]{32}$')` — `MD5(username:realm:password)`, set by an admin command; `NULL` ⇒ the deployment password applies. A realm change invalidates every stored HA1 (stated in the RUNBOOK). Built only if per-user SIP passwords are wanted. |

## 80.8 Verification and load plan (F5)

### 80.8.1 What the gate proves (GPU-free, no network, no Docker beyond the test postgres/redis)

| Capability | Gate test |
|:--|:--|
| (1) SIP server: register + call through (E6a) | `workers/voice_agent/tests/sip/`: the headless UA against the in-process gateway with `FakeRoomBridge` on ephemeral loopback UDP/TCP ports — `REGISTER → 401 → REGISTER(Digest) → 200`, expiry, wrong password `403`; `INVITE → 100/180/200/ACK`, SDP answer selects PCMA/PCMU, RTP both ways for 2 s with sequence / timestamp continuity, `BYE → 200`, `CANCEL`, `OPTIONS`; echo `999`; malformed messages `400` without a crash; codec round-trip error bounds; `check_imports` green (no `livekit` outside `transport/`, no `livekit.agents`) |
| (2) ДДС → service head, AI voice by category (E6c) | `backend/tests/api/dds/test_dds_calls.py` on `FakeCallTransport` / `FakeASR` / `FakeTTS`: `POST …/dds-calls {kind: SERVICE_HEAD, assignment_id}` → `DDS_CALL_STARTED/ANSWERED`; persona by catalog (`101` → `BRIGADE_101`, a `DISTRICT` id → `DDS_DISTRICT`); first-call checklist asks the snapshot's required paths; `DDS_CALL_ASSERTION` matches by code; a later call proposes exactly the due steps, `DDS_CALL_STATUS_PROPOSED` identical at tick 100 vs 900 ms (INV 7); `set_service_status {proposed_by_call_id}` → `DDS_SERVICE_STATUS_SET`; INV 3-style constructor test; `test_r3`-style prompt-builder signature test; INV 1/2/14 in both dialogue modes; rescore equality (INV 9) |
| (3) ДДС → claimant (E6b) | same file: `kind: CLAIMANT` runs `DialogueResponder` unchanged — INV 1, INV 12 barge-in, INV 14 per `call_id`; `FACTS_DELIVERED` on the DDS call does not move a 112 `FACT_OBTAINED` score; `busy` while the 112 call is live |
| (4) ДДС → 112 (E6d) | `kind: OPERATOR_112`: REQ-5332 checklist items → `DDS_CALL_ASSERTION`s → rule points; a missing self-identification ⇒ penalty |
| SIP endpoint wired (E6e) | the headless UA dials `101` / `112` / the claimant's digits against the gateway + a fake backend dial endpoint, and the real use case on fake transport; session selection cases; `leg DOWN` ⇒ `hang_up` |
| Frozen caller path | every existing voice / API test unchanged; a session with `dds_brigade_call: OFF` appends no `DDS_CALL_*` and offers no call action; call-scoped visibility test (a DDS call's `CALLER_TTS_STARTED` never reaches an OPERATOR_112 socket) |
| Latency probe, structural (E6a) | `benchmarks/tests/`: `benchmark_voip.py --path sip-loopback` — UA → gateway → echo, in-process one-way delay below a generous bound (60 ms) and the JSON shape; `NOT_RUN` for the other paths |

### 80.8.2 Manual / bench runs (no hardware phone, no downloads)

1. **Our softphone with a headset**: `python -m voice_agent.tools.softphone --register <user> --dial 101
   --headset` (sox). This is ТЗ ¶175's "software emulation of an IP phone" and the DoD-walk instrument
   for (1)–(4) over SIP.
2. **Third-party interop**: `baresip` only if already present offline; it is not on this machine
   today, so the report records **`NOT_RUN`** and states that interop against a foreign stack is
   unproven. No download is made.
3. **Full path with real models**: `make up` (+ `--profile sip`), `make preflight`, a memo session with
   `ON`, the softphone or the browser widget, GPU only under `flock -w 10800
   /tmp/teamwork-112-maxxing/gpu.lock`; evidence (event-log excerpts of `DDS_CALL_*`,
   `DDS_CALL_STATUS_PROPOSED`, the trainee's `DDS_SERVICE_STATUS_SET`) in the DoD-walk style.

### 80.8.3 Delay and load (ТЗ ¶161 ≤ 150 ms; «≥ 20 concurrent sessions»)

`benchmarks/benchmark_voip.py` follows the `_common.py` contract of the five E19 scripts (JSON/CSV,
`NOT_RUN` honesty, no number in the repo a script did not produce).

- **Method**: mouth-to-ear on one host clock. UA-A sends PCMA frames carrying a 1 kHz burst every 2 s at
  known send offsets; the far end detects the burst by energy and stamps arrival; delay = arrival −
  send, 30 bursts per run; p50 / p95 / max, jitter (RFC 3550 interarrival), loss (RTP sequence gaps). The
  number excludes the softphone's own capture / playout and a hardware phone's jitter buffer; the report
  states both.
- **Paths**: `sip-loopback` (gate), `sip-livekit` and `livekit-only` (`requires_livekit`), and
  `sip-direct` only if plan B is built.
- **Load**: `--concurrent N`, N ∈ {1, 5, 10, 20, 40}: N UAs in N calls to the echo through the gateway and
  the SFU, 60 s each; per-N delay percentiles, loss, gateway and SFU CPU % (`/proc`). GPU-free by design.
  The AI-in-the-loop concurrency bound (LLM/TTS on one 8 GB card) is a different number, left unmeasured
  by E19 (`docs/benchmarks/vram.md`), and E6f says so rather than folding it in.
- **Where the numbers go**: `docs/benchmarks/voip.md`; `DEV_3060TI.yaml` gains
  `voip.one_way_delay_ms_p50 / p95` and `voip.concurrent_calls_measured` (measured, or absent).

**Result (I3 E6f, 2026-09-24, `docs/benchmarks/voip.md`).** `sip-loopback` (gateway-only, its own
subprocess): p50/p95 stay sub-millisecond and 0 % RTP loss at every swept N — 1: 0.22/0.35 ms;
5: 0.21/0.32 ms; 10: 0.13/0.23 ms; 20: 0.17/0.34 ms; 40: 0.16/0.36 ms. `sip-livekit` (the full
SIP+SFU path): N=1 p50/p95 95.8/108.6 ms (meets target); N=5 1298.7/1319.2 ms (target missed,
0 % RTP loss); N=10 583.6/1856.9 ms with 47.7 % burst-detection loss (PARTIAL); N=20/N=40
`NOT_RUN` — this benchmark's single-process harness did not complete a run within 250 s. Highest N
meeting p95 ≤ 150 ms and loss < 1 %: `sip-loopback` 40 (largest tested), `sip-livekit` 1.

## 80.9 Invariants and decisions kept

| Rule | Held by |
|:--|:--|
| INV 1, 2 | Claimant calls: the unchanged gate. Service head: `ResponderKnowledge` is script + snapshot only; `llm` mode's validator leak-checks against every scenario value outside it; a not-yet-due step is never spoken. |
| INV 3 | `ResponderContextLoader` and every DDS call use case constructed without WorldTruth / CallerBelief repositories (signature tests); the script reaches the agent through the probe E5b binds for stage automation. |
| INV 4 | No call writes the card; `DDS_CALL_ASSERTION` is an event about what was *said*, matched by code; statuses are written only by the trainee's `set_service_status`. |
| INV 7 | Proposals carry due offsets from `due_scripted_steps`; the `ON` skip is a function of recorded variants + leg data. |
| INV 8 | `DDS_CALL_TRANSITIONS` table-driven; the leg machine untouched. |
| INV 12, 14 | The pipeline as built, per `call_id`; template fallback for the responder. |
| INV 13 | `dds_calls` read model + REST restore a live call; the only new Redis key (`sip:binding:{username}`, E6e) is transient and its loss changes nothing but the endpoint choice. |
| D2 / D9 | `livekit` only under `transport/`; the agent is not the SIP server; no `livekit-agents`; the backend and the workers mint LiveKit tokens, no token over Redis. |
| D3 | The head's snapshot view is the DDS's own layer; no layer object crosses into the prompt; call-scoped visibility keeps a DDS call's turns off the 112 socket. |
| D5, P2, P4 | All new payloads self-sufficient; scoring reads events only; endpoint, persona and selection recorded on the event. |
| D13 | Fakes in the gate: `FakeRoomBridge`, headless UA, `FakeCallTransport`; real runs `requires_livekit`, GPU under the lock. |
| SPEC §15 | LiveKit remains the media plane; the SIP server complements it; no PSTN. `SipCallTransport` stays the reserved seam (plan B). |
| C7 | Default `OFF`; `ON` implemented by E6b (`IMPLEMENTED_VARIANT_VALUES`). |
| Machine rules | Ports 5060, 20000–20199, 8114 — none of 8000/8001/8011/8012/5000; no GPU in the gate; no downloads. |

Nothing above replaces a D-decision or an invariant.

## 80.10 Owner questions

1. **ДДС → 112: AI 112 operator, or the lesson's 112 trainee?** The human variant needs a second
   incoming line on the 112 console — the singular `CallStateView` / `session:{id}:call_state` / 112
   `_calls` entry is one call per session — i.e. a widening of the frozen caller path. **Manager default
   until the owner answers: AI (E6d).** The human variant is reserved as a hook (`DdsCall.kind =
   OPERATOR_112`, `answered_by: TRAINEE`) and listed as the later sub-epic **E6g**, not in I3.
2. **Default of `dds_brigade_call` for schema-2 scenarios once `ON` exists** (C7). `OFF` = the memo
   world (statuses only, E5b); `ON` = the customer's phone world (the trainee's own leg is heard, not
   applied). The choice changes what every generated ticket scenario (E8) trains by default. Default
   stays `OFF` until answered.

Defaulted, stated so the owner can veto: no third-party softphone download (`baresip` `NOT_RUN` unless
present offline); one deployment SIP password for all trainee usernames (per-user HA1 optional in E6e);
Piper has no male voice on disk (REQ-4041 partial under the Piper fallback).

## 80.11 Falsification checkpoint (after E6a, before E6b–E6d are staffed)

E6a measures `sip-livekit` one-way delay and completes calls with our `--headset` softphone (and
`baresip` if present offline). **If `sip-livekit` p95 > 150 ms, or a softphone cannot complete a call
(register, INVITE/ACK, two-way audio, BYE) after the obvious fixes, E6e is re-issued** — as
`SipCallTransport` direct RTP (delay) or Asterisk-AudioSocket (interop) — **before E6b–E6d are
staffed**. Nothing in E6b–E6d depends on which one wins: the domain chooses the transport per
`DdsCall.endpoint`, and everything above `bridge.py` survives either fallback.

## 80.12 Contract and schemes

- `docs/hld/contracts/i3-telephony-openapi-delta.yaml` — `dds-calls` (start, list, get, answer,
  hang-up), `createVoiceToken` additive `call_id`, `setDdsServiceStatus` additive `proposed_by_call_id`,
  `DdsLegView` additive `phone_extension`, the gateway-facing telephony endpoints (`dial`, `leg`, call
  read, optional HA1 lookup), `GET /reference/personas`, the enums and error codes. Each epic merges its
  items into `docs/hld/openapi.yaml` in its own commit.
- `docs/hld/puml/i3-telephony-components.puml` — softphone ↔ gateway ↔ LiveKit room ↔ voice agent ↔
  backend.
- `docs/hld/puml/i3-telephony-dds-call-state.puml` — §80.3.2.
- `docs/hld/puml/i3-telephony-sequence-service-head-call.puml` — ДДС → service head with a status
  proposal and the trainee's confirmation.
- `docs/hld/puml/i3-telephony-sequence-sip-register-invite.puml` — SIP register + INVITE → room join.

## 80.13 Where this document departs from the analysis's wording, and why

| Item | Analysis | Here | Reason |
|:--|:--|:--|:--|
| Third-party interop | `baresip` from apt, "the one download this analysis recommends if the owner allows it" | run only if already present offline, otherwise `NOT_RUN`; no download | manager decision (no downloads) |
| Falsifier wording | "a foreign softphone cannot complete a call" | "a softphone cannot complete a call" (our `--headset` UA; `baresip` if present) | manager decision; a foreign UA may be `NOT_RUN` |
| Per-turn events visibility | reuse "avoids touching … the visibility table" | call-scoped `▲` rule in HLD 40 §40.4 for the DDS column (§80.6.2) | today's rows push those events to OPERATOR_112 only, by type: a DDS call's turns would reach the 112 socket and never the ДДС widget |
| `FACTS_DELIVERED` on a claimant call | "works per `call_id` as it does today" | `deliveries_of` excludes DDS call ids; `FACT_OBTAINED.on_call` additive (§80.6.2) | `FACT_OBTAINED` counts every delivery of the session today, so a call-back would move the 112 trainee's score |
| Redis | "no new Redis key" | one transient key `sip:binding:{username}` (E6e) | the endpoint rule "a registered softphone wins" needs the backend to see live registrations; loss only changes the endpoint to the browser |
| Gateway ↔ backend | one REST call (`dial`) | `dial` + `leg {UP \| FAILED \| DOWN}` + call read; the gateway also listens to `voice:join` (`endpoint: SIP`), `voice:cancel:*`, `session:{id}:events` | click-to-call and softphone hang-up need a signal each way; no new channel |
| `DDS_CALL_STARTED` payload | no `persona_id` | `persona_id` added; `DDS_CALL_STATUS_PROPOSED` also carries `due_offset_ms` | P4 (persona reproducible from the log); INV 7 needs the due offset explicit |
| One line per workstation | not stated | `409 DDS_LINE_BUSY`; claimant `busy` while the 112 call is live | a phone has one line; the claimant cannot be on two calls (the frozen `CallerBelief` would be driven by two pipelines at once) |
| `session:{id}:call_state` | not stated | a DDS call never writes it | that key is the 112 call's (HLD 40 §40.6) |

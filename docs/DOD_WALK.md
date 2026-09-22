# SPEC §46 Definition-of-Done walk — performed for real on 2026-09-22 (E20-C)

This is not a test report. It is the record of one person driving the **real** stack, with real
models on this machine's RTX 3060 Ti, through all sixteen items of SPEC §46 in the order a trainee
and an instructor would meet them, and writing down what actually happened — including the four
things that did not work.

Where a human would click in the browser, the **API was called instead** (the frontend is served
and reachable, but the walk drives `POST /api/v1/...` so every step leaves a quotable response);
where a human would speak into a microphone, the **audio-injection CLI**
(`python -m voice_agent.tools.inject`, E20-B / ruling R8) published the trainee's WAVs into the
session's real LiveKit room. Both substitutions are named per item below.

**Verdict in one line: 12 of 16 PASS, 4 PARTIAL, 0 items replaced by a fake UI animation.** Every
PARTIAL is a real defect with a named file and a reproduction, listed in §4 "Open items".

| | |
|:--|:--|
| Date | 2026-09-22 |
| Profile | `DEV_3060TI` (`SIM_MODEL_PROFILE=DEV_3060TI`), measured peak 5560 MB on an 8192 MB card |
| Simulation tick | **`SIM_SIM_TICK_MS=500`** — the shipped default (E20-F/R14 removed the 10 s workaround) |
| Walked session | `49accdb9-e2c2-4d43-9247-ddb168e16ae8`, incident `dbbf45cc-9c95-4c21-83fb-2e293a1c51d2` |
| Scenario | `apartment-fire` v1 (`scenarios/examples/apartment-fire/v1.yaml`) |
| Wall-clock of the walk | 17:31:59 → 17:42:07 local (10 min 8 s), 228 events, `last_seq_no` 216 |
| Evidence directory | `docs/benchmarks/results/dod-walk-20260922/` |
| Real-transport §27 re-run | `docs/benchmarks/results/e2e-DEV_3060TI-20260922T144530930Z.json`, published into `docs/benchmarks/e2e.md` §3.1 |

---

## 1. The run path — `make up` was tried first, and why the walk did not use it

The brief says try the documented `make up` path first. It was tried first, for 30 minutes, and it
**cannot run a real voice call today**. Four defects, in the order they appeared:

1. **`llama-server` never starts.** `infra/docker-compose.yml` defaults
   `SIM_LLAMA_SERVER_BIN` to `llama-server`, which is not on `PATH` in the pinned image; the binary
   is at `/app/llama-server`. Verbatim, from `docker compose logs llama-server`:
   `/entrypoint.sh: line 65: exec: llama-server: not found` (three times, then `Restarting (127)`).
   The compose comment already flags the default as UNVERIFIED. Worked around for this run with
   `SIM_LLAMA_SERVER_BIN=/app/llama-server`.
2. **`.env.example`'s `MODELS_DIR=./models` is wrong for compose.** Compose resolves a relative
   bind-mount source against the **compose file's** directory, so `./models` becomes
   `infra/models` — an empty directory Docker creates on the spot. Verbatim:
   `gguf_init_from_file: failed to open GGUF file '/models/llm/Qwen3.5-2B-Q4_K_M.gguf' (No such
   file or directory)`. `.env.example`'s own comment says "Relative to the repo root", which is not
   how compose reads it. Worked around with `MODELS_DIR=../models`.
3. **`make up` can never report success.** The `frontend` service serves correctly
   (`curl http://127.0.0.1:5173/` → `200`) but its healthcheck runs `wget`, which is not installed
   in that image (`wget_exit=127` inside the container), so the container is permanently
   `unhealthy` and `up -d --wait` exits 1 — `dependency failed to start ... is unhealthy`.
4. **The blocker: the `voice-agent` image has no LiveKit SDK.** `workers/voice_agent/Dockerfile`
   defaults `VOICE_AGENT_EXTRAS="asr-gigaam,vad-silero,tts-piper"`; `livekit` is not among them.
   Every call ends, verbatim:
   `ModuleNotFoundError: No module named 'livekit'` →
   `TransportError: the 'livekit' SDK is not installed; install the voice extra or run with
   SIM_CALL_TRANSPORT=fake`.
   So `make up` + `SIM_CALL_TRANSPORT=livekit` — the documented demo path — cannot place a call.

**Path actually used: the host-run variant** (README "Host-run (development) variant"), which is
E19-E-proven: compose `postgres` (15432) / `redis` (16379) / `livekit` v1.13.7 (7880-7882) for
infra, and host processes for `llama-server` (8101, Qwen3.5-2B Q4_K_M, `--parallel 2`), the
Qwen3-TTS worker (8112, 0.6B), the voice agent and the API (8100). The compose `backend`,
`frontend`, `llama-server` and `voice-agent` containers were stopped once the four defects above
were recorded. All GPU work ran under `flock /tmp/teamwork-112-maxxing/gpu.lock`.

Two further host-run traps, both in the documented instructions:

5. **README's "each needs `.env` sourced" does not work as written.** `set -a && . ./.env` lets
   bash strip the inner quotes of the two JSON-list values, and the process dies with
   `SettingsError: error parsing value for field "cors_allow_origins" from source
   "EnvSettingsSource"`. `SIM_CORS_ALLOW_ORIGINS` and `SIM_LLM_ALLOWED_INTERNAL_HOSTS` must be
   re-exported with quoting intact.
6. **`make run-llama-server` resolves container model paths on a host run.** `make profile-env`
   writes `SIM_LLAMA_MODEL_PATH=/models/llm/Qwen3.5-2B-Q4_K_M.gguf` into `infra/.env.profile`;
   `SIM_MODELS_ROOT` (E20-F/R15) is applied by the voice agent, `preflight` check 3 and the TTS
   worker but **not** by `infra/scripts/llama-server-entrypoint.sh`. The host run must export
   `SIM_LLAMA_MODEL_PATH` itself.

## 2. `make preflight`, as run

Run against the live host stack at 17:28, before the walk (`preflight.txt` in the evidence dir):

```
preflight — profile DEV_3060TI
[PASS]  1. cuda_gpu_available: 1 GPU(s): NVIDIA GeForce RTX 3060 Ti
[FAIL]  2. expected_gpu_detected: NVIDIA GeForce RTX 3060 Ti: 2341 MB free < 7680 MB required (vram_budget_mb 7168 + min_vram_margin_mb 512)
[PASS]  3. model_files_exist: 5 file(s) present
[FAIL]  4. llm_responds: ConnectError: [Errno -3] Temporary failure in name resolution
[FAIL]  5. asr_responds: empty transcription
[PASS]  6. tts_responds: 2560 ms of audio (ok)
[PASS]  7. postgresql_responds: SELECT 1 ok; exactly one alembic head
[PASS]  8. redis_responds: PING ok; SET/GET/DEL ok
[PASS]  9. livekit_responds: GET http://127.0.0.1:7880 -> 200
[PASS] 10. scenario_validation: 1 scenario file(s) valid
[SKIP] 11. audio_devices_accessible: skipped (--skip-audio-devices or AUDIO_DEVICE_CHECK != true)
[PASS] 12. llama_server_binary: /home/andreipc/src/llama.cpp/build/bin/llama-server --version exited 0
exit code: 1
```

(Check 5's `empty transcription` is the warm-up *sample*, not the ASR: `SIM_ASR_WARMUP_SAMPLE_PATH`
is empty in `.env.example`, so a synthesised tone is sent, and a tone transcribes to nothing. The
ASR itself demonstrably works — every trainee turn in §3 was transcribed correctly by GigaAM
`v3_e2e_ctc`.)

Three of the twelve checks are wrong **about a running stack**, which is the state the preflight
script's own header says it is for:

* **check 2** demands the profile's entire VRAM budget be *free*, so it fails precisely because the
  models it is checking for are already loaded (2341 MB free with the stack warm);
* **check 4** dials the profile's **container** base URL (`http://llama-server:8080/v1`) rather
  than `Settings.llm_base_url`, so it cannot resolve the name on a host run — the same class of bug
  R15 fixed for model *files*, unfixed for the LLM *URL*;
* **check 5** fails on a tone rather than on a Russian sample.

## 3. The sixteen items

Roles: **(I)** = done as the INSTRUCTOR over REST, **(T)** = as the TRAINEE over REST, **(V)** = as
the trainee's *voice* through the injection CLI, **(E)** = evidence read from the event log **as
the INSTRUCTOR** (the trainee's own feed redacts caller text by design, HLD 40 §40.4 row 12).

| # | §46 item | verdict |
|---:|---|:--|
| 1 | start an incident | **PASS** |
| 2 | receive a realistic incoming call | **PASS** |
| 3 | talk naturally with an AI caller | **PASS** (E20-I, through `make up` with the shipped Qwen3-TTS — §7) |
| 4 | interrupt the caller | **PASS** |
| 5 | obtain information only by asking appropriate questions | **PARTIAL** |
| 6 | manually fill a 112 incident card | **PASS** |
| 7 | make mistakes that remain real mistakes | **PASS** |
| 8 | select services and send the card | **PASS** |
| 9 | move into the DDS stage | **PASS** |
| 10 | receive exactly the submitted information | **PASS** |
| 11 | choose and dispatch resources | **PASS** |
| 12 | respond to evolving incident events | **PARTIAL** |
| 13 | close the incident | **PASS** |
| 14 | receive a deterministic evidence-backed assessment | **PASS** |
| 15 | replay the timeline, transcript and relevant audio | **PASS** |
| 16 | see model/inference latency metrics | **PARTIAL** |

### 1 — Start an incident — PASS

**(I)** `POST /api/v1/auth/login` as `instructor`, `GET /scenarios`, `GET /scenarios/{id}/versions`,
then `POST /sessions` with `session_mode: FULL_CYCLE_SINGLE_TRAINEE` and the seeded `trainee` as
`OPERATOR_112`, then `POST /sessions/{id}/start`.

Session `49accdb9-…` went `READY` → `ACTIVE`, `role_chain [OPERATOR_112, DDS]`, `time_scale 1.0`,
`session_seed "apartment-fire-v1"`, `transition_pause_seconds 20`, `last_seq_no 3`. Events 1-3 are
`SESSION_CREATED` (offset 0, actor INSTRUCTOR) / `SESSION_STARTED` / `ROLE_STAGE_STARTED`.

### 2 — Receive a realistic incoming call — PASS

The `SimulationRunner` rang the call by itself, 353 ms after start:

```
seq 4  offset 353 ms  CALL_RINGING  {"call_id": "60f405ea-b2c7-42d7-931c-14b3aace8536",
  "room_name": "session-49accdb9-e2c2-4d43-9247-ddb168e16ae8", "at_offset_ms": 353,
  "caller_display_ru": "Входящий вызов 112"}
```

**(T)** `POST /sessions/{id}/operator/call/answer` was issued **≈0.5 s later**, deliberately, to
exercise **E20-F/R2** (the join retry used to stop the instant the call was answered, leaving a
connected call with no caller). The stage went to `CONNECTED`, the agent joined afterwards
(`voice_agent` log: `livekit_signaling - connecting to ws://127.0.0.1:7880/rtc/v1`), and the caller
answered every subsequent turn — **R2 confirmed on the real transport.** `SIM_REQUIRE_INFERENCE_READY`
was `true`, so `startSession` had already insisted on all four `voice:health:*` keys being `READY`.

### 3 — Talk naturally with an AI caller — PARTIAL in this walk → PASS in the E20-I re-walk (§7)

**(V)** `python -m voice_agent.tools.inject --session 49accdb9-… --wait-caller` with six WAVs from
`benchmarks/data/e2e/wav/`. The CLI's own output (evidence `inject-B.log`), trainee-side only:

```
-> sending greeting.wav (turn 1/6, id=turn-1)
   heard (trainee speech): "Служба 112. Что у вас случилось?"
   caller replying (turn_index=0, at_offset_ms=15189) - text withheld from OPERATOR_112 by design
   speech_end_to_first_audio_ms: 1582
   caller done (completed=True)
```

Six turns, six caller replies, `speech_end_to_first_audio_ms` **1582 / 1221 / 1513 / 4532 / 1600 /
1200 ms — every one positive**, which is E20-F/R13's clock-origin fix proven on a live LiveKit call
(the same figures were negative and drifting before it).

**(E)** What the caller actually said, from the instructor's event log:

```
seq 21  offset 14752 ms  CALLER_RESPONSE_GENERATED  {"text": "Мне кажется, в нашей квартире есть дым.",
  "attempt": 1, "llm_model": "Qwen3-4B", "validated": true, "turn_index": 0}
seq 22  offset 15191 ms  CALLER_TTS_STARTED  {"text": "Мне кажется, в нашей квартире есть дым.",
  "provider": "piper", "voice_id": "ru_female_adult_01", "tts_model": "ru_RU-irina-medium"}
seq 23  offset 18542 ms  CALLER_TTS_ENDED  {"completed": true, "at_offset_ms": 18517}
seq 24  offset 18609 ms  FACTS_DELIVERED  {"fact_ids": ["incident.type", "incident.smoke_visible"],
  "delivered_via": "TTS_COMPLETED"}
```

**Why PARTIAL, on two counts.**

*(a) The profile's own TTS default cannot speak this scenario's caller.* `DEV_3060TI` selects
`qwen3_tts` (the owner's GPU decision) and the demo scenario's `caller_profile.voice_id` is
`ru_female_adult_01`. `Qwen3TTS.stream()` (`backend/app/inference/tts/qwen3_tts.py:337`) rejects any
non-empty voice id that is not one of the four vendor speakers, so **every** caller utterance failed:

```
seq 22  MODEL_ERROR {"stage": "TTS", "message": "TtsVoiceSpec.voice_id='ru_female_adult_01' is not
  one of the vendor speakers ('Serena', 'Ryan', 'Vivian', 'Aiden')"}
seq 23  MODEL_FALLBACK_USED {"stage": "TTS", "reason": "TTS_PROVIDER_FAILED",
  "fallback_kind": "TTS_FALLBACK_PROVIDER"}
```

*(b) INV 14's fallback ladder is dead, because the fallback provider is never warmed.* With
`SIM_TTS_FALLBACK_PROVIDER=piper` the retry then produced, every single turn:

```
seq 24  MODEL_ERROR {"model": "ru_RU-irina-medium", "stage": "TTS",
  "message": "TTS exceeded 8000 ms", "provider": "piper", "error_code": "TIMEOUT"}
```

Reproduced directly against `PiperTTS`, which names the cause the timeout hides:
`RuntimeError: PiperTTS.warm_up() must be called before stream()` (and, in the playback task,
`RuntimeError: PiperTTS.warm_up() must be called before output_sample_rate`).
`VoiceAgent._warm_tts` (`workers/voice_agent/voice_agent/main.py:508-532`) builds and warms
**only** `build_tts(settings)` — the primary. The configured fallback is constructed by the sink
and never warmed, so INV 14's "retried once on the configured fallback" can only ever fail.
**Net effect on a shipped `.env`: the caller is silent on every turn of a real DEV_3060TI demo.**

The walk therefore ran with `SIM_TTS_PROVIDER=piper` (the profile's own CPU fallback promoted to
primary, so that it *is* warmed) — the caller then spoke Russian on every turn, as quoted above.
Both defects are open items 3 and 4 in §4.

*(c) Dialogue quality, recorded not judged.* The generator fell back to the deterministic composer
on several turns (`MODEL_FALLBACK_USED {"stage": "GENERATOR", "reason": "NEW_NUMBER" | "TOO_LONG"}`)
and one reply arrived as `"}112, я не знаю, …"` — the stray `"}"` prefix E19-C already recorded.
The caller also parrots earlier turns. This is model/prompt quality, not a missing §46 capability.

### 4 — Interrupt the caller — PASS

**(V)** A second injection run **without** `--wait-caller`, so the trainee's next WAV starts while
the caller is still speaking.

```
seq 124  offset 92542 ms  CALLER_UTTERANCE_INTERRUPTED
  {"turn_index": 7, "planned_text": "На каком этаже квартира?",
   "delivered_text": "На каком этаже квартира?", "cutoff_latency_ms": 2990,
   "delivered_audio_ms": 1504, "total_audio_ms_generated": 1536,
   "fact_ids_not_revealed": ["address.floor"]}
```

The mechanism is exactly what SPEC asks for: the caller was cut off mid-utterance **and the fact it
was about to reveal was withheld** (`fact_ids_not_revealed: ["address.floor"]`). The dedicated
re-run measured 19 barge-ins at p50 **62 ms**, p95 732 ms, `over_250ms_count` **3**
(`e2e-DEV_3060TI-20260922T144530930Z.json`) — so the capability passes and the §6.2 250 ms budget
is missed on 3 of 19, recorded as open item 6.

### 5 — Obtain information only by asking appropriate questions — PARTIAL

**(V)/(E)** Asking for a fact the caller does not have (`incident.fire_source`, policy
`NEVER_DISCLOSE`, caller knowledge `UNKNOWN`):

```
trainee (ASR_FINAL, seq 68): "Что именно горит в квартире?"
seq 69  DIALOGUE_INTERPRETED {"speech_act": "QUESTION",
  "requested_facts": [{"fact_id": "incident.fire_source", "explicit": true}]}
seq 70  FACT_GATE_EVALUATED  — fire_source not among the released facts
seq 72  CALLER_RESPONSE_GENERATED {"text": "У меня нет информации о том, что именно горит
  в вашей квартире."}
```

The gate held: an unknown, never-disclosed fact was asked for explicitly and the caller said it did
not know, rather than inventing a kitchen. The explicitly-asked path also worked
(`people.total_inside` released and delivered at seq 59, `FACTS_DELIVERED {"fact_ids":
["people.total_inside", "incident.smoke_visible"]}`).

**Why PARTIAL:** the two address questions in the corpus were classified
`speech_act: "INSTRUCTION"` with `requested_facts: []` ("Назовите улицу.", "И номер дома."), so the
gate released nothing and the caller answered "Я не знаю адреса и номера дома" — for facts it
*knows* (`address.street`/`address.house`, policy `ON_ASK`, knowledge `KNOWN`). A grammatically
imperative request for a fact is not recognised as a fact request. Open item 5; it is an
interpreter-prompt quality gap, not a missing gate.

### 6 — Manually fill a 112 incident card — PASS

**(T)** Twelve separate `PUT /sessions/{id}/operator/card/field` commands, one field each (SPEC §9
forbids a bulk write). Every one returned `200` with its own `CardRevision`, revisions 1-12, and
each appended one `CARD_FIELD_CHANGED`:

```
seq 147  offset 134696 ms  CARD_FIELD_CHANGED {"field_path": "address.floor", "new_value": 5,
  "value_type": "INTEGER", "revision_no": 6}
seq 152  offset 141430 ms  CARD_FIELD_CHANGED {"field_path": "address.street",
  "new_value": "улица Николаева", "revision_no": 11}
```

Fields set: `incident.type`, `address.{locality,street,house,entrance,floor,apartment}`,
`caller.phone`, `description.text`, `people.trapped_count`, `flags.threat_to_life`.

### 7 — Mistakes that remain real mistakes — PASS

**(T)** `address.house` was filled with **`72`** where the world truth is **`27`** (a transposition
an operator makes), and `address.floor` with the caller's own wrong belief, `5` (truth `4`).

Nothing corrected either one. They survived into the frozen snapshot (item 8), into what DDS
received (item 10) and into the score (item 14, `-4` and a critical failure). The report's
truth-vs-card diff names it:

```json
{"field_path": "address.house", "label_ru": "Дом", "world_value": "27",
 "card_value": "72", "verdict": "MISMATCH"}
```

### 8 — Select services and send the card — PASS

**(T)** `POST /operator/services/select` ×2 (`FIRE_RESCUE`, `AMBULANCE`) — each emitted both
`CARD_FIELD_CHANGED{recipients.services}` and `SERVICE_SELECTED` (seq 154-157) — then
`POST /operator/handoff/prepare` (`INTERVIEW → HANDOFF_PREPARATION`, seq 158) and
`POST /operator/handoff` → `201`.

```
seq 160  offset 148515 ms  HANDOFF_CREATED  card_values {"address.house": "72", "address.floor": 5,
  "incident.type": "FIRE", "address.street": "улица Николаева", ...}
seq 162/163  HANDOFF_RECEIVED ×2  (FIRE_RESCUE assignment 075ecd09-…, AMBULANCE 5f4292ea-…)
```

`content_sha256 0cc3feaf45f290d69e981c6072f8bc78df096b51d8cf073f7f8cc4a94a78415f`. One
`HANDOFF_CREATED` for one trainee action, one `HANDOFF_RECEIVED` per recipient — as §10 specifies.

### 9 — Move into the DDS stage — PASS

**(T)** `POST /operator/call/end {"reason": "OPERATOR_HANGUP"}` (seq 164,
`duration_ms 164774`), then `POST /operator/stage/complete`:

```
seq 165  STAGE_STATE_CHANGED   HANDED_OFF → STAGE_COMPLETED  (trigger complete_stage)
seq 166  ROLE_STAGE_COMPLETED  {"role_type": "OPERATOR_112", "duration_ms": 166450}
seq 167  ROLE_TRANSITION_STARTED {"to_role_type": "DDS", "pause_seconds": 20}
seq 168  ROLE_TRANSITION_COMPLETED {"incident_id": "dbbf45cc-…"}   <- same incident, no new one
seq 169  ROLE_STAGE_STARTED    {"role_type": "DDS", "order_index": 1, "initial_state": "RECEIVED"}
```

`POST /sessions/{id}/stage/continue` was then issued on a retry loop and succeeded once the 20 s
`transition_pause_seconds` had elapsed (`ROLE_TRANSITION_COMPLETED` at the same offset as the
transition's start in the log above, the runner having completed the pause); the pause lives in
`SessionPolicy`, not in a frontend timer.

### 10 — Receive exactly the submitted information — PASS

**(T)** `GET /sessions/{id}/dds/work-item` (`work-item.json`), quoted for the wrong number:

```json
{"assignment_id": "075ecd09-7d27-59d2-9f1d-401ddda2a782", "state": "RECEIVED",
 "card_values": {"address.house": "72", "address.floor": 5, "address.apartment": "45",
                 "address.street": "улица Николаева", "incident.type": "FIRE", ...},
 "recipient_services": ["FIRE_RESCUE", "AMBULANCE"],
 "handoff_content_sha256": "0cc3feaf45f290d69e981c6072f8bc78df096b51d8cf073f7f8cc4a94a78415f",
 "missing_field_paths": []}
```

**The DDS trainee is shown house `72`.** The world's `27` appears nowhere in the payload, and there
is no endpoint through which DDS could learn it. INV 3 holds on the real stack.

### 11 — Choose and dispatch resources — PASS

**(T)** `POST /dds/acknowledge` (seq 170, `latency_from_handoff_ms 25475`), `GET /dds/resources`
(11 units), `POST /dds/resources/selection/open`, three `POST /dds/resources/select`
(АЦ-1 `FIRE_SUPPRESSION`, АЛ-1 `HIGH_RISE_ACCESS`, СМП-11 `BASIC_LIFE_SUPPORT`), then
`POST /dds/resources/dispatch`:

```
seq 185  offset 182311 ms  RESOURCE_DISPATCHED {"callsigns": ["АЛ-1", "АЦ-1", "СМП-11"],
  "note_ru": "Направлены на пожар, Николаева 27."}
seq 193/195/196  RESOURCE_STATUS_CHANGED → EN_ROUTE   (207311 / 212311 / 222311 ms, per-unit turnout)
seq 197  АЦ-1 ON_SCENE  362311 ms       seq 200  АЦ-1 WORKING  392311 ms
```

The ETA model ran on its own clock afterwards, without further input.

### 12 — Respond to evolving incident events — PARTIAL

The world engine fired on time and the log is complete:

```
seq 172  offset 180554 ms  WORLD_EVENT_TRIGGERED {"kind": "TIMED", "title_ru": "Огонь перекинулся
  в комнату", "effect_kinds": ["MUTATE_WORLD_TRUTH","MUTATE_CALLER_BELIEF","CREATE_NOTIFICATION",
  "CHANGE_CALLER_EMOTION"]}
seq 175  NOTIFICATION_CREATED {"title_ru": "Развитие пожара", "severity": "WARNING",
  "audience_role": "DDS", "notification_id": "0549e382-5db5-5afa-999d-36a89bc07aba"}
seq 176/177  CALLER_EMOTION_CHANGED  FRIGHTENED → PANICKED, stress 0.6 → 1.0
seq 192  offset 208597 ms  NOTIFICATION_CREATED {"title_ru": "Повторное сообщение",
  "severity": "CRITICAL"}          <- ACTION_TRIGGERED, 60 s after HANDOFF_CREATED
```

**(T)** `GET /dds/notifications` returned the CRITICAL one, and — importantly — **without
`source_world_event_id`**, which is E20-A/R1 (INV 3 on the REST path) proven live while the
`notifications` table still carries the column:

```json
{"notification_id": "9a5471e7-a0b2-5c65-8b55-1c1201c603b1", "audience_role": "DDS",
 "severity": "CRITICAL", "title_ru": "Повторное сообщение",
 "body_ru": "Очевидцы сообщают о человеке на балконе 4-го этажа.",
 "created_at_offset_ms": 208597, "acknowledged_at_offset_ms": null}
```

**Why PARTIAL — two defects, both reproduced.**

*(a) A world-event notification is swallowed on every session after the first.* `Развитие пожара`
is in **our** event log at seq 175 with id `0549e382-5db5-5afa-999d-36a89bc07aba`, but the
`notifications` row carrying that id belongs to an **earlier, ABORTED** session's incident:

```
sim=# select id, audience_role, title_ru, incident_id from notifications ...
 0549e382-5db5-5afa-999d-36a89bc07aba | DDS | Развитие пожара | b7b27301-… (session 4579e295-…, ABORTED)
 9a5471e7-a0b2-5c65-8b55-1c1201c603b1 | DDS | Повторное сообщение | dbbf45cc-… (this walk)
```

The id is derived deterministically from the scenario/seed/world-event and **not** from the session
or incident, so the projection's idempotent upsert treats the second session's notification as one
it has already written. The DDS console never shows it. The `CRITICAL` one survived only because
its id folds in the handoff offset, which differs between sessions. The same happened again at
seq 213 (`Угроза взрыва`, 542015 ms).

*(b) A DDS trainee can see a notification they cannot acknowledge.*
`POST /dds/notifications/{id}/acknowledge` → `403 FORBIDDEN_FOR_ROLE`:
`"notification … is addressed to DDS, not to the caller's role"`.
`ListNotifications.audience_roles_for` walks **every stage the user plays** (so the DDS audience is
visible), while `AcknowledgeNotification._acting_role`
(`backend/app/application/dds/acknowledge_notification.py:148-155`) prefers
`participant.assigned_role_type` — which is `OPERATOR_112` for the whole of a
`FULL_CYCLE_SINGLE_TRAINEE` session — over the active stage's role. Two different role resolutions
for the same notification.

**(T)** `POST /dds/status-updates {"update_kind": "ON_SCENE_REPORT", …}` → `201` (seq 202) did work.

### 13 — Close the incident — PASS

The resolution condition (`FIRE_SUPPRESSION` unit `WORKING` **and** `sim_time ≥ 540000 ms`) was met
by the simulation itself at 541427 ms; the stage reached `RESOLVED` and
`POST /dds/close {"closure_reason": "RESOLVED", "comment_ru": "Пожар ликвидирован, пострадавшая
передана СМП."}` returned `200`, emitting `DDS_INCIDENT_CLOSED`, `ROLE_STAGE_COMPLETED`,
`STAGE_STATE_CHANGED`, ten `SCORING_RULE_EVALUATED` and `SESSION_COMPLETED`.

### 14 — Deterministic, evidence-backed assessment — PASS

**(I)** `GET /reports/{session_id}` → `docs/benchmarks/results/dod-walk-20260922/report.json`
(219 KB). **Total 45.0 / 78.0**, `checksum e0fbb0a2611633ed`, ten rules, **every rule carrying at
least one evidence pointer**:

| rule | points | evidence |
|:--|--:|:--|
| `fact_victim_inside` | 0 / 10 **critical failure** | `"Факт «people.victim_01.inside» не был получен за время сессии."` |
| `card_house_correct` | **−4** / 8 **critical failure** | `"Поле «address.house»: в карточке 72, в действительности 27 (NORMALIZED_DIGITS)."` (revision `43b04f35-…`) |
| `card_phone_present` | 3 / 3 | revision pointer |
| `card_no_false_floor` | 0 / 4 | `"Факт «address.floor» заявителем не сообщался — значение «5» противоречить ему не может."` |
| `services_fire_and_ambulance` | 12 / 12 | 2 events |
| `deadline_handoff` | 10 / 10 | 2 events |
| `workflow_answered_call` | 2 / 2 | 1 event |
| `resources_fire_high_rise` | 12 / 12 | 1 event |
| `status_on_scene_report` | **−2** / 5 | `"ON_SCENE_REPORT на 399160 мс. Задержка от RESOURCE_STATUS_CHANGED: 279160 мс при норме 60000 мс."` |
| `handoff_minimum_fields` | 12 / 12 | 1 event |

The two critical failures are exactly the two mistakes item 7 planted — the assessment caught the
operator's own errors from the log, with no model in the loop. `POST /instructor/sessions/{id}/report/release`
→ `200` (the saved JSON was fetched before the release and therefore records `released: false`).

One evaluator defect fell out of this and is recorded as open item 7: `status_on_scene_report`
measured the delay from the **first** `RESOURCE_STATUS_CHANGED` in the whole log (120000 ms — a
unit merely becoming *available* by world-event schedule, nothing to do with arrival) rather than
from the nearest preceding one, making `REQUIRED_STATUS_UPDATE` unsatisfiable in practice.

### 15 — Replay the timeline, transcript and relevant audio — PASS

Same report: **`timeline` 228 entries** (each with `seq_no`, `monotonic_offset_ms`, UTC timestamp,
actor and a Russian `summary_ru`), **`transcript` 18 segments, 16 carrying an `audio_segment_id`**,
`audio_segments` 17.

**(I)** A real HTTP Range request against `GET /sessions/{id}/audio/{audio_segment_id}`:

```
audio_segment_id  be754c17-fb9b-454b-b9fb-c4b9bdfba523
GET (no Range)    200  105 644 bytes  Accept-Ranges: bytes  Content-Type: audio/wav
GET Range: bytes=0-1023
                  206  1 024 bytes    Content-Range: bytes 0-1023/105644
```

### 16 — See model/inference latency metrics — PARTIAL

**(I)** `GET /reports/{session_id}/inference-metrics` → `200`, one row per real model call
(`inference-metrics.json`), e.g.

```json
{"component": "ASR", "provider": "gigaam", "model_version": "v3_e2e_ctc",
 "input_duration_ms": 1892, "total_latency_ms": 243, "turn_index": 10}
{"component": "LLM_INTERPRETER", "provider": "Qwen3-4B", "input_tokens": 1897,
 "output_tokens": 31, "total_latency_ms": 209}
{"component": "LLM_GENERATOR", "input_tokens": 629, "output_tokens": 41, "total_latency_ms": 394}
{"component": "TTS", "provider": "piper", "output_audio_ms": 4598, "ttft_ms": 19,
 "total_latency_ms": 8028, "realtime_factor": 1.746}
```

The report's own `timing_metrics` block:

```json
{"turn_count": 10, "speech_end_to_first_audio_ms_p50": null, "speech_end_to_first_audio_ms_p95": null,
 "asr_latency_ms_p50": 243.0, "llm_ttft_ms_p50": null, "tts_first_audio_ms_p50": 19.0,
 "barge_in_cutoff_ms_p95": 2990.0, "fallback_count": 0}
```

**Why PARTIAL:** SPEC §27's headline metric is **`null` in the report** even though the same
session's event log yields it turn by turn (the injection CLI printed 1582 / 1221 / 1513 / 4532 /
1600 / 1200 ms from the very same events, and `benchmark_e2e.py` computed p50 1566 / p95 4622 ms
over 29 turns of the re-run). `llm_ttft_ms_p50` is also `null` — the LLM rows carry
`first_output_at` but no `ttft_ms` for a non-streaming call. The one number a demo audience will
ask for is the one the report does not show. Open item 8.

## 4. Open items (dated 2026-09-22; none fixed by E20-C — all outside this task's files)

| # | item | where | §46 impact |
|---:|---|---|---|
| 1 | `make up` cannot start `llama-server`: `SIM_LLAMA_SERVER_BIN` defaults to a name not on the image's `PATH` (`/app/llama-server`) | `infra/docker-compose.yml` (llama-server `environment`) | blocks the documented demo path — **fixed E20-G 2026-09-22** — compose defaults `SIM_LLAMA_SERVER_BIN` to `/app/llama-server`, verified by `docker run --rm --entrypoint ls <pinned image> -l /app/llama-server` |
| 2 | `.env.example`'s `MODELS_DIR=./models` resolves to `infra/models` under compose; the models volume mounts empty | `.env.example`, and its own comment | blocks the documented demo path — **fixed E20-G 2026-09-22** — `.env.example` says `MODELS_DIR=../models` and both it and the compose comment say the path is relative to `infra/` |
| 3 | `make up` always exits 1: the `frontend` healthcheck runs `wget`, absent from that image | `infra/docker-compose.yml` (frontend `healthcheck`) | the documented demo path never reports success — **fixed E20-G 2026-09-22** — the healthcheck is a `node -e fetch(...)` probe (the image has node and neither wget nor curl); proven with `docker exec` exit 0 |
| 4 | `voice-agent` image has no `livekit` extra, so `SIM_CALL_TRANSPORT=livekit` cannot connect in compose | `workers/voice_agent/Dockerfile` (`VOICE_AGENT_EXTRAS`) | **blocks every voice item under `make up`** — **fixed E20-G 2026-09-22** — `VOICE_AGENT_EXTRAS` gains `transport-livekit`; image rebuilt and smoke-tested |
| 5 | the demo scenario's `caller_profile.voice_id: ru_female_adult_01` is rejected by the profile's own TTS default (`qwen3_tts` accepts only the four vendor speakers) | `scenarios/examples/apartment-fire/v1.yaml` vs `backend/app/inference/tts/qwen3_tts.py:337` | item 3 — caller silent on the shipped profile — **fixed E20-G 2026-09-22** — `voice_id` is a scenario-LOGICAL id resolved through the profile's `tts.voice_map`/`tts.default_voice`; an unmapped id warns once and uses the default, never raises |
| 6 | the configured TTS **fallback** provider is never warmed, so INV 14's retry always fails (`PiperTTS.warm_up() must be called before stream()`, surfacing as an 8000 ms `TIMEOUT`) | `workers/voice_agent/voice_agent/main.py:508-532` (`_warm_tts` warms only the primary) | item 3 — a primary-TTS failure means silence, not a fallback — **fixed E20-G 2026-09-22** — `VoiceAgent._warm_tts` warms the configured fallback too; a fallback warm-up failure is one WARN and a `fallback unavailable` detail on `voice:health:tts`, never fatal |
| 7 | barge-in over budget on the real transport: 3 of 19 cuts over 250 ms, worst 732 ms (one walk sample 2990 ms) | `docs/benchmarks/e2e.md` §3.1 | item 4 quality (capability passes) |
| 8 | an imperative fact request ("Назовите улицу") is interpreted as `INSTRUCTION` with `requested_facts: []`, so a known `ON_ASK` fact is never released | interpreter prompt, `backend/app/application/dialogue/` | item 5 quality — **fixed E20-H 2026-09-22: not a prompt change (R12 out of scope); the labelled eval corpus gained this case + 2 siblings so the gap is measured (`benchmarks/interpreter_eval/ru_operator_utterances.yaml`, `benchmarks/data/llm/interpreter_cases.jsonl`); recorded as a known 2B limitation, `docs/AUDIT.md` §3 item 28. The underlying model behaviour is unchanged.** |
| 9 | world-event notification ids are deterministic per scenario/seed and not per incident, so the same notification is written once globally and is invisible in every later session | `notifications` projection / notification id derivation | item 12 — **fixed E20-H 2026-09-22: `uuid5` derivation in `app/domain/world/apply.py` now includes `state.incident_id` (random per session); bite-proof test `backend/tests/unit/domain/world/test_apply.py::test_notification_and_radio_ids_are_distinct_across_sessions`; sibling snapshot/assignment/resource id derivations checked and found not to collide (`docs/AUDIT.md` §3 item 25).** |
| 10 | `listNotifications` and `acknowledgeNotification` resolve the caller's role differently; a DDS-stage trainee gets `403` acknowledging a notification they can read | `backend/app/application/dds/acknowledge_notification.py:148-155` | item 12 — **fixed E20-H 2026-09-22: `acknowledge_notification.py` now calls `list_notifications.audience_roles_for` — one shared role-resolution function; test `backend/tests/api/modes/test_notification_role_resolution.py::test_a_full_cycle_trainee_lists_and_acknowledges_the_dds_notification` (`docs/AUDIT.md` §3 item 26).** |
| 11 | `REQUIRED_STATUS_UPDATE` anchors on the **first** matching event in the log, not the nearest preceding one, so the rule is unsatisfiable once any early `RESOURCE_STATUS_CHANGED` exists | scoring evaluator | item 14 (scoring fairness) — **fixed E20-H 2026-09-22: every qualifying reference event now opens its own window per the manager's ruling (`backend/app/domain/scoring/evaluators/required_status_update.py`, HLD 10 §10.14 #9 reading 6 rewritten); bite-proof tests in `backend/tests/unit/domain/scoring/test_evaluators.py` (`docs/AUDIT.md` §3 item 27).** |
| 12 | the report's `timing_metrics.speech_end_to_first_audio_ms_p50/p95` and `llm_ttft_ms_p50` are `null` although the event log yields them | report timing-metrics assembly | item 16 — **fixed E20-H 2026-09-22 (partially): `speech_end_to_first_audio_ms_p50/p95` root cause was `voice_agent.wiring.build_pipeline` building two different `MetricsRecorder` instances (ASR side vs TTS side) — fixed by sharing one; test `workers/voice_agent/tests/test_dialogue_wiring.py::test_build_pipeline_shares_one_metrics_recorder_between_asr_and_tts` + `backend/tests/api/reports/test_session_report.py::test_speech_end_to_first_audio_percentiles_are_present_over_three_turns`. `llm_ttft_ms_p50` stays `null` **by construction** (non-streaming LLM calls) — documented, not a bug (`docs/hld/openapi.yaml`, `docs/AUDIT.md` §3 item 5 and §27's main paragraph, item 11).** |
| 13 | preflight check 2 requires the whole VRAM budget to be **free** on a warm stack; check 4 dials the profile's container LLM URL on a host run; check 5 fails on a synthesised tone | `backend/app/cli/preflight.py` | §38 preflight is red on a healthy stack — **fixed E20-G 2026-09-22** — check 2 is stack-aware, check 4 dials `Settings.llm_base_url`, check 5 requires a Cyrillic word and `.env.example` points the warm-up at `models/warmup/warmup_ru.wav` |
| 14 | README's "source `.env`" host-run instruction breaks on the two JSON-list variables; `make run-llama-server` does not apply `SIM_MODELS_ROOT` | `README.md`, `infra/scripts/llama-server-entrypoint.sh` | host-run path friction — **fixed E20-G 2026-09-22** — README/RUNBOOK say never to source `.env` (Settings reads it); `make run-llama-server` resolves the profile's model path onto this host via `make profile-env PROFILE_MODELS_ROOT=...` |

## 5. Teardown

All processes this walk started were stopped: the host voice agent, the host `llama-server` (8101),
the host Qwen3-TTS worker (8112), the host API (8100) and the compose `backend` / `frontend` /
`llama-server` / `voice-agent` containers; `make dev-infra-down` removed the dev infra.
`nvidia-smi --query-compute-apps` prints nothing and ports 8100 / 8101 / 8112 / 8113 / 5173 /
7880-7882 / 15432 / 16379 are free. The owner's processes on 8000 / 8001 / 8011 / 8012 were never
touched. The GPU lock was released.

---

## 6. Re-walk through `make up` (E20-G, 2026-09-22 20:07 → 21:40)

E20-C could not use the documented `make up` path at all. This section is the re-walk after
E20-G's fixes. It is **not** a second sixteen-item walk: it re-tests exactly what blocked the
first one, and it stops where a defect outside E20-G's files stops it.

### 6.1 `make up` now works — §46 items 1-2 reachable through the documented path

```
$ cp .env.example .env            # + ONLY the documented real-run edits (README):
                                  #   SIM_{VAD,ASR,LLM,TTS}_PROVIDER, SIM_CALL_TRANSPORT
$ TTS_COMPOSE_PROFILE=qwen3-tts make up
 Container sim112dev-postgres-1 Healthy
 Container sim112dev-redis-1 Healthy
 Container sim112dev-livekit-1 Healthy
 Container sim112dev-llama-server-1 Healthy
 Container sim112dev-backend-1 Healthy
 Container sim112dev-frontend-1 Healthy
 Container sim112dev-tts-qwen3-1 Healthy
 Container sim112dev-voice-agent-1 Healthy
MAKE_UP_EXIT=0
```

**All eight services healthy, `up -d --wait` exit 0** — open items 1-4 of §4 are closed. The
`llama-server` container starts (`/app/llama-server`), the models volume mounts the real
`models/` (`MODELS_DIR=../models`), the `frontend` healthcheck passes (`node -e fetch(...)`), and
the `voice-agent` image carries `livekit==1.1.19`.

### 6.2 `make preflight` — three more checks green, three still red

Preflight is a HOST command, and under `make up` the host can reach neither `llama-server` nor the
voice agent's loopback preflight port (HLD 60 §9: neither publishes a port). Run from the host it
therefore reports `ConnectError` for checks 4/5/6 and, with `SIM_MODELS_ROOT` unset, a missing
`/models` for check 3. Run **inside the `voice-agent` container** — the one process that can see
every dependency — it reports:

```
$ docker compose … exec voice-agent python -m app.cli preflight
[PASS]  1. cuda_gpu_available: 1 GPU(s): NVIDIA GeForce RTX 3060 Ti
[FAIL]  2. expected_gpu_detected: … 464 MB free < 7680 MB required (vram_budget_mb 7168 + min_vram_margin_mb 512)
[PASS]  3. model_files_exist: 5 file(s) present
[PASS]  4. llm_responds: Qwen3.5-2B
[PASS]  5. asr_responds: Проверка готовности перед началом смены.
[FAIL]  6. tts_responds: GET /preflight/tts -> 503
[PASS]  7. postgresql_responds: SELECT 1 ok; exactly one alembic head
[PASS]  8. redis_responds: PING ok; SET/GET/DEL ok
[PASS]  9. livekit_responds: GET http://livekit:7880 -> 200
[FAIL] 10. scenario_validation: no scenario file found under scenarios/examples
[SKIP] 11. audio_devices_accessible
[SKIP] 12. llama_server_binary: SIM_LLAMA_SERVER_BIN is not set
```

* **check 3 and check 4 now PASS** (they were the host-run failures §2 recorded): the model paths
  resolve and the check dials `Settings.llm_base_url`.
* **check 5 now PASSES with real Russian speech**, `Проверка готовности перед началом смены.` —
  the tone fixture is gone and the Cyrillic-word bar is met.
* check 2 is a truthful FAIL here: 464 MB free with three models resident. Its stack-aware branch
  needs the voice agent's endpoints to answer 200, and check 6 is 503, so the pre-start rule
  applies.
* check 10 fails because the `voice-agent` image does not copy `scenarios/` (it has no reason to;
  preflight does). **Open, E20-G did not fix it**: the scenario check belongs to a process that has
  the repository — the backend image — which cannot reach the voice agent's loopback endpoints.
  Preflight has no single vantage point under compose today.

### 6.3 The blocker: `tts-qwen3` cannot synthesise in its own image

`/health` answers `{"loaded": true, "model": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", …}` — the
weights load. `/warm_up` and `/synthesize` answer **503 in 0.3 s**, verbatim from the worker log:

```
RuntimeError: Failed to find C compiler. Please specify via CC environment variable or set
              triton.knobs.build.impl.
/bin/sh: 1: sox: not found
SoX could not be found!
```

`qwen_tts` JIT-compiles Triton kernels and shells out to `sox`; `workers/tts_qwen3/Dockerfile`
installs neither a C toolchain nor `sox` (`which cc gcc g++` inside the container prints nothing).
`TORCHDYNAMO_DISABLE=1` was tried and does not help — the Triton use is direct, not via Dynamo.
So `voice:health:tts` never reaches READY and, with the shipped `SIM_REQUIRE_INFERENCE_READY=true`,
`POST /sessions/{id}/start` refuses:

```
503 {"detail":"a required inference service is not READY and REQUIRE_INFERENCE_READY is true",
     "code":"INFERENCE_NOT_READY"}
```

**§46 item 3 therefore stays PARTIAL** and item 2 could not be re-exercised through `make up`.
Both are blocked by two missing system packages in a file outside E20-G's scope. The two causes
E20-C named for the silent caller ARE fixed and one of them is visible in this very run's agent
log — the logical voice id no longer raises:

```
WARNING:app.inference.tts.qwen3_tts:TTS voice_id 'ru_female_1' is not in qwen3_tts's
  tts.voice_map; falling back to the profile's tts.default_voice 'Serena'
  (add the mapping to the active model profile to silence this)
```

### 6.4 Two further defects found on the documented path, both fixed here

* **`.env.example` shipped host-relative model paths** (`SIM_ASR_MODEL_DIR=models/…` and four
  siblings). An explicitly-set `SIM_*` beats the profile (HLD 60 §2.0), so inside every container
  they overrode the profile's `/models/…` and the agent died with
  `ModelNotAvailableError: GigaAM checkpoint not found at models/gigaam-v3-e2e_ctc`. Now commented
  out; the profile names the paths and `SIM_MODELS_ROOT` maps them for a host run.
* **`.env.example` shipped `SIM_TTS_FALLBACK_PROVIDER=none`**, overriding every profile's
  `tts.fallback_provider` — a real run had INV 14's retry disabled. Now commented out.

### 6.5 Still open after this re-walk (not E20-G's files)

| # | item | where |
|---:|---|---|
| 15 | `tts-qwen3` image has no C compiler and no `sox`, so Qwen3-TTS cannot synthesise under `make up` | `workers/tts_qwen3/Dockerfile` |
| 16 | `make demo-init` fails from a fresh `.env`: `seed_users` reads the three `SIM_SEED_*_PASSWORD` from `os.environ`, never from `.env` — `error: SIM_SEED_TRAINEE_PASSWORD is unset or empty` | `backend/app/tools/seed_users.py`, `Makefile` `seed-users` |
| 17 | `seed_users` does not refresh an existing user's password hash, so a re-seed against a surviving `postgres-data` volume silently leaves the old password (login 401) | `backend/app/tools/seed_users.py` |
| 18 | preflight has no vantage point under compose: the host cannot reach `llama-server`/`voice-agent` (no published ports), the voice-agent image has no `scenarios/`, the backend image cannot reach the agent's loopback port | `infra/docker-compose.yml`, `backend/app/cli/preflight.py`, HLD 60 §9 |
| 19 | `workers/voice_agent/tests/test_livekit_contract.py::test_connect_publish_receive_and_cancel` fails: `LiveKitCallTransport.__init__() missing 2 required keyword-only arguments: 'clock' and 'started_at'` (E20-F/R13 changed the constructor; this test was not updated) | `workers/voice_agent/tests/test_livekit_contract.py` |

### 6.6 Teardown

`make down` removed all eight containers and the network; the `.env` this re-walk created was
deleted; `infra/models` does not exist; `nvidia-smi --query-compute-apps` prints nothing and
7842 MiB is free; ports 8100/8101/8112/8113/5173/7880/7881/15432/16379 are all free; the owner's
8000/8001/8011 were never touched and are still listening.

## 7. E20-I — the documented path, end to end (2026-09-22 23:37 → 2026-09-23 00:09)

Done by the manager directly (single-agent), after E20-G left §46 item 3 blocked on the `tts-qwen3`
image. Every run below started from **nothing**: stack down, no `.env`, then exactly README's
"Fresh clone to a working demo" — `cp .env.example .env`, the five README provider edits (the diff
in `run-proof.log` shows no other change), `make demo-init`, `TTS_COMPOSE_PROFILE=qwen3-tts make
up`, `make preflight`, one real call. Driver and evidence:
`docs/benchmarks/results/dod-walk-20260922/e20i/` (`run-proof.sh`, `proof.py`, `run-proof.log`,
`events-caller-excerpt.json`, `events-instructor-full.json` — read as the INSTRUCTOR, `inject.log`).
All GPU work under `flock /tmp/teamwork-112-maxxing/gpu.lock`.

### 7.1 Result of the final run (round 4)

* `make demo-init` from a fresh `.env`: migrate, seed (passwords read from `.env`), scenario import.
* `make up`: **exit 0 in 101 s**, all eight services healthy; `GET /health/ready` **READY** at once.
* `make preflight` (runs inside the voice-agent container): **10 PASS, 2 SKIP, exit 0** — check 2
  in its stack-aware form (`2434 MB free >= 1608 MB`), check 5 on real Russian speech, check 6
  `1840 ms of audio`.
* One real call, session `ce835582-a6f8-47f1-9199-5beec49e8652`, three trainee WAVs through
  `python -m voice_agent.tools.inject --wait-caller` (exit 0):

```
seq 15 +7278 ms  ASR_FINAL                 "Служба 112. Что у вас случилось?"
seq 20 +8636 ms  CALLER_RESPONSE_GENERATED "У меня в квартире горит. Видно дым. Есть риск возгорания."
seq 21 +10305 ms CALLER_TTS_STARTED        provider qwen3_tts, voice_id_native "Serena"
seq 22 +18797 ms CALLER_TTS_ENDED
seq 23 +18842 ms FACTS_DELIVERED           ["incident.type", "incident.smoke_visible"]
seq 59 +45598 ms CALLER_RESPONSE_GENERATED "Я не знаю, что горит. У меня в квартире дым. …"
seq 60 +47229 ms CALLER_TTS_STARTED        provider qwen3_tts, voice_id_native "Serena"
```

**§46 item 3 is PASS on the documented path with the shipped profile**: the caller speaks Russian
with the owner's chosen Qwen3-TTS (0.6B, `Serena`), facts are delivered only after uninterrupted
audio. Observed and correct, not a defect: the address WAV contains a pause, so the trainee's
"Назовите улицу." / "И номер дома." became two turns and two caller replies queued; Qwen3-TTS is
serial, so the second waited past its guard (`MODEL_ERROR{TIMEOUT}`), INV 14's fallback spoke it
with Piper (`voice_id_native "ru_RU-irina-medium"`), and the trainee's next turn barged in
(`CALLER_UTTERANCE_INTERRUPTED`). Quality note (2B model, already an AUDIT item): the reply to
"Назовите улицу." repeated the first reply.

### 7.2 What the four rounds found, and the fixes (all in the E20 commit)

| # | defect found on the documented path | fix |
|---:|---|---|
| a | `tts-qwen3` image: no C compiler (qwen_tts JIT-compiles Triton kernels) and no `sox` → 503 (open item 15) | `workers/tts_qwen3/Dockerfile`: `build-essential sox` in a late layer; `/warm_up` 200 in 25.9 s, a Russian line in 4.3 s |
| b | the voice agent's first `/warm_up` of a cold worker used the 8 s per-request timeout (a cold load + generation is ~26 s) → TTS started NOT_READY | `Qwen3TTS(warmup_timeout_ms=…)` from the profile's `warmup.timeout_ms` (`Settings.tts_warmup_timeout_ms`), + tests |
| c | the Piper FALLBACK kept `Settings`' host-relative voice path inside the container → INV 14 had no warmed fallback | `apply_profile` overlays `tts.fallback_model_path` when the fallback is Piper, + test |
| d | **every Qwen3-TTS turn timed out**: the sink's first-chunk guard is 1500 ms, but Qwen3-TTS is whole-utterance (first audio p50 4130 / p95 11078 / max 14771 ms, E19) → silent caller | additive `tts.first_chunk_timeout_ms` / `tts.timeout_ms` in the profile, DEV_3060TI 12000 / 15000 (sized from that measurement); `.env.example` no longer pins them |
| e | caller said `}I не знаю…` — the E19 Cyrillic rule passes a line that *contains* Cyrillic | grammar `speech-char` excludes braces, brackets, angle brackets, backslash and backtick; validator backstop → `SCHEMA_INVALID`; bite-proven |
| f | a stale `voice:health:fatal` latch from an earlier run (Redis volume survives `make down`) refused `startSession` | by design (E18): cleared with the documented ADMIN `clear-fatal` (RUNBOOK); `start-refused.txt` is that round's evidence |
| g | `DEV_3060TI` measured its 5560 MB peak with the 0.6B TTS but shipped `model_variant: null` → the worker loaded 1.7B; `make models` only downloads 0.6B | measured 1.7B: **7448 MB > the 7168 MB budget**, LLM pushed to GPU_PARTIAL → DEV ships `0.6B`; the variant now reaches the worker via `make profile-env` (docs/benchmarks/vram.md §2.3) |
| h | `.env.example` silently overrode the profile (LLM model name, interpreter timeout, ASR/TTS device settings, TTS voice, TTS guards, TTS variant) | those lines commented as profile-owned; only the README's provider switches remain |
| i | `make demo-init` failed from a fresh `.env` (open item 16); `make demo-inject` the same | `settings.read_env_value` (environment, then `.env`) used by `seed_users` and the inject CLI; `demo-init` starts compose `postgres` itself |
| j | inject CLI exited 134 after a successful run (LiveKit's native runtime panics at interpreter shutdown) | flush + `os._exit` at the CLI entry point |

Open items of §6.5: **15** fixed (a); **16** fixed (i); **17** not a defect — a re-seed does rotate
the hash (the upsert sets `password_hash` on conflict; `test_seed_users_rotation.py` proves it
against real PostgreSQL); **18** fixed — under compose `make preflight` runs inside the voice-agent
container, `scenarios/` mounted read-only (RUNBOOK "Where it runs"); **19** fixed — the contract
test passes `clock`/`started_at`.

Image builds: `workers/voice_agent/Dockerfile` and `backend/Dockerfile` now install third-party
dependencies from the lock + manifests before copying source, with a BuildKit uv cache — a
source-only rebuild took **36-67 s** instead of E20-G's ~38 min, and a PyPI timeout mid-download
resumes instead of restarting.

### 7.3 Teardown

`make down` (all eight containers and the network), `.env` deleted, `infra/models` absent,
`nvidia-smi --query-compute-apps` empty (7842 MiB free), ports 8100/8101/8112/8113/8180/5173/7880/
7881/15432/16379 free; the owner's 8000/8001/8011 untouched and listening.


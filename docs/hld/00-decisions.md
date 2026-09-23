# HLD 00 — Design frame (decided; do not relitigate inside a task)

Source of requirements: `docs/SPEC.md` (owner's spec, verbatim, §1–§47). This file fixes every
cross-cutting design choice so that the other HLD artifacts and every TBD epic agree on names and
boundaries. Where this file and the spec disagree, the spec wins and the disagreement is escalated.

Language rule: code, identifiers, docs, event names — English. Trainee-facing UI strings, scenario
content, caller persona and caller speech — Russian.

## D1. Repository and tooling (§33, §35, §36)

- Layout exactly as SPEC §35: `frontend/`, `backend/app/{api,domain,application,infrastructure,inference,db,config}`,
  `backend/tests/`, `workers/voice_agent/`, `scenarios/{schemas,examples}`, `benchmarks/`, `infra/`, `docs/`.
- Python **3.12** (`/usr/bin/python3.12`; the conda `python3` on PATH is 3.10 and must not be used),
  managed by **uv** as one workspace: root `pyproject.toml` (workspace members `backend`,
  `workers/voice_agent`, `benchmarks`), one `uv.lock`, one `.venv`. Backend import package is `app`;
  the worker's is `voice_agent` and depends on `app` as a workspace dependency (it reuses the
  application layer in-process — see D9).
- Heavy ML dependencies (torch, gigaam, onnxruntime, TTS models) are **optional extras**
  (`asr-gigaam`, `asr-whisper`, `vad-silero`, `tts-piper`, `tts-qwen3`, `tts-chatterbox`); adapters
  import them lazily. The gate installs base + dev only and runs entirely on fake providers.
- Lint/format `ruff`; types `mypy --strict` on `app/domain` and `app/application` only; tests `pytest`
  + `pytest-asyncio`. Frontend: npm, Vite, TypeScript strict, vitest, eslint.
- `make gate` = ruff → mypy (domain, application) → import-boundary check (D2) → scenario validation
  → pytest (unit + integration) → frontend `tsc --noEmit` + vitest + `vite build`. Integration tests
  use real PostgreSQL 16 and Redis 7 from `infra/docker-compose.test.yml` (ports 55432 / 56379,
  tmpfs volumes); `make gate` brings them up with `--wait` and leaves them running.
- Full stack: `infra/docker-compose.yml` with services `postgres`, `redis`, `livekit`, `backend`,
  `frontend`, `llama-server`, `voice-agent` (SPEC §36 names, literally). GPU services use the
  NVIDIA runtime. All secrets/config through `.env` (`.env.example` tracked, `.env` ignored).

## D2. Layering and the import-boundary check (§33, §2, §3)

```
api            -> application -> domain
infrastructure -> application, domain      (implements ports)
inference      -> application, domain      (implements ports)
voice_agent    -> application, inference, infrastructure
```

- `app/domain` is pure Python + Pydantic v2: no FastAPI, SQLAlchemy, LiveKit, Redis, httpx, no I/O,
  no wall clock, no `random` module-level state. Time and randomness are passed in.
- `app/application` holds use-case services, ports (`typing.Protocol`), the Unit of Work, the
  simulation runner and the dialogue turn pipeline. It may not import `infrastructure`, `inference`
  adapters, `api`, or any vendor SDK.
- A gate script `backend/tools/check_imports.py` (stdlib `ast`) enforces the table above and fails on
  any forbidden import. It is part of the architecture, not a nicety.

## D3. The four information layers are four types and four storage locations (§3)

| Layer | Domain type | Storage | Written by |
|:--|:--|:--|:--|
| WorldTruth | `WorldTruth` | `incident_world_states` (1 row / incident, `revision`, `facts` JSONB) | scenario instantiation, WorldEvent engine only |
| CallerBelief | `CallerBelief` | `incident_caller_beliefs` (1 row / incident, `revision`, `facts` JSONB, `emotion` JSONB) | scenario instantiation, WorldEvent engine only |
| OperatorCard | `OperatorCard` | `incident_cards` + `incident_card_revisions` | trainee commands only |
| DDSReceivedSnapshot | `HandoffSnapshot` | `handoff_snapshots` (immutable; DB trigger rejects UPDATE/DELETE) | handoff use case only, copied from OperatorCard by value |

- No type inherits from, wraps, or holds a reference to another layer's object. Conversions are
  explicit deep copies inside one named use case each.
- **Visibility is structural, not conventional.** Every role's read model is built by a
  `DataVisibilityPolicy` from a whitelist of sources. The DDS application services and API handlers
  are constructed **without** a WorldTruth repository: they cannot read it because they are never
  given it. (SPEC §42 test 3 asserts this on the constructor signature and on the API payload.)
- Same for the LLM boundary: `CallerPromptBuilder` accepts only `AllowedFactsPackage` + persona +
  recent turns; it has no parameter through which a `WorldTruth` or `ScenarioVersion` could arrive.

## D4. Scenario files and the fact model (§4, §5, §6)

- `Scenario` (identity: slug, title) and `ScenarioVersion` (content) are separate tables and types.
  Source files: `scenarios/examples/<slug>/v<N>.yaml`, one file per version, validated by Pydantic
  models in `app/domain/scenario/`. JSON Schema is exported to `scenarios/schemas/scenario_version.schema.json`
  by a script and the gate fails if the committed schema is stale.
- A ScenarioVersion file has exactly the SPEC §4 top-level keys. Fact data is split across three of
  them and joined at load time into one `FactDefinition` per `fact_id`:
  - `world_truth.facts[fact_id]` → `world_value`, `value_type`, `label_ru`
  - `caller_knowledge.facts[fact_id]` → `caller_value`, `knowledge` (KNOWN | UNKNOWN | INCORRECT_BELIEF | UNCERTAIN), `certainty` 0..1
  - `disclosure_rules.facts[fact_id]` → `policy` (SPONTANEOUS | ON_ASK | ONLY_IF_EXPLICITLY_ASKED | NEVER_DISCLOSE),
    `aliases_ru[]`, `categories[]`, optional `available_after` (sim-time or world-event condition)
- Load-time validation (a scenario that fails cannot start a session): every caller fact exists in
  world truth; KNOWN ⇒ `caller_value == world_value`; UNKNOWN ⇒ `caller_value is None`;
  INCORRECT_BELIEF ⇒ `caller_value` set and `!= world_value`; every fact referenced by scoring rules,
  world events, expected_response and card mappings exists; resource ids unique; role_chain roles are
  registered RoleModules; scoring max_points > 0; event graph has no unconditional cycles.
- The DB stores the full validated document in `scenario_versions.content` JSONB plus a `content_sha256`.
  `scenario_versions.locked_at` is set in the same transaction that creates the first session using it;
  a DB trigger rejects any UPDATE of `content`/`content_sha256` once `locked_at` is not null (§42 test 6).
  Re-importing a changed file under an existing version number is rejected; bump the version.
- `CallerProfile` carries every SPEC §6 field. `baseline_emotion` is scenario data; `current_emotion`,
  `stress_level` live in CallerBelief state and change only through deterministic
  `EmotionRule`s (scenario data: trigger → delta), applied by the world engine / turn pipeline code.

## D5. Event sourcing and persistence (§8, §30)

- One append-only table `session_events` with the SPEC §8 fields. `seq_no` is allocated under a row
  lock: `simulation_sessions.next_seq_no` is incremented with `SELECT … FOR NO KEY UPDATE` in the
  same transaction as the insert; `UNIQUE(session_id, seq_no)`. A DB trigger rejects UPDATE and
  DELETE on `session_events`. Several processes (backend, voice-agent) append safely.
  `FOR NO KEY UPDATE` is the one lock mode any writer takes on a `simulation_sessions` row — the
  aggregate lock of `get_for_update` too — and a writer that takes both takes the aggregate lock
  first. `FOR UPDATE` would conflict with the `FOR KEY SHARE` that a foreign key from
  `audio_segments` / `transcript_segments` / `dialogue_turns` / `inference_metrics` already holds on
  that row, turning the allocation into a lock upgrade that deadlocks (E20 R14; `20-db-schema.md`
  §20.8 carries the full account).
- Every use case runs in one Unit of Work: load aggregate → call pure domain method → get
  `(new_state, [DomainEvent])` → persist materialized state **and** append events in one transaction →
  after commit, publish event envelopes to Redis channel `session:{id}:events`.
- Materialized tables exist for reads; the event log is the audit source. Scoring reads **only**
  `(ScenarioVersion, ordered SessionEvents)` — never the materialized tables (§28, §42 tests 9–11).
  Therefore every event payload must be self-sufficient for scoring (e.g. `CARD_FIELD_CHANGED`
  carries `revision_id`, `field_path`, `previous_value`, `new_value`).
- `monotonic_offset_ms` = ms since `SESSION_STARTED`, from the injected `Clock` port (never `time.time()` in domain).
- Event type enum: every name in SPEC §8, plus (additive, allowed by "at least"): `SESSION_ABORTED`,
  `STAGE_STATE_CHANGED`, `ROLE_TRANSITION_STARTED`, `ROLE_TRANSITION_COMPLETED`, `SERVICE_DESELECTED`,
  `RESOURCE_DESELECTED`, `DDS_STATUS_UPDATE_SENT`, `DDS_INCIDENT_CLOSED`, `NOTIFICATION_CREATED`,
  `NOTIFICATION_ACKNOWLEDGED`, `RADIO_MESSAGE_CREATED`, `WORLD_TRUTH_MUTATED`, `CALLER_BELIEF_MUTATED`,
  `CALLER_EMOTION_CHANGED`, `CALL_ENDED`, `DIALOGUE_INTERPRETED`, `FACT_GATE_EVALUATED`,
  `FACTS_DELIVERED`, `TRANSPORT_DISCONNECTED`, `TRANSPORT_RECONNECTED`, `INFERENCE_HEALTH_CHANGED`.
- Actor types: `TRAINEE`, `INSTRUCTOR`, `SIMULATION`, `MODEL`, `SYSTEM`.
- All SPEC §30 tables exist with UUID PKs, FKs and indexes; additional tables from this file
  (`incident_world_states`, `incident_caller_beliefs`, `notifications`) are additive. Alembic, one
  linear history, async SQLAlchemy 2 (`asyncpg`). ORM classes live in `app/db/models/`; mapping
  to/from domain types in `app/infrastructure/persistence/`.

## D6. State machines and the role abstraction (§7, §13, §14)

- Generic `StateMachine[S]` in domain: explicit transition table `{(from, trigger): to}`, guard
  callables, raises `InvalidTransitionError`. Session, Operator112 stage and DDS stage each declare a
  table with exactly the SPEC §7 states. Only backend use cases fire triggers.
- `RoleModule` (domain Protocol): `role_type`, `permissions`, `available_actions(stage_state)`,
  `state_machine`, `visibility_policy`, `ui_schema`. Registry `ROLE_MODULES`. `Operator112Module` and
  `DDSModule` are full; `EDDSModule` is a registered stub with `implemented = False` — scenario
  validation rejects a role_chain containing a not-implemented role.
- One `SimulationSession` → one `Incident` → N `RoleStage` rows (ordered, one per role_chain entry).
  Session modes `SINGLE_ROLE | FULL_CYCLE_SINGLE_TRAINEE | MULTI_TRAINEE | ASSESSMENT` map to a
  `SessionPolicy` value object (participant-to-stage assignment rule, transition pause seconds,
  whether ASR partials are shown, whether the report is trainee-visible before instructor release).
  SINGLE_ROLE for DDS needs the scenario's optional `expected_response.prefab_handoff`; absent ⇒ that
  mode is rejected for that scenario at session creation.
- DDS stage triggers: trainee → `acknowledge`, `open_resource_selection`, `dispatch`, `close`;
  simulation → `first_en_route`, `first_arrived`, `work_started`, `incident_resolved`. Simulation
  triggers pass through the same state machine and are rejected the same way when invalid.

## D7. World event engine and simulation time (§12)

- Pure function core: `advance(state, now_ms, pending_actions, rng_factory) -> (state', [effects])`.
  Four event classes exactly as SPEC §12. Effects: `MutateWorldTruth`, `MutateCallerBelief`
  (only if the event is flagged `caller_observable`), `CreateNotification`, `CreateRadioMessage`,
  `AlterResourceAvailability`, `TriggerEvent`, `ChangeCallerEmotion`.
- Randomness: `rng = Random(sha256(f"{session_seed}:{event_id}:{occurrence}"))` — independent of
  evaluation order, so identical seed + identical timestamped actions ⇒ identical event stream.
  `session_seed` defaults to `ScenarioVersion.deterministic_seed`, overridable at session creation,
  recorded in `SESSION_CREATED`.
- Resource movement (turnout delay, travel time, on-scene work) is scheduled by the same engine from
  scenario-defined ETA data through a local `EtaModel` port (`ScenarioDefinedEta` implementation).
- `SimulationRunner` (application, asyncio): one task per ACTIVE session, ticks every
  `SIM_TICK_MS` (default 500) and immediately after each command. On backend start it re-adopts all
  ACTIVE sessions from PostgreSQL; sim time is derived from the persisted `started_at` plus paused
  intervals, so a restart or refresh never resets a session (§39). A Redis lock
  `lock:session:{id}:runner` guarantees a single runner.
- The engine's bookkeeping (occurrence counters, `last_fired_ms`, queued `ScheduledTrigger`s,
  emotion-rule application counts, reached stage states, `last_tick_ms`, `last_folded_seq_no`) lives
  in its own table `world_engine_states`, one row per incident (§20.3, additive, E6) — never merged
  into `incident_world_states`, which holds facts only (D3).

## D8. Commands API and realtime channel (§34)

- REST under `/api/v1`, JSON, commands return the new materialized view. Errors: RFC 7807 problem
  JSON; invalid transition ⇒ 409 with `code = INVALID_TRANSITION`. Contract: `docs/hld/openapi.yaml`.
- Auth: local username/password → JWT (HS256, secret from env). Roles `TRAINEE`, `INSTRUCTOR`, `ADMIN`.
  Every command checks (participant is assigned to the active RoleStage) ∧ (RoleModule permits action
  in the current stage state).
- Realtime: WebSocket `/api/v1/ws/sessions/{id}?token=…`. Server pushes role-filtered event envelopes
  `{seq_no, event_type, timestamp_utc, monotonic_offset_ms, payload}` (filtered by the role's
  `DataVisibilityPolicy` — a trainee never receives `WORLD_TRUTH_MUTATED` or gate internals). Client
  sends only `{"type":"resume","after_seq_no":N}`; the server replays from PostgreSQL then tails Redis.
  Refresh = REST snapshot + resume from last `seq_no`.
- Health: `/api/v1/health/live` (process) and `/api/v1/health/ready` (postgres, redis, livekit,
  llm, asr, tts, vad — each `READY | WARMING | NOT_READY | FATAL`). `POST /sessions/{id}/start`
  is refused with 503 `INFERENCE_NOT_READY` while a required service is not READY and
  `REQUIRE_INFERENCE_READY=true` (default true; tests set false explicitly).

## D9. Voice path (§15–§19, §25, §27)

- `CallTransport` port (application): `connect(call_id)`, `inbound_audio() -> AsyncIterator[AudioFrame]`,
  `play(AsyncIterator[AudioFrame]) -> PlaybackHandle`, `PlaybackHandle.cancel() -> DeliveredAudio`,
  `clear_outbound()`, `events()`, `disconnect()`. `AudioFrame` is our own dataclass (PCM s16le,
  sample_rate, samples). `LiveKitCallTransport` lives in `workers/voice_agent/transport/` and is the
  only module that imports the `livekit` SDK (plain `livekit` rtc + `livekit-api` packages — **not**
  the livekit-agents framework, whose built-in pipeline would replace the mandated one).
  `SipCallTransport` is a documented TODO stub of the same port.
- The voice-agent process hosts VAD, ASR and TTS models and runs the turn loop. It joins a room when
  the backend publishes `voice:join {session_id, room, call_id}` on Redis (at `CALL_RINGING`);
  the trainee answers in the UI (`POST …/call/answer` ⇒ `CALL_ANSWERED`), the frontend joins the same
  room with a backend-minted LiveKit token.
- Pipeline stages are separate classes behind ports, wired by `TurnPipeline`:
  `Resampler(→16 kHz mono, normalize)` → `VADProvider` → `TurnDetector` → `ASRProvider` →
  `DialogueInterpreter` → `FactAccessGate` → `CallerResponseGenerator` → `ResponseValidator` →
  `TTSProvider.stream()` → `CallTransport.play()`.
- `TurnDetector` config (`VoiceTurnConfig`, from env/profile, no literals in code):
  `speech_start_threshold`, `speech_start_min_ms`, `endpoint_silence_ms` (default 300, valid 250–350
  initial target), `pre_roll_ms` (default 300), `barge_in_min_speech_ms` (default 120),
  `max_turn_ms`. Emits `USER_SPEECH_STARTED` / `USER_SPEECH_ENDED`; the response starts only from a
  finalized turn. Partials are emitted as `ASR_PARTIAL` when the provider streams.
- Barge-in: TTS is pulled chunk-by-chunk (≤ 40 ms frames, outbound queue ≤ 200 ms). On sustained
  trainee speech during playback: cancel TTS generator → `clear_outbound()` → `PlaybackHandle.cancel()`
  → emit `CALLER_UTTERANCE_INTERRUPTED {planned_text, delivered_text, delivered_audio_ms,
  total_audio_ms_generated}` → process the trainee turn normally. `delivered_text` is computed from
  per-chunk text alignment metadata the TTS adapter attaches to chunks (word-proportional fallback).
  Cross-process cancellation signal (UI hang-up, abort): Redis `voice:cancel:{session_id}`.
- Providers: VAD — `SileroVAD` (onnx), `EnergyVAD` (tests/fallback). ASR — `GigaAMProvider`
  (`v3_e2e_ctc` primary, `v3_ctc` benchmarked), `FasterWhisperProvider` optional, `FakeASR`.
  TTS — `Qwen3TTS` (Qwen3-TTS 1.7B CustomVoice, GPU; OWNER DECISION, E14: the default for every
  profile including `DEV_3060TI`, an httpx client of the standalone `workers/tts_qwen3` worker
  process/venv), `PiperTTS` (CPU, the configured fallback everywhere — no longer the DEV default),
  `ChatterboxTTS`, `FakeTTS` (gate). LLM — `LlamaCppClient` (OpenAI-compatible HTTP to the local llama-server only;
  `base_url` must be loopback/compose-internal, enforced in config validation — §41), `FakeLLM`.
  **MEASURED (E19), 2026-09-22:** the DEV default LLM is `Qwen3.5-2B` (not one of the two SPEC §22
  illustrations) — fastest by >2x and the only model clearing 3 of E19's 4 quality-bar criteria; no
  model, including SPEC §22's own "Qwen3-4B quantized", clears all four
  (`dialogue_consistency_rate` is the failing one everywhere it is tried); decision unchanged,
  `docs/benchmarks/llm.md`. TTS default (Qwen3-TTS, above) is unchanged by measurement: it is
  whole-utterance-per-call (mean RTF 0.848, p50 first-audio 4.1 s on a NUMERIC-category sentence),
  mitigated by the sentence chunker, not by this decision; Piper meets SPEC §27's target trivially
  (p50 136 ms) but stays the fallback per the owner's own choice; `docs/benchmarks/tts.md`.
- Recording: the agent writes trainee and caller audio to `DATA_DIR/recordings/{session_id}/` (WAV),
  rows in `audio_segments` with session-relative `start_ms`; `transcript_segments.audio_segment_id`
  links them. Backend serves audio with HTTP Range. Retention: `RECORDING_RETENTION_DAYS` + a purge
  command that deletes files and nulls `audio_segments.file_path`, emitting an audit record.
- Telemetry: every ASR/LLM/TTS call goes through a `MetricsRecorder` port producing the SPEC §27
  `InferenceMetric`. The product metric `speech_end_to_first_audio_ms` is computed per turn from the
  `USER_SPEECH_ENDED` and first `CALLER_TTS_STARTED`-audible timestamps and stored on the turn.
- Model profiles: `backend/app/config/profiles/{DEV_3060TI,FINAL_3080TI_12GB,FINAL_3080TI_16GB}.yaml`,
  selected by `MODEL_PROFILE`. Each profile records `measured_peak_vram_mb` and `vram_budget_mb`;
  config validation refuses a profile whose measured margin is below `min_vram_margin_mb`
  (unmeasured = allowed only for DEV with a warning, never for FINAL_*).

## D10. Dialogue: interpreter → gate → generator → validator (§20–§24, §43)

- **Interpreter** input: operator utterance + last 4–6 turns + the **fact catalog**
  (`fact_id`, `label_ru`, `aliases_ru`, `categories` — **never values**). Output: SPEC §20 schema
  (`speech_act`, `requested_facts[]`, `operator_assertions[]`, `confirmation_targets[]`,
  `semantic_confidence`), grammar-constrained via llama.cpp `response_format: json_schema`, validated
  by Pydantic with `extra="forbid"`; `requested_facts` ⊆ catalog ids. Invalid ⇒ one repair retry ⇒
  `speech_act = UNINTELLIGIBLE` + `MODEL_FALLBACK_USED` (the caller asks to repeat). No guessed fields.
  Whether a request was *explicit* (needed for `ONLY_IF_EXPLICITLY_ASKED`) is part of the schema:
  each requested fact is `{fact_id, explicit: bool}`; a broad category question ("что случилось?")
  yields `explicit=false`.
- **FactAccessGate** (pure domain function). Inputs exactly per SPEC §21. For each requested fact:
  NEVER_DISCLOSE or UNKNOWN ⇒ `unavailable(reason)`; `available_after` unmet ⇒ `not_yet`;
  ONLY_IF_EXPLICITLY_ASKED ∧ ¬explicit ⇒ withheld; INCORRECT_BELIEF ⇒ the **caller_value** is
  released (the caller sincerely asserts the wrong value); UNCERTAIN ⇒ released with `certainty`.
  SPONTANEOUS facts not yet revealed are attached to the first eligible turn. Output
  `AllowedFactsPackage {allowed[], unavailable[], withheld_count, metadata}` contains **caller values
  only**; world values never enter it. Emits `FACT_GATE_EVALUATED`.
- **Generator**: prompt = fixed system rules (SPEC §23 text, in Russian + persona block from
  CallerProfile + current emotion) + `ALLOWED_FACTS` + `ALREADY_REVEALED` + last 4–6 turns + current
  utterance. `max_tokens=80`, `n_ctx=4096`, Qwen3 thinking disabled (`/no_think` + `chat_template_kwargs.enable_thinking=false`).
  Output schema `{"utterance": str}` only, `extra="forbid"`.
- **Validator** (deterministic): length; schema; forbidden identifiers (fact_ids, enum literals);
  meta-language lexicon (RU+EN); entity check — every number, address-like token and capitalized
  name in the utterance must occur in (allowed fact values ∪ already revealed values ∪ the operator's
  own recent utterances ∪ a small persona whitelist); world-value leak check against all scenario
  values not in the package (the validator is code and may see them; the LLM never does).
  Fail ⇒ one regeneration ⇒ deterministic template fallback chosen from gate output
  ("Я не знаю", "Повторите, пожалуйста", or a templated statement of the allowed facts) +
  `MODEL_FALLBACK_USED`. Baseline validates the whole (≤ 80 token) response before TTS; sentence-level
  streaming validation is a permitted optimisation behind the same `ResponseValidator` interface.
- **Fact delivery is decided by code, not text**: a fact is *revealed* when its response finished
  playback uninterrupted (`CALLER_TTS_ENDED`) ⇒ `FACTS_DELIVERED {fact_ids}`. An interrupted response
  reveals nothing; the operator may ask again. `FACT_OBTAINED` scoring reads `FACTS_DELIVERED` only,
  so rewording caller text cannot change a score (§42 test 10).

## D11. Scoring and report (§28, §29)

- `score(scenario_version, events) -> ScoreReport` — pure, no I/O, no LLM, no clock. Ten evaluator
  classes named exactly as SPEC §28, registry keyed by `evaluator_type`. Every `ScoreResult` has
  ≥ 1 `ScoreEvidence {event_id | card_revision_id | snapshot_id, note}`; a rule that awards or deducts
  without evidence is a hard error (§42 test 11). "Absence" evidence points at the bounding events
  (e.g. `HANDOFF_CREATED` for a field never filled). Results are persisted to `score_results` /
  `score_evidence` and each evaluation emits `SCORING_RULE_EVALUATED`; re-scoring from the log must
  reproduce identical numbers.
- The report API assembles: totals, per-category, critical errors, full timeline, transcript with
  audio offsets, final card, truth-vs-card diff (**instructor/report context only** — the one place
  WorldTruth is shown to a human), handoff snapshot, DDS decisions, resource timeline, latency
  metrics, evidence per rule. Optional LLM explanation is generated only from an already persisted
  ScoreReport, stored separately, and cannot write to score tables.

## D12. Frontend (§32)

- One Vite app, FSD-style `src/{app,features,entities,shared}`, routes `/operator`, `/dds`,
  `/instructor`, `/report`, `/login`. TanStack Query for REST, one Zustand store per realtime concern
  (session events, call state), shadcn/ui + Tailwind, dense dark "operations console" look, Russian
  strings in `shared/i18n/ru.ts` (single bundle, keyed — no hard-coded strings in components).
- The call is a **phone widget** (ringing, answer, timer, mute, hang-up, level meter); the transcript
  is a collapsible secondary panel. The frontend never decides a transition: buttons are enabled from
  `available_actions` returned by the backend and every click is a REST command.
- TypeScript API types are generated from `docs/hld/openapi.yaml` (`openapi-typescript`); the gate
  fails when generated types are stale.

## D13. Testing strategy (§42, §43)

- `backend/tests/unit` (pure domain), `backend/tests/integration` (PostgreSQL/Redis/API),
  `backend/tests/invariants/test_inv_NN_*.py` — one file per SPEC §42 item 1–14, named by number,
  `backend/tests/adversarial/` for the §43 suite (generated question matrix × FakeLLM adversary that
  tries to leak; reports `forbidden_fact_leak_rate`, asserts 0 at the context boundary). The same
  suite can run against the real llama-server via `benchmarks/benchmark_llm.py`.
- Every fake provider lives next to its port and is what the gate uses; real adapters get contract
  tests that are skipped unless the model/extra is present (marker `requires_models`).

## D14. Variant switches (I3, F1 — `70-i3-alignment.md` §70.2, §70.11)

- One frozen value object `SessionVariants` (`backend/app/domain/session/variants.py`) with four
  switches: `card_source` {`GENERATED_CARD`, `CALLER_VOICE`} (the AI caller is frozen, kept), `dds_mode`
  {`MEMO_STATUSES`, `RESOURCE_PICKER`}, `dds_card_check` {`OFF`, `ON`}, `dds_brigade_call` {`OFF`, `ON`}.
- Three homes, fixed precedence, no fourth: the scenario declares *supported + default* (schema-2 key
  `variants`; a schema-1 document gets a derived set that reproduces today's behaviour), session
  creation *selects* within `supported` (`409 VARIANT_NOT_SUPPORTED`; an unimplemented value is
  `409 VARIANT_NOT_AVAILABLE`), and `SESSION_CREATED.variants` + `simulation_sessions.variants`
  *record* the result. Immutable after creation.
- Scoring rules gain `applies_to_variants` with exactly the `applies_to_roles` "non-applicable ⇒
  zero/zero result" semantics; no evaluator changes.
- E1 ships `dds_mode` with effective default `RESOURCE_PICKER`; E5 flips the product default to
  `MEMO_STATUSES` for schema-2 scenarios (schema-1 scenarios keep `RESOURCE_PICKER`, P5).
- **Amends D4:** "a ScenarioVersion file has exactly the SPEC §4 top-level keys" now reads "a
  `schema_version: 1` file has exactly those keys; `schema_version: 2` adds the optional keys
  `variants`, `timers`, `reference_pack` (and `expected_response.responders`)". SPEC §4 lists a
  *required* structure; D4's *exactly* is the part amended. The loader refuses the schema-2 keys in a
  schema-1 document.

## D15. A card stream is a Lesson of ordinary sessions (I3, F2 — `70-i3-alignment.md` §70.3)

- `uq_incidents_session`, SPEC §1 and §13 are kept literally: one session = one incident = one card.
- A **Lesson** (занятие) owns N ordinary sessions, all created at lesson creation (`READY`) and
  started by a `LessonRunner` (the `SimulationRunner` discipline: one task per ACTIVE lesson, Redis lock,
  re-adoption) when each `scenario_plan` entry's arrival holds (`AT_OFFSET`,
  `AFTER_PREVIOUS_112_STAGE`, `AFTER_PREVIOUS_SESSION`), acting as the instructor who created the
  lesson. Lessons have no event log of their own.
- Per-card timers are scenario data in **session** ms (`timers.accept_within_ms` 30 000,
  `fill_within_ms` 180 000, `not_completed_after_ms` default 48 h, author-scaled). Their consequences
  are SIMULATION-authored `DDS_CARD_STATUS_CHANGED` events stamped with the deadline offset, appended
  under the flush-before-append rule; the late action is scored by ordinary `DEADLINE` rules.

## D16. Per-service response statuses on the legs (I3, F3 — `70-i3-alignment.md` §70.4)

- Each `DDSAssignment` leg carries a `ServiceResponseStatus` machine in the ДДС memo vocabulary
  (Добавлена → Получена службой → Принята / Не принята → Начало реагирования → Прибытие → Проведение
  работ → Работы завершены | Отказ от выполнения работ), one step at a time, comment mandatory for
  «Не принята» / «Отказ», service 103 policy `NO_REFUSAL`, «Номер наряда» free text per status entry,
  append-only history `dds_service_status_history`. The competence decision is always on.
- `DDSStageState` is unchanged; `DDS_TRANSITIONS` gains exactly **one additive row**
  `ACKNOWLEDGED --close--> RESOLVED` (TRAINEE, like the existing `close` row) with guard
  `memo_all_legs_terminal` (holds iff `dds_mode = MEMO_STATUSES` and every leg is `COMPLETED`,
  `NOT_ACCEPTED` or `REFUSED`; denies in picker mode). In memo mode it is the only closure path and
  `RESOURCE_SELECTION` … `WORKING` are never entered; the picker mode is unchanged. Guards
  (`DDS_GUARDS_MEMO`) and the available-actions map become variant-aware. Memo scoring rules key on
  `DDS_SERVICE_STATUS_SET`, never on dispatch events. (Manager decision on open point O-1, option (a)
  tightened; `70` §70.4.4.) E5a lands the row with HLD 10 §10.8/§10.9, the parsed-table test and INV 8.
- Card statuses (Зарегистрирована, Отработана, Проверена, Не оповещено, Отказ, Не завершено,
  Завершена) are a pure derived projection, materialised into `incidents.card_status`.
- The card is broadcast to every notified service; every ДДС participant sees every leg and its history.
  Several ДДС trainees = participant→service binding inside the one DDS stage
  (`session_participants.assigned_service_id`); unbound legs are played by scripted responders.

## D17. The 112 card schema is versioned data (I3, F4 — `70-i3-alignment.md` §70.5)

- `reference/card-schema/v1.yaml` = today's 38 `CARD_FIELDS`; `v2.yaml` is authored from the organizer
  docx. Fields that mean the same keep their `field_path`; the per-type questionnaire is `visible_when`
  (a card-local `CardCondition`) + option lists; everything is served through the existing
  `field_specs` (additive `CardFieldSpec` properties) to both the 112 and the ДДС side.
- The scenario names the reference pack; `SESSION_CREATED.reference_pack` records ids and sha256s.
  Scoring stays path-and-payload only; one additive `Comparison` member `CONTAINS`.

## D18. Classifier, services catalog and routing (I3, F5 — `70-i3-alignment.md` §70.6)

- Classifier v_046_24 and «СЛУЖБЫ 112» are sha-pinned data files under `reference/`, generated from the
  source xlsx/docx by `backend/tools/import_*.py`; not tables. F4 and F5 share one reference pack and
  one version; questionnaire option codes are the classifier's признак codes.
- `ServiceType` becomes `ServiceId = str`; the six current ids stay verbatim as catalog ids; the DB CHECK
  on `dds_assignments.service_type` is relaxed to non-empty; a scenario's service ids are checked
  against the catalog at import.
- Routing is a pure resolver whose result is recorded as a SIMULATION `RECIPIENTS_RESOLVED` event —
  never a SYSTEM write into the card (INV 4, D3). Notification list = auto ∪ manual; only 112 adds
  services; removal is refused under schema v2 (`409 SERVICE_REMOVAL_FORBIDDEN`). The LLM never sees the
  card (SPEC §2).

## D19. I3 requirement-conflict picks (`70-i3-alignment.md` §70.9, §70.10)

- C1 ДДС card check: both behind `dds_card_check`, default `OFF` (latest customer answer).
- C2 no control-department role: «Отказ» from the leg alone; «Проверена» = instructor report release.
- C3/C4 the 48-h and 3-minute norms are scenario timer data with the memo/room values as defaults.
- C5/C6 SPEC §1/§13 and §7 kept; the stream is a lesson, the memo statuses live per leg.
- C7 `dds_brigade_call` default `OFF` until H2/E6 (owner to confirm).
- C8 `UTILITY_EMERGENCY` kept as a deprecated catalog entry, hidden from the v2 picker.
- C10 removal refused under schema v2; `SERVICE_DESELECTED` kept for v1 and old logs.
- C11 automatic routing is a table lookup, not an LLM decision.
- Evidence gaps are carried as explicit assumptions A-1…A-13, each with the epic that checks it.

## D20. The reference look replaces D12's dark console for the 112 card and ДДС screens (I3, C9)

- The organizer asks for screens «100 % похожи» on the real system. E7a (with E3's and E5's layouts)
  moves the 112 card and ДДС screens to a light theme: orange bar `#EC653B`, blue tags `#157DBD`,
  backgrounds `#EFEFEF` / `#C9CED1`, checked by Playwright screenshot comparison against images extracted
  from the organizer files. D12's structure (FSD layout, TanStack Query, Zustand, `ru.ts` strings,
  `available_actions`-driven buttons, generated types) is unchanged; only its "dense dark operations
  console" look is superseded on those screens.

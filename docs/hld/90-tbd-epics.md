# HLD 90 — The TBD epic list issued by E1

Each epic below is one commit on a green `make gate`. Order follows SPEC §45 (Phases A–L); an epic
may only rely on epics above it. Every epic owes: the vertical slice, its migrations, its tests, and
an explicit list of anything left unimplemented (SPEC §47). "INV n" = SPEC §42 invariant test *n*,
which lands as `backend/tests/invariants/test_inv_<nn>_*.py` in the epic named here and is never
weakened afterwards.

The list is rescheduled as evidence arrives; this file is updated in the same commit that changes it.

| # | Phase | Epic | SPEC § | HLD refs | Invariants / key tests owed |
|:--|:--|:--|:--|:--|:--|
| E2 | A1 | **Skeleton and gate** — uv workspace (py3.12), `backend/app/*` layer packages, `backend/tools/check_imports.py`, ruff/mypy/pytest config, Vite+React+TS+Tailwind+shadcn scaffold with the four route groups as placeholders, `infra/docker-compose.test.yml` (postgres 55432, redis 56379), `Makefile` (`deps`, `gate`, `test`, `fmt`), `.env.example`, `.gitignore`, README | 32, 33, 35, 36 | D1, D2 | import-boundary self-test (a forbidden import in a fixture tree goes red); smoke tests both sides |
| E3 | A2 | **Domain core and scenario validation** — enums, ids, `ActorRef`, `EventType`, `SessionEvent`/`DomainEvent` + payload catalog, `Condition` model, fact model, the four layer types + copy functions, CallerProfile/EmotionRule, world-event and scoring-rule definition models (evaluator config models only), generic `StateMachine`, the three transition tables + resource status table, `RoleModule` protocol + Operator112/DDS modules + EDDS stub, `SessionPolicy` (pure-domain parts pulled forward from E5 because scenario validation needs the RoleModule registry), ScenarioVersion Pydantic models, YAML loader + full load-time validation, JSON Schema export with staleness check in the gate, demo scenario `scenarios/examples/apartment-fire/v1.yaml`, `python -m app.tools.validate_scenarios` | 3, 4, 5, 6, 7, 14 | 10, 30, D3, D4, D6 | each validation rule has a failing-fixture test; layer types share no references (deep-copy test); INV 8 (table-driven: every non-listed transition fails); role visibility sets equal HLD 40 §40.4 (parsed at test time) |
| E4 | A3 | **Database and event store** — all ORM models, Alembic baseline incl. immutability triggers, `EventStore` with locked `seq_no` allocation, Unit of Work, scenario import + version locking, Redis event publisher port + adapter | 8, 30, 31 | 20, D5 | INV 6; UPDATE/DELETE on `session_events` and `handoff_snapshots` rejected; concurrent appends yield gap-free unique `seq_no` |
| E5 | B1 | **Session lifecycle** — `SimulationSession`/`Incident`/`RoleStage`/`SessionParticipant` aggregate, the guard callables for every `guard_name` in the transition tables (E3 ships the tables with names only) wired into the RoleModules, use cases create/start/abort session (one Incident, N RoleStages, world + belief state instantiated from the ScenarioVersion, ScenarioVersion locked in the same transaction), repositories for the session aggregate and the four layer storages | 1, 7, 13, 14 | 10, 20, D6 | every guarded transition has an allow + deny test; EDDS in a role_chain is rejected at session creation; INV 8 re-run through the use cases (invalid command ⇒ `InvalidTransitionError`, no event appended) |
| E6 | B2 | **World event engine and simulation runner** — four event kinds, condition language, effects, seeded RNG rule, `EtaModel`, emotion rules, asyncio `SimulationRunner` with Redis lock and re-adoption of ACTIVE sessions on start | 6, 12, 39 | 10, D7 | INV 7 (same seed + same timestamped actions ⇒ identical event stream, different seed ⇒ differs); runner restart does not reset sim time |
| E7 | C1 | **API foundation and Operator 112 backend** — FastAPI app, JWT auth + seeded users, problem+json errors, scenarios + sessions endpoints, role-filtered snapshot, WebSocket realtime with replay/resume + visibility filter, operator commands: call answer/end, card set-field with `incident_card_revisions`, service select/deselect, handoff-preparation | 8, 9, 34 | openapi, 40, D8 | INV 4 (ASR_FINAL never mutates the card; no code path from transcript to card), INV 13 (snapshot + resume restores state); every command rejected for wrong role / wrong state |
| E8 | C2 | **Frontend foundation and Operator 112 console** — generated API types + staleness check, auth, app shell, `/instructor` minimal "create + start session", `/operator` console: phone widget (state only, audio arrives in E11), manual card form bound to set-field commands, services panel, secondary transcript panel, WS event store, refresh restore | 9, 32 | openapi, D12 | vitest: card edits issue one command per field and never write locally-derived values; buttons driven by `available_actions` |
| E9 | D1 | **Handoff and DDS backend** — immutable `HandoffSnapshot` by-value copy, DDS work item from snapshot only, acknowledge, resources + capabilities + statuses, select/dispatch, ETA-driven status changes via the engine, notifications, radio messages, status updates, closure | 10, 11 | 10, 20, D3, D6 | INV 3 (DDS services constructed without a WorldTruth repository; payload contains "72" not "27"); omitted card facts stay omitted |
| E10 | D2 | **DDS console** — `/dds`: incoming work item, acknowledgment, resource board with capabilities/ETA/status, dispatch, live notifications + radio log, status update, close | 11, 32 | openapi, D12 | vitest on action gating; no WorldTruth field exists in generated DDS types |
| E11 | E | **LiveKit transport and turn management** — livekit service in compose, token endpoint, `workers/voice_agent` process, `CallTransport` port + `LiveKitCallTransport` + `FakeCallTransport`, resampler, `TurnDetector` with `EnergyVAD`, chunked playback with cancel/clear, call recording → `audio_segments`, frontend LiveKit call widget (ring / answer / hang-up / mute / meter) | 15, 16, 17, 34 | 50, D9 | turn detector unit tests over synthetic audio (pre-roll kept, endpoint at configured silence, config not literals); domain/application import no `livekit` (boundary check) |
| E12 | F | **VAD and ASR** — `SileroVAD`, `GigaAMProvider` (v3_e2e_ctc, v3_ctc), optional `FasterWhisperProvider`, `FakeASR`, partial + final transcript events, `transcript_segments`, `MetricsRecorder` → `inference_metrics` | 17, 19, 27 | 50, 60 | ASR failure leaves session state intact and emits MODEL_ERROR; contract tests marked `requires_models` |
| E13 | G | **Interpreter, Fact Access Gate, caller LLM, validator** — catalog builder (no values), interpreter with json_schema + repair retry, pure `FactAccessGate`, prompt builder accepting only `AllowedFactsPackage`, `LlamaCppClient` (loopback-only) + `FakeLLM`, `ResponseValidator`, deterministic fallbacks, `FACTS_DELIVERED` bookkeeping, emotion updates | 2, 20–24, 41, 43 | 10, 50, D10 | INV 1, INV 2, INV 14; adversarial suite with `forbidden_fact_leak_rate == 0` at the context boundary and validator rejection of invented entities |
| E14 | H | **Streaming TTS and barge-in** — `TTSProvider` adapters (`PiperTTS`, `Qwen3TTS`, `ChatterboxTTS`, `FakeTTS`), configured fallback chain on failure, barge-in path end to end, delivered-text accounting, playback timing persisted | 18, 25, 39 | 50, D9 | INV 12 (queued audio cancelled, interruption event carries delivered portion); measured onset→cutoff on FakeTransport < 250 ms |
| E15 | I | **Deterministic scoring** — ten evaluators, evidence model, `score()` pure function, persistence to `score_results`/`score_evidence`, `SCORING_RULE_EVALUATED`, re-score equality endpoint | 28 | 10, D11 | INV 9, INV 10, INV 11 |
| E16 | J | **Post-session report and replay** — report API (every SPEC §29 item), Range audio serving, **report release to the trainee** (`releaseReportToTrainee`, moved here from E17: the release flag is what `getSessionReport` reads, and only one epic may own its migration), `/report` UI: totals, categories, critical errors, timeline, transcript click → audio seek, final card, truth-vs-card diff, handoff snapshot, DDS decisions, resource timeline, latency metrics, evidence per rule; optional LLM explanation stored separately | 29 | openapi, D11, D12, D6 | explanation cannot write score tables; report for an unfinished session refused; release is idempotent and emits no event |
| E17 | K | **Full-cycle and multi-role modes** — ROLE_TRANSITION with configurable pause, FULL_CYCLE_SINGLE_TRAINEE UI hand-over, MULTI_TRAINEE participant assignment, ASSESSMENT policy, SINGLE_ROLE incl. DDS `prefab_handoff`, instructor **live** overview (`getInstructorSessionOverview`; report *release* moved to E16) | 1, 13 | 10, D6 | INV 5 (same Incident id, one event timeline across stages) |
| E18 | L1 | **Profiles, warm-up, preflight, resilience, full compose** — three model profiles + VRAM-margin refusal, warm-up + readiness vs liveness, start refused when not ready + UI gating, `infra/scripts/preflight.py`, GPU-OOM → FATAL health, LiveKit reconnect, TTS fallback, retention purge, `infra/docker-compose.yml` with all seven services | 26, 37, 38, 39, 41 | 60 | each SPEC §39 behaviour has a test; preflight returns explicit pass/fail per check |
| E19 | L2 | **Benchmarks and real models** — five benchmark scripts with JSON/CSV export and `NOT_RUN` honesty, corpus under `benchmarks/data/`, model download script, real runs on the DEV machine, measured values written into the DEV profile and `docs/benchmarks/`. **AS BUILT (2026-09-22, E19-G consolidation):** all five scripts + `_common.py` built and green against fakes in the gate (48 tests, `benchmarks/tests/`). Real runs on `DEV_3060TI`/`DEV_3060TI_SHARED`: ASR (GigaAM `v3_e2e_ctc`/`v3_ctc`, cuda+cpu; faster-whisper `NOT_RUN`, never installed per E12); LLM (Qwen3.5-{0.8B,2B,4B}, Qwen3-4B both parallel settings, Qwen3-8B `NOT_RUN` — no model clears E19's quality bar, DEV default stays Qwen3.5-2B, a real degenerate-caller-utterance product bug found and fixed at the grammar+validator boundary); TTS (Piper vs Qwen3-TTS 0.6B **and 1.7B** time-to-first-audio + cancellation — 1.7B RTF 0.823, latency-indistinguishable from 0.6B's 0.848, the variant choice is quality not speed; Chatterbox `NOT_RUN`, no streaming entry point in the installed `qwen_tts` package); VRAM (`DEV_3060TI_SHARED` OK, peak 1559 MB; `DEV_3060TI` **OK, peak 5560 MB**, run for real once the owner's GPU process was stopped — two earlier PARTIAL attempts on the shared card kept as history — both now in their profiles); E2E (in-process real full dialogue chain, `DEV_3060TI_SHARED --runs 4`: p50 1192 / p95 1864 / p99 2056 ms, 35/36 turns, `meets_target: true`; real LiveKit run: the agent now joins after a per-call-token fix, 34/39 turns answered, 24/24 scripted barge-ins under the 250 ms budget over real WebRTC, but its latency figure is withheld — `speech_end_to_first_audio_ms` is unmeasurable over LiveKit because the transport stamps capture offsets from a different clock than the session offsets TTS uses, open → E20 R13 — and the shipped `SIM_SIM_TICK_MS` deadlocks the runner against the agent on the same DB row lock, open → E20 R14; see `docs/benchmarks/e2e.md` §6 for the full six-bug history); model hashes/provenance (`docs/benchmarks/models.md`); both CUDA images built for real and smoke-tested; llama.cpp `b11065` flag spellings verified against the pinned image. Two further real product bugs found and fixed: the voice-agent's per-call VAD was never warmed (E19-E2), and the voice agent could not join a LiveKit room at all for want of its own access token (E19-E3). All 18 of the epic's TODO markers resolved (a repo-wide grep for the open-marker pattern is empty). Docs: `docs/benchmarks/{README,asr,llm,tts,vram,models,e2e}.md` written. | 26, 27, 40 | 60 | scripts run against fakes in the gate (shape only); no number in the repo that a script did not produce |
| E20 | L3 | **Demo hardening and definition-of-done walk** — audio-injection tool for a mic-less end-to-end run, SPEC §46 items 1–16 walked and recorded with evidence, operator runbook, requirement-by-requirement audit of SPEC §1–§47 with every gap listed explicitly. **E19 hand-off items (2026-09-22):** both TTS adapters buffer the whole utterance before the first `TtsChunk` (cancel never interrupts in-flight synthesis) (E19-D); multi-session concurrency in `benchmark_vram.py` is untested (E19-D2); numeric-only caller answers are now `EMPTY` under the tightened validator rule — owner to confirm this is intended (E19-C2); `50-voice-pipeline.md` §7.1/§5.2 prompt proposal: a re-asked fact should return the same value (E19-C2 proposal, not applied); ~570 ms of the E2E turn budget sits in VAD endpointing + detector + persistence, not in any model call (E19-E); the LiveKit `ListRooms` preflight check is HTTP reachability only, not a real room check (E18); `make deps` lacks `--inexact` and strips heavy ML extras other workers installed — proposed fix text: change the `deps` target's `uv sync --all-packages --group dev` to add `--inexact`, matching `deps-models`/`deps-tts-piper`/`deps-tts-qwen3`'s own discipline (E19-B, not applied to the Makefile); the `EMPTY` validator rule (widened in E19-C2 to "no letter after strip") accepts Latin-only text, which is `META_LANGUAGE`'s job under SPEC §7.4, not `EMPTY`'s (E19-C2). **E19-E3 hand-off items (2026-09-22):** `R13` — `speech_end_to_first_audio_ms` could not be computed over the real LiveKit transport: `USER_SPEECH_ENDED` was stamped from `LiveKitCallTransport`'s own per-transport capture clock while `CALLER_TTS_STARTED` was stamped from the session clock, so the two origins diverged and every real sample came out negative (E19-E3, **fixed in E20 by E20-F**: `backend/app/application/ports/call_transport.py` now defines `capture_offset_ms` as `session_offset_ms`, and `voice_agent.main._session_started_at` fixes a second bug — the real agent never passed a real `started_at`, silently zeroing every offset; `workers/voice_agent/tests/test_transport_clock_origin.py`). `R14` — the API's `SimulationRunner` tick and the voice agent took the `simulation_sessions` row lock in conflicting modes; at the shipped `SIM_SIM_TICK_MS=500` a real LiveKit call deadlocked within a couple of turns (E19-E3, **fixed in E20 by E20-F**: `backend/app/infrastructure/persistence/{event_store,session_repository}.py` both now take `FOR NO KEY UPDATE`; `backend/tests/integration/persistence/test_seq_lock_order.py`). `R15` — the voice agent (and `app/cli/preflight.py`) resolved a profile's compose-internal `/models/...` paths with no host-side equivalent, so every real component failed to warm up off compose (E19-E2/E3, **fixed in E20 by E20-F**: `backend/app/config/model_paths.py` + `Settings.models_root`/`SIM_MODELS_ROOT`, 14 new tests — the README host-run note is still owed, E20-B). `R2` — `call_flow._retry_join` used to stop re-publishing `voice:join` the moment a call was answered, so a voice agent that was still starting, reconnecting or re-adopting a session when the trainee answered never received a join signal again, with no error surfaced anywhere (E19-E2, **fixed in E20 by E20-F**: `_retry_join` now fires on `RINGING` or `CONNECTED` and stops on the agent's own first appended event for that `call_id`; `backend/app/application/operator/call_flow.py`, HLD 40 §40.6, `backend/tests/api/voice/test_call_signals.py`). **E20-D (2026-09-22):** `docs/AUDIT.md` written — the §1–§47 requirement-by-requirement table (merged/re-verified against audit-1 + audit-2), the §46 DoD table (fake-provider/test-suite evidence only; the 16 real-stack PASS/FAIL verdicts are left as an explicit placeholder for E20-C to fill in `docs/DOD_WALK.md`), a dated "Not implemented / deviations" list (Chatterbox; Qwen3-8B FINAL unmeasured; DEV LLM Qwen3.5-2B by measurement; per-unit TTS buffering; TTFT==total for non-streaming LLM calls; §6 current_emotion/stress on EmotionState by design; numeric-only answers pending owner; multi-session VRAM untested; ~570 ms non-model turn overhead; R1/R2/R3/R4/R5/R6/R8/R11/R13/R14/R15 items still landing at capture time), and the HLD-gap fold across every report this epic's brief named (e7-d, e11-a/b, e12-a, e13-a/b1-4, e14-a-d, e16-a-c, e17-a-d, e18-a-e, e19-a-g) — one prose correction made in `docs/hld/60-inference-ops.md` §8 (the flash-attention "falls back to `auto`" claim did not match `infra/scripts/llama-server-entrypoint.sh`, which has no such runtime fallback). This row's artifacts: `docs/AUDIT.md` (E20-D, done), `docs/DOD_WALK.md` (E20-C, not yet written), `docs/RUNBOOK.md` (E20-B, not yet written — README's fresh-clone runbook gap is R7, also E20-B's). **E20-D2 (2026-09-22, follow-up):** every one of E20-A/B/E/F's rulings (R1–R6, R8, R11, R13–R15) re-verified landed by reading the current tree directly (not by trusting the reports alone) and `docs/AUDIT.md` updated to final verdicts throughout; stale "open"/pending wording for R2/R13/R14/R15 corrected across `docs/benchmarks/e2e.md` §3/§6/§8, `docs/benchmarks/README.md`, this row and `docs/hld/60-inference-ops.md` §10 item 13 (measured numbers kept as-is — a post-fix LiveKit re-run is E20-C's); `docs/benchmarks/vram.md`'s two open-item markers reworded to `TODO(POST-I1)`; one-sentence fixes to `docs/hld/60-inference-ops.md` §9 (names `SIM_TTS_QWEN3_HOST` as the bind) and HLD 40's `voice:join` row cross-check (R2's fix already correctly documented there by E20-F); `workers/voice_agent/Dockerfile`'s stale "health CLI not built" comment and `infra/docker-compose.yml`'s stale `dev-infra-up` "three services" comment both corrected (both comment-only). The §46 table (`docs/AUDIT.md` §2) was intentionally left untouched — E20-C's walk owns it. **E20-C (2026-09-22) — the §46 walk, DONE:** the sixteen items were walked for real on the `DEV_3060TI` stack at the shipped `SIM_SIM_TICK_MS=500` (session `49accdb9-e2c2-4d43-9247-ddb168e16ae8`, 10 min 8 s, 228 events), instructor/trainee actions over the real REST API and the trainee's voice published into a real LiveKit room by `python -m voice_agent.tools.inject`. **Verdicts: 12 PASS, 4 PARTIAL (items 3, 5, 12, 16), 0 items replaced by a fake UI animation** — written up with commands, event-log excerpts and fourteen dated open items in `docs/DOD_WALK.md`, evidence in `docs/benchmarks/results/dod-walk-20260922/`, and folded into `docs/AUDIT.md` §2. The walk had to use the **host-run** path: the documented `make up` path cannot place a voice call today (llama-server binary not on the image's PATH; `MODELS_DIR=./models` resolves to `infra/models` under compose; the frontend healthcheck runs a `wget` the image lacks; and decisively the `voice-agent` image carries no `livekit` extra). Two further real defects block the shipped `DEV_3060TI` caller voice: the demo scenario's `caller_profile.voice_id` is not a Qwen3-TTS vendor speaker, and the configured TTS *fallback* provider is never warmed (`_warm_tts` warms only the primary), so INV 14's retry can only fail — the walk ran with Piper promoted to primary. R13/R14 are confirmed on the real transport: `benchmark_e2e.py --transport livekit --runs 4` at the shipped tick published the first real §27 percentile — **p50 1566 / p95 4622 ms over 29 turns, `discarded_nonpositive_count: 0`, no deadlock** (`docs/benchmarks/e2e.md` §3.1, `e2e-DEV_3060TI-20260922T144530930Z.json`); the DEV p95 target of 2500 ms is not met over a real media plane. **E20-G (2026-09-22) — the documented `make up` demo path:** all four of E20-C's `make up` defects fixed and proven — `SIM_LLAMA_SERVER_BIN` defaults to the VERIFIED `/app/llama-server` inside the pinned image, `MODELS_DIR=../models` (compose resolves it against `infra/`, not the repo root), the `frontend` healthcheck is a `node -e fetch(...)` probe (that image has neither `wget` nor `curl`; proven with `docker exec` exit 0 vs the old probe's `wget_exit=127`), and `VOICE_AGENT_EXTRAS` gains `transport-livekit` (image rebuilt, 7.26 GB, `livekit==1.1.19`, `--gpus all` smoke `cuda True 12.8`). **`TTS_COMPOSE_PROFILE=qwen3-tts make up` now exits 0 with `--wait` and all EIGHT services healthy.** Both named causes of the silent caller are fixed: `TtsVoiceSpec.voice_id` is a SCENARIO-LOGICAL id (HLD 30 §30.3) resolved through the active profile's new `tts.voice_map`/`tts.default_voice` (`Settings.tts_voice_map`/`tts_default_voice`, `apply_profile` overlay, every shipped profile maps `ru_female_adult_01`; a miss warns ONCE per (provider, id) and never raises; the native id is recorded on the additive `CALLER_TTS_STARTED.voice_id_native`, HLD 10 §10.13, and dropped for trainees by HLD 40 §40.4 row 12), and the configured TTS fallback is warmed at start-up and passed through `build_pipeline` to the per-call sink so INV 14's retry finds a warmed provider. Preflight (SPEC §38) is stack-aware (check 2), dials the EFFECTIVE `Settings.llm_base_url` (check 4) and requires a Cyrillic word from real Russian speech (check 5, `.env.example` now points `SIM_ASR_WARMUP_SAMPLE_PATH` at `models/warmup/warmup_ru.wav`) — checks 3/4/5 measured GREEN inside the running stack, check 5 returning `Проверка готовности перед началом смены.`. `make run-llama-server` resolves the profile's model path onto the host itself (`profile_env --models-root`), and README/RUNBOOK now forbid sourcing `.env`. Two further `.env.example` defects found and fixed on the way: host-relative `SIM_*_MODEL_PATH`/`MODEL_DIR` values overrode the profile inside every container, and `SIM_TTS_FALLBACK_PROVIDER=none` overrode every profile's configured fallback. **Still blocking §46 item 3 under `make up`, outside E20-G's files:** the `tts-qwen3` image has no C compiler (Triton JIT) and no `sox`, so Qwen3-TTS answers 503 and `startSession` refuses with `INFERENCE_NOT_READY`; plus `make demo-init`'s `seed_users` reads its passwords from `os.environ`, never from `.env`. Full account, commands and verbatim errors: `docs/DOD_WALK.md` §6 (open items 15-19). | 46, 47 | all | full §42 list green; audit table committed **E20-I (manager, 2026-09-23): the documented path works end to end** — fresh clone → `make demo-init` → `make up` (8 healthy) → `make preflight` 10/10 (inside the voice-agent container) → a real call with the SHIPPED `DEV_3060TI` voiced by Qwen3-TTS: §46 item 3 PASS (`docs/DOD_WALK.md` §7). Fixed on the way: tts-qwen3 image (C compiler + sox), TTS warm-up timeout, Piper fallback voice path, profile-sized TTS guards for a whole-utterance provider, `}` in caller speech (grammar + validator), DEV TTS variant 0.6B by measurement (1.7B = 7448 MB > budget), `.env.example` profile overrides, seed/inject read `.env`, image dependency layers cached. |

## Parallelism notes for the manager

- Frontend epics (E8, E10, E16-UI) touch only `frontend/` and can be staffed beside a backend epic's
  tasks, but still commit as their own epic on a gate run alone.
- E13's pure `FactAccessGate` and E15's pure `score()` depend only on E3 and may be pulled forward if
  a blocker stalls the voice path (blocker ladder rung 1).

## I3 TBD epics

Issued by H1 (the I3 HLD, `docs/hld/70-i3-alignment.md`, decisions D14–D20). **I3 numbering is its
own series:** `E1`…`E7a` below are initiative-I3 epics and have nothing to do with the I1 rows of the
same names above. Order is dependency order; an epic may rely only on rows above it (B1, rung 1: E3a′
was moved in front of E2b′ and both rows re-issued, `00-decisions.md` D21); each lettered
sub-epic lands green on its own (`make gate`). Every row owes the HLD 10/20/30/40 and `openapi.yaml`
updates for exactly what it implements, copied literally from `70-*.md` and
`docs/hld/contracts/i3-openapi-delta.yaml` (items tagged with its `x-epic`), in the same commit — those
documents are parsed by tests. "Leaves" lists what the epic explicitly does not implement.

| # | Wave | Epic | SPEC § / REQ | HLD refs | Invariants / key tests owed |
|:--|:--|:--|:--|:--|:--|
| E1 | 1 | **Variant switches** — **Modules:** `domain/session/variants.py` (new: `SessionVariants`, `VariantSupport`, `ScenarioVariants`, `resolve_variants`, `IMPLEMENTED_VARIANT_VALUES`), `domain/session/{session,policy}.py` (effective chain, `EXACTLY_ONE` on it), `domain/scenario/{version,sections,validation}.py` (`SUPPORTED_SCHEMA_VERSIONS = {1, 2}`, key `variants`, R01 extension, R32–R36, R40, schema-1 derivation), `domain/scoring/{rules,context,engine}.py` (`applies_to_variants`), `domain/roles/{module,dds,registry}.py` (`variants` kwarg), `application/sessions/create_session.py`, `application/handoff/prefab_handoff.py` (reached through `GENERATED_CARD`), `api/routers/{sessions,scenarios}.py`, `openapi.yaml` (E1 items), `scenarios/schemas/scenario_version.schema.json` regen, frontend instructor create-session form (variant pickers from `ScenarioVariantsView`) + generated types. **Migration:** `0009_session_variants`. **Leaves:** `MEMO_STATUSES`, `dds_card_check: ON`, `dds_brigade_call: ON` (all `409 VARIANT_NOT_AVAILABLE`); the schema-2 keys `timers`, `reference_pack`, `responders` stay refused until E4/E2/E5b | §1, §4, §13, §28; REQ-5915/5916 (C1), assessment §4.1 (caller excluded) | 70 §70.2, §70.11; D14 | failing fixture per R32–R36, R40; 409 `VARIANT_NOT_AVAILABLE` per unimplemented value and `VARIANT_NOT_SUPPORTED` outside `supported`; `GENERATED_CARD` on the demo builds effective chain `[DDS]` and materialises the prefab; a non-applicable `applies_to_variants` rule yields zero/zero; pre-E1 logs rescore identically (INV 9); INV 5, INV 7 unchanged and green |
| E2a | 1 | **Reference pack and `ServiceId`** — **Modules:** `backend/tools/{import_classifier,import_services}.py`, `reference/{manifest.json, classifier/v046_24.json, classifier/v046_24.columns.json, services/v1.yaml, card-schema/v1.yaml}` (v1 generated from today's `CARD_FIELDS`), `domain/enums.py` (`ServiceType` → `ServiceId = NewType(str)`), `domain/routing/{classifier,catalog}.py`, `application/ports/reference.py` + `infrastructure/reference/file_catalog.py` + composition root, `domain/scenario/{sections,validation}.py` (key `reference_pack`, R37, R38 for the pack name), `SESSION_CREATED.reference_pack`, `api/routers/reference.py` (manifest, services, classifier search/row), `openapi.yaml` (`ServiceType` → string, reference ops), frontend `features/dds/dds-labels.ts` and every `Record<ServiceType, …>` → catalog lookups. All 55 «СЛУЖБЫ 112» picker frames transcribed first (A-6). **Migration:** `0010_service_id_open`. **Leaves:** the resolver, `RECIPIENTS_RESOLVED`, the removal rule, the services-bar UI (E2b); card schema v2 (E3a) | §4, §9, §10; REQ-3042–3045, REQ-5701–5717 | 70 §70.6.1–§70.6.3; D18 | gate sha check of every reference file and source (stdlib); classifier row/column counts asserted against REQ-5701–5717; regen-and-diff test (skipped without the readers); `openpyxl` + `python-docx` in a dev/tools-only dependency group (approved, `uv sync --inexact`), with an import-boundary check that `backend/app/**` never imports them (A-13); six legacy ids resolve; R37/R38 failing fixtures; every existing `FIRE_RESCUE` fixture and stored snapshot passes unchanged |
| E3a′ | 1 | **Card schema as data (backend) + schema v2** (re-issued by B1 and moved before E2b′) — **Modules:** `domain/layers/{card_schema,operator_card}.py` (loader, `CardCondition` evaluator, `CARD_FIELDS` kept as the v1 alias, `set_field` per session schema, `CARD_OPTION_UNKNOWN`), `reference/card-schema/{v2.yaml, conditions.fixtures.json}` authored from «КАРТОЧКА 112.docx» + screenshots (101/104/Взрыв branches full, others from screenshots; administrative entries `routing: none`, A-3), manifest re-pinned, `domain/scenario/validation.py` (rule 14 + `HANDOFF_COMPLETENESS` against the named schema), `domain/scoring/comparisons.py` (+`CONTAINS`), `application/operator/{set_card_field,views}.py`, `application/handoff/work_item.py` (`DdsWorkItem.field_specs`), `application/reports/{truth_vs_card,assemble_report}.py` (by schema), `api/routers/reference.py` (card-schema), `openapi.yaml` (`CardFieldSpec` additive props), one schema-2 example scenario on pack `v046_24-r1` with `GENERATED_CARD` (prefab in v2 paths). **Added by B1 (rung 1, manager decision):** reference plumbing — `domain/routing/catalog.py` (`ReferenceCatalog.card_schema(pack_id)`), `infrastructure/reference/file_catalog.py` (loads `card-schema/*.yaml` pinned by the manifest), `manifest.json` gains pack `v046_24-r1`; session → schema lookup through `ScenarioVersion.reference_pack_id` via the version repository (`application/operator/command_context.py`, no migration); the card ↔ classifier binding (70 §70.5.2: codes = признак text, flag keys, `group_no`, catalog okrug/district; `options[].classifier_features`; `routing_relevant: true` on `incident.types`, `incident.classifier_code`, every `q.*` toggle set, the three header flags, `address.okrug`, `address.district`); `address.okrug` / `address.district` as `SELECT`s from the catalog; `backend/tools/import_services.py` takes `v046_24.columns.json` as a second input and appends the classifier-only orgs as `display: false` entries, `FIRE_RESCUE` answers to `MCHS_ODS_PSC` too (`classifier_org_ids`); manifest re-pinned. **Migration:** none. **Leaves:** every frontend change (E3b, E3c); a UI to edit the questionnaire; no resolver call yet — `routing_relevant` has no consumer until E2b′ | §3, §9, §10; REQ-3001–3008, REQ-3014, REQ-3044 | 70 §70.5; D17 | v1 schema file ≡ today's `CARD_FIELDS` (field-by-field test; `test_inv_03_*` imports by name still pass); conditions fixtures green; a hidden field is accepted (advisory); `CONTAINS` on `STRING_LIST`; INV 3 (DDS field specs come from the pack, the DDS service still gets no `ScenarioVersion`); INV 4; **added by B1:** the binding coverage test (every routing-relevant option resolves to ≥1 признак of its group; every chip-reachable group-1/«Запах газа»/«Взрывы» row is reachable), the `display: false` count, `FIRE_RESCUE` maps both MCHS columns |
| E2b′ | 1 | **Routing resolver and the notification list** (re-issued by B1, after E3a′) — **Modules:** `domain/routing/resolve.py`, `domain/events/{types,catalog}.py` (+`RECIPIENTS_RESOLVED`, `HANDOFF_CREATED` additive keys), `application/operator/{set_card_field,select_service,deselect_service,views}.py`, `application/handoff/{create_handoff,prefab_handoff}.py` (final resolve, union), `domain/layers/{handoff,copies}.py`, `domain/scoring/evaluators/service_selection.py` (`SESSION_END` fold), HLD 40 §40.4 row, frontend `features/operator/services-panel.tsx` (modal picker with search, auto/manual marking, no remove under v2). ~~API tests run against a **fixture pack** injected through `ReferencePort` (the real v2 card arrives in E3a)~~ — **retired by B1**: E2b′ runs on pack `v046_24-r1` and E3a′'s example scenario. **B1 re-issue (rung 1):** step 1 — group by `incident.types`; rows covered by the card's codes (via `classifier_features`); union of the candidates until `incident.classifier_code` is set; A-3 entries produce nothing; step 2 — flags from codes, missing ⇒ false; **any** holding sub-column; step 3 — district from `address.district`, prefecture from `address.okrug`; BX for ТиНАО else BW (70 §70.6.4 resolver defaults); `informed_services` exercised by the real `display: false` orgs. **Migration:** none. **Leaves:** ~~the real v2 questionnaire (E3a)~~ (retired: E3a′ lands first); v1 cards keep manual selection only (no classifier path on v1, so v1 stays exactly today's 38 fields) | §2 (C11), §9, §10; REQ-3009, REQ-3025, REQ-5261, REQ-5275, REQ-5280 | 70 §70.6.4, §70.7; D18, D19 | INV 4 (a routing-path `setCardField` appends `CARD_FIELD_CHANGED` + `RECIPIENTS_RESOLVED` and no second revision); resolver fixtures from the memo's worked examples (A-1) and, per B1, the four «КАРТОЧКА 112.docx» frames image19/22/24/39 (the first three exact; image39 records «Деп. ЖКХ» as a finding) plus REQ-5314/5315/5324; `409 SERVICE_REMOVAL_FORBIDDEN` under v2, `200` under v1 (C10); `SERVICE_SELECTION` at `HANDOFF` unchanged, at `SESSION_END` folds the last resolution; rescore equality |
| E4a | 1 | **Lessons, timers, card status (backend)** — **Modules:** `domain/lesson/{lesson,plan}.py` (`LESSON_TRANSITIONS`, arrivals), `domain/scenario/*` (key `timers`, R39), `domain/dds/card_status.py` (pure; legs mirrored from the stage), `domain/events/*` (+`DDS_CARD_STATUS_CHANGED`, `SESSION_CREATED`/`SESSION_STARTED` additive keys), `application/lessons/{create_lesson,start_lesson,abort_lesson,lesson_runner,queries,release,lesson_report}.py`, `application/dds/stage_automation.py` (deadlines) + the flush-before-append hook in every session UoW, `application/sessions/{create_session,start_session}.py`, `application/reports/release_report.py` (`CHECKED`), `infrastructure/persistence/lesson_repository.py`, `api/routers/{lessons,incidents}.py`, composition root (runner re-adoption), HLD 40 row. **Migration:** `0011_lessons` (+ `card_status` backfill). **Leaves:** leg response statuses (E5a — `ACCEPTED` ≡ `DDS_ACKNOWLEDGED` until then); lesson-level WS feed; E9a groups/weights UI; all screens (E4b) | §1, §13 (kept), §7; REQ-5254, REQ-5283, REQ-5305–5312, REQ-5909/5910, REQ-6020/6021, REQ-3010 | 70 §70.3, §70.4.6, §70.8; D15 | INV 8 (`LESSON_TRANSITIONS` table-driven); INV 5 (a 3-card lesson = 3 sessions × 1 incident); INV 7 (tick 100 ms vs 900 ms ⇒ identical `DDS_CARD_STATUS_CHANGED` stream; deadline events precede later-stamped commands); INV 13 (lesson list refresh); runner re-adoption after restart; allow + deny test per arrival kind; card-status precedence table (A-5); migration backfill test |
| E4b | 1 | **Lesson screens (frontend)** — **Modules:** instructor lesson form (plan editor, arrivals, per-card variants), `features/lesson/*`, `features/dds/incident-list-page.tsx` («Список/Поиск происшествий», ui-check D-8), `features/operator/register-page.tsx` (112 «реестр», D-2), countdowns from `IncidentListItem` offsets, one existing socket per active card, `ru.ts` strings. **Migration:** none. **Leaves:** the reference look (E7a); lesson report UI beyond the list of N card reports | §32; REQ-5909/5910, REQ-5312 | 70 §70.3.6; D12, D15 | vitest: the list never derives a status (renders `card_status` only); red flag for `NOT_NOTIFIED`/`REFUSED`/`NOT_COMPLETED`; refresh restores the list (INV 13, client side) |
| E3b | 2 | **112 card 1:1 (frontend)** — **Modules:** `features/operator/card-form.tsx` rewritten to the reference layout (header strip: АОН / предоставленный / на место phones and the red `fill_within_ms` timer; applicant and address blocks; «Что случилось» chips; questionnaire blue toggle tags; orange services bar with the E2b modal), `entities/card/*` (TS `CardCondition` evaluator over the shared fixtures), generated types, `ru.ts`. **Migration:** none. **Leaves:** pixel-level look and screenshot comparison (E7a); a 112 trainee filling from a text narrative under `GENERATED_CARD` (A-7) | §9, §32; REQ-3001–3014; ui-check D-3…D-7 | 70 §70.5.2–§70.5.3; D17 | vitest: one command per field (unchanged D12 rule), `visible_when` over the shared fixtures, v1 cards still render from `field_specs` |
| E3c | 2 | **ДДС and report render by schema (frontend)** — **Modules:** `features/dds/*` sentence view from `field_specs` + option labels (D-9), delete `features/dds/card-field-labels.ts`, generated-card display on the ДДС side, `features/report/{snapshot-card-fields.ts,handoff-section.tsx}` by schema. **Migration:** none. **Leaves:** the memo workstation (E5c) | §10, §29, §32; ui-check D-9 | 70 §70.5.4; D17 | vitest: no hard-coded card label list remains (grep test); a v1 and a v2 snapshot both render |
| E5a | 2 | **ДДС memo mode — leg machine (backend)** — O-1 decided (option (a) tightened): one additive `DDS_TRANSITIONS` row `ACKNOWLEDGED --close--> RESOLVED`, guard `memo_all_legs_terminal`, the only memo closure path; `RESOURCE_SELECTION` … `WORKING` never entered in memo mode. **Modules:** `domain/dds/{response,policy}.py` (`ServiceResponseStatus`, `SERVICE_RESPONSE_TRANSITIONS`, `NO_REFUSAL`), `domain/dds/assignment.py`, `domain/dds/card_status.py` (leg-aware), `domain/session/{transitions,guards}.py` (the additive row, `memo_all_legs_terminal`, `DDS_GUARDS_MEMO`), `domain/roles/{module,dds}.py` (memo action map, `SET_SERVICE_STATUS`), `domain/events/*` (+`DDS_CARD_OPENED`, `DDS_SERVICE_STATUS_SET`, `HANDOFF_RECEIVED` additive keys), `application/dds/{set_service_status,open_card,acknowledge,close_incident,stage_automation,command_context,views}.py` (memo close fires `close` twice in one UoW; picker mirror), `infrastructure/persistence/*` (history), `api/routers/dds.py` (legs, open, status), HLD 10 §10.8 (the new `DDS_TRANSITIONS` row) and §10.9 (memo available-actions table) + `test_dds_tables_match_the_hld.py` (parses §10.7/§10.9) taught the variant-labelled table, HLD 20/40; `IMPLEMENTED_VARIANT_VALUES` += `MEMO_STATUSES`; product default flipped to `MEMO_STATUSES` for schema 2. **Migration:** `0012_dds_response_status` (with backfill by the picker map). **Leaves:** service binding, scripted responders, card check (E5b); UI (E5c) | §7 (states kept), §11; REQ-5281–5297, REQ-5327/5328, REQ-3041 | 70 §70.4.1–§70.4.4, §70.4.6; D16 | INV 8 (every non-listed leg transition fails; skipping a step fails, A-8; the new `close` row allowed in memo only when every leg is terminal, denied in picker; every resource trigger rejected in memo); memo scoring rules key on `DDS_SERVICE_STATUS_SET`, not on dispatch events; `422 COMMENT_REQUIRED`; 103 `complete_without_brigade`; picker mirror map; memo guards allow + deny; INV 3 (constructor signatures of the new DDS use cases); rescore equality for a memo session (INV 9); order number kept per entry (A-2) |
| E5b | 2 | **Several ДДС trainees, scripted responders, card check** — **Modules:** `application/sessions/{create_session,authorisation}.py` + lesson participants (`assigned_service_id`, distinct per session), `guard_leg_actor_bound` (`403 FORBIDDEN_FOR_SERVICE`), `domain/scenario/*` (key `expected_response.responders`, R36 active), scripted responders in `application/dds/stage_automation.py`, `application/dds/flag_card_issue.py` + `DDS_CARD_ISSUE_FLAGGED` (`FLAG_CARD_ISSUE`), `IMPLEMENTED_VARIANT_VALUES` += card check `ON`, `application/reports/dds_decisions.py` (status history, per-participant totals). **Migration:** none (0012 already carries the columns). **Leaves:** brigade voice (H2/E6) | §1 (MULTI_TRAINEE), §13, §28; REQ-5297, REQ-5915/5916 (C1) | 70 §70.4.5, §70.2; D16, D19 | `tests/api/modes/test_multi_trainee_two_users.py` extended to two ДДС trainees bound to two services; INV 7 (scripted responder stream identical at two tick rates); INV 3 (responders read only by stage automation); card-check rules non-applicable when `OFF` |
| E5c | 2 | **ДДС memo workstation (frontend)** — **Modules:** `features/dds/*` per-service blocks (collapsed last status + time, expandable history with author, pencil form «Статус / Номер наряда / Комментарий», dropdown = the leg's `available_actions`), every notified service's block visible, 103 policy UI, «Отметить ошибку в карточке» under card check, the picker UI kept behind `RESOURCE_PICKER`, instructor participant→service assignment in the session and lesson forms, report `dds_decisions` history. **Migration:** none. **Leaves:** pixel look (E7a) | §11, §32; REQ-5292–5295, REQ-3041; ui-check D-10 | 70 §70.4; D16 | vitest: buttons only from `available_actions`; comment field required client-side mirrors the 422; both `dds_mode` variants render |
| E7a | 2 | **Reference look 1:1 for the 112 card and ДДС screens** — **Modules:** light theme tokens (orange bar `#EC653B`, blue tags `#157DBD`, backgrounds `#EFEFEF` / `#C9CED1`) applied to the E3b card, the E4b lists and the E5c workstation; reference images extracted from «СКРИНШОТ КАРТОЧКИ 112ГСИ.docx», «СКРИНШОТ ДДСГСИ.docx» and the memo PDF into the frontend test tree; Playwright screenshot comparison with a per-screen tolerance — Playwright as a frontend `devDependency` (approved), pinned to the version whose browser is already cached in `~/.cache/ms-playwright`; no new browser download unless unavoidable (A-12). **Migration:** none. **Leaves:** screens with no reference counterpart (login, instructor, report — ui-check D-11) keep D12's look | §32; assessment §4.4; ui-check D-1…D-10 | D20 (C9) | Playwright diffs per reference screen under tolerance; vitest unchanged; no behaviour change (API snapshot tests untouched) |
| E6a | 3 | **SIP gateway core + echo + latency probe** — no domain change. **Modules:** `workers/voice_agent/voice_agent/transport/sip/{message,registrar,dialog,rtp,bridge,gateway,softphone}.py` (RFC 3261 subset, Digest, SDP, G.711 via `audioop`, `FakeRoomBridge` / `LiveKitRoomBridge`), `voice_agent/sip_gateway.py` (entry), `voice_agent/tools/softphone.py` (CLI, `--headset` via sox), `Settings` `SIM_SIP_*` (port 5060 udp+tcp, RTP 20000–20199, realm, password from env, media ip, jitter, health 8114), `infra/docker-compose.yml` service `sip-gateway` under `profiles: ["sip"]`, `benchmarks/benchmark_voip.py` (`sip-loopback` in the gate; `sip-livekit` / `livekit-only` `requires_livekit`), HLD 50 §2.1 note, HLD 60 §9 service note, README/RUNBOOK ports. **Migration:** none. **Leaves:** every number but `999`; per-user SIP credentials; G.722; `SipCallTransport` (plan B, only if the checkpoint fires). **Falsification checkpoint** (80 §80.11) before E6b–E6d are staffed | §15, §36, §40; REQ-2249, REQ-2139, REQ-2150, REQ-4004, REQ-1025 | 80 §80.2, §80.8, §80.11; D22 | `workers/voice_agent/tests/sip/`: headless UA ↔ in-process gateway on loopback — REGISTER 401→200, wrong password 403, expiry; INVITE 100/180/200/ACK, PCMA/PCMU answer, 2 s RTP both ways (seq/timestamp continuity), BYE, CANCEL, OPTIONS, echo `999`, malformed ⇒ 400 without a crash; codec round-trip bounds; `check_imports` green; `benchmarks/tests/` `sip-loopback` delay < 60 ms + JSON shape; `compose-check` renders the profile; manual: `--headset` call to `999`, `baresip` only if present offline (else `NOT_RUN`), `sip-livekit` p50/p95 into `docs/benchmarks/voip.md` |
| E6b | 3 | **ДДС calls in the domain + browser endpoint + claimant call** — **Modules:** `domain/dds/call.py` (`DdsCall`, `DDS_CALL_TRANSITIONS`, kinds, endpoint), `domain/routing/dial_plan.py` (pure), `domain/events/{types,catalog}.py` (+`DDS_CALL_STARTED/ANSWERED/ENDED`), `domain/scenario/validation.py` (R41), `domain/roles/dds.py` (call actions + `PLACE_DDS_CALL` under `ON`), `domain/session/variants.py` (`IMPLEMENTED_VARIANT_VALUES["dds_brigade_call"] += ON`), `domain/scoring/{context,evaluators/fact_obtained}.py` (DDS call ids excluded from `deliveries_of`; `on_call` additive), `application/dds/{start_dds_call,end_dds_call,dds_call_flow,dds_call_views}.py` (`application/operator/call_flow.py` untouched), `application/voice_token/create_voice_token.py` (`call_id`), `application/dialogue/prompt_builder.py` (speaker-label parameter only), `application/realtime/redaction.py` (call-scoped `▲`), `workers/voice_agent/voice_agent/main.py` (`_calls` keyed by `(session_id, call_id)`; `call_kind: CLAIMANT` → today's pipeline; no `call_state` write for DDS calls), `infrastructure/persistence/dds_call_repository.py`, `api/routers/dds.py`, `openapi.yaml` (delta items `x-epic: E6b`), HLD 10 §10.13 / HLD 30 §30.8 / HLD 40 §40.4 + §40.6 (`voice:join` keys) rows, frontend `features/dds/phone-widget.tsx`, `entities/call` store per `call_id`, «Позвонить заявителю», `ru.ts`. **Migration:** `0014_dds_calls` (table `dds_calls`, additive). **Leaves:** service head, 112 operator, SIP endpoint, inbound calls | §8, §15, §16, §20; REQ-5917/5919/5920, REQ-1028 | 80 §80.3, §80.5, §80.6, §80.7; D23, D25 | `backend/tests/api/dds/test_dds_calls.py` on fakes: `kind: CLAIMANT` runs the frozen chain — INV 1, INV 12, INV 14 per `call_id`; claimant `busy` while the 112 call is live; a DDS call's `FACTS_DELIVERED` moves no 112 `FACT_OBTAINED` score; INV 8 table-driven on `DDS_CALL_TRANSITIONS`; INV 13 (`GET …/dds-calls` + `createVoiceToken {call_id}` restore a live call); `409 DDS_LINE_BUSY`; call-scoped visibility (a DDS call's `CALLER_TTS_STARTED` never reaches an OPERATOR_112 socket); `OFF` sessions append no `DDS_CALL_*` and offer no call action; R41 allow + deny; rescore equality (INV 9); INV 3 constructor signatures; manual: browser call from the ДДС console with real models (GPU lock) |
| E6c | 3 | **Service-head AI voice by category** — **Modules:** `reference/personas/v1.yaml` + manifest re-pin, `domain/dds/personas.py` (pure, `code` > `kind`), `domain/dds/responders.py` (optional `report: CALL_IN`, `persona` override), `domain/scenario/validation.py` (R42), `application/dds/stage_automation.py` (under `ON`, `TRAINEE` legs' steps not applied; `CALL_IN` steps start an `INBOUND` `DdsCall`), `application/dds/answer_dds_call.py`, `application/dialogue/{responder_context,responder_templates,responder_prompt_builder}.py`, `application/dialogue/interpreter.py` (responder slot catalog), `domain/events/*` (+`DDS_CALL_STATUS_PROPOSED`, `DDS_CALL_ASSERTION`, `DDS_SERVICE_STATUS_SET.proposed_by_call_id`), `application/dds/set_service_status.py` (`422 PROPOSAL_UNKNOWN`), `voice_agent/tts_cache.py` (warm-up line cache), `Settings.responder_dialogue = template \| llm`, profile `tts.voice_map` male ids (verified against the installed `qwen_tts`), scoring fixtures (`WORKFLOW_ACTION` / `DEADLINE` on the new events; `CALL_STATUS_TRANSCRIBED` only if `must_occur_after` cannot express it), report calls grouped by `call_id` with party labels, `GET /reference/personas`, HLD 10/30/40 rows, `openapi.yaml` (`x-epic: E6c`), frontend «Позвонить старшему», «Ответить», proposal chip on the pencil form. **Migration:** none. **Leaves:** 112 operator; SIP endpoint | §16, §20–§24, §28; REQ-1028, REQ-1038, REQ-5918, REQ-4041, REQ-5325 | 80 §80.3.3, §80.4, §80.6; D24 | persona by catalog `code` / `kind` (fixtures 101/102/103/104/DISTRICT); first-call checklist + `DDS_CALL_ASSERTION` by code; later-call proposals identical at tick 100 vs 900 ms (INV 7); a not-yet-due step never spoken (INV 2); proposal → trainee confirmation → history; INV 3-style constructor test for `ResponderContextLoader`; `test_r3`-style signature test for the responder prompt builder; INV 1/2/14 in `template` and `llm` modes; `OFF` sessions unchanged (E5b tests green); R42 allow + deny; manual: bench call with a real 101 persona voice (GPU lock) |
| E6d | 3 | **ДДС→112 answered by an AI 112 operator** (owner Q1 default) — **Modules:** `reference/personas/v1.yaml` (`OPERATOR_112`), `application/dialogue/responder_templates.py` (REQ-5332 checklist), `DDS_CALL_ASSERTION` field paths for the checklist (`call.self_identification`, `call.card_reference`, `address.*`, `incident.change`), scoring fixtures, frontend «Позвонить в 112», `openapi.yaml` (`OPERATOR_112` kind enabled). **Migration:** none. **Leaves:** a human 112 trainee on a second line — reserved hook `DdsCall.kind = OPERATOR_112`, `answered_by: TRAINEE`, later sub-epic E6g (not in I3) | §28; REQ-5332 | 80 §80.3.4, §80.10; D23 | on fakes: every checklist item covered ⇒ assertions ⇒ rule points; a missing self-identification ⇒ penalty; the persona's knowledge is the snapshot only (INV 3 constructor test); `answered_by` is `AI` on every I3 call |
| E6e | 3 | **SIP endpoint wired to the domain** (re-issued as plan B / Asterisk-AudioSocket if the E6a checkpoint fires) — **Modules:** gateway dial handling → `POST /api/v1/telephony/dial` (service credential `SIM_SIP_GATEWAY_SECRET`) → `startDdsCall` (dial plan, session selection), `POST /api/v1/telephony/calls/{call_id}/leg`, `GET /api/v1/telephony/calls/{call_id}`, `api/routers/telephony.py`; gateway subscribes to `voice:join` (`endpoint: SIP`), `voice:cancel:*`, `session:{id}:events`; click-to-call and `CALL_IN` to a registered softphone (UAC INVITE); endpoint choice via the Redis key `sip:binding:{username}` (HLD 40 §40.6 row); `DDS_CALL_STARTED.endpoint = SIP`; SIP username ↔ `users.username`; optional per-user HA1 (`GET /telephony/sip-credentials/{username}`); `DdsLegView.phone_extension` and the claimant's number on the ДДС screen; `openapi.yaml` (`x-epic: E6e`); RUNBOOK «SIP-телефон». **Migration:** `0015_users_sip_ha1` (optional, additive: `users.sip_ha1`). **Leaves:** G.722; SRTP/TLS; PSTN | §15; REQ-2249, REQ-2150, REQ-2168, REQ-1038 | 80 §80.2.3, §80.3.5, §80.3.7, §80.7; D22, D25 | gate: headless UA dials `101` / `7xxx` / `112` / the claimant's digits against the gateway + a fake backend dial endpoint, and the real use case on fake transport; session selection (last opened card wins, else oldest); `404 DIAL_NUMBER_UNKNOWN` ⇒ SIP 404, `409 NO_ACTIVE_DDS_SESSION` ⇒ SIP 480; `leg DOWN` ⇒ `hang_up` TRAINEE, `FAILED` ⇒ SYSTEM `ABORT`; loss of `sip:binding:*` ⇒ browser endpoint; manual: `tools/softphone --headset` (and `baresip` only if present offline) through the full stack |
| E6f | 3 | **VoIP load sweep and the ТЗ ¶161 record** — **Modules:** `benchmark_voip.py --concurrent N` sweep (1/5/10/20/40) over `sip-livekit`, gateway / SFU CPU (`/proc`), loss, jitter; `docs/benchmarks/voip.md` final; `DEV_3060TI.yaml` `voip.one_way_delay_ms_p50/p95`, `voip.concurrent_calls_measured` (measured, or absent); `docs/AUDIT.md` / assessment cross-reference for REQ-2139 and the «≥ 20 concurrent» row. **Migration:** none. **Leaves:** AI-in-the-loop concurrency (E19 VRAM, stated as unmeasured) | §40; REQ-2139 | 80 §80.8.3; D22 | the measured p50/p95 vs 150 ms; the highest N with p95 ≤ 150 ms and loss < 1 %; `NOT_RUN` where a path was not run; no number in the repo a script did not produce (`_common.py` contract) |

### How wave 3 hangs off this design

- **H2 → E6 (telephony).** Designed in `docs/hld/80-telephony.md` (D22–D25); the sub-epics are the
  rows E6a–E6f above, the contract delta is `docs/hld/contracts/i3-telephony-openapi-delta.yaml`.
- **E8 (96 tickets → scenarios).** Each ticket (OCR in `requirements/evidence/tickets-ocr.md`) becomes
  schema-2 scenario content on pack `v046_24-r1`, marked as a candidate for generation (where the mark
  lives is E8's to decide within schema 2); a ticket's three calls are a lesson plan of three entries;
  competence-decline cases use `responders` / `NOT_ACCEPTED` and close through the memo-only `ACKNOWLEDGED --close--> RESOLVED` row (O-1 decided); card-error cases
  use deliberately imperfect `prefab_handoff` values plus `dds_card_check: ON` rules.
- **E9a (instructor).** Distinct tasks per workstation = `PlanEntry.participants`; groups key to lessons;
  difficulty = `ScenarioVersion.difficulty` + `PlanEntry.weight`; AI-suggested weights are proposals an
  instructor accepts — scoring stays deterministic (70 §70.3.7).

## I4 TBD epics

Issued by E24, the I4 wave-4 HLD (`docs/hld/71-i4-wave4.md`, decisions D29–D35), from the accepted
E22 analysis §3.3. These rows are initiative-I4 epics. Each row lands green on its own (`make gate`,
run alone between commits).

Every row owes, in the same commit:
- the HLD 10/20/30/40 and `openapi.yaml` updates for exactly what it implements, copied literally
  from `71-*.md`, from `docs/hld/contracts/i4-openapi-delta.yaml` (the items tagged with its
  `x-epic`) and from HLD 20 §20.11;
- when it creates a table, the move of that table from §20.11 into §20.1 and §20.x. The §20.1
  inventory is parsed by `test_migration_baseline.py`.

Each row states what it leaves out. Every item it leaves out is an owner question
(`docs/owner-decisions.md`) or a named out-of-scope item. The I4 rule (D29): nothing ambiguous is
built.

**Hot shared files rule.** These files are touched by several slices:
- `backend/app/api/container.py`
- `docs/hld/openapi.yaml`
- `frontend/src/shared/i18n/ru.ts`
- `frontend/src/shared/api/client.ts`
- `docs/hld/20-db-schema.md`

Each epic **appends its own section** to them and never rewrites or reorders another epic's section.
The manager regenerates `frontend/src/shared/api/schema.d.ts` **last**, after the wave's contract
merges, the same as E9a/E6b.

**Migrations are pre-allocated (D30):**
- `0016_audit_log` (E25);
- `0017_result_comments_scenario_archive` (E32);
- `0018_training_materials` (E34).

No other I4 epic adds a migration. The epic that lands a migration sets `down_revision` to the head
at that moment. The chain at E24 ends at `0015_users_sip_ha1`.

**Waves:**
- α: E25 ∥ E26 ∥ E32 ∥ E34. E31 starts as soon as E21 is committed (3ee2764).
- β: E27 (after E26) ∥ E28 (after E25) ∥ E31.
- γ: E29 (after E25 and E26) ∥ E33 (after E31).
- δ: E30 ∥ E35.

| # | Slice | Wave | Deps | Tier | Migration |
|:--|:--|:--|:--|:--|:--|
| E25 | S1 Audit + JSON logs | α | — | opus | `0016_audit_log` |
| E26 | S2 Ops hardening + backup/restore | α | — | sonnet | none |
| E27 | S3 TLS edge | β | E26 | opus | none |
| E28 | S4 Accounts backend | β | E25 | sonnet | none |
| E29 | S5 Admin monitoring backend | γ | E25, E26 | sonnet | none |
| E30 | S6 Admin UI | δ | E28, E29 | sonnet | none |
| E31 | S7 Instructor core | α → β | E21 committed | opus | none |
| E32 | S8 Instructor misc | α | — | sonnet | `0017_result_comments_scenario_archive` |
| E33 | S9 Reports, statistics, CSV, trainee history | γ | E31 | sonnet (opus review of the norms) | none |
| E34 | S10 Materials | α | — | sonnet | `0018_training_materials` |
| E35 | S11 Text quality (report-only) | δ | E23 data, E33 | sonnet | none |

### E25 — S1 Audit + JSON logs

- **Kind:** TBD.
- **Wave:** α.
- **Deps:** none.
- **Tier:** opus, because it touches every request path.
- **Migration:** `0016_audit_log`.
- **Content** (71 §71.2, D31):
  - `application/ports/audit_log.py` (`AuditRecorder`, `AuditReader`, `AuditEntry`);
  - `infrastructure/persistence/audit_log_repository.py`;
  - the ASGI audit middleware in `api/main.py`, with no bodies and `/health/*` excluded, which also
    records 401/403 and WebSocket connects;
  - `loginUser` recording success and failure;
  - the real actor on `rescoreSession persist=true`;
  - `infrastructure/logging/json_formatter.py`, wired into uvicorn `log_config`, the backend, the
    voice agent and the SIP gateway;
  - `SIM_AUDIT_RETENTION_DAYS` (≥ 183, default 365), `SIM_LOG_FORMAT`, `SIM_LOG_DIR`;
  - HLD 20 §20.11.1 moved into §20.1 and §20.6.
- **Areas:** `api/main.py`, `application/ports`, `infrastructure/{persistence,logging}`, `db/*`,
  the logging lines of the workers.
- **Tests owed:**
  - UPDATE/DELETE on `audit_log` rejected;
  - one entry per contract route except health, parametrised over `openapi.yaml`;
  - a login failure recorded without a password;
  - retention < 183 refused.
- **Leaves:** the semantic before/after journal (Q-E15-3); the read API (E29).

### E26 — S2 Ops hardening + backup/restore

- **Kind:** TBD.
- **Wave:** α.
- **Deps:** none.
- **Tier:** sonnet.
- **Migration:** none.
- **Content** (71 §71.3, D33):
  - redis `requirepass` (`SIM_REDIS_PASSWORD`, `SIM_REDIS_URL`);
  - postgres and redis ports bound to `127.0.0.1`;
  - `restart: unless-stopped` on postgres, redis and livekit;
  - `livekit.yaml` `json: true`;
  - the compose service `backup` on `postgres:16`: a daily `pg_dump -Fc` plus a `tar.gz` of
    `recordings-data` into `./backups/`, keeping `SIM_BACKUP_KEEP` (14), and writing `last.json`;
  - `infra/scripts/restore.sh`;
  - `make backup-now`, `make restore FILE=…` and `make backup-verify`;
  - the RUNBOOK sections «Резервное копирование» and «Восстановление», with one recorded restore
    walk.
- **Areas:** `infra/**`, `.env.example`, `Makefile`, `docs/RUNBOOK.md`.
- **Tests owed:** unit tests of `last.json` parsing. There is no gate-side restore test.
- **Leaves:** service control from the UI (Q-E14-2); an off-box copy.

### E27 — S3 TLS edge

- **Kind:** TBD.
- **Wave:** β.
- **Deps:** E26 (same compose and `.env` files).
- **Tier:** opus, because it changes every client URL and the LiveKit signalling.
- **Migration:** none.
- **Content** (71 §71.4, D32):
  - **step 1: pull the Caddy image, within the time-box the brief sets**;
  - the `edge` service on 443 (frontend, `/api`, `/api/v1/ws`, `/rtc` → livekit), with gzip/zstd;
  - `infra/scripts/make-certs.sh` (local CA plus a server certificate with SANs);
  - `SIM_LIVEKIT_PUBLIC_URL=wss://…`;
  - CORS and Vite `allowedHosts`;
  - the RUNBOOK section on installing the CA.
  - If the pull fails, build the named fallback instead: uvicorn TLS, Vite https, and the backend
    proxying `/rtc`.
- **Areas:** `infra/**`, `frontend/vite.config.ts`, `.env.example`, RUNBOOK.
- **Tests owed:** a Playwright check of `window.isSecureContext` via `https://<LAN-IP>`; the phone
  widget over `wss://`.
- **Leaves:** SIP TLS/SRTP (Q-E15-2).

### E28 — S4 Accounts backend

- **Kind:** TBD.
- **Wave:** β.
- **Deps:** E25, so that the actions are audited.
- **Tier:** sonnet.
- **Migration:** none.
- **Content** (71 §71.5):
  - `application/users/{create_user,update_user,set_active,reset_password}.py`;
  - the guards: no blocking or demoting yourself, and the last active ADMIN kept;
  - `createUser`, `updateUser`, `resetUserPassword`, and `listUsers` `include_inactive`, plus
    `UserAccount.is_active` (delta `x-epic: E28`);
  - `api/routers/{users,admin}.py`.
- **Tests owed:**
  - the role gate;
  - the self and last-admin guards;
  - a blocked user's live token refused on the next request;
  - one audit entry per operation.
- **Leaves:** Q-E14-1, Q-E15-1, Q-E14-4, Q-E16-4; custom rights.

### E29 — S5 Admin monitoring backend

- **Kind:** TBD.
- **Wave:** γ.
- **Deps:** E25, E26.
- **Tier:** sonnet.
- **Migration:** none.
- **Content** (71 §71.6):
  - `listAuditLog`;
  - `getUsageStats` (per day: logins, sessions, lessons, active users);
  - `getServerLoad` (`/proc`, `shutil.disk_usage`; GPU from the heartbeat or `null`);
  - `getErrorReport` (the JSON log at ERROR or above, `MODEL_ERROR`, FATAL transitions);
  - `listAdminAlerts` (derived: FATAL, a stale or failed backup, login failures);
  - `getBackupStatus`;
  - `purgeRecordings` `409 BACKUP_REQUIRED` (delta `x-epic: E29`);
  - `application/admin/*`, `api/routers/admin.py`, `application/recording/purge_recordings.py`.
- **Tests owed:**
  - an API test per operation;
  - an absent metric is `null`, never 0;
  - the purge refused and then allowed;
  - the alerts for a stale backup and for FATAL.
- **Leaves:** Q-E14-2, Q-E14-4, Q-E14-1. The metric set is to be confirmed (Q-E14-3).

### E30 — S6 Admin UI

- **Kind:** TBD.
- **Wave:** δ.
- **Deps:** E28, E29.
- **Tier:** sonnet.
- **Migration:** none.
- **Content** (71 §71.7):
  - `frontend/src/features/admin/*` at `/admin`, ADMIN only, with `homeRouteForRole` updated;
  - the tabs Пользователи / Журнал / Статистика / Нагрузка / Ошибки / Оповещения;
  - the backup status;
  - the alerts badge in the app shell;
  - the `ru.ts` strings.
- **Tests owed:** a vitest per tab; the route refused to non-ADMIN users; «нет данных» for an absent
  metric.
- **Leaves:** as E28 and E29.

### E31 — S7 Instructor core

- **Kind:** TBD.
- **Wave:** α → β. It starts once E21 is committed, because it edits `scenarios/tickets/**`.
- **Deps:** E21 committed.
- **Tier:** opus, because it changes scoring and the scenario schema.
- **Migration:** none.
- **Content** (71 §71.8, D34):
  - `PlanEntry.timers` and `SessionCreateRequest.timers`, resolved as scenario ← override and
    recorded in `SESSION_CREATED.timers`;
  - `DeadlineConfig.max_offset_timer`, which reads the recorded timer;
  - scenario rule R43 (HLD 30);
  - the tickets' `memo_*_in_time` rules switched to `max_offset_timer: accept_within_ms`;
  - ABORTED cards in `getLessonReport`, with `score: null` and `unscored`;
  - the lesson form timer fields;
  - HLD 10/30/70 updates;
  - delta `x-epic: E31`.
- **Areas:** `domain/{lesson,scenario,scoring}`, `application/{lessons,sessions}`, the lesson form.
- **Tests owed:**
  - INV 9 with an overridden timer;
  - R43 allow and deny;
  - a lesson aborted mid-card lists the card unscored with its events, and the weighted sum ignores
    it;
  - the ticket fixtures still pass with the default timers.
- **Leaves:** Q-E9b-2, Q-E9b-6, Q-E9b-3, Q-E9b-5.

### E32 — S8 Instructor misc

- **Kind:** TBD.
- **Wave:** α.
- **Deps:** none.
- **Tier:** sonnet.
- **Migration:** `0017_result_comments_scenario_archive`.
- **Content** (71 §71.9):
  - `result_comments`: append-only, edits as new rows;
  - `list/createSessionComment` and `list/createLessonComment`, shown under the report visibility
    gate, and the report section «Комментарии преподавателя»;
  - `scenarios.archived_at`, `archiveScenario`/`unarchiveScenario`, and `listScenarios`
    `include_archived`;
  - the «Сценарии» upload page (`validateScenarioFile` → `importScenarioVersion`);
  - the `/instructor/board` all-trainees board, built from `getLesson` plus sockets, or from the
    optional `getLessonBoard`;
  - delta `x-epic: E32`.
- **Areas:** the new comments module, `api/routers/{reports,scenarios,lessons}.py`,
  `features/{instructor,report}`.
- **Tests owed:**
  - comment visibility equals report visibility;
  - an edit is a new row;
  - an archived scenario is hidden and its running session unaffected;
  - the upload page shows the issues;
  - the board lists every card.
- **Leaves:** instructor isolation, Q-E9b-4 (no change, D-g); the expert grade, Q-E9b-5.

### E33 — S9 Reports, statistics, CSV, trainee history

- **Kind:** TBD.
- **Wave:** γ.
- **Deps:** E31, because the norms read the recorded timers and it shares the lesson report shape.
- **Tier:** sonnet, with an opus review of the norms definitions.
- **Migration:** none.
- **Content** (71 §71.10):
  - the pure `application/reports/norms.py` (accept and fill against the norm, deviation, failed
    rules, criticals);
  - `getLessonReport` `norms`;
  - `getTraineeStatistics`, `getTraineeStatisticsCsv`, `getMyHistory` and `getLessonReportCsv`
    (UTF-8 BOM, `;`, Russian headers);
  - the lesson report table with «Скачать CSV», `/instructor/statistics` and the trainee's
    `/history`;
  - delta `x-epic: E33`.
- **Areas:** `application/{reports,statistics}/`, `features/{lesson,report,statistics,history}`.
- **Tests owed:**
  - no score is recomputed (D11);
  - the CSV round-trips to the same numbers;
  - a TRAINEE gets 403 for someone else;
  - ¶165: 30 s or less on seeded data (1000 sessions, marked).
- **Leaves:** Q-E12-1, Q-E12-2, Q-E12-3, Q-E9b-2; charts, heat maps and Excel/PDF (bonus); AI
  insights.

### E34 — S10 Materials

- **Kind:** TBD.
- **Wave:** α.
- **Deps:** none.
- **Tier:** sonnet.
- **Migration:** `0018_training_materials`.
- **Content** (71 §71.11):
  - `training_materials`, with files at `data_dir/materials/<sha256>`;
  - the allow-list (pdf, docx, doc, xlsx, txt, md, png, jpg) and `SIM_MATERIAL_MAX_MB`;
  - `uploadMaterial`, `listMaterials`, `getMaterialFile` and `archiveMaterial`;
  - the instructor page «Материалы» and the trainee page «Справочная база»;
  - delta `x-epic: E34`.
- **Areas:** the new `materials` module, `features/materials`.
- **Tests owed:** the role gates; the allow-list refusal; the sha dedupe; the download content type.
- **Leaves:** assignment (Q-E13-1); preloading the organizers' files (Q-E13-2); XML structure
  (¶368); certificates (Q-E16-2).

### E35 — S11 Text quality (report-only)

- **Kind:** TBD.
- **Wave:** δ.
- **Deps:** the E23 data (in `/tmp/teamwork-112-maxxing/data/`); E33, for the lesson and statistics
  columns.
- **Tier:** sonnet. It is blocked on Q-E11-1 for any scoring.
- **Migration:** none.
- **Content** (71 §71.12, D35):
  - `application/ports/text_checker.py` (`misspellings`, `street_status`);
  - the adapters in `infrastructure/reference/`: ru_RU hunspell via `spylls`, and the OSM street
    names;
  - **the packaging decision** for `reference/{lexicon,streets}`: sha-pinned, with licence notes
    (BSD-style LibreOffice dictionary, ODbL), plus the `spylls` dependency;
  - `application/reports/text_quality.py`, over the trainee-typed texts;
  - the report section «Грамотность и адреса» and the lesson and statistics column;
  - the fallback «Проверка недоступна…» (`available: false`);
  - its own `openapi.yaml` section, which is not in the I4 delta.
- **Tests owed:**
  - a seeded misspelling is found;
  - with the data absent the section says «Проверка недоступна»;
  - the score and the checksum are identical with and without the checker;
  - the data sha is recorded.
- **Leaves:**
  - any score effect (Q-E11-1);
  - streets outside Moscow (Q-E11-2);
  - Q-E23-1…Q-E23-4;
  - live underlining (contradicts REQ-6017);
  - changing «ул. Зверенецкая» (organizer-verbatim, D-h).

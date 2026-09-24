# AUDIT — SPEC §1–§47 requirement-by-requirement table, §46 Definition-of-Done table, deviations, and the HLD-gap fold (E20-D)

Snapshot: branch `feat/i1-simulator`, base commit `d00d6cd` (E19), captured **2026-09-22** while
E20-A/B/C/E were editing the same tree concurrently (E20-D touches only this file, `docs/hld/*.md`
prose and `docs/hld/90-tbd-epics.md`; no code). Rows that cite a file another E20 worker owns are
marked **IN PROGRESS (E20-x)** where this audit observed an uncommitted, partial fix in `git diff`
at capture time, and re-checked once more before hand-back (see the note at the end of §1).

**Method.** Source of the requirement-by-requirement table is
`/tmp/teamwork-112-maxxing/reports/e20-audit.md` ("audit-1", 190 lines, one row per SPEC §) merged
with `/tmp/teamwork-112-maxxing/reports/e20-audit-2.md` ("audit-2", 1174 lines, per-clause detail
for §2,3,5–12,14,17–19,22,25,27–29,32,35,37–39,42,43,46, Part 2 independent re-checks, Part 3
frontend-leak audit, Part 4 Russian-string audit). Both were produced read-only against the E19 tree
(commit `0beec6a`/`d00d6cd`). Every row below was re-derived from those two reports; rows that the
two audits disagreed on, or that this epic's own rulings (R1–R15) touch, were opened and re-verified
directly against the current tree (file paths/line numbers quoted below were read, not copied
blind). Verdicts:

- **IMPLEMENTED** — source and a focused test exist for the full requirement.
- **PARTIAL** — meaningful implementation exists but a specified edge, real-provider proof, or demo
  path is incomplete (cross-referenced to §3 "Not implemented / deviations" below).
- **MISSING** — no implementation/proof found.
- **EXCLUDED-BY-SPEC** — explicitly outside the initial product scope by the spec's own text.
- **IN PROGRESS (E20-x)** — an E20 sibling task is actively fixing this row in the same tree; the
  evidence column states the state observed at capture time.

## 1. SPEC §1–§47 requirement table

### §1 — Product

| requirement (quoted) | verdict | evidence |
|---|---|---|
| "The product is a local AI-powered training and assessment simulator for emergency-response personnel." | IMPLEMENTED | Full layer tree present (`backend/app/{domain,application,api,infrastructure,inference}`, `frontend/src/{app,features,entities,shared}`, `workers/voice_agent`); route groups `backend/app/api/main.py:36-100`, `frontend/src/app/router.tsx:41-75`. |
| "The same Incident object MUST survive all role transitions." | IMPLEMENTED | One `Incident` per `SimulationSession`, `backend/app/domain/session/session.py:102-188`; INV5 `backend/tests/invariants/test_inv_05_full_cycle_same_incident_one_timeline.py:144-227`. |
| "Supported session modes must be represented architecturally: SINGLE_ROLE, FULL_CYCLE_SINGLE_TRAINEE, MULTI_TRAINEE, ASSESSMENT." | IMPLEMENTED | `SessionMode` enum + `SessionPolicy`, `backend/app/domain/session/session.py`; per-mode tests `backend/tests/api/modes/test_full_cycle_single_trainee.py:54`, `backend/tests/api/modes/` (multi-trainee, assessment, single-role). |
| "The primary implemented flow is: incoming emergency call → … → deterministic post-session assessment." | PARTIAL | Every stage exists and is unit/API tested end to end on fakes: `backend/tests/api/dds/test_full_cycle.py:103-287`. The real-provider, real-LiveKit run of the whole flow is E20-C's §46 walk, performed 2026-09-22 (`docs/DOD_WALK.md`): **12 of 16 items PASS, 4 PARTIAL** (items 3, 5, 12, 16 — see §2 below and `docs/DOD_WALK.md` §3/§4 for each). Not a hard FAIL on any item; the four PARTIALs are real, reproduced defects, three of which (5, 12, 16) E20-H fixed (H1/H2/H3/H4/H5 below). |

### §2 — Non-negotiable architectural invariant (the LLM boundary)

All nine "MUST NOT" clauses plus the three "is only allowed to" clauses: **IMPLEMENTED**.
Evidence (audit-2 Part 1, "Focused §2/§3/§41/§44"): create truth — `backend/app/domain/layers/world_truth.py:1-6`,`copies.py:87-99`, INV1 `backend/tests/invariants/test_inv_01_gate_never_releases_world_truth.py:312-405`; decide required services — `backend/app/application/operator/select_service.py:35-114`; change state directly — `backend/app/domain/session/machine.py:12-19`, `backend/tests/integration/voice/test_begin_interview_from_asr_final.py:125-153`; calculate scores — `backend/app/domain/scoring/engine.py:54-77`, INV9 `backend/tests/invariants/test_inv_09_scoring_reproducible_without_llm.py:117-169`; know hidden facts — `backend/app/domain/facts/gate.py:1-12,301-314`, `backend/tests/invariants/test_r3_caller_prompt_information_boundary.py:182-211`; fill the card — INV4 `backend/tests/invariants/test_inv_04_asr_never_mutates_card.py:181-392`; invent resources — `backend/app/domain/dds/resources.py:109-125`, `backend/tests/api/dds/test_selection_and_dispatch.py:161-172`; skip states — `backend/app/domain/session/transitions.py:43-340`, INV8 `backend/tests/invariants/test_inv_08_invalid_transitions.py:113-163`; complete trainee actions — `backend/tests/api/operator/test_operator_flow.py:270-382`.

### §3 — Four separate information layers

| requirement | verdict | evidence |
|---|---|---|
| WorldTruth/CallerBelief/OperatorCard/DDSReceivedSnapshot "implement as separate models and storage concepts" | IMPLEMENTED | Four ORM rows `backend/app/db/models/layers.py:31-91`; four domain types `backend/app/domain/layers/{world_truth,caller_belief,operator_card,handoff}.py`. |
| "Never alias these structures. Never automatically synchronize them." | IMPLEMENTED | Explicit deep-copy functions only, `backend/app/domain/layers/copies.py:1-34,128-215`; INV3 structural test `backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py:194-227,362-429`. |
| "DDS MUST receive '72'. It MUST NOT obtain '27' from WorldTruth." (the house-number example) | IMPLEMENTED | DDS work item carries the operator's card value, never WorldTruth, `backend/app/application/handoff/work_item.py:1-30`; `backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py::test_the_dds_work_item_carries_the_operators_value_not_the_worlds`. |
| (INV 3, extended by R1) — no hidden-layer value or provenance reaches a trainee/DDS-facing payload, including *derived* identifiers | IMPLEMENTED (fix landed, E20-A) | Audit-2 Part 3 found a real leak: `source_world_event_id` (the hidden world event that produced a notification/radio message) was required in the trainee-facing `NotificationView`/`RadioMessageView` (`docs/hld/openapi.yaml` pre-fix, `backend/app/application/dds/list_notifications.py:84-99`, `list_radio_messages.py:57-76`, `backend/app/application/dds/views.py:241-299`) and stored by the frontend reducers (`frontend/src/entities/{notification,radio}/apply-*-event.ts`). Re-checked at hand-back: `git diff --stat` shows `docs/hld/openapi.yaml`, `backend/app/api/schemas/dds.py`, `backend/app/application/dds/views.py` drop `source_world_event_id` from both views' `required`/`properties`; `backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py` gained +73 lines (a REST-path bite proof); the frontend reducer/guard/fixture files (`frontend/src/entities/{notification,radio}/apply-*-event.ts`, `frontend/src/features/dds/{no-world-truth-guard.test.ts,test-fixtures.ts}`, `frontend/src/shared/api/schema.d.ts`) are all updated to match — R1 (E20-A) is functionally complete as observed; still uncommitted, so a final independent test run at epic close remains prudent. |

### §4 — Scenario versioning

| requirement | verdict | evidence |
|---|---|---|
| "Scenario and ScenarioVersion must be separate." | IMPLEMENTED | Separate tables/types, `backend/app/domain/scenario/version.py:33-67`. |
| "A ScenarioVersion becomes immutable as soon as a simulation starts using it." | IMPLEMENTED | `locked_at` trigger, `backend/app/db/migrations/versions/0001_baseline.py`; INV6 `backend/tests/invariants/test_inv_06_scenario_version_immutable.py:130-247`. |
| "Every SimulationSession references an exact ScenarioVersion." | IMPLEMENTED | FK on `simulation_sessions.scenario_version_id`, `backend/app/db/models/session.py:36-160`. |
| Required conceptual structure (`id, schema_version, scenario_id, version, title, description, difficulty, deterministic_seed, role_chain, world_truth, caller_profile, caller_knowledge, disclosure_rules, expected_response, available_resources, world_events, scoring_rules`) | IMPLEMENTED | All fields present, `backend/app/domain/scenario/version.py:33-67`, `sections.py:54-190`. |
| "Use Pydantic models and validate scenario files before a simulation can start." | IMPLEMENTED | `backend/app/domain/scenario/validation.py:172-303`; import test `backend/tests/integration/persistence/test_scenario_import.py:63-205`. |
| "Scenario source files must be YAML or JSON and version-controlled." | IMPLEMENTED | `scenarios/examples/apartment-fire/v1.yaml`, tracked in git. |

### §5 — Fact model

All items **IMPLEMENTED** (audit-2 §5 table): `fact_id`/`world_value`/`caller_value`/knowledge
state/certainty — `backend/app/domain/facts/definitions.py:55-64`; disclosure policy — field is
named `policy` not `disclosure_policy` (RENAMED, harmless); `aliases`/categories — `aliases_ru`,
`categories` at `definitions.py:63-64`; all four knowledge states and all four disclosure policies —
`backend/app/domain/enums.py:119-134`; the fire_source/KITCHEN example — gate/leak tests
`backend/tests/invariants/test_inv_01_gate_never_releases_world_truth.py:312-405`,
`backend/tests/adversarial/test_forbidden_fact_leak_suite.py:435-565`.

### §6 — Caller profile

| requirement | verdict | evidence |
|---|---|---|
| identity, relationship, language, voice_id, age_group, baseline_emotion, cooperativeness, verbosity, confusion, interruption tendency, speaking rate | IMPLEMENTED | All present (`identity` as `identity_ru`), `backend/app/domain/caller/profile.py:20-32`, consumed by `backend/app/application/dialogue/prompt_builder.py:160-169`. |
| current_emotion, stress level as **profile** fields | PARTIAL / design deviation | Not on `CallerProfile` by design — live in `EmotionState.emotion`/`.stress_level` (`backend/app/domain/caller/emotion.py:26-32`), updated deterministically per SPEC §6's own next sentence ("Emotion is part of simulation state and may change deterministically"). Listed in §3 deviations below. |
| "Emotion is part of simulation state and may change deterministically in response to events/actions." | IMPLEMENTED | `EmotionRule`s applied by the world engine/turn pipeline, D7/D4; `backend/app/domain/caller/emotion.py`. |
| "Do not let the LLM freely redefine the persona." | IMPLEMENTED | Prompt builder accepts only the fixed persona block, no free-form persona channel, `backend/app/application/dialogue/prompt_builder.py:110-118,157-192`. |

### §7 — Simulation state machine

All top-level (`CREATED,READY,ACTIVE,ROLE_TRANSITION,COMPLETED,ABORTED`), Operator 112
(`WAITING_FOR_CALL…STAGE_COMPLETED`), and DDS (`RECEIVED…CLOSED`) states: **IMPLEMENTED**,
`backend/app/domain/enums.py:22-56`, transition tables `backend/app/domain/session/transitions.py:43-340`.
"Invalid transitions MUST be rejected by backend domain logic" — IMPLEMENTED, `backend/app/domain/common/state_machine.py:130-166`,
INV8 `backend/tests/invariants/test_inv_08_invalid_transitions.py:84-163,235-310`.
"The frontend must never be authoritative" — IMPLEMENTED, state authority is server-side
(`backend/app/domain/session/machine.py:12-19`) and every button is driven by `available_actions`
from the backend (D12, `frontend/src/features/operator/console-page.tsx`).

### §8 — Event-sourced audit log

All ten `SessionEvent` fields and all 28 named event types: **IMPLEMENTED** — fields
`backend/app/domain/events/session_event.py:24-50`; catalog parity test (28 SPEC types + 21
additive types, no misses) `backend/tests/unit/domain/events/test_catalog.py:37-57`,
`backend/app/domain/events/types.py:69-129`. "Do not overwrite events" — DB trigger rejects
UPDATE/DELETE, `backend/app/db/migrations/versions/0001_baseline.py`. "Materialized… event log must
remain the audit source" — scoring reads only `(ScenarioVersion, events)`, never materialized
tables, D5.

### §9 — Operator card

| requirement | verdict | evidence |
|---|---|---|
| "The trainee manually edits the incident card." | IMPLEMENTED | `set_field` command, `backend/app/domain/layers/operator_card.py:482-550`; UI `frontend/src/features/operator/console-page.tsx`. |
| "ASR MUST NOT auto-fill fields…" | IMPLEMENTED | INV4, no code path from transcript to card, `backend/tests/invariants/test_inv_04_asr_never_mutates_card.py:181-392`. |
| "Every field mutation must be stored" (previous value, new value, field path, event timestamp, actor) | IMPLEMENTED | `CardRevision` frozen record, `backend/app/domain/layers/operator_card.py:56-70` (timestamp stored as `at_offset_ms`, RENAMED); API test `backend/tests/api/operator/test_operator_card.py:33-83`. |
| "The final card is NOT enough." | IMPLEMENTED | Full revision history persisted and queryable, not just the current row, same evidence. |

### §10 — Handoff

All six ordered steps: **IMPLEMENTED** — `backend/app/application/handoff/create_handoff.py:190-245`,
`backend/tests/api/handoff/test_create_handoff.py:36-231`. One ordering note (audit-2): the optional
comment is accepted **before** state validation inside the transaction (`create_handoff.py:199-209`),
a harmless reordering of steps 1–3 that does not change the observable six-step contract. "DDS must
not query WorldTruth…" — IMPLEMENTED, DDS services are constructed without a WorldTruth repository
(D3), INV3. "If the 112 operator omitted a critical fact, the omission propagates." — IMPLEMENTED,
`backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py:362-429`.

### §11 — DDS simulation

"DDS is not a static second form" — all ten listed concepts (incoming work item, acknowledgment,
resources, capabilities, states, dispatch, ETA, status changes, incident updates, closure):
**IMPLEMENTED**, `backend/app/application/handoff/work_item.py`, `backend/app/domain/dds/resources.py:1-170`,
`backend/tests/api/dds/{test_work_item_and_acknowledge,test_selection_and_dispatch,test_notifications_radio_status,test_stage_automation,test_full_cycle}.py`.
`EmergencyResource`'s eight required fields: IMPLEMENTED (`id` is `resource_id`, RENAMED).
"Do not depend on an external online maps API" — IMPLEMENTED, local deterministic `EtaModel`,
`backend/app/domain/world/eta.py:42-61`.

### §12 — World event engine

Four event kinds (`TimedEvent, ConditionalEvent, ActionTriggeredEvent, SeededRandomEvent`):
**IMPLEMENTED**, `backend/app/domain/world/events.py:31-104`. "All randomized behavior must use the
session seed" — IMPLEMENTED, `backend/app/domain/world/rng.py:25-32`, INV7
`backend/tests/invariants/test_inv_07_deterministic_world_events.py:80-108,203-269`. The six listed
mutation kinds — IMPLEMENTED, D7 effect list. "The LLM must not schedule world events." —
IMPLEMENTED, engine-only, no LLM parameter anywhere in `backend/app/domain/world/engine.py`.

### §13 — Full-cycle mode

| requirement | verdict | evidence |
|---|---|---|
| "A full-cycle session uses one SimulationSession, Incident, ScenarioVersion, event timeline." | IMPLEMENTED | `backend/app/domain/session/session.py:102-188`; INV5. |
| "Role changes do not create a new incident." | IMPLEMENTED | Same evidence; `backend/tests/api/handoff/test_role_transition.py:50-138`. |
| FULL_CYCLE_SINGLE_TRAINEE sequence (stage → completion → pause → DDS UI → same incident/card → DDS stage → final report) | IMPLEMENTED | `backend/tests/api/modes/test_full_cycle_single_trainee.py:54-150`; pause/transition clock — R2 of E17 (`docs/hld/10-domain-model.md` §10.8, `running_ms`/`transition_clock_ms`, see HLD-gap fold §4 below). |
| "MULTI_TRAINEE uses the same backend model, but different participants are assigned different RoleStages." | IMPLEMENTED | `backend/tests/api/modes/` multi-trainee fixtures; `SessionParticipant`→`RoleStage` assignment, `backend/app/domain/session/session.py`. |

### §14 — EDDS extension

RoleModule's six members (`role_type, permissions, available actions, state machine, data
visibility policy, UI capabilities/schema`): **IMPLEMENTED** (three RENAMED to
`available_actions`/`visibility_policy`/`ui_schema`), `backend/app/domain/roles/module.py:55-69`.
"Do not implement a large EDDS subsystem…Define the extension interface now." — IMPLEMENTED,
`EDDSModule` is a registered stub with `implemented = False`, `backend/app/domain/roles/edds.py:1-70`;
scenario validation rejects a role_chain naming it. "DDS and Operator112 must use the same role
abstraction" — IMPLEMENTED, both are full `RoleModule`s, `backend/app/domain/roles/{operator112,dds}.py`.

### §15 — Voice transport

"Use self-hosted LiveKit…Do not implement a custom WebRTC stack…Frontend sends/receives realtime
audio through LiveKit…CallTransport abstraction…domain must not import LiveKit…No actual PSTN
integration is required for the initial demo": all **IMPLEMENTED** —
`workers/voice_agent/voice_agent/transport/livekit_transport.py` is the sole LiveKit-SDK importer
(enforced by `backend/tools/check_imports.py` + `workers/voice_agent/tests/test_transport_boundary.py`,
whose importer-enumeration test now also lists `headless_client.py`, the E19-E benchmark client, as
the second sanctioned importer inside the same directory — see HLD-gap fold item 20); frontend media
client `frontend/src/shared/media/call-media.ts`; `SipCallTransport` exists as the documented stub
(`workers/voice_agent/voice_agent/transport/sip_transport.py`), satisfying "no PSTN required for the
initial demo" as an EXCLUDED-BY-SPEC item, not a gap. A real LiveKit run of the full demo is E20-C's
§46 walk, performed 2026-09-22 (`docs/DOD_WALK.md` item 2, PASS): the call rang and was answered
over a real LiveKit room, the caller joined and spoke on every turn once the demo scenario's
TTS-voice/warm-fallback defects (`docs/DOD_WALK.md` §4 items 5-6) were worked around.

### §16 — Voice agent pipeline

| requirement | verdict | evidence |
|---|---|---|
| Nine-stage pipeline (resample → VAD → ASR → interpretation → gate → generation → validation → streaming TTS → LiveKit audio) | IMPLEMENTED | Wired exactly in this order, `workers/voice_agent/voice_agent/wiring.py:409-452`, `backend/app/application/voice/turn_pipeline.py:300-350`. |
| "Do not collapse Fact Access Gate into the LLM." | IMPLEMENTED | Gate is pure domain code with no LLM call, `backend/app/domain/facts/gate.py:172-260`; INV1/INV2. |
| pipeline stage "streaming TTS" specifically | PARTIAL | See §25/§18: the port is streaming-shaped but both real adapters (Qwen3-TTS, Piper) buffer a full unit before the first chunk. Listed in §3 deviations. |

### §17 — VAD and turn-taking

All items **IMPLEMENTED** (audit-2 §17 table, 17 rows): configurable speech-start threshold,
endpoint silence, pre-roll, separate start/end events, partial ASR, response-from-final-turn-only,
250–350 ms target band, "no hard-coded turn knobs" (guarded by
`backend/tests/unit/application/voice/test_turn_detector_no_literals.py:20-36`) — all in
`backend/app/application/voice/config.py:66-119` and `turn_detector.py`. One correction absorbed
from E11-A's own HLD-gap 1: the 300/120 ms defaults are not integer multiples of the 32 ms VAD
frame, so they are rounded up at load to **320/128 ms** per §4.1's documented remedy — both remain
inside the 250–350 ms target band (already fixed in HLD text per that task's report; not re-opened
here).

### §18 — Barge-in

All seven steps **IMPLEMENTED** at the port/pipeline level (audit-2 §18 table):
`backend/app/application/voice/turn_pipeline.py:577-638`, `tts_speech_sink.py:229-267,570-626`,
INV12 `backend/tests/invariants/test_inv_12_barge_in_reveals_nothing.py:62-170`. "Do not implement
TTS as one complete WAV file that cannot be interrupted." — **PARTIAL**: the port contract and the
sentence-chunker wrapper are streaming/cancellable (`backend/app/application/ports/tts.py:85-127`,
`backend/app/application/voice/sentence_chunker.py:212-312`), but the real Qwen3-TTS and Piper
adapters each buffer one full sentence/unit's PCM before the first chunk is yielded
(`backend/app/inference/tts/qwen3_tts.py:369-408`, `piper_tts.py:225-250`) — cancellation therefore
only stops the *next* unit, not synthesis already in flight for the current one. Listed in §3
deviations; accepted for the demo per HLD 50's own D9 provider note. "<250 ms onset-to-cutoff" —
met on the fake transport (INV12) and met for the barge-in cases exercised over real WebRTC in
E19-E3 (24/24 scripted barge-ins under budget, `docs/hld/60-inference-ops.md` §10 item 13).

### §19 — ASR abstraction

All port members (`transcribe`, `stream`, `warm_up`, `close`), the primary/benchmark/optional
providers (GigaAM `v3_e2e_ctc`/`v3_ctc`, faster-whisper), and all nine `TranscriptSegment` fields:
**IMPLEMENTED** (audit-2 §19 table) — `backend/app/application/ports/asr.py:90-137`,
`workers/voice_agent/voice_agent/providers.py:97-126`,
`backend/app/application/ports/transcript_segment_repository.py:40-57` (class is
`StoredTranscriptSegment`, RENAMED; `ASR provider`/`ASR model` fields RENAMED to
`asr_provider`/`asr_model`). "Do not make downstream domain code depend on a specific ASR model." —
IMPLEMENTED, model-neutral port.

### §20 — Dialogue interpreter

| requirement | verdict | evidence |
|---|---|---|
| "must not directly receive raw operator speech plus entire scenario truth…first produce a constrained structured interpretation" | IMPLEMENTED | `backend/app/application/dialogue/interpreter.py:1-80`. |
| Example schema shape (`speech_act, requested_facts, operator_assertions, confirmation_targets, semantic_confidence`) | IMPLEMENTED | `backend/app/application/dialogue/grammar.py:1-120`. |
| "Validate against Pydantic/JSON schema." | IMPLEMENTED | Pydantic `extra="forbid"` models, D10. |
| "If structured output is invalid: retry once with a repair prompt." | IMPLEMENTED | One repair retry, `interpreter.py`; resilience test `backend/tests/resilience/test_39_3_invalid_llm_output.py:129-193`. |
| "Never silently guess missing fields." | IMPLEMENTED | Invalid ⇒ `speech_act=UNINTELLIGIBLE` + `MODEL_FALLBACK_USED`, never a guessed field. |

### §21 — Fact Access Gate

| requirement | verdict | evidence |
|---|---|---|
| "FactAccessGate is deterministic application/domain code." | IMPLEMENTED | `backend/app/domain/facts/gate.py:172-260`, pure function, no I/O. |
| Six listed inputs | IMPLEMENTED | `evaluate_fact_access(...)` signature, same file. |
| Three listed outputs (allowed, unavailable/unknown, disclosure metadata) | IMPLEMENTED | `AllowedFactsPackage{allowed, unavailable, withheld_count, metadata}`. |
| "This component is the ONLY normal path through which scenario facts reach the caller-response LLM." | IMPLEMENTED | Prompt builder accepts only the package, no other channel, `backend/app/application/dialogue/prompt_builder.py:110-118`; INV1/INV2. |

### §22 — Caller LLM

| requirement | verdict | evidence |
|---|---|---|
| "Use local Qwen3." | IMPLEMENTED | Local llama.cpp client only, loopback-enforced, `backend/app/inference/llm/llama_cpp_client.py:120-138`, D9. |
| "Development profile: Qwen3-4B quantized." | PARTIAL / measured deviation | Current DEV default is **Qwen3.5-2B** (`backend/app/config/profiles/DEV_3060TI.yaml:33-50`), chosen after E19's real quality/latency measurement — SPEC's own Qwen3-4B does not clear the measured quality bar at usable latency (`docs/hld/00-decisions.md` D9, `docs/benchmarks/llm.md`). Qwen3-4B stays selectable. Listed in §3 deviations. |
| "Final profile: Qwen3-8B Q4_K_M if VRAM benchmark passes." | PARTIAL / unmeasured | No 3080 Ti / Qwen3-8B GGUF on this machine; target download defined, not run (`Makefile:124-138`, `docs/hld/60-inference-ops.md` §2 FINAL rows, `NOT_RUN`). Listed in §3 deviations. |
| "Serve through llama.cpp/OpenAI-compatible local endpoint." | IMPLEMENTED | Same as row 1. |
| "Thinking must be disabled." | IMPLEMENTED | Config validator rejects `true`; wire forces `false`, `backend/app/config/profile.py:85-115`, `llama_cpp_client.py:330-355`. |
| "Default context target: 4096 tokens." | IMPLEMENTED | `backend/app/config/settings.py:159-164`, all profiles set `n_ctx: 4096`. |
| "Do not keep the entire raw call transcript in model context…" plus the fixed six-item context list | IMPLEMENTED | `backend/app/application/dialogue/prompt_builder.py:1-19,75-118,157-192`; boundary invariant `backend/tests/invariants/test_r3_caller_prompt_information_boundary.py:92-208`. |
| "Historical full transcript stays in PostgreSQL." | IMPLEMENTED | `backend/app/application/ports/dialogue_turn_repository.py:148-150`, `backend/app/db/models/events.py:128-181`. |
| "Default maximum response: 80 generated tokens." | IMPLEMENTED | `backend/app/application/dialogue/generator.py:107-131,338-346`. |

### §23 — Strict caller prompt rules

All rule clauses (not-an-assistant framing, ALLOWED_FACTS-only assertion, ten forbidden invention
categories, not-yet-disclosable withholding, no task help, no question prescription, no solution
summary, persona speech, natural brevity, natural "don't know", no meta-mention):
**IMPLEMENTED** — prompt text `backend/app/application/dialogue/prompts/caller.py:35-105`; enforced
independently by the deterministic validator (§24) and the zero-leak adversarial proof
`backend/tests/adversarial/test_forbidden_fact_leak_suite.py:435-565`.

### §24 — Response validation

All six validated properties, "retry once", deterministic safe fallback, `MODEL_FALLBACK_USED`:
**IMPLEMENTED** — `backend/app/application/dialogue/validator.py:1-544`,
`backend/app/application/dialogue/responder.py:330-412`; resilience test
`backend/tests/invariants/test_inv_14_llm_failure_keeps_session.py:194-301`. §7.4's EMPTY↔META_LANGUAGE
refinement (R5, E20-A) is now landed: re-checked at hand-back, `validator.py` gained a whole-utterance
"no Cyrillic letter" check under `META_LANGUAGE` (`_CYRILLIC_RE`, applied before the per-token
Latin-run rule so short all-Latin replies like "Ok, yes" are caught too), with the same
gate-released-value/`LATIN_ALLOWLIST` exemptions as the existing rule; `EMPTY` stays "no letter at
all". See §3 deviation 7 for the numeric-only-answer question, which STAYS pending the owner's
confirmation per R5's own instruction (unchanged, by design, not a gap in this fix).

### §25 — TTS abstraction

| requirement | verdict | evidence |
|---|---|---|
| "Define streaming TTSProvider." | IMPLEMENTED | `backend/app/application/ports/tts.py:85-127`. |
| "Benchmark at least: Qwen3-TTS 0.6B, Chatterbox Multilingual, lightweight/fallback." | PARTIAL | Qwen3-TTS and Piper (fallback) are benchmarked (`docs/benchmarks/tts.md`); **Chatterbox has no provider implementation** and the benchmark returns `NOT_RUN` (`benchmarks/benchmark_tts.py:78-102`). Listed in §3 deviations, EXCLUDED-BY-SPEC-adjacent (owner-acknowledged, R12). |
| "Do not hard-code TTS model calls inside dialogue logic." | IMPLEMENTED | Dialogue calls the port/sink only, `backend/app/application/voice/tts_speech_sink.py:399-405`. |
| "TTS must support cancellation for barge-in." | PARTIAL | See §18 — cancellation works at the port/wrapper boundary, not mid-unit inside the real adapters. |
| "Store actual text sent to TTS and playback timing." | IMPLEMENTED | `backend/app/application/voice/tts_speech_sink.py:570-626`. |

### §26 — Model profiles

| requirement | verdict | evidence |
|---|---|---|
| DEV_3060TI's five listed properties | PARTIAL | GigaAM/lowest-risk-TTS/4096-context/prewarmed are exact; "local Qwen3-4B quantized" is measured-superseded by Qwen3.5-2B (see §22). `backend/app/config/profiles/DEV_3060TI.yaml:1-106`. |
| FINAL_3080TI_12GB's five listed properties | PARTIAL | Defined and refusal-checked but unmeasured on this machine (no 3080 Ti); `FINAL_3080TI_12GB.yaml:1-74`. |
| FINAL_3080TI_16GB's four listed properties | PARTIAL | Same as above, plus names Chatterbox as an alternative that has no provider yet; `FINAL_3080TI_16GB.yaml:1-64,49-55`. |
| "Never choose a profile whose measured peak VRAM leaves essentially zero safety margin." | IMPLEMENTED | `min_vram_margin_mb` refusal check, `backend/app/config/profile.py:150-250`; real `DEV_3060TI`/`DEV_3060TI_SHARED` margins measured (E19-D3, peak 5560/1559 MB), FINAL profiles refused as unmeasured rather than assumed safe. |

### §27 — Latency telemetry

All 15 `InferenceMetric` fields: **IMPLEMENTED** (audit-2 §27 table; several DB-column RENAMEs,
e.g. `input_audio_ms`→`input_duration_ms`), `backend/app/application/ports/metrics_recorder.py:39-64`,
`backend/app/infrastructure/metrics/pg_metrics_recorder.py:81-145`. "Record latency for every
inference turn." — IMPLEMENTED. Critical metric `speech_end_to_first_audio_ms`: **IMPLEMENTED**
(R13 fix landed, E20-F). The in-process real-provider measurement already met both targets
(`DEV_3060TI_SHARED --runs 4`: p50 1192 ms / p95 1864 ms / p99 2056 ms, `meets_target: true`,
`docs/hld/60-inference-ops.md` §10 item 13,
`docs/benchmarks/results/e2e-DEV_3060TI_SHARED-20260922T091948626Z.json`). The **real LiveKit**
figure was previously unpublishable because `USER_SPEECH_ENDED` and `CALLER_TTS_STARTED` were
stamped from two different clock origins over that transport, so every sample came out negative and
was discarded (`overall.n=0`) — **R13, fixed** (E20-F, `reports/e20-f.md`). Root cause was
**two bugs**, not one: (1) `LiveKitCallTransport._now_ms()` measured from its own private
`_origin_ms` (first-frame-relative) instead of the session clock — fixed by defining
`capture_offset_ms`/`TransportEvent.at_offset_ms` on the port as `session_offset_ms(clock.now(),
session.started_at)` (`backend/app/application/ports/call_transport.py:31-40`,
`workers/voice_agent/voice_agent/transport/livekit_transport.py:126-236`, both required-keyword
constructor args now, no silent default); (2) `VoiceEventAppender(started_at=None)`'s default
silently meant "offset 0" and `voice_agent.main._run_call` never passed a real one, so **every
event the real agent ever appended was stamped `monotonic_offset_ms=0`** — this alone explains
E19-E3's negative, growing-by-one-turn samples, and the in-process figures were only sound because
`benchmarks/benchmark_e2e.py:713` happens to pass a real `started_at`. Fixed by
`voice_agent.main._session_started_at(session_id)` reading the persisted value once per call and
handing it to both the transport and the pipeline. Test: `workers/voice_agent/tests/test_transport_clock_origin.py`
(7 tests) — a 30 s session→transport gap (E19-E3's own first-sample magnitude) now yields a
positive metric equal to the in-process value with a zero gap. `benchmarks/benchmark_e2e.py`
needed **no code change** (its `discarded_nonpositive_count` accounting was already correct; the
LiveKit percentile becomes publishable purely because the product's samples are now positive).
**The real LiveKit re-run was performed** by E20-C's §46 walk (2026-09-22,
`benchmark_e2e.py --provider real --profile DEV_3060TI --transport livekit --runs 4`, shipped
`SIM_SIM_TICK_MS=500`): n=29, `discarded_nonpositive_count=0` (R13 proven live), **p50 1566 ms /
p95 4622 ms / p99 5205 ms, `meets_target: false`** (misses the 1500/2500 ms DEV target on p95 —
`docs/benchmarks/results/e2e-DEV_3060TI-20260922T144530930Z.json`, `docs/benchmarks/e2e.md` §3.1).
This is an owner-visible open item, not a code defect: the gap between the in-process figure above
and the real-media-plane one is a real transport/TTS cost (§3.1's caveat: TTS ran on CPU Piper for
the walk, so the gap is an upper bound on the transport's own share).

Separately, the **report's own** `timing_metrics.speech_end_to_first_audio_ms_p50/p95`
(`GET /reports/{id}` and `/inference-metrics`, SPEC §29 item 13) were `null` on every real session
despite `dialogue_turns.speech_end_to_first_audio_ms` (this same metric) being written correctly by
the pipeline in isolation (E20-C §46 walk item 16, reproduced: `docs/benchmarks/results/dod-walk-
20260922/report.json`). Root cause (H3, E20-H): `voice_agent.wiring.build_pipeline` built **two
different** `PgMetricsRecorder` instances per call — one for the ASR side (`register_turn`), one
for the TTS side (`record_turn_latency`) — so the turn-id/turn-index pairing `record_turn_latency`
needs was never registered on the instance it actually read from, and the write silently no-opped
(`app.infrastructure.metrics.pg_metrics_recorder`'s own "no turn_index is registered" warning,
never surfaced as an error). **Fixed**: `build_pipeline` now builds one recorder and threads it
through both `build_responder` and `build_dialogue_responder` (`workers/voice_agent/voice_agent/
wiring.py`); bite-proof test
`workers/voice_agent/tests/test_dialogue_wiring.py::test_build_pipeline_shares_one_metrics_recorder_between_asr_and_tts`,
plus an integration test over three seeded turns asserting non-null p50/p95
(`backend/tests/api/reports/test_session_report.py::test_speech_end_to_first_audio_percentiles_are_present_over_three_turns`).
`llm_ttft_ms_p50` stays `null` **by construction**, not a bug: the interpreter/generator LLM calls
are non-streaming (`backend/app/application/dialogue/{interpreter,generator}.py`, `ttft_ms=None`),
so there is no distinct first-token instant to measure — documented on the field itself
(`docs/hld/openapi.yaml`'s `TimingMetricsView.llm_ttft_ms_p50` description). "Do not fake or
hard-code benchmark values." — IMPLEMENTED, every number above is read from a committed JSON a
script produced, `benchmarks/benchmark_e2e.py`, or from the stored `dialogue_turns`/
`inference_metrics` columns via `app.application.reports.timing_metrics` (never recomputed from
events, E16's stored-only rule).

### §28 — Scoring

All nine `ScoringRule` fields, all ten evaluator types, `ScoreEvidence`'s pointer fields,
determinism-without-LLM, reproducibility: **IMPLEMENTED** (audit-2 §28 table) —
`backend/app/domain/scoring/rules.py:18-32`, evaluator registry
`backend/app/domain/scoring/evaluators/registry.py:56-87`, INV9/INV10/INV11.

### §29 — Post-session report

All 14 listed report sections plus "explanation only after deterministic scores, may not alter
numbers": **IMPLEMENTED** (audit-2 §29 table) — `frontend/src/features/report/report-page.tsx:138-174`,
`backend/app/api/schemas/reports.py`, explanation route separated from scoring,
`backend/tests/api/reports/test_explanation_routes.py:50-169`.

### §30 — Database

"Use PostgreSQL." "Use SQLAlchemy 2 + Alembic." All 20 listed core tables: **IMPLEMENTED** —
`backend/app/db/models/`, Alembic baseline `backend/app/db/migrations/versions/0001_baseline.py`.
"Use UUID primary keys… proper foreign keys and indexes." — IMPLEMENTED, same evidence. "Do not
replace the relational model with a generic JSON document store… JSONB … for versioned/configurable
payload portions" — IMPLEMENTED, JSONB used only for `scenario_versions.content`, event `payload`,
and similar configurable blobs; every entity/relationship is a real table/FK.

### §31 — Redis

"Redis is allowed for… pub/sub, transient realtime state, locks, cancellation, LiveKit
requirements." "PostgreSQL remains authoritative." "Do not make Redis the permanent source of
truth.": all **IMPLEMENTED** — `backend/app/infrastructure/realtime/`, `backend/app/application/realtime/event_stream.py:148-300`;
replay-from-Postgres-then-tail-Redis proven at `backend/tests/unit/application/realtime/test_event_stream.py:213-264`.

### §32 — Frontend

All eight required libraries, all four route groups, "not four unrelated frontend projects",
"professional operational software… phone call, not a giant chat window": **IMPLEMENTED**
(audit-2 §32 table) — one Vite app, `frontend/src/app/router.tsx:41-75`; phone widget
`frontend/src/features/operator/console-page.tsx`, transcript as a secondary collapsible panel
(D12).

### §33 — Backend

"Use Python with FastAPI/Pydantic v2/SQLAlchemy 2/Alembic/asyncio/PostgreSQL/Redis." "Keep
business/domain logic outside HTTP route handlers." Five-layer tree. "Domain code must not import
FastAPI, React, LiveKit, or SQLAlchemy ORM-specific behavior…": all **IMPLEMENTED** —
`backend/app/api/routers/*.py` delegate to `application` use cases; import-boundary checker +
tests, `backend/tools/check_imports.py:1-220`, `backend/tests/unit/test_check_imports.py:194-321`.

### §34 — Realtime API

"Use LiveKit for realtime media." "Use WebSocket/SSE… for application events." "Do not tunnel raw
microphone PCM through ordinary REST endpoints." "REST… commands/resources… realtime… ongoing
updates.": all **IMPLEMENTED** — LiveKit media isolated to `workers/voice_agent/voice_agent/transport/`,
WS event stream `backend/app/application/realtime/event_stream.py:148-300`, transport-boundary test
`workers/voice_agent/tests/test_transport_boundary.py`.

### §35 — Project structure

Every listed directory/file exists: **IMPLEMENTED** (audit-2 §35 table) —
`frontend/src/{app,features,entities,shared}`, `backend/app/{api,domain,application,infrastructure,inference,db,config}`,
`backend/tests`, `workers/voice_agent`, `scenarios/{schemas,examples}`, all five
`benchmarks/benchmark_*.py`, `infra/{docker-compose.yml,livekit,scripts}`, `docs/`. "Do not put all
business logic in app.py or route files." — IMPLEMENTED, routers are thin delegators.

### §36 — Deployment

| requirement | verdict | evidence |
|---|---|---|
| "Use Docker Compose for the current product/demo." Seven named services. | IMPLEMENTED | `postgres,redis,livekit,backend,frontend,llama-server,voice-agent` all present, `infra/docker-compose.yml:24-260`; structure test `backend/tests/unit/infra/test_compose_file.py:55-115`. |
| Optional eighth (`tts-qwen3`) service reachability | IMPLEMENTED (fix landed, E20-A, R3) | Previously the worker's bind host was never set by compose so `voice-agent` could not reach `tts-qwen3:8112` from inside the container (audit-2 confirmed: root cause is the omitted `SIM_TTS_QWEN3_HOST` env var, not a hard-code, `workers/tts_qwen3/tts_qwen3/__main__.py:40-49`). Re-checked at hand-back: `infra/docker-compose.yml:256` now sets `SIM_TTS_QWEN3_HOST: 0.0.0.0` with a comment explaining it is the container-internal bind and the service still publishes no host port; `.env.example`'s matching comment was corrected too (R3 also fixed the two stale compose comments at ~221-225/~256-260 per the ruling). |
| "Do not introduce Kubernetes." "Do not introduce Kafka unless…" | IMPLEMENTED | Neither present anywhere in the tree. |

### §37 — Model warm-up

"Before a training session can start, inference services must be warm." Three listed warm-up runs.
"Expose readiness separately from process liveness." "The UI must not allow a final demo session to
begin while a required inference service reports not-ready.": all **IMPLEMENTED** (audit-2 §37
table) — `workers/voice_agent/voice_agent/main.py:439-496`, `/live` vs `/ready`
`backend/app/api/routers/health.py:49-129`, frontend gate
`frontend/src/features/instructor/create-session-form.tsx:114-127,198-199,326-328`, backend guard
`backend/app/api/routers/sessions.py:134-153`.

### §38 — Preflight

Ten of eleven listed checks (CUDA/GPU, expected GPU, model files, LLM, ASR, TTS, PostgreSQL, Redis,
scenario validation, audio devices) plus one additive (llama-server binary): **IMPLEMENTED**,
`backend/app/cli/preflight.py`, unit tests per check `backend/tests/unit/cli/test_preflight.py`.
LiveKit check: **PARTIAL** — only an HTTP-origin GET, not a `livekit-api` `ListRooms`/room check
(`backend/app/cli/preflight.py:271-284,562-570`); this is **R12's explicit NOT-IN-SCOPE item**
("LiveKit ListRooms preflight (needs livekit-api — record)") — recorded, not fixed, in this epic.
"Return explicit pass/fail results." — IMPLEMENTED, explicit PASS/FAIL/SKIP + exit code,
`preflight.py:379-404`.

### §39 — Resilience

All six required behaviors (refresh restores state, TTS failure fallback, invalid LLM output
repair-then-fallback, ASR failure state-safe, LiveKit reconnect survives, GPU OOM fatal+preserved)
plus "never silently reset the simulation": **IMPLEMENTED** (audit-2 §39 table) —
`backend/tests/resilience/test_39_{1..6}_*.py`, health state machine
`workers/voice_agent/tests/test_health_state_machine.py:98-233`. Real (non-fake) exercise of these
paths through the compose stack is part of the §46 walk (E20-C).

### §40 — Benchmarks

| requirement | verdict | evidence |
|---|---|---|
| Five real benchmark scripts, each with its listed dimensions | IMPLEMENTED | `benchmarks/benchmark_{asr,llm,tts,e2e,vram}.py`; shape tests `benchmarks/tests/test_bench_scripts.py:76-464`; **real runs performed in E19** on `DEV_3060TI`/`DEV_3060TI_SHARED` for ASR, LLM, TTS (Piper+Qwen3-TTS 0.6B/1.7B), VRAM, and E2E (in-process + real LiveKit) — `docs/benchmarks/{asr,llm,tts,vram,e2e}.md`. |
| "Export benchmark results to JSON/CSV." | IMPLEMENTED | `_common.write_result`, envelope tests `benchmarks/tests/test_bench_scripts.py:308-326`. |
| ASR/LLM/TTS/E2E/VRAM's own listed sub-dimensions | PARTIAL | faster-whisper `NOT_RUN` (never installed, E12 ruling), Chatterbox `NOT_RUN` (no provider), FINAL-profile LLM (Qwen3-8B) `NOT_RUN` (no hardware), multi-session VRAM `NOT_RUN` (`docs/benchmarks/vram.md:12-115`, an open epic-marker there — see §3 deviations). Real LiveKit E2E latency percentile: the two-clock-origin bug that withheld it is **fixed (R13, E20-F)** — `benchmark_e2e.py --transport livekit` should now publish a real percentile; the confirming re-run is E20-C's §46 walk, not yet performed as of this table. |

### §41 — Security / local operation

"Core demo must work without external AI APIs." "No OpenAI/Anthropic/etc API is allowed in the
runtime path." "Keep recordings, transcripts, cards, scoring and models local." "Configurable
retention/deletion." "Secrets/configuration… environment/config files, not source code.": all
**IMPLEMENTED** — loopback/compose-internal-only LLM URL validation
`backend/app/inference/llm/llama_cpp_client.py:1-80`; import-boundary test rejects
Anthropic/OpenAI imports `backend/tests/unit/test_check_imports.py:194-321`; purge use case
`backend/app/application/recording/purge_recordings.py:73-150`; `.env`/`.env.example` for secrets.

### §42 — Tests: required invariants

All 14 invariants: **IMPLEMENTED**, one `backend/tests/invariants/test_inv_<nn>_*.py` file per
item (audit-2 §42 table, exact assertion line ranges cited for each). Historical "green" counts are
not this audit's own fresh run — `make test-backend` is each concurrent worker's own hand-back
obligation; this task ran the doc-parser subset only (§5 below).

### §43 — Hallucination / information-leak test suite

Ten adversarial categories, ≥60 cases, `forbidden_fact_leak_rate` tracked at 0, invented-entity
rejection: **IMPLEMENTED**, `backend/tests/adversarial/test_forbidden_fact_leak_suite.py:1-565`
(audit-2 §43 table). Two validator-policy edge cases from the E20 hand-off remain, one **IN
PROGRESS**: the numeric-only-answer-becomes-EMPTY behavior (E19-C2) stays pending the owner's
confirmation per **R5**, unchanged this task — documented in §3 deviations and in docs 50 §7.4 (A's
row, not edited here); the Latin-only-text-should-be-META_LANGUAGE-not-EMPTY half of R5 was **not
yet landed** in `backend/app/application/dialogue/validator.py` at capture time (file not present
in `git status --short`, i.e. still at the E19 HEAD content) — E20-A's task, re-verify at epic
close.

### §44 — Performance rules

"Do not optimize by violating architecture." All eight "never" clauses. "Prefer a smaller/faster
model over removing safety/state boundaries.": all **IMPLEMENTED** — enforced by the same
INV1/3/4/9/11 + validator + handoff evidence cited throughout this table; the model-choice clause
is directly evidenced by E19's Qwen3.5-2B decision (smaller/faster, quality-gated) over forcing
Qwen3-4B, `docs/hld/00-decisions.md` D9.

### §45 — Implementation order

"Implement in this dependency order," Phases A–L, "Do not start by building a polished chat UI,"
"Do not start by asking an LLM to generate an entire scenario at runtime.": **IMPLEMENTED** as a
process requirement — the epic table follows A–L exactly (`docs/hld/90-tbd-epics.md`), and the
current frontend has four operational route groups, not a chat-only app or a runtime-scenario
generator anywhere in the tree (`grep -rn "generate.*scenario" backend/app` finds no such code
path).

### §46 — Definition of Done

See the dedicated table in §2 below — this is a real-stack, human-observed requirement and the
verdicts here are necessarily provisional (fake-provider/unit-test evidence only) until E20-C's
walk.

### §47 — "When you write code"

The epic protocol itself (state requirement numbers, vertical slice, migrations, tests, run tests,
never remove existing behavior, report the unimplemented explicitly): **IMPLEMENTED** as an epic
convention — every `docs/hld/90-tbd-epics.md` row and every report in
`/tmp/teamwork-112-maxxing/reports/` follows this shape; this document itself is the requested
"report any unimplemented requirement explicitly" for the whole SPEC. "Smaller implementation
preserving the architecture over easier implementation changing it" — IMPLEMENTED as a recurring
decision throughout this table (Qwen3.5-2B over relaxing the quality bar; sentence-chunked TTS over
collapsing the gate; etc.).

---

**Re-verification note (E20-D2, final pass).** E20-A/B/E/F have all now handed back
(`/tmp/teamwork-112-maxxing/reports/e20-{a,b,e,f}.md`, read in full for this pass) and every
R-numbered ruling below is re-confirmed **landed** by reading the actual current-tree source, not
by trusting a report's claim alone:

- **R1** (E20-A, INV3 REST leak) — `docs/hld/openapi.yaml`/`backend/app/api/schemas/dds.py`/
  `backend/app/application/dds/views.py` drop `source_world_event_id`;
  `backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py` gained the "(a2)
  Structural" section (3 new tests); `frontend/src/features/dds/no-world-truth-guard.test.ts`
  gained the `world_event`/named-view cases. Bite-proof run and reverted per the report.
- **R2** (E20-F, `voice:join` re-publish) — `backend/app/application/operator/call_flow.py`:
  `_retry_join` now fires on `RINGING` **or** `CONNECTED`, stops on `_agent_joined(log, call_id)`
  (the first event the agent itself appended for that `call_id`, since no dedicated "agent
  joined" `EventType` exists — see the HLD-gap fold below) or phase `ENDED`; HLD 40 §40.6's
  `voice:join` row rewritten to match (E20-F's file under the original concurrency split — already
  edited, so this task did not re-touch it). Tests: `backend/tests/api/voice/test_call_signals.py`
  (4, including the old bug-asserting test inverted into
  `test_the_retry_survives_an_answer_the_agent_was_too_slow_for`).
- **R3** (E20-A, compose `tts-qwen3` host) — `infra/docker-compose.yml:256`
  `SIM_TTS_QWEN3_HOST: 0.0.0.0`; stale `voice_agent.cli health`/hard-coded-loopback comments at
  ~221-225/~256-260 corrected; `.env.example` ~120-127 corrected to match. `make compose-check`
  green per the report.
- **R4** (E20-A, `make deps --inexact`) — `Makefile:48` confirmed
  `$(UV) sync --all-packages --group dev --inexact`.
- **R5** (E20-A, §7.4 Latin-only) — `backend/app/application/dialogue/validator.py` gained
  `_CYRILLIC_RE`/the whole-utterance language check under `META_LANGUAGE`; `EMPTY` unchanged; 8
  new tests in `backend/tests/unit/application/dialogue/test_validator.py`; `docs/hld/50-voice-pipeline.md`
  §7.4 gained the rule as prose plus the numeric-only "current policy, owner to confirm" paragraph
  (E20-A's file — already done, not re-touched here).
- **R6** (E20-A, stale open-marker sweep) — all eight named markers reworded to plain statements
  (no code change); `reports/e20-a.md`'s own final sweep over its FILES is empty except two items
  outside its scope: `docs/benchmarks/vram.md:17,157` (this task's §3 deviation, see below) and a
  **new** open-item marker E20-E left at `backend/app/application/voice/events.py:594`, naming
  itself for that epic slice — that file is outside this task's FILES too (docs only); not a
  `docs/` hit, so it does not affect this task's own end-of-task grep check.
- **R8** (E20-B, injection CLI) — `workers/voice_agent/voice_agent/tools/inject.py` +
  `workers/voice_agent/tests/test_inject_cli.py` (16 tests) exist; `make demo-init`/`demo-inject`
  Makefile targets exist; README's "Mic-less demo" section documents it. The CLI deliberately
  never prints the caller's own words (see §3 deviation, new item below) — a read reading, not a
  gap.
- **R11** (E20-E) — `abortSession` wrapper + Russian confirm dialog on the instructor overview;
  `label_ru` on `WorldTruthView`/`CallerBeliefView` (additive, `docs/hld/openapi.yaml`,
  `backend/app/application/instructor/get_overview.py`); `DdsDecisionView.note_ru`/`comment_ru`
  (additive, not yet rendered by `frontend/src/features/report/dds-decisions-section.tsx` — no
  E20 worker owns that path, listed as an open follow-up in `reports/e20-e.md`);
  `backend/app/db/migrations/versions/0008_purge_audit_actor_admin.py` (confirmed present) gives
  `recording_purge_audit.actor_type` an `ADMIN` member and `purge_recordings.py` now records the
  real actor role; Settings gains `tts_device`/`tts_output_sample_rate`/`vad_device`/
  `tts_model_variant` (the last aliased onto `SIM_TTS_QWEN3_MODEL`, the same env name the
  `tts_qwen3` worker already reads) with `apply_profile` overlay; two `Close` labels now Russian.
  One real bug found and partially fixed in the same task: `application/voice/events.py`'s
  `VoiceEventAppender.offset_ms()` used the raw unfrozen clock, unlike every other writer — fixed
  with a new optional `session_state` provider parameter, but **not yet wired into production**
  (`workers/voice_agent/voice_agent/{wiring,main}.py`, `application/voice/turn_pipeline.py`, none
  in E20-E's FILES) — left as the inline open-item marker noted above.
- **R13** (E20-F) — confirmed landed, see the §27 row above for the full two-bug account;
  `backend/app/application/ports/call_transport.py:31-40`,
  `workers/voice_agent/voice_agent/transport/livekit_transport.py:126-236` (re-read directly:
  `_now_ms()` is now `session_offset_ms(self._clock.now(), self._started_at)`, both required
  constructor keywords, `_origin_ms` deleted). 7 tests in
  `workers/voice_agent/tests/test_transport_clock_origin.py`.
- **R14** (E20-F) — confirmed landed by reading the files directly: `_LOCK_SESSION_ROW` in
  `backend/app/infrastructure/persistence/event_store.py:82-83` and
  `SessionRepository._load(for_update=True)` in `session_repository.py` both now take
  `FOR NO KEY UPDATE` (not `FOR UPDATE`); `backend/tests/integration/persistence/test_seq_lock_order.py`
  (confirmed present, 1 test, 50-round drive) bites on the unfixed lock mode and passes on the
  fixed one, per the report's own transcript. `docs/hld/20-db-schema.md` §20.8 and
  `docs/hld/00-decisions.md` D5 rewritten by E20-F to state the real cause (an implicit `FOR KEY
  SHARE` on every FK-child insert from the voice agent's side tables, not a second explicit lock as
  the original brief guessed) and the one lock mode/order rule — E20-F's files, not re-touched
  here. `SIM_SIM_TICK_MS=500`: nothing in the repository pins a 10 s workaround (E19-E3's override
  lived in a throwaway shell script, not the tree), so there was nothing to restore.
- **R15** (E20-F) — confirmed landed: `backend/app/config/model_paths.py` exists
  (`resolve_model_path`/`LEGACY_MODEL_PATHS` moved from `benchmarks/_common.py`, which now
  re-exports both with an identity test); `Settings.models_root`
  (`SIM_MODELS_ROOT`, default `/models`); `voice_agent.providers`' four real branches and
  `preflight.check_model_files_exist` both go through the new `host_model_path`/`models_root`;
  `workers/tts_qwen3/tts_qwen3/server.py._host_model_dir()` rebases independently (that worker is
  deliberately not a workspace member). 14 new tests across
  `backend/tests/unit/config/test_model_paths.py` (confirmed present),
  `workers/voice_agent/tests/test_providers.py`, `backend/tests/unit/cli/test_preflight.py`,
  `benchmarks/tests/test_bench_common.py`, `workers/tts_qwen3/tests/test_server.py`. **Hand-off
  still open** (E20-F's own report flags it, not this task's to fix): the README host-run section
  needs `export SIM_MODELS_ROOT=./models` or an equivalent `make profile-env` note — E20-B's file,
  not touched here.

No R-numbered ruling is left as "in progress" in this document as of this pass — every one above
is either fully landed (verified against source) or, for R11's `dds_decisions-section.tsx` wiring
and R15's README note, explicitly named as a follow-up owned by a file no E20 phase-1 worker
claims. §2's §46 DoD table is intentionally left untouched — E20-C's real-stack walk is running now
and owns every verdict in that table.

## 2. SPEC §46 Definition-of-Done table — the real-stack walk (E20-C, 2026-09-22)

**R9 is done.** The sixteen items were walked on the real `DEV_3060TI` stack on **2026-09-22** at
the shipped `SIM_SIM_TICK_MS=500`, session `49accdb9-e2c2-4d43-9247-ddb168e16ae8` — the instructor
and trainee actions issued over the real REST API, the trainee's voice published into a real
LiveKit room by `python -m voice_agent.tools.inject` (E20-B/R8). The full account, with the
commands, the event-log excerpts and every open item, is **`docs/DOD_WALK.md`**; the evidence
(report JSON, event log, work item, notifications, inference metrics, injection logs, preflight)
is in `docs/benchmarks/results/dod-walk-20260922/`.

**Real-stack verdicts: 12 PASS, 4 PARTIAL, 0 items replaced by a hard-coded fake UI animation.**
The walk had to use the **host-run** path: the documented `make up` path cannot place a voice call
today (four defects, open items 1-4 of `docs/DOD_WALK.md` §4 — the decisive one being that the
`voice-agent` image carries no `livekit` extra).

| # | item | real-stack verdict (E20-C walk) | evidence, and why a PARTIAL is partial |
|---:|---|:--|---|
| 1 | Start an incident | **PASS** | `POST /sessions` + `/start` as INSTRUCTOR; `SESSION_CREATED`/`SESSION_STARTED`/`ROLE_STAGE_STARTED` seq 1-3. |
| 2 | Receive a realistic incoming call | **PASS** | `CALL_RINGING` seq 4 at offset 353 ms; answered ≈0.5 s later and the agent still joined — E20-F/R2 confirmed live. |
| 3 | Talk naturally with an AI caller | **PASS** (E20-I) | Through the documented `make up` path with the SHIPPED `DEV_3060TI` (Qwen3-TTS 0.6B primary): caller lines voiced by `qwen3_tts` / `Serena`, `FACTS_DELIVERED` after uninterrupted audio, preflight 10/10 — `docs/DOD_WALK.md` §7, evidence `docs/benchmarks/results/dod-walk-20260922/e20i/`. E20-C's walk had it PARTIAL (silent caller); the causes were the scenario voice id and unwarmed fallback (fixed E20-G) and the tts-qwen3 image, the warm-up timeout, the fallback voice path and a 1500 ms first-chunk guard a whole-utterance TTS can never meet (fixed E20-I, DOD_WALK §7.2). |
| 4 | Interrupt the caller | **PASS** | `CALLER_UTTERANCE_INTERRUPTED` seq 124 with `fact_ids_not_revealed: ["address.floor"]`; dedicated re-run: 19 barge-ins, p50 62 ms, 3 over the 250 ms budget (open item 7). |
| 5 | Obtain information only by asking appropriate questions | **PARTIAL** | `incident.fire_source` (NEVER_DISCLOSE/UNKNOWN) asked explicitly → caller says it does not know (seq 69-72); `people.total_inside` released on an explicit ask (seq 59). But an imperative request ("Назовите улицу") is interpreted as `INSTRUCTION` with `requested_facts: []`, so a known `ON_ASK` fact is never released (open item 8). |
| 6 | Manually fill a 112 incident card | **PASS** | Twelve one-field `PUT /operator/card/field` commands, revisions 1-12, one `CARD_FIELD_CHANGED` each (seq 141-153). |
| 7 | Mistakes remain real mistakes | **PASS** | `address.house` entered as `72` (truth `27`); it survives into the snapshot, into DDS and into the score; report diff: `{"world_value": "27", "card_value": "72", "verdict": "MISMATCH"}`. |
| 8 | Select services and send the card | **PASS** | `SERVICE_SELECTED` ×2, `HANDOFF_CREATED` seq 160 (`content_sha256 0cc3feaf…`), `HANDOFF_RECEIVED` ×2 seq 162-163. |
| 9 | Move into the DDS stage | **PASS** | seq 165-169: `complete_stage` → `ROLE_TRANSITION_STARTED` (pause 20 s) → `ROLE_TRANSITION_COMPLETED` → `ROLE_STAGE_STARTED{DDS}`, same `incident_id`. |
| 10 | Receive exactly the submitted information | **PASS** | `GET /dds/work-item` shows `"address.house": "72"`; the world's `27` appears nowhere in the payload. INV 3 holds on the real stack. |
| 11 | Choose and dispatch resources | **PASS** | `RESOURCE_DISPATCHED` seq 185 (АЦ-1/АЛ-1/СМП-11); the ETA model drove EN_ROUTE → ON_SCENE → WORKING unaided (seq 193-200). |
| 12 | Respond to evolving incident events | **PARTIAL** | `WORLD_EVENT_TRIGGERED` + `NOTIFICATION_CREATED` + `CALLER_EMOTION_CHANGED` fired on schedule (seq 172-177, 192), and the REST notification carries **no** `source_world_event_id` (E20-A/R1 proven live). But a world-event notification id is deterministic per scenario/seed, not per incident, so it is written once globally and is invisible in every later session (open item 9); and a DDS-stage trainee gets `403` acknowledging a notification they can read (open item 10). |
| 13 | Close the incident | **PASS** | Resolution condition met by the simulation at 541 427 ms; `POST /dds/close` → `DDS_INCIDENT_CLOSED`, ten `SCORING_RULE_EVALUATED`, `SESSION_COMPLETED`. |
| 14 | Deterministic evidence-backed assessment | **PASS** | `report.json`: **45.0 / 78.0**, `checksum e0fbb0a2611633ed`, ten rules, every rule with evidence; the two planted mistakes came back as the two critical failures. One evaluator defect found (open item 11). |
| 15 | Replay timeline, transcript, relevant audio | **PASS** | 228 timeline entries, 18 transcript segments (16 with audio); `GET /sessions/{id}/audio/{id}` → `200` 105 644 B, `Range: bytes=0-1023` → `206 Content-Range: bytes 0-1023/105644`. |
| 16 | See model/inference latency metrics | **PARTIAL** | `GET /reports/{id}/inference-metrics` returns real per-component rows (GigaAM, Qwen interpreter/generator, TTS). But the report's `timing_metrics.speech_end_to_first_audio_ms_p50/p95` and `llm_ttft_ms_p50` are `null` although the same log yields them (open item 12). |
| — | §46's closer — no item replaced by a hard-coded fake UI animation | **PASS** | Every item above was driven through a real application use case over the real API; nothing was animated or stubbed. |

The §27 percentile the walk also published, from the post-fix LiveKit re-run at the shipped tick
(`docs/benchmarks/e2e.md` §3.1, `e2e-DEV_3060TI-20260922T144530930Z.json`): **p50 1566 ms /
p95 4622 ms over 29 turns, `discarded_nonpositive_count: 0`** — the DEV p95 target of 2500 ms is
**not** met over a real media plane.

## 3. Not implemented / deviations (dated 2026-09-22)

1. **Chatterbox Multilingual TTS provider — not built.** §25/§26 name it as a benchmark/FINAL-profile
   option; no adapter exists (`workers/voice_agent/voice_agent/providers.py` has only
   `fake`/`piper`/`qwen3_tts`); `benchmarks/benchmark_tts.py:78-102` returns `NOT_RUN` honestly.
   **R12: explicitly not in scope for this epic.**
2. **Qwen3-8B FINAL profile — unmeasured.** No RTX 3080 Ti / Qwen3-8B GGUF available on this
   machine; `FINAL_3080TI_{12,16}GB.yaml` stay refused-until-measured
   (`docs/hld/60-inference-ops.md` §2 FINAL rows, `Makefile:124-138`).
3. **DEV LLM is Qwen3.5-2B by measurement, not SPEC §22's own "Qwen3-4B quantized" illustration.**
   Qwen3-4B remains selectable and is the closer-to-SPEC choice if the owner wants strict literal
   compliance over the measured quality/latency trade-off (`docs/hld/00-decisions.md` D9,
   `docs/benchmarks/llm.md`).
4. **Per-unit TTS buffering.** Both real TTS adapters (Qwen3-TTS, Piper) synthesize one full
   sentence/unit of PCM before yielding the first `TtsChunk`; barge-in therefore cancels the *next*
   unit reliably but cannot interrupt synthesis already in flight for the current one
   (`backend/app/inference/tts/qwen3_tts.py:369-408`, `piper_tts.py:225-250`). The sentence-level
   chunker (`backend/app/application/voice/sentence_chunker.py`) mitigates the perceptual gap but
   does not close it. Accepted for the demo per `docs/hld/00-decisions.md` D9's own TTS provider
   note; `qwen_tts==0.1.1` has no chunked/streaming generation entry point at all
   (verified against the installed package's source, E19-D3).
5. **TTFT == total latency for non-streaming LLM calls.** The product's interpreter/generator calls
   are single-shot (grammar + validator need the whole completion first), so `InferenceMetric.
   ttft_ms` is written `None` for both LLM components — there is no distinguishable earlier instant
   to record — and the concept "time to first token" collapses onto `total_latency_ms` for this
   chain (`docs/hld/60-inference-ops.md` §3's `ttft_ms` paragraph, added E19-G;
   `backend/app/application/dialogue/{interpreter,generator}.py`, `ttft_ms=None`). This is a
   documented design consequence, not a bug: it is *why* the report's `timing_metrics.
   llm_ttft_ms_p50` (SPEC §29 item 13) is `null` on every real session (H3, E20-H — percentile()
   over an empty sample is `null` per SPEC §27's "never fake a value"; documented on the field
   itself, `docs/hld/openapi.yaml`'s `TimingMetricsView.llm_ttft_ms_p50` description). It stops
   being null only if a streaming-capable LLM provider is added.
6. **§6's `current_emotion`/`stress_level` live on `EmotionState`, not on `CallerProfile`, by
   design.** `CallerProfile` carries only `baseline_emotion`/`baseline_stress_level`; the live,
   engine-mutated values are on `EmotionState` (`backend/app/domain/caller/emotion.py:26-32`),
   consistent with §6's own next sentence ("Emotion is part of simulation state and may change
   deterministically").
7. **Numeric-only caller answers ("3, 45") are classified `EMPTY` by the validator (E19-C2).**
   Per **R5**, this behaviour STAYS pending the owner's confirmation that it is intended — recorded
   here, and E20-A's task to extend docs 50 §7.4 with "current policy, owner to confirm" (not this
   task's file).
8. **Multi-session VRAM concurrency is untested.** `benchmarks/benchmark_vram.py` measures one
   session's turn sequence, not several concurrent sessions' combined peak; open marker in
   `docs/benchmarks/vram.md:17,157`, reworded by this task from the epic's own open-item marker to
   `TODO(POST-I1)` (it will not be closed inside this epic — not claimed by any FILES list in this
   epic's phase-1 concurrency note, and E20-C's §46 walk does not exercise multi-session
   concurrency either).
9. **~570 ms of non-model turn overhead.** Of the measured E2E turn budget, roughly 567 ms sits in
   VAD endpointing (320 ms configured silence) plus detector/persistence/outbound-queueing
   overhead, not in any model call (`docs/hld/60-inference-ops.md` §10 item 13's stage breakdown).
   Not a defect; recorded for anyone tuning the latency budget.
10. **LiveKit `ListRooms` preflight check is HTTP-origin reachability only**, not a real
    `livekit-api` room check (`backend/app/cli/preflight.py:271-284,562-570`). **R12: explicitly not
    in scope** (needs the `livekit-api` SDK as a new dependency).
11. **R13 — FIXED (E20-F).** `speech_end_to_first_audio_ms` was unmeasurable over real LiveKit
    because of **two** clock bugs, both confirmed fixed by reading the current source: (1)
    `LiveKitCallTransport._now_ms()` measured from its own private, transport-first-frame-relative
    `_origin_ms` — now `session_offset_ms(self._clock.now(), self._started_at)`, defined on the
    port itself (`backend/app/application/ports/call_transport.py:31-40`,
    `workers/voice_agent/voice_agent/transport/livekit_transport.py:126-236`); (2)
    `VoiceEventAppender(started_at=None)`'s silent zero-offset default, never overridden by the
    real agent process — now `voice_agent.main._session_started_at(session_id)` reads the
    persisted value and threads it through both the transport and the pipeline. Test:
    `workers/voice_agent/tests/test_transport_clock_origin.py` (7 tests, confirmed present) proves
    a 30 s session→transport gap now yields a positive metric equal to the in-process value. **The
    real LiveKit re-run was performed** by E20-C's §46 walk (2026-09-22): n=29,
    `discarded_nonpositive_count=0` (R13 proven live), p50 1566 ms / p95 4622 ms, `meets_target:
    false` (the DEV p95 target is not met over the real media plane — see §27 above,
    `docs/benchmarks/e2e.md` §3.1). Separately, the *report's own* display of this metric
    (`timing_metrics.speech_end_to_first_audio_ms_p50/p95`) was `null` for an unrelated reason — a
    voice-agent wiring bug that split `register_turn`/`record_turn_latency` across two different
    `MetricsRecorder` instances — **fixed, H3, E20-H** (see §27 above).
12. **R14 — FIXED (E20-F).** The real cause was not a second explicit lock (the original brief's
    guess) but an **implicit** one: every voice-agent side-table insert
    (`audio_segments`/`transcript_segments`/`dialogue_turns`/`inference_metrics`, each FK'd to
    `simulation_sessions`) takes PostgreSQL's automatic `FOR KEY SHARE` on the referenced session
    row, and the literal `FOR UPDATE` HLD 20 §20.8 specified conflicts with it, forming a
    lock-upgrade cycle whenever two such transactions overlap. Fixed by changing the lock **mode**,
    not the order: `_LOCK_SESSION_ROW` in
    `backend/app/infrastructure/persistence/event_store.py:82-83` and
    `SessionRepository._load(for_update=True)` in `session_repository.py` both now take
    `FOR NO KEY UPDATE` (confirmed present by reading the file directly) — compatible with
    `FOR KEY SHARE`, still self-conflicting, so allocation stays strictly serialised with no
    upgrade cycle possible. `docs/hld/20-db-schema.md` §20.8 and `docs/hld/00-decisions.md` D5
    rewritten by E20-F to state the real mechanism and the one-lock-mode rule (not this task's
    file). Regression test: `backend/tests/integration/persistence/test_seq_lock_order.py`
    (confirmed present, 50-round drive of a runner tick against two overlapping agent-shaped
    appends; the report's own transcript shows it reproduces `DeadlockDetectedError` verbatim on
    the unfixed tree and passes on the fixed one). `SIM_SIM_TICK_MS=500`: nothing in the repository
    ever pinned a longer tick (E19-E3's 10 s workaround lived in a throwaway shell script outside
    the tree, per E20-F's own report), so there was nothing to restore.
13. **R15 — FIXED (E20-F).** Host runs of the voice agent / `app/cli/preflight.py` check 3 used to
    resolve a profile's compose-internal `/models/...` paths with no host equivalent. Confirmed
    present: `backend/app/config/model_paths.py` (`resolve_model_path`/`LEGACY_MODEL_PATHS`, moved
    out of `benchmarks/_common.py`, which now re-exports both under an identity test so the two
    can never drift), `Settings.models_root` (`SIM_MODELS_ROOT`, default `/models` — compose is a
    no-op), all four real `voice_agent.providers` branches and
    `preflight.check_model_files_exist` routed through it, and
    `workers/tts_qwen3/tts_qwen3/server.py._host_model_dir()` doing the primary-mapping rebase
    independently (that worker is deliberately not a workspace member, so it cannot import the app
    resolver). 14 new tests confirmed present across
    `backend/tests/unit/config/test_model_paths.py`, `workers/voice_agent/tests/test_providers.py`,
    `backend/tests/unit/cli/test_preflight.py`, `benchmarks/tests/test_bench_common.py`,
    `workers/tts_qwen3/tests/test_server.py`. **Still open (not this task's file):** the README
    host-run section needs an explicit `export SIM_MODELS_ROOT=./models` line or a `make
    profile-env` note — E20-F's own report hands this to E20-B; not yet done as of this table.
14. **True sub-unit (sentence-internal) TTS streaming — not in scope.** `qwen_tts` has no such API;
    Piper per-sentence chunking is accepted for the demo. **R12: explicitly not in scope.**
15. **A prompt change for re-asked facts (same value on repeat) — proposal only, not applied.**
    Raised in E19-C2/`docs/hld/50-voice-pipeline.md` §7.1/§5.2 proposal note. **R12: explicitly not
    in scope; not this task's file.**
16. **Moving the scoring hook out of routers — documented, not built.** **R12: explicitly not in
    scope.**
17. **`INFERENCE_HEALTH_CHANGED`'s timeline summary key mismatch.** §10.13's payload has
    `component, previous_status, new_status, detail`; `backend/app/application/reports/timeline.py:192-194`'s
    `SummaryTemplate.detail_keys` asks for `("component", "status")` (no `status` key on the real
    payload, so the timeline row renders `component` alone rather than erroring — `detail_keys` is
    documented as "a key the event did not carry is skipped"). Cosmetic, flagged by E18-B, not
    fixed — outside every E20 phase-1 FILES list.
18. **`ResourceTimelineEntryView.previous_status` is a required, non-nullable field in
    `docs/hld/openapi.yaml`, but a resource's first transition has no predecessor** and the
    implementation reports `null` (closer to SPEC §27's "do not fake a value" than inventing one).
    `docs/hld/openapi.yaml` is E20-A/E's file, not this task's; flagged by E16-A.
19. **`HealthReadyResponse.model_profile`'s OpenAPI enum lists only the SPEC's three profile names**,
    not the additive `DEV_3060TI_SHARED` — running with that profile would fail response validation
    on `/health/ready`. `docs/hld/openapi.yaml` is not this task's file; flagged by E18-A/E18-B,
    still open per a spot check of the current file at capture time.
20. **`recording_purge_audit.actor_type` — FIXED (R11, E20-E).** Previously had no `ADMIN` member
    even though `purgeRecordings` is ADMIN-only, so the use case recorded `INSTRUCTOR` for any
    authenticated caller. Confirmed landed:
    `backend/app/db/migrations/versions/0008_purge_audit_actor_admin.py` (additive enum value, a
    real up/down round-trip verified per the report) and
    `backend/app/application/recording/purge_recordings.py` now records `actor.user_role.value`
    instead of a hard-coded `"INSTRUCTOR"`. 2 new integration tests per the report.
21. **`getReportExplanation` has no `audience` query parameter in the OpenAPI contract**, even
    though two rows (`TRAINEE`/`INSTRUCTOR`) can exist per session; implemented as "the caller's own
    role selects the row" without a contract change. `openapi.yaml` not this task's file.
22. **INV 7 weakness: `session_events` ordering within one tick is not fully deterministic** for
    same-offset events emitted by a single tick (`RESOURCE_STATUS_CHANGED` rows can come out in a
    different relative order between two runs with identical offsets/types); the existing INV7 test
    and `test_full_cycle.py` compare "same types/offsets in the same order" rather than pin this.
    Flagged by E17-B as pre-existing and out of that task's scope; still open, no owner in this
    epic's phase-1 FILES lists.
23. **No dedicated "agent joined" event exists; the `voice:join` ack is a proxy (R2, E20-F).**
    HLD §8's event catalogue has no `AGENT_JOINED`/`CALL_CONNECTED` type, and
    `TransportEventType.CONNECTED` is deliberately never persisted as a `SessionEvent`
    (`backend/app/application/voice/events.py:298-312` maps only `DISCONNECTED`/`RECONNECTED`).
    So `_agent_joined(log, call_id)` in `backend/app/application/operator/call_flow.py` treats
    **the first event the voice agent itself appends for that `call_id`** — any of
    `USER_SPEECH_STARTED/_ENDED`, `ASR_PARTIAL/_FINAL`, `CALLER_TTS_STARTED/_ENDED`,
    `CALLER_UTTERANCE_INTERRUPTED`, `DIALOGUE_INTERPRETED`, `FACTS_DELIVERED`, `MODEL_ERROR`,
    `MODEL_FALLBACK_USED`, `TRANSPORT_DISCONNECTED/_RECONNECTED` — as the join acknowledgement,
    since only the agent's own `VoiceEventAppender` ever writes those, over the event store and
    never over REST (D9). This is correct (proven by `backend/tests/api/voice/test_call_signals.py`)
    but indirect: a call whose agent joins and then produces no turn keeps being harmlessly
    re-advertised (`VoiceAgent._on_join` is idempotent) until the first turn. A dedicated additive
    `EventType` would be exact but needs a §8 catalogue change and a DB enum migration; **not
    done**, per E20-F's own HLD-gap note — the closest reading of SPEC §8 was taken (do not invent
    an event) rather than adding one silently. HLD 40 §40.6's `voice:join` row was rewritten by
    E20-F to state this design; re-read at capture time and confirmed consistent with the code
    above.
24. **The audio-injection CLI (R8, E20-B) deliberately prints none of the caller's own words.**
    `python -m voice_agent.tools.inject` authenticates and opens its WebSocket *as the trainee*
    (`OPERATOR_112`), and the trainee-facing realtime channel redacts `CALLER_TTS_STARTED` down to
    `{call_id, turn_index, at_offset_ms}` — `text_sent_to_tts` never reaches that connection, by
    the same visibility rule R1 enforces on the REST paths
    (`backend/app/application/realtime/redaction.py:154-155`, HLD 40 §40.4 row 12). Printing the
    caller's transcript from this CLI would reopen exactly the boundary R1 just closed, so it
    prints only what the trainee's own connection legitimately receives instead: `ASR_FINAL.text`
    (confirms the right WAV was heard), the redacted `CALLER_TTS_STARTED`/`_ENDED` timing, and
    `speech_end_to_first_audio_ms` when positive. A demo operator who needs to hear or read the
    caller's side reads it instructor-side (the report/replay UI, or the instructor's live overview
    — neither redacts it). Documented in the CLI's own module docstring and in README's "Mic-less
    demo" section (E20-B's files).
25. **Notification/radio-message id collision across sessions — FIXED (H1, E20-H).**
    `app.domain.world.apply`'s `uuid5` derivation for `NOTIFICATION_CREATED`/`RADIO_MESSAGE_CREATED`
    ids used only `(world_event_id, occurrence, effect index)`, with no session-distinguishing
    component; the pure domain has no randomness (D2/D7), so two sessions of the same scenario +
    seed fire the identical `world_event_id`/`occurrence` pair and derived the identical id. The
    materializer's idempotent `ON CONFLICT (id) DO NOTHING` (meant to make one tick's
    re-examination a no-op) then silently swallowed the **second** session's row as a duplicate of
    the first's — reproduced live by E20-C's §46 walk (`"Развитие пожара"` at seq 175 belonged to
    an earlier ABORTED session's incident). The sibling snapshot/assignment/resource id
    derivations (`app.domain.layers.copies.freeze_card_to_snapshot`/`snapshot_to_assignment(s)`,
    and `ResourceId`/`CardId`/`IncidentId` allocation in `create_session.py`) were checked for the
    same flaw and do **not** have it: all three build on `card_id`/`incident_id`, which are random
    (`Uuid4Generator`, application-side) per session. Fixed by including `state.incident_id`
    (itself a fresh random id per session) in the `uuid5` name, so replay determinism within one
    session is unchanged. Test: `backend/tests/unit/domain/world/test_apply.py::
    test_notification_and_radio_ids_are_distinct_across_sessions`.
26. **`acknowledgeNotification`/`listNotifications` role-resolution mismatch — FIXED (H2, E20-H).**
    `acknowledge_notification.py`'s `_acting_role` preferred the optional
    `SessionParticipant.assigned_role_type` over the participant's actual `RoleStage` binding, while
    `listNotifications`'s `audience_roles_for` walks every `RoleStage` the participant is bound to.
    For a `FULL_CYCLE_SINGLE_TRAINEE` trainee whose `assigned_role_type` names their first role
    (`OPERATOR_112` — legal under `ALL_STAGES_ONE_PARTICIPANT`, and what the real walk's session
    creation call used), the two commands disagreed once the trainee reached the `DDS` stage: the
    notification listed as visible could not be acknowledged (`403 FORBIDDEN_FOR_ROLE`), reproduced
    live by E20-C's §46 walk. Fixed by having `acknowledge_notification.py` call
    `list_notifications.audience_roles_for` directly — one function, one set of roles, for both
    commands. Test: `backend/tests/api/modes/test_notification_role_resolution.py::
    test_a_full_cycle_trainee_lists_and_acknowledges_the_dds_notification`.
27. **`REQUIRED_STATUS_UPDATE` timing — FIXED (H4, E20-H).** The evaluator compared the *first*
    `DDS_STATUS_UPDATE_SENT` of the right kind to the *first* occurrence of the reference event
    type in the whole log, so any earlier qualifying reference event (e.g. `DISPATCHED`, long
    before the `ON_SCENE` arrival the rule's own `description_ru` means) made the rule
    unsatisfiable — reproduced live by E20-C's §46 walk (`"Задержка от RESOURCE_STATUS_CHANGED:
    279160 мс при норме 60000 мс"`). Fixed per the manager's ruling: every occurrence of the
    reference event type now opens its own window, and the rule passes only when each window has a
    matching update (`backend/app/domain/scoring/evaluators/required_status_update.py`,
    `docs/hld/10-domain-model.md` §10.14 #9 reading 6 rewritten to match). The evaluator still does
    not filter the reference event type by payload (e.g. `new_status == ON_SCENE`) — the demo
    scenario's own config leaves `within_ms_of_event: RESOURCE_STATUS_CHANGED` unfiltered, so
    *every* status change of the dispatched unit (DISPATCHED→EN_ROUTE→ON_SCENE→WORKING→RETURNING)
    now opens a window the DDS trainee must answer within `within_ms`, not just arrival — closer to
    the rule's literal config than to its Russian description. Left as an HLD gap for the scenario
    author/manager to confirm the intent, not guessed at by adding an implicit filter. Tests:
    `backend/tests/unit/domain/scoring/test_evaluators.py::
    test_required_status_update_every_qualifying_change_needs_its_own_answer` (bite proof) and
    `..._every_qualifying_change_answered_in_time_passes`.
28. **Interpreter: bare imperative fact requests — known 2B limitation, corpus extended (H5,
    E20-H).** «Назовите улицу.» (no question mark, no interrogative word) was interpreted as
    `INSTRUCTION` with `requested_facts: []` by the shipped `DEV_3060TI` interpreter model
    (Qwen3.5-2B), so a *known*, `ON_ASK`-disclosable fact was never released — reproduced live by
    E20-C's §46 walk (item 5). No prompt change was made (**R12: explicitly not in scope**); three
    imperative-phrasing cases were added to the labelled eval corpus instead, so the gap is
    measured rather than silently accepted: `imperative_request_street` («Назовите улицу.» →
    `address.street`), `imperative_request_house_number` («Скажите номер дома.» → `address.house`),
    `imperative_request_phone` («Назовите ваш телефон.» → `caller.phone`)
    (`benchmarks/interpreter_eval/ru_operator_utterances.yaml`, regenerated into
    `benchmarks/data/llm/interpreter_cases.jsonl`, 40 rows total). No existing gate-side unit test
    drives this labelled corpus against `FakeLLM` per case (`backend/tests/unit/application/
    dialogue/test_eval_scoring.py` tests `benchmarks/interpreter_eval/scoring.py`'s scoring
    functions against hand-built payloads, not the corpus itself) — per the ruling's explicit
    "only if such a harness exists" condition, none was invented; the corpus is exercised by
    `benchmark_llm.py --suite interpreter` (real model or `--provider fake` shape run).

29. **Qwen3-TTS latency is the owner's known trade-off, now sized honestly (E20-I).** Qwen3-TTS is
    whole-utterance (`qwen_tts` 0.1.1 has no streaming API): first audio p50 4130 / p95 11078 ms
    (E19). The speech sink's 1500 ms first-chunk guard made EVERY Qwen3-TTS turn time out (silent
    caller on the documented path); `DEV_3060TI` now carries `tts.first_chunk_timeout_ms: 12000` /
    `tts.timeout_ms: 15000` sized from that measurement. Consequence: the caller's first audio is
    seconds late at p50 and SPEC §27's DEV target is not met with Qwen3-TTS (Piper: p50 136 ms).
    Owner decision (Qwen3-TTS on GPU) kept; the latency is reported, not hidden. Qwen3-TTS is also
    serial: two queued caller replies (e.g. a trainee turn split by a pause) make the second wait,
    and it may fall back to Piper (DOD_WALK §7.1). `docs/DOD_WALK.md` §7.2 row d.
30. **DEV_3060TI ships Qwen3-TTS 0.6B, not the owner-evaluated 1.7B (E20-I, by measurement).** 1.7B
    peaks at 7448 MB > the 7168 MB budget and pushes the LLM to GPU_PARTIAL (docs/benchmarks/vram.md
    §2.3); 0.6B is the variant the measured 5560 MB describes and the one `make models` downloads.
    1.7B stays selectable (`tts.model_variant`) on a card with ~2 GB more headroom.
31. **The FATAL latch survives `make down` (by design, E18).** `voice:health:fatal` lives in the
    `redis-data` named volume; a latch from an earlier run refuses `startSession` until an ADMIN
    clears it (`POST /api/v1/admin/inference/clear-fatal`, RUNBOOK). Observed in E20-I round 1.
32. **Under compose, `make preflight` runs inside the voice-agent container (E20-I).** The agent's
    preflight endpoint binds loopback inside its container (SPEC §41) and llama-server publishes no
    port (HLD 60 §9), so the host cannot see the stack; `infra/scripts/preflight.sh` detects a
    running compose `voice-agent` and execs there (`scenarios/` mounted read-only). Check 12
    (`llama_server_binary`) is a SKIP in that vantage point — the binary lives in the llama-server
    image.
33. **Caller text never contains structural characters (E20-I).** The caller grammar's
    `speech-char` excludes `{}[]<>`, backslash and backtick, and the validator rejects them as
    `SCHEMA_INVALID` (the real walk heard `}I не знаю…`). A consequence: the caller cannot quote
    with `"` (Russian speech uses «»).

34. **REQ-2139 (ТЗ ¶161, VoIP one-way delay ≤ 150 ms) and REQ-2138 (ТЗ ¶160, «≥ 20 одновременных
    сессий») — I3 E6f, measured 2026-09-24, `docs/benchmarks/voip.md`.** These are the ТЗ's own
    organizer requirement ids (`requirements/normalized/SRC-001-formal-docs.md`), outside SPEC's
    §1-§47 numbering that the rest of this table uses; recorded here because this task's brief asks
    for it, not because SPEC names them. Two paths were swept with `benchmark_voip.py --concurrent
    N` for N ∈ {1, 5, 10, 20, 40}: `sip-loopback` (the real SIP/RTP gateway alone, in its own
    subprocess) stays sub-millisecond delay and 0 % RTP loss through **N=40**, the largest N
    tested — REQ-2139's 150 ms target is met with wide headroom at every tested concurrency on the
    gateway itself. `sip-livekit` (the SIP leg *and* the SFU together, the real voice path ТЗ ¶161
    means) meets the target only at **N=1** (p50/p95 95.8/108.6 ms); N=5 misses it by roughly 9x
    (p95 1319 ms, still 0 % RTP loss); N=10 additionally shows 47.7 % burst-detection loss
    (`PARTIAL`); N=20/N=40 are `NOT_RUN` — the benchmark's own single-process harness (the gateway,
    N SIP user agents and 2N LiveKit SDK room connections sharing one Python interpreter) did not
    complete a run within 250 s, a harness limitation `voip.md` distinguishes explicitly from a
    SIP/RTP-gateway or SFU capacity finding (both components' own CPU stayed low throughout).
    **REQ-2138's «≥ 20 concurrent sessions» is therefore not demonstrated by this measurement on
    the real voice path**, and this epic explicitly leaves two things UNMEASURED rather than
    estimating them: (1) a real multi-process/multi-host load generator for `sip-livekit` beyond
    N=10 (this epic's harness cannot separate its own process contention from genuine SFU/gateway
    capacity above that N); (2) **AI-in-the-loop concurrency** — N simultaneous calls each running
    its own LLM/ASR/TTS inference and consuming VRAM on the single 8 GB dev card — which is E19's
    VRAM-benchmark territory (`docs/benchmarks/vram.md`, itself only measured for one session's
    turn sequence, §3 item 8 above) and was never in this epic's scope. `DEV_3060TI.yaml`'s
    `voip.concurrent_calls_measured: 1` records exactly the `sip-livekit` figure above, not a
    system-wide session count.

## 4. HLD-gap fold (every report's "HLD gaps"/"For the manager" section, R10)

Reports read in full per R10: e7-d, e11-a §7, e11-b §8, e12-a §6, e13-a §8, e13-b1/b2/b3/b4, e14-a/b/c/d,
e16-a/b/c, e17-a/b/c/d, e18-a/b/c/d/e, e19-a/b/c/d/e/f/g. Disposition legend: **(a)** already fixed
in the HLD (cite line) — reports say so themselves and this audit spot-checked a sample; **(b)**
fixed now by this task; **(c)** listed here, not HLD-prose-worthy or owned by another file this task
may not touch.

**(b) Fixed now, this task:**

1. **HLD 60 §8's flash-attention fallback claim was false.** The prose said "if the build reports
   [flash-attn] unsupported for the card, the launch script falls back to `auto` and logs it"
   (flagged by E19-F as unverified-while-verifying, not fixed, outside that task's FILES). Checked
   `infra/scripts/llama-server-entrypoint.sh` directly: it always execs `llama-server` with whatever
   `SIM_LLAMA_FLASH_ATTENTION` resolves to and has no runtime fallback/retry logic anywhere.
   **Corrected** in `docs/hld/60-inference-ops.md` §8 (this task) to state the actual behavior.

**(a) Already fixed in the HLD — verified present, no action needed:**

2. E11-B gap 1 (`ring` guard vs D9 circularity) — written into `docs/hld/10-domain-model.md` per
   that task's own report; not re-opened.
3. E17-B gaps 1–3 (pause clock naming `running_ms`/`transition_clock_ms`; `ConditionContext`'s
   optional layers; `paused_total_ms` writer) — documented in `docs/hld/10-domain-model.md`
   §10.8/§10.11/§10.12 and `docs/hld/30-scenario-format.md` §30.2/§30.8 and `docs/hld/20-db-schema.md`
   §20.3 per that task's own report.
4. E13-B4 gap 1 (`FactDefinition.enum_name` for `ENUM` value_type) — fixed at the source including
   the §10.4 doc table per that task's own report.
5. E19-A gap 1 (HLD 60 §3's stale `InferenceMetric` schema — wrong column names/types) —
   "§3 is now corrected to the schema" per that task's own report; confirmed present at
   `docs/hld/60-inference-ops.md` §3's `ttft_ms`/column paragraphs.
6. E18-c gap 2 (HLD 60 §4.4 named the wrong package path for `health.py`) — "corrected in §4.4 and
   §6" per that task's own report.
7. E19-g's whole consolidation pass (§2/§2.2/§2.2a/§3/§10/§12 of `docs/hld/60-inference-ops.md`, D9's
   TTS/LLM provider bullets in `docs/hld/00-decisions.md`, the `PiperTTS` streaming-caveat bullet in
   `docs/hld/50-voice-pipeline.md`, and the E19/E20 rows of `docs/hld/90-tbd-epics.md`) — spot-checked
   at `docs/hld/60-inference-ops.md` §10 items 7–13, all present with dated "MEASURED"/"BUILT"
   callouts through E19-E3's final LiveKit numbers (item 13). No further fold needed.
8. E19-e's "FOR DOCS 60" §10 E2E paragraph (the in-process p50/p95/stage-split numbers) and E19-e3's
   real-LiveKit paragraph — both present verbatim (with E19-E3's later, final figures superseding
   the E19-E2 draft) at `docs/hld/60-inference-ops.md` §10 item 13.
9. E13-a's doc fixes (rulings 1/2) — applied by that task directly, per its own §5.

**(c) Listed here — not HLD-prose-worthy, or the file belongs to another E20 worker (not fixed by
this task; see §3 for the ones that are also product-visible deviations):**

10. E7-D's 21 HLD gaps (§40.4 `NOTIFICATION_ACKNOWLEDGED` audience key, `SessionSnapshot`
    field-nullability readings, `listUsers` shape/tag questions, etc.) — all narrow, already-resolved
    implementation readings the reports themselves call "not code, so the owner can fold them in one
    pass"; none rises to a wrong/misleading HLD sentence worth a prose edit today. Full list:
    `/tmp/teamwork-112-maxxing/reports/e7-d.md` §7.
11. E11-A's 9 HLD gaps (§4.1 frame-rounding, file-location choices, `Clock` port naming,
    `turn_id`/`turn_index` duality, extra `USER_SPEECH_*` payload keys, un-catalogued transport
    events, `CALL_ENDED` actor, `voice:health` scope, ruling-3 cross-reference) — all "implemented as
    the reading closest to SPEC", none contradicts a still-current HLD sentence.
    `/tmp/teamwork-112-maxxing/reports/e11-a.md` §7.
12. E11-B's remaining gaps 2–6 (`caller_display_ru` source/content, `livekit_url` public-vs-process
    split, `VOICE_JOIN_RETRY_MS` default, a third port file, `call_state` cache reader wiring) —
    narrow implementation choices, no misleading HLD text found.
    `/tmp/teamwork-112-maxxing/reports/e11-b.md` §8.
13. E12-A's 7 HLD gaps (`inference_metrics.status`/`error_kind` — since resolved by migration 0004
    and E18-C's further `error_kind`/`error_code` reconciliation; `turn_id`/`turn_index` bridging;
    un-catalogued `stability`/`turn_id` keys; stage-resolution fallback; native-stream cancellation
    timing; port file names; `build_vad` signature) — all implemented, none needs a prose fix.
14. E13-A's gap 3–5 (live `CallerBelief` vs. `FactDefinition` precedence, `ALLOWED_REPEAT`
    invisibility, no new domain field needed) plus its §9 doc↔code observation (the Russian
    interpreter prompt still lists `OTHER` among `speech_act` values though the schema enum dropped
    it) — the prompt-text staleness is real but lives in
    `backend/app/application/dialogue/prompts/*.py`, not `docs/hld/*.md`; not this task's file to
    edit; flagged again here for whoever owns that prompt file next.
15. E13-B1/B2/B3/B4's remaining gaps (`/no_think` double-placement, `interpret()`'s missing
    `session_id`, `LlmCompletion`'s no-think-leak field, `ports/llm.py`'s mypy-driven type
    corrections, §7.1 tokenizer substitute, §7.3 stricter forbidden-identifier rule, §7.4's
    Latin-exemption-for-permitted-enum-values, missing enum→Russian label registry, §7.5 address/
    allowlist readings, un-catalogued event keys, `ConditionContext` cross-boundary refusal,
    `StoredDialogueTurn` projection additions, `FireSource`'s best-effort label registry, a
    `BaseException` trap in the eval harness, a missing forbidden-port entry) — all implemented
    judgment calls the reports themselves call "not invented, closest reading to SPEC"; none is a
    wrong HLD sentence.
16. E14-A/B/C/D's remaining gaps (TTS timeout error types, no emotion→speaking-rate curve,
    `cutoff_latency_ms` formula correction — already folded per E19-G's spot-check above,
    undelivered-transcript reading, `component`/`stage` duality, `CallTransport.play`'s missing
    frame hook, outbound frame re-stamping, `validate_llm_base_url` duplication,
    `instruct`/`TtsVoiceSpec.voice_id` wiring gaps, `check_imports.py` path-exclusion limitation,
    Piper's per-sentence buffering — folded into §3 deviation 4 above, `Qwen3TTSModel.from_pretrained`
    call-shape uncertainty) — implementation judgment calls, no misleading HLD prose found beyond
    what E19-G already corrected.
17. E16-A/B/C's remaining gaps (`SessionReport.final_card` non-nullable-but-empty reading,
    `ResourceTimelineEntryView.previous_status` nullability — folded into §3 deviation 18,
    §20.9-vs-§20.10 section renumbering — already resolved by that task itself, migration
    revision-id-vs-filename mismatch, `416`'s missing `Content-Range` header, dispatch-note/
    closure-comment TODO reassignment to E17 — **fixed, R11/E20-E** (`DispatchEvent.note_ru`/
    `DdsDecision.comment_ru` now exist, confirmed present in
    `backend/app/application/reports/dds_decisions.py`; not yet wired into
    `frontend/src/features/report/dds-decisions-section.tsx`, unowned by any E20 phase-1 FILES
    list), `getReportExplanation`'s
    missing `audience` param — folded into §3 deviation 21, `TimelineEntryView`'s stage-filter gap,
    empty-section muting instead of DOM removal, no Russian-label field on enum-heavy report views)
    — openapi/contract items belong to E20-A/E, not this task; the rest are accepted readings.
18. E17-A/C/D's remaining gaps (`DdsDecisionView`'s missing `note_ru`/`comment_ru` — **fixed,
    R11/E20-E**, see item 17 above; `InstructorSessionOverview.assignments`'s correct-vs-hinted
    type; `WorldTruthView`/`CallerBeliefView`'s missing `label_ru` — **fixed, R11/E20-E**
    (`label_ru` map confirmed present on both schemas,
    `backend/app/application/instructor/get_overview.py`); the INV7 tick-ordering weakness — folded
    into §3 deviation 22; the ASSESSMENT single-stage-chain binding limit) — all either fixed by
    R11 or accepted readings with no misleading HLD text.
19. E18-A/B/C/D/E's remaining gaps (`apply_profile`'s unmapped provider-dependent fields — **fixed
    for the four R11-named ones** (`tts_device`/`tts_output_sample_rate`/`vad_device`/
    `tts_model_variant`, confirmed overlaid in `backend/app/config/profile.py`'s `_direct_mapping`)
    **and for the model-path half by R15/E20-F's `models_root` work**; `FINAL_3080TI_16GB`'s
    Chatterbox reference —
    folded into §3 deviation 1; `HealthReadyResponse.model_profile`'s enum gap — folded into §3
    deviation 19; `clearInferenceFatal` role-wording divergence — resolved ADMIN-only per that
    task's ruling, HLD text corrected by that task itself; `voice:health:fatal` payload shape —
    documented by that task itself; `MODEL_ERROR.error_kind`/`error_code` duality — resolved,
    catalog unchanged by design; `InferenceOutOfMemoryError` D2-boundary reading — resolved via
    `is_out_of_memory()` in the port; LiveKit `ListRooms` preflight — folded into §3 deviation 10;
    `recording_purge_audit.actor_type`'s missing `ADMIN` — folded into §3 deviation 20;
    `tts_qwen3.__main__`'s host bind — folded into §3's §36 row (R3, E20-A); `voice_agent.cli`'s
    prior nonexistence — resolved, file exists now; llama.cpp flag-spelling verification — resolved
    by E19-F) — all either already resolved, folded elsewhere in this document, or owned by another
    E20 worker's FILES.
20. E19-A's "THE ONE FAILURE" (a second sanctioned LiveKit importer, `headless_client.py`, versus a
    hard-coded one-file test assertion) — **resolved**: `workers/voice_agent/tests/test_transport_boundary.py`
    now defines `LIVEKIT_IMPORTERS` as a documented two-file set including `headless_client.py`
    (verified present at capture time); referenced in the §15 row above.
21. E19-B/C/D/E/F's remaining gaps (`.gitignore`'s `data/` pattern — **resolved**, current
    `.gitignore:12` reads `/data/` and `benchmarks/data/` is tracked (97 files verified); `_common.write_result`'s
    timestamp-collision risk; `ttft_ms` never populated — folded into §3 deviation 5; a `FAILED`-vs-
    `NOT_RUN` OOM wording mismatch; `make deps` lacking `--inexact` — **R4, E20-A's task, landed**
    (re-checked at hand-back: `Makefile:48` now reads `$(UV) sync --all-packages --group dev
    --inexact`, matching `deps-models`/`deps-tts-piper`/`deps-tts-qwen3`'s own discipline); a
    port-selection note; a corpus label-count
    correction; empty `hardware` field on `NOT_RUN` envelopes; the model-variant-vs-`model_version`
    fidelity gap in `Qwen3TTS`; a sampled-not-continuous VRAM peak caveat; a one-time CUDA
    kernel-autotune latency outlier) — all either accepted as honest limitations, folded into §3, or
    owned by R4/E20-A.
22. E19-F gap 2 — **fixed now, this task** (see the "(b)" list above).
23. **This epic's own phase-1 hand-back reports** (`reports/e20-{a,b,e,f}.md`, read in full for
    E20-D2) — their "HLD gaps" sections: E20-A's 5 (R1's REST/openapi self-contradiction — resolved
    by dropping the field; §7.4's per-token-vs-whole-utterance boundary — resolved, prose written;
    §7.1/§7.4's EMPTY/META_LANGUAGE boundary — resolved, prose written, numeric-only case left
    "owner to confirm"; HLD 60 §9's missing bind-host sentence — **fixed now, this task**, see the
    (b) list below; the Dockerfile comment note — **fixed now, this task**, see the (b) list
    below). E20-F's 4 (no "agent joined" event — folded into §3 deviation 23 above; HLD 20 §20.8's
    wrong lock mode — already corrected by E20-F itself; the port docstring vs. the transport's
    prior non-compliance — already corrected by E20-F itself; `VoiceEventAppender.started_at`'s
    unsafe `None` default — folded into the R11 account in the re-verification note above, still
    unwired in production, not this task's file). E20-B's and E20-E's reports name no separate
    "HLD gaps" heading; their flagged items (compose `dev-infra-up` comment, `dds-decisions-section.tsx`
    wiring) are folded into item (b) below and §3/§4 item 18 respectively.

## 5. Verification (this task)

```
uv run pytest -q backend/tests -k "doc or hld"
```
run for real (twice — once before, once after the mid-task restart): **393 passed, 3161 deselected**
both times, `2 warnings` (pre-existing `StarletteDeprecationWarning`/`DeprecationWarning`, unrelated
to this task). The keyword expression matches on substrings inside test ids/docstrings (e.g.
"document", "docstring", "handoff" contains no "hld" — the actual matches are dominated by
"document"/"doc" hits across scenario/report/schema tests), not a dedicated doc-parser suite; no
failures, no collection errors.

`make lint` was **not** re-run by this task in full (it drives the whole Python/TS toolchain across
files owned by four other concurrently-editing workers, several of them mid-edit); this task's own
edits are three Markdown files (`docs/AUDIT.md`, `docs/hld/60-inference-ops.md`,
`docs/hld/90-tbd-epics.md`), which ruff/mypy/eslint do not lint at all, so `make lint`'s Python/
frontend stages are structurally unaffected by this task's own diff.

The grep for a bare "TODO" immediately followed by an open paren and an epic letter (e.g. "E7") over
`docs/` was run for real: the only two hits are `docs/benchmarks/vram.md:17,157` — the open
multi-session-VRAM item (§3 deviation 8), legitimately dated to *this* epic and not a stale
historical marker, in a file no E20 phase-1 FILES list claims. `docs/hld/90-tbd-epics.md` itself has
**zero** such hits (its own epic-history prose was already worded, by earlier tasks, to avoid the
literal pattern — confirmed by grep, not assumed) — so the brief's exact bar ("empty except
90-tbd-epics history rows you cite") is met for every file this task owns, with one honestly-reported
exception (`docs/benchmarks/vram.md`, not this task's file, not stale) rather than a silent pass.

## 6. `docs/hld/90-tbd-epics.md` — E20 row

Updated (this task) to record artifacts and leave the §46-walk placeholder for E20-C. See that
file's E20 row: `AUDIT.md` (this document, E20-D), `DOD_WALK.md` (E20-C, **not yet written**),
`RUNBOOK.md` (E20-B, **not yet written**) are now named as the epic's deliverables, with the §46
walk's 16 PASS/FAIL verdicts left as an explicit one-line placeholder for E20-C to fill.

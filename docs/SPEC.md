<!-- The owner's specification, verbatim. Do not edit: it is the contract every epic is checked against. -->

You are implementing a production-style local emergency-response training simulator. Follow this specification literally.

DO NOT simplify the architecture unless explicitly instructed.

DO NOT replace deterministic domain logic with an LLM.

DO NOT invent alternative product requirements.

DO NOT turn this project into a chatbot.

DO NOT auto-fill trainee actions.

DO NOT merge Ground Truth, Caller Knowledge, Operator Card, DDS State, or Scoring State.

If something has not yet been implemented, leave a clearly defined interface/TODO and continue implementing the specified architecture. Never silently delete a requirement because it is difficult.

# 1. PRODUCT

The product is a local AI-powered training and assessment simulator for emergency-response personnel.

A simulation is one persistent incident that may pass through several professional roles:

1. Operator 112.
2. Profile DDS dispatcher.
3. Optional later EDDS/coordinator role.

The same Incident object MUST survive all role transitions.

This is NOT three independent exercises.

Supported session modes must be represented architecturally:

- SINGLE_ROLE
- FULL_CYCLE_SINGLE_TRAINEE
- MULTI_TRAINEE
- ASSESSMENT

The primary implemented flow is:

incoming emergency call
→ Operator 112 interview
→ trainee manually fills incident card
→ trainee selects recipients/services
→ immutable handoff
→ DDS receives exactly that card
→ DDS dispatches/manages resources
→ simulated incident develops
→ incident closes
→ deterministic post-session assessment.

# 2. NON-NEGOTIABLE ARCHITECTURAL INVARIANT

The LLM IS NOT the simulation.

The canonical simulation state is deterministic Python/domain state.

The LLM is only allowed to:

- interpret natural-language operator utterances;
- produce natural caller wording from explicitly provided facts;
- optionally explain already-computed scoring results.

The LLM MUST NOT:

- create incident truth;
- decide what services are objectively required;
- change incident state directly;
- calculate numeric scores;
- know hidden facts that the caller does not know;
- fill the trainee's incident card;
- invent resources;
- skip workflow states;
- complete trainee actions automatically.

# 3. FOUR SEPARATE INFORMATION LAYERS

Implement these as separate models and storage concepts.

A. WorldTruth
What objectively exists in the simulated incident.

B. CallerBelief
What the simulated caller believes/knows.

C. OperatorCard
What the trainee actually entered.

D. DDSReceivedSnapshot
The immutable information actually sent to DDS.

Never alias these structures.

Never automatically synchronize them.

Example:

WorldTruth.house = "27"
CallerBelief.house = "27"
OperatorCard.house = "72"
DDSReceivedSnapshot.house = "72"

DDS MUST receive "72".

It MUST NOT obtain "27" from WorldTruth.

# 4. SCENARIO VERSIONING

Scenario and ScenarioVersion must be separate.

A ScenarioVersion becomes immutable as soon as a simulation starts using it.

Every SimulationSession references an exact ScenarioVersion.

Required conceptual structure:

ScenarioVersion
- id
- schema_version
- scenario_id
- version
- title
- description
- difficulty
- deterministic_seed
- role_chain
- world_truth
- caller_profile
- caller_knowledge
- disclosure_rules
- expected_response
- available_resources
- world_events
- scoring_rules

Use Pydantic models and validate scenario files before a simulation can start.

Scenario source files must be YAML or JSON and version-controlled.

# 5. FACT MODEL

Facts cannot simply be key/value pairs.

Each caller-related fact must support:

- fact_id
- world_value
- caller_value
- knowledge state
- certainty
- disclosure policy
- aliases/semantic categories if needed

Knowledge states:

- KNOWN
- UNKNOWN
- INCORRECT_BELIEF
- UNCERTAIN

Disclosure policies:

- SPONTANEOUS
- ON_ASK
- ONLY_IF_EXPLICITLY_ASKED
- NEVER_DISCLOSE

Example:

people.victim_01.inside:
    world_value: true
    caller_value: true
    knowledge: KNOWN
    disclosure: ONLY_IF_EXPLICITLY_ASKED

incident.fire_source:
    world_value: KITCHEN
    caller_value: null
    knowledge: UNKNOWN
    disclosure: NEVER_DISCLOSE

If the trainee asks about fire_source, the caller must say that they do not know.

The caller must never receive KITCHEN in its LLM context.

# 6. CALLER PROFILE

Implement a structured caller profile containing at least:

- identity
- relationship to incident
- language
- voice_id
- age_group
- baseline_emotion
- current_emotion
- cooperativeness
- verbosity
- confusion
- interruption tendency
- speaking rate
- stress level

Emotion is part of simulation state and may change deterministically in response to events/actions.

Do not let the LLM freely redefine the persona.

# 7. SIMULATION STATE MACHINE

Implement an explicit state machine.

Top-level session states:

CREATED
READY
ACTIVE
ROLE_TRANSITION
COMPLETED
ABORTED

Operator 112 stage should support at least:

WAITING_FOR_CALL
RINGING
CONNECTED
INTERVIEW
HANDOFF_PREPARATION
HANDED_OFF
STAGE_COMPLETED

DDS stage should support at least:

RECEIVED
ACKNOWLEDGED
RESOURCE_SELECTION
DISPATCHED
EN_ROUTE
ARRIVED
WORKING
RESOLVED
CLOSED

Invalid transitions MUST be rejected by backend domain logic.

The frontend must never be authoritative for workflow transitions.

# 8. EVENT-SOURCED AUDIT LOG

Every meaningful user, model, and simulation action MUST emit an immutable SessionEvent.

SessionEvent fields:

- id: UUID
- session_id
- seq_no
- event_type
- timestamp_utc
- monotonic_offset_ms
- actor_type
- actor_id nullable
- correlation_id nullable
- payload JSON

Include event types for at least:

SESSION_CREATED
SESSION_STARTED
ROLE_STAGE_STARTED
CALL_RINGING
CALL_ANSWERED
USER_SPEECH_STARTED
USER_SPEECH_ENDED
ASR_PARTIAL
ASR_FINAL
CALLER_RESPONSE_PLANNED
CALLER_RESPONSE_GENERATED
CALLER_TTS_STARTED
CALLER_TTS_ENDED
CALLER_UTTERANCE_INTERRUPTED
CARD_FIELD_CHANGED
SERVICE_SELECTED
HANDOFF_CREATED
HANDOFF_RECEIVED
DDS_ACKNOWLEDGED
RESOURCE_SELECTED
RESOURCE_DISPATCHED
RESOURCE_STATUS_CHANGED
WORLD_EVENT_TRIGGERED
ROLE_STAGE_COMPLETED
SCORING_RULE_EVALUATED
SESSION_COMPLETED
MODEL_FALLBACK_USED
MODEL_ERROR

Do not overwrite events.

Current state may be materialized for efficient reads, but the event log must remain the audit source.

# 9. OPERATOR CARD

The trainee manually edits the incident card.

ASR MUST NOT auto-fill fields in assessment/training mode.

Every field mutation must be stored.

Store:

- previous value
- new value
- field path
- event timestamp
- actor

This enables reconstruction of when and how values changed.

The final card is NOT enough.

# 10. HANDOFF

When the trainee sends information to DDS:

1. Validate allowed workflow state.
2. Create an immutable HandoffSnapshot.
3. Freeze exactly the trainee-entered information.
4. Record selected recipient services.
5. Emit HANDOFF_CREATED.
6. Create the DDS work item from the snapshot.

DDS must not query WorldTruth for missing operator-card information.

If the 112 operator omitted a critical fact, the omission propagates.

# 11. DDS SIMULATION

DDS is not a static second form.

Implement:

- incoming work item;
- acknowledgment;
- available resources;
- resource capabilities;
- resource states;
- dispatch actions;
- ETA/travel-time metadata;
- status changes;
- incident updates;
- closure.

EmergencyResource must include at minimum:

- id
- service_type
- resource_type
- callsign/name
- capabilities
- current_status
- scenario-defined availability
- scenario-defined ETA/travel-time data

For the hackathon/demo, ETAs may be scenario-defined or computed by a local deterministic module.

Do not depend on an external online maps API for core operation.

# 12. WORLD EVENT ENGINE

The simulated world continues evolving after the initial call.

Implement event types:

- TimedEvent
- ConditionalEvent
- ActionTriggeredEvent
- SeededRandomEvent

All randomized behavior must use the session seed so runs can be reproduced.

A WorldEvent may:

- mutate WorldTruth;
- mutate CallerBelief if the caller could observe the change;
- create a notification;
- create a radio/status update;
- alter resource availability;
- trigger another event.

The LLM must not schedule world events.

# 13. FULL-CYCLE MODE

A full-cycle session uses one:

SimulationSession
Incident
ScenarioVersion
event timeline

Role changes do not create a new incident.

FULL_CYCLE_SINGLE_TRAINEE behavior:

Operator 112 stage
→ stage completion
→ configurable pause/transition
→ DDS UI
→ same incident and transferred card
→ DDS stage
→ final report.

MULTI_TRAINEE uses the same backend model, but different participants are assigned different RoleStages.

# 14. EDDS EXTENSION

Architect the role system so EDDS can be added as another RoleModule.

Do not implement a large EDDS subsystem unless explicitly requested.

Define the extension interface now.

A RoleModule should define:

- role_type
- permissions
- available actions
- state machine
- data visibility policy
- UI capabilities/schema if needed

DDS and Operator112 must use the same role abstraction where reasonable.

# 15. VOICE TRANSPORT

Use self-hosted LiveKit for realtime audio.

Do not implement a custom WebRTC stack.

Frontend sends/receives realtime audio through LiveKit.

The architecture must define a CallTransport abstraction so LiveKit can later be complemented by SIP/real telephony.

Core simulation/domain logic must not import LiveKit-specific objects.

Possible future implementation:

LiveKit WebRTC
→ LiveKit SIP
→ PSTN

No actual PSTN integration is required for the initial demo.

# 16. VOICE AGENT PIPELINE

Required pipeline:

LiveKit audio
→ resample/normalize
→ VAD
→ ASR
→ semantic dialogue interpretation
→ deterministic Fact Access Gate
→ caller-response generation
→ response validation
→ streaming TTS
→ LiveKit audio.

Do not collapse Fact Access Gate into the LLM.

# 17. VAD AND TURN-TAKING

Implement proper realtime turn handling.

Requirements:

- configurable speech-start threshold;
- configurable endpoint silence duration;
- pre-roll audio buffer so word beginnings are not lost;
- separate USER_SPEECH_STARTED and USER_SPEECH_ENDED events;
- partial ASR may be displayed;
- caller response begins only from finalized turn unless explicitly designed otherwise.

Initial endpoint target:
250–350 ms of silence.

Make this configuration, not a hard-coded magic value.

# 18. BARGE-IN

Barge-in is mandatory.

If AI speech is currently playing and trainee speech is detected:

1. confirm sustained trainee speech;
2. cancel current TTS generation where possible;
3. clear queued outbound audio;
4. stop playback quickly;
5. emit CALLER_UTTERANCE_INTERRUPTED;
6. preserve how much of caller text/audio was actually delivered;
7. process trainee speech normally.

Acceptance target:
speech onset to caller audio cutoff <250 ms.

Do not implement TTS as one complete WAV file that cannot be interrupted.

# 19. ASR ABSTRACTION

Define:

ASRProvider.transcribe(...)
ASRProvider.stream(...) if supported.

Primary candidate:
GigaAM v3_e2e_ctc.

Also benchmark:
GigaAM v3_ctc.

Optional fallback:
faster-whisper.

Do not make downstream domain code depend on a specific ASR model.

Store TranscriptSegment with:

- id
- speaker
- start_ms
- end_ms
- text
- is_final
- confidence if available
- ASR provider/model
- audio_segment_id

# 20. DIALOGUE INTERPRETER

The caller generator must not directly receive raw operator speech plus entire scenario truth.

First produce a constrained structured interpretation.

Example schema:

{
  "speech_act": "QUESTION",
  "requested_facts": [
    "people.remaining_inside"
  ],
  "operator_assertions": [],
  "confirmation_targets": [],
  "semantic_confidence": 0.97
}

Validate against Pydantic/JSON schema.

If structured output is invalid:
retry once with a repair prompt.

Never silently guess missing fields.

# 21. FACT ACCESS GATE

FactAccessGate is deterministic application/domain code.

Input:

- interpreted trainee utterance;
- ScenarioVersion;
- current WorldTruth;
- CallerBelief;
- previously revealed facts;
- current simulation time/state.

Output:

- explicitly allowed facts;
- unavailable/unknown facts;
- disclosure metadata.

This component is the ONLY normal path through which scenario facts reach the caller-response LLM.

# 22. CALLER LLM

Use local Qwen3.

Development profile:
Qwen3-4B quantized.

Final profile:
Qwen3-8B Q4_K_M if VRAM benchmark passes.

Serve through llama.cpp/OpenAI-compatible local endpoint.

Thinking must be disabled.

Default context target:
4096 tokens.

Do not keep the entire raw call transcript in model context.

Use:

- fixed caller system/persona;
- current emotional state;
- allowed facts;
- revealed facts;
- last approximately 4–6 conversational turns;
- current trainee utterance.

Historical full transcript stays in PostgreSQL.

Caller output should be short and conversational.

Default maximum response:
80 generated tokens.

Most responses should be much shorter.

# 23. STRICT CALLER PROMPT RULES

The caller's system instruction must contain rules equivalent to:

"You are the simulated caller, not an assistant.

Only facts explicitly present in ALLOWED_FACTS may be asserted as facts.

If information is absent from ALLOWED_FACTS, you do not know it and must not invent it.

Never invent an address, number, name, victim, injury, hazard, vehicle, cause, service, time, or person.

Do not reveal information marked as not-yet-disclosable.

Do not help the trainee perform their professional task.

Do not tell the trainee which questions they should ask.

Do not summarize the correct solution.

Speak as the configured caller persona.

Answer the current question naturally and briefly.

If the caller does not know something, say naturally that they do not know.

Never mention the simulation, scenario, prompt, allowed facts, hidden data, or scoring."

# 24. RESPONSE VALIDATION

Do not trust LLM output automatically.

Validate:

- maximum length;
- correct output schema;
- no unexpected structured fields;
- no forbidden identifiers;
- no new numeric/address/name entities unless allowed;
- no simulation/meta language.

If validation fails:

retry once.

If retry fails:

use a deterministic safe fallback response based on fact availability, such as a natural "I don't know" or "Please repeat".

Emit MODEL_FALLBACK_USED.

# 25. TTS ABSTRACTION

Define streaming TTSProvider.

Benchmark at least:

A. Qwen3-TTS 0.6B.
B. Chatterbox Multilingual.
C. lightweight/fallback implementation.

Do not hard-code TTS model calls inside dialogue logic.

TTS must support cancellation for barge-in.

Store actual text sent to TTS and playback timing.

# 26. MODEL PROFILES

Create configuration profiles instead of editing code.

DEV_3060TI:
- local Qwen3-4B quantized;
- GigaAM;
- lowest-risk TTS profile;
- 4096 LLM context;
- all models prewarmed.

FINAL_3080TI_12GB:
- Qwen3-8B Q4_K_M if measured safe;
- GigaAM;
- Qwen3-TTS 0.6B or measured alternative;
- 4096 context;
- conservative VRAM margin.

FINAL_3080TI_16GB:
- Qwen3-8B Q4_K_M;
- GigaAM;
- Qwen3-TTS 0.6B or Chatterbox;
- 4096 context initially.

Never choose a profile whose measured peak VRAM leaves essentially zero safety margin.

# 27. LATENCY TELEMETRY

Record latency for every inference turn.

InferenceMetric must support:

- model/provider
- model version
- request id
- session id
- input duration/tokens
- output tokens/audio duration
- start timestamp
- first-output timestamp
- finish timestamp
- TTFT
- total latency
- tokens per second
- realtime factor where relevant
- GPU memory measurement if available
- fallback/retry count

Critical product metric:

USER_SPEECH_ENDED
→
first audible caller audio.

Target:

final demo p50 < 1.2 seconds
final demo p95 < 2.0 seconds

development acceptable target:

p50 < 1.5 seconds
p95 < 2.5 seconds.

Do not fake or hard-code benchmark values.

# 28. SCORING

Numeric scoring is deterministic.

The LLM must never assign points.

ScoringRule supports:

- id
- name
- description
- category
- max_points
- critical flag
- evaluator type
- evaluator configuration
- evidence requirements

Required evaluator concepts include:

- FACT_OBTAINED
- CARD_FIELD_CORRECT
- CARD_FIELD_PRESENT
- CARD_CONTRADICTION
- SERVICE_SELECTION
- DEADLINE
- WORKFLOW_ACTION
- RESOURCE_SELECTION
- REQUIRED_STATUS_UPDATE
- HANDOFF_COMPLETENESS

Each ScoreResult must contain ScoreEvidence pointing to concrete events/card snapshots.

The same event log and scenario version must always reproduce the same score.

# 29. POST-SESSION REPORT

Build a real report UI.

Must contain:

- total score;
- score by category;
- critical errors;
- complete event timeline;
- transcript;
- audio playback;
- click transcript → seek to audio;
- card final state;
- ground-truth vs entered-card diff;
- handoff snapshot;
- DDS decisions;
- resource timeline;
- timing metrics;
- evidence for every scoring rule.

LLM-generated explanation may be displayed only after deterministic scores exist.

It may not alter numeric results.

# 30. DATABASE

Use PostgreSQL.

Use SQLAlchemy 2 + Alembic.

Core tables/entities:

users
scenarios
scenario_versions
simulation_sessions
session_participants
role_stages
incidents
incident_cards
incident_card_revisions
handoff_snapshots
dds_assignments
emergency_resources
resource_state_changes
session_events
transcript_segments
audio_segments
scoring_rules
score_results
score_evidence
inference_metrics

Use UUID primary keys where appropriate.

Use proper foreign keys and indexes.

Do not replace the relational model with a generic JSON document store.

JSONB is allowed for versioned/configurable payload portions, but relational identity and references must remain explicit.

# 31. REDIS

Redis is allowed for:

- pub/sub;
- transient realtime state;
- locks;
- cancellation signals;
- LiveKit requirements where applicable.

PostgreSQL remains authoritative.

Do not make Redis the permanent source of truth.

# 32. FRONTEND

Use:

- React
- TypeScript
- Vite
- TanStack Query
- Zustand for local realtime/UI state
- Tailwind CSS
- shadcn/ui
- LiveKit client SDK

Primary route groups:

/operator
/dds
/instructor
/report

Do not create four unrelated frontend projects.

The role interface must look like professional operational software, not a chatbot.

The caller's dialogue should primarily be experienced as a phone call, not as a giant chat window.

A transcript may exist as a secondary panel.

# 33. BACKEND

Use Python with:

- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- asyncio
- PostgreSQL
- Redis

Keep business/domain logic outside HTTP route handlers.

Use layers roughly equivalent to:

domain/
application/
api/
infrastructure/
inference/

Domain code must not import FastAPI, React, LiveKit, or SQLAlchemy ORM-specific behavior where avoidable.

# 34. REALTIME API

Use LiveKit for realtime media.

Use WebSocket/SSE/backend realtime channel for application events where appropriate.

Do not tunnel raw microphone PCM through ordinary REST endpoints.

REST endpoints handle commands/resources.

Realtime channels handle ongoing session updates.

# 35. PROJECT STRUCTURE

Use a structure comparable to:

frontend/
    src/
        app/
        features/
        entities/
        shared/

backend/
    app/
        api/
        domain/
        application/
        infrastructure/
        inference/
        db/
        config/
    tests/

workers/
    voice_agent/

scenarios/
    schemas/
    examples/

benchmarks/
    benchmark_asr.py
    benchmark_llm.py
    benchmark_tts.py
    benchmark_e2e.py
    benchmark_vram.py

infra/
    docker-compose.yml
    livekit/
    scripts/

docs/

Do not put all business logic in app.py or route files.

# 36. DEPLOYMENT

Use Docker Compose for the current product/demo.

Expected logical services:

postgres
redis
livekit
backend
frontend
llama-server
voice-agent

Do not introduce Kubernetes.

Do not introduce Kafka unless a concrete requirement later proves Redis/application messaging insufficient.

# 37. MODEL WARM-UP

Before a training session can start, inference services must be warm.

Run:

- short dummy ASR;
- tiny LLM generation;
- tiny TTS generation.

Expose readiness separately from process liveness.

The UI must not allow a final demo session to begin while a required inference service reports not-ready.

# 38. PREFLIGHT

Create a preflight command/script.

It must verify:

- CUDA/GPU available;
- expected GPU detected;
- required model files exist;
- LLM responds;
- ASR responds;
- TTS responds;
- PostgreSQL responds;
- Redis responds;
- LiveKit responds;
- scenario validation passes;
- configured audio devices can be accessed where relevant.

Return explicit pass/fail results.

# 39. RESILIENCE

Required behavior:

Browser refresh:
restore active session.

TTS failure:
log failure and use configured fallback.

Invalid LLM structured output:
one repair retry, then safe fallback.

ASR failure:
do not corrupt state.

LiveKit temporary reconnect:
session/domain state survives.

GPU OOM:
surface a fatal inference health error and preserve session state.

Never silently reset the simulation.

# 40. BENCHMARKS

Implement real benchmark scripts.

ASR benchmark:
- several utterance lengths;
- clean/noisy samples;
- addresses;
- numbers;
- emergency terminology;
- latency;
- RTF;
- transcription accuracy.

LLM benchmark:
- TTFT;
- output tokens/s;
- structured-output validity;
- forbidden-fact hallucination rate;
- dialogue consistency.

TTS benchmark:
- first-audio latency;
- total synthesis latency;
- RTF;
- peak VRAM;
- cancellation behavior.

E2E benchmark:
measure precisely from USER_SPEECH_ENDED to first emitted/played caller audio.

VRAM benchmark:
measure idle model residency and peak during a realistic sequence.

Export benchmark results to JSON/CSV.

# 41. SECURITY / LOCAL OPERATION

Core demo must work without external AI APIs.

No OpenAI/Anthropic/etc API is allowed in the runtime path.

Keep recordings, transcripts, cards, scoring and models local.

Define configurable retention/deletion of recordings.

Secrets/configuration belong in environment/config files, not source code.

# 42. TESTS — REQUIRED INVARIANTS

Write automated tests proving at minimum:

1. Caller LLM never receives a WorldTruth fact unavailable to CallerBelief.
2. Unknown caller facts do not become concrete answers.
3. DDS cannot read hidden WorldTruth to repair an incomplete handoff.
4. The operator card is not auto-filled from ASR.
5. Full-cycle role transition retains the same Incident.
6. ScenarioVersion cannot change during a running session.
7. Identical seed and actions produce identical deterministic world events.
8. Invalid state-machine transitions fail.
9. Scoring is reproducible without an LLM.
10. Rewording caller dialogue does not modify factual scoring.
11. Every scoring point/penalty has evidence.
12. Barge-in cancels queued caller audio.
13. Refresh does not lose active incident state.
14. Model failure does not erase simulation data.

# 43. HALLUCINATION / INFORMATION-LEAK TEST SUITE

Create an automated adversarial test.

Generate many operator questions requesting:

- facts the caller knows;
- facts the caller does not know;
- incorrect assumptions;
- leading questions;
- numeric values;
- addresses;
- names;
- hazards;
- victims;
- causes.

Verify that the caller never asserts scenario facts that were not present in the allowed-facts package for that turn.

Track:

forbidden_fact_leak_rate

Target for the deterministic/context boundary:
0.

If an LLM invents a new factual entity, response validation must reject or regenerate it.

# 44. PERFORMANCE RULES

Do not optimize by violating architecture.

Never:

- expose all scenario truth to the LLM to save one lookup;
- skip response validation;
- auto-fill fields;
- remove event logging;
- merge role states;
- omit immutable handoff;
- let DDS access perfect information;
- use the LLM as scoring engine.

Prefer a smaller/faster model over removing safety/state boundaries.

# 45. IMPLEMENTATION ORDER

Implement in this dependency order.

Phase A:
project skeleton, DB, domain models, ScenarioVersion validation, SessionEvent.

Phase B:
simulation state machine, scenario runtime, deterministic WorldEvent engine.

Phase C:
Operator 112 UI, manual card, card revisions, service selection.

Phase D:
handoff snapshot and DDS UI/state machine/resources.

Phase E:
LiveKit voice transport and turn management.

Phase F:
VAD + ASR.

Phase G:
Dialogue Interpreter + Fact Access Gate + local caller LLM.

Phase H:
streaming/cancellable TTS + barge-in.

Phase I:
deterministic scoring and evidence.

Phase J:
post-session report/replay.

Phase K:
full-cycle transitions and multi-role session modes.

Phase L:
benchmarking, GPU profiles, resilience and demo hardening.

Do not start by building a polished chat UI.

Do not start by asking an LLM to generate an entire scenario at runtime.

# 46. DEFINITION OF DONE

The primary demo scenario is considered complete only when a person can:

1. start an incident;
2. receive a realistic incoming call;
3. talk naturally with an AI caller;
4. interrupt the caller;
5. obtain information only by asking appropriate questions;
6. manually fill a 112 incident card;
7. make mistakes that remain real mistakes;
8. select services and send the card;
9. move into the DDS stage;
10. receive exactly the submitted information;
11. choose and dispatch resources;
12. respond to evolving incident events;
13. close the incident;
14. receive a deterministic evidence-backed assessment;
15. replay the timeline, transcript and relevant audio;
16. see model/inference latency metrics.

If any of these is replaced by a hard-coded fake UI animation, the implementation is incomplete.

# 47. WHEN YOU WRITE CODE

Before each implementation step:

1. State which requirement numbers you are implementing.
2. Identify affected domain models/interfaces.
3. Implement the complete vertical slice.
4. Add/update migrations.
5. Add tests.
6. Run tests.
7. Do not remove existing behavior to make tests pass.
8. Report any unimplemented requirement explicitly.

If a requirement seems complex, implement it incrementally behind the correct interface. Do NOT replace it with an easier different feature.

Whenever there is a choice between:
"smaller implementation preserving the architecture"
and
"easier implementation changing the architecture",

always choose the first.

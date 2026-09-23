# HLD 70 — I3: aligning the simulator with the organizer's requirements

Elaborates `docs/hld/00-decisions.md` D14–D20 (appended by this epic, H1) against the organizer
material digested under `requirements/` (the traceable matrices in `requirements/normalized/*.md`, the
assessment `requirements/assessments/2026-09-23-requirements-vs-product.md`). The design follows the
read-only H1 analysis the manager accepted in full; every place where this document departs from that
analysis's wording is listed in §70.13 with the reason.

Nothing here edits HLD 10/20/30/40 or `openapi.yaml`. Those documents are parsed by tests
(`test_dds_tables_match_the_hld.py`, `test_gate_matches_the_hld.py`,
`test_visibility_matches_protocol_table.py`, `tests/api/test_contract.py`); **each implementing epic
updates them together with its code**, copying identifiers from this file literally. The contract delta
is `docs/hld/contracts/i3-openapi-delta.yaml`; the schemes are `docs/hld/puml/i3-*.puml`; the epic list
is the "I3 TBD epics" section of `docs/hld/90-tbd-epics.md`.

Language rule unchanged (header of 00): identifiers English; trainee-facing labels Russian.

## 70.0 The five forks in one table

| Fork | Decision | Decision entry | Section |
|:--|:--|:--|:--|
| F1 | Typed `SessionVariants`: the scenario declares *supported + default*, session creation *selects*, `SESSION_CREATED` *records*; scoring rules gain `applies_to_variants`. Scenario `schema_version: 2`. | D14 | §70.2 |
| F2 | `uq_incidents_session` and SPEC §1/§13 kept. A **Lesson** (занятие) owns N ordinary sessions started by a `LessonRunner` per `scenario_plan` arrivals; per-card timers are scenario data in session ms; consequences are SIMULATION-authored, deadline-stamped `DDS_CARD_STATUS_CHANGED` events. | D15 | §70.3 |
| F3 | A per-leg (`DDSAssignment`) `ServiceResponseStatus` machine in the memo vocabulary; `DDSStageState` unchanged, `DDS_TRANSITIONS` gains one memo-only closure row, guards and available actions variant-aware; card statuses are a derived projection; several ДДС trainees = participant→service binding in the one DDS stage. | D16 | §70.4 |
| F4 | The 112 card schema is versioned data (`reference/card-schema/v1.yaml` = today's 38 `CARD_FIELDS`, `v2.yaml` from the organizer docx), same `field_path`s for existing fields, questionnaire via `visible_when` + option lists, served through `field_specs`. | D17 | §70.5 |
| F5 | Classifier v_046_24 and «СЛУЖБЫ 112» as sha-pinned data generated from the source xlsx/docx; `ServiceType` → `ServiceId = str` keeping the six ids verbatim; routing is a pure resolver recorded as `RECIPIENTS_RESOLVED`, never a SYSTEM write into the card; 112 may add, never remove, under schema v2. F4 and F5 share one reference pack. | D18 | §70.6 |

## 70.1 Principles and the invariants kept

Principles (from the analysis, binding on every I3 epic):

- **P1 Additive over structural.** Every SPEC list that says "at least" (§7 states, §8 events, §28
  evaluators) is extended, never replaced; every DB change is a new column/table or a dropped CHECK.
- **P2 The event log stays self-sufficient for scoring.** Reference data (card schema, classifier,
  service catalog) is a command-time validator and a rendering spec, never a scoring input.
- **P3 The DDS reads only snapshot + legs.** New DDS data (statuses, history, card status) lives on
  legs and their history, both derived from the snapshot's `recipient_services`.
- **P4 Variants are recorded, not looked up.** Whatever a switch does is reproducible from `SESSION_CREATED`.
- **P5 Existing scenarios load and score unchanged** under every epic: schema 1 stays supported, the
  six legacy service ids stay valid, existing card paths stay.

| Invariant | What it says | How I3 keeps it | Proven by (existing test + what the epic adds) |
|:--|:--|:--|:--|
| INV 3 | DDS cannot read hidden WorldTruth (SPEC §42.3) | Legs, leg history and card status derive from the snapshot and DDS-side events only. Scripted responders read `expected_response.responders` inside **stage automation** (runner side, which already reads `resolution_condition`), never inside a DDS command or read service; DDS services stay constructed without a WorldTruth repository **and** without the `ScenarioVersion`. The DDS `field_specs` come from the reference pack, not the scenario. With `dds_card_check: ON` the ДДС flags issues against the snapshot; the comparison to truth happens only in scoring. | `tests/invariants/test_inv_03_dds_never_reads_world_truth.py`; E5 adds the constructor-signature assertion for `SetServiceStatusUseCase`, `OpenDdsCardUseCase`, `FlagCardIssueUseCase` |
| INV 4 | The card is not auto-filled from ASR (SPEC §42.4) | The routing resolver writes **no** card value: `RECIPIENTS_RESOLVED` is an event; `incident_card_revisions.actor_type` stays CHECK-limited to `TRAINEE`/`INSTRUCTOR` (`backend/app/db/models/layers.py`); `recipients.services` holds only what the trainee added. GENERATED_CARD sessions materialise the prefab exactly as `[DDS]` chains do today (`backend/app/application/handoff/prefab_handoff.py`). | `tests/invariants/test_inv_04_asr_never_mutates_card.py`; E2 adds "setCardField on a routing path appends `CARD_FIELD_CHANGED` + `RECIPIENTS_RESOLVED` and the card's revision set is unchanged by the second" |
| INV 5 | Full-cycle keeps the same Incident (SPEC §42.5) | `uq_incidents_session` (`backend/app/db/models/session.py:161`) kept; a card stream is N sessions of a lesson, each one incident, one timeline. | `tests/invariants/test_inv_05_full_cycle_same_incident_one_timeline.py` unchanged; E4 adds "a lesson of 3 cards = 3 sessions × 1 incident" |
| INV 7 | Same seed + actions ⇒ same world events | Variants, resolved timers and reference-pack shas are in `SESSION_CREATED`; deadline events are stamped with the deadline offset under the **flush-before-append** rule (§70.3.5); scripted-responder schedules are a pure function of `HANDOFF_RECEIVED` offsets and scenario data; a lesson's wall-clock arrival decides only *when* a session starts, never its internal stream. | `tests/invariants/test_inv_07_deterministic_world_events.py`; E4/E5 add a tick-rate independence case (tick 100 ms vs 900 ms ⇒ identical `DDS_CARD_STATUS_CHANGED` / scripted `DDS_SERVICE_STATUS_SET` streams) |
| INV 8 | Invalid transitions fail | Two new table-driven machines (`SERVICE_RESPONSE_TRANSITIONS`, `LESSON_TRANSITIONS`) join the table-driven INV 8 expectations; `DDS_TRANSITIONS` gains exactly one additive row (`ACKNOWLEDGED --close--> RESOLVED`, guard `memo_all_legs_terminal`, §70.4.4), allowed only in memo mode. | `tests/invariants/test_inv_08_invalid_transitions.py` extended by E4 (lesson) and E5 (leg machine) |
| INV 13 | Refresh does not lose state | Per session unchanged (REST snapshot + WS resume). Lesson list = REST (`GET /lessons/{id}`, `GET /incidents`) + one existing per-session socket per active card. `incidents.card_status` and `dds_service_status_history` are materialised in the same UoW as their events. | `tests/invariants/test_inv_13_refresh_restores_state.py`; E4/E5 add list + leg-history refresh cases |
| D3 | Four layers, four types, one writer each | No new writer to `OperatorCard`; reference data is not a layer; leg status is DDS-side state, not a copy of the card. | the D3 deep-copy tests (E3 of I1) unchanged |
| D5 | Append-only log, scoring reads only `(ScenarioVersion, events)` | Every new payload is self-sufficient (§70.7); `dds_service_status_history`, `incidents.card_status`, `lessons` are read models; `score()` never reads them. | `test_inv_09_*`, `test_inv_11_every_point_has_evidence.py`; E5 adds a rescore-equality case for a memo-mode session |

## 70.2 F1 — Variant switches

### 70.2.1 Types — `backend/app/domain/session/variants.py` (new)

```python
class CardSource(str, Enum):
    GENERATED_CARD = "GENERATED_CARD"   # no caller: the card arrives generated (prefab); chain starts at DDS
    CALLER_VOICE = "CALLER_VOICE"       # today's AI-voiced caller + 112 interview; FROZEN, kept (owner)

class DdsMode(str, Enum):
    MEMO_STATUSES = "MEMO_STATUSES"     # per-service statuses of the ДДС memo (F3) — exists from E5
    RESOURCE_PICKER = "RESOURCE_PICKER" # today's resource board + dispatch

class DdsCardCheck(str, Enum):
    OFF = "OFF"                         # ДДС does not check the 112 card (customer 23.09, REQ-5915)
    ON = "ON"                           # ДДС may flag card issues (msg638 reading) — exists from E5

class DdsBrigadeCall(str, Enum):
    OFF = "OFF"
    ON = "ON"                           # ДДС ↔ brigade voice call — exists from H2/E6

class SessionVariants(BaseModel):       # model_config = ConfigDict(frozen=True, extra="forbid")
    card_source: CardSource
    dds_mode: DdsMode
    dds_card_check: DdsCardCheck
    dds_brigade_call: DdsBrigadeCall

class VariantSupport(BaseModel):        # frozen, extra="forbid"; every tuple non-empty
    card_source: tuple[CardSource, ...]
    dds_mode: tuple[DdsMode, ...]
    dds_card_check: tuple[DdsCardCheck, ...]
    dds_brigade_call: tuple[DdsBrigadeCall, ...]

class ScenarioVariants(BaseModel):      # the schema-2 scenario key `variants`
    supported: VariantSupport
    default: SessionVariants

PRODUCT_DEFAULT_VARIANTS: SessionVariants        # the switch matrix, §70.11 ("product default")
IMPLEMENTED_VARIANT_VALUES: Mapping[str, frozenset[str]]   # grows per epic; E1: see §70.11
def resolve_variants(requested: PartialVariants, scenario: ScenarioVariants,
                     implemented: Mapping[str, frozenset[str]]) -> SessionVariants: ...
```

### 70.2.2 The three homes and their precedence (no fourth)

1. **Scenario** — schema 2 top-level key `variants: {supported: …, default: …}`. A schema-1 document has
   no key; its `ScenarioVariants` is **derived** (P5):
   `card_source` supported = `CALLER_VOICE` iff `OPERATOR_112 ∈ role_chain`, `GENERATED_CARD` iff
   `expected_response.prefab_handoff` present; derived default = `CALLER_VOICE` when supported (today's
   behaviour), else `GENERATED_CARD`. `dds_mode` supported = `{RESOURCE_PICKER}` (schema-1 documents
   have no responders section), default `RESOURCE_PICKER` **also after E5** — the E5 default flip applies
   to schema-2 documents only, so every schema-1 session behaves exactly as today. `dds_card_check`
   supported `{OFF, ON}`, default `OFF`; `dds_brigade_call` supported `{OFF}`.
   A schema-2 document that omits `variants` gets the same derivation with `PRODUCT_DEFAULT_VARIANTS`
   as default where the derived support allows it.
2. **Session creation** — `SessionCreateRequest.variants` (every field optional). Resolution per switch:
   request value → scenario default → product default. A value not in the scenario's `supported` ⇒
   `409 VARIANT_NOT_SUPPORTED`; a value outside `IMPLEMENTED_VARIANT_VALUES` ⇒ `409 VARIANT_NOT_AVAILABLE`
   (checked first, so an unimplemented value never reaches content validation). Deployment settings may
   only *remove* `dds_brigade_call: ON` when no telephony transport is configured; they never change
   semantics.
3. **The record** — the resolved `SessionVariants` goes into `SESSION_CREATED.variants` (additive) and
   into `simulation_sessions.variants jsonb` (materialised copy, like `time_scale`). Immutable after
   creation; no mid-session switching.

### 70.2.3 Scenario validation rules (HLD 30 §30.8 continues at 32 — rule 31 exists)

| Rule | Check |
|:--|:--|
| R01 (extended) | `schema_version ∈ {1, 2}` (`SUPPORTED_SCHEMA_VERSIONS`, `backend/app/domain/scenario/version.py`); a key introduced by schema 2 (`variants`, `timers`, `reference_pack`, `expected_response.responders`) in a schema-1 document is refused. |
| R32 | `variants.default` ∈ `variants.supported`, every `supported` tuple non-empty and duplicate-free. |
| R33 | `CALLER_VOICE` supported ⇒ `OPERATOR_112 ∈ role_chain` and the three fact sections non-empty. |
| R34 | `GENERATED_CARD` supported ⇒ `expected_response.prefab_handoff` present (rule 29's check, reached through the variant). |
| R35 | `RESOURCE_PICKER` supported ⇒ `available_resources` non-empty and `resolution_condition` present. |
| R36 | `MEMO_STATUSES` supported ⇒ `expected_response.responders` present **or** the key `responders: DEFAULT` written explicitly (E5). |
| R37 | Every service id in `expected_response.*`, `available_resources[*].service_type`, `prefab_handoff.recipient_services`, `responders` keys and `SERVICE_SELECTION` configs exists in the pack's service catalog (E2; replaces the enum check). |
| R38 | `reference_pack` names a pack in `reference/manifest.json`; every card path in rule 14's scope, in `HANDOFF_COMPLETENESS.required_field_paths` and in `prefab_handoff.card_values` exists in **that pack's** card schema (E2 adds the key, E3 switches rule 14 to the named schema). |
| R39 | `timers.*` are positive integers; `accept_within_ms < not_completed_after_ms` (E4). |
| R40 | Every `applies_to_variants` key is a `SessionVariants` field and every value a member of that switch's enum (E1). |

`validate_scenario_version(version, *, role_modules=ROLE_MODULES, reference=…)` receives the reference
pack the way it already receives `role_modules`; it stays pure.

### 70.2.4 How the machines consult the variants

- `SimulationSession.variants: SessionVariants` is loaded on the aggregate.
- **Flow (`card_source`)** — consumed by `create_session`: under `GENERATED_CARD` stages are built for the
  chain *suffix starting at DDS*; `SESSION_CREATED.role_chain` records the **effective** chain and the
  additive `scenario_role_chain` the scenario's; `start_session` materialises the prefab exactly as for a
  `[DDS]` chain today. `SINGLE_ROLE`'s `EXACTLY_ONE` check and `ScoringContext.role_chain` read the
  effective chain, so the existing `applies_to_roles: [OPERATOR_112]` rules become non-applicable in a
  GENERATED_CARD session without any rule change.
- **Behaviour (`dds_mode`)** — `RoleModule.available_actions(stage_state, *, variants: SessionVariants | None = None)`
  gains an optional keyword (Protocol-compatible; `Operator112Module` ignores it). `DDSModule` keeps one
  `state_machine` over `DDS_TRANSITIONS` (plus one additive memo-only row) but is built per variant with
  `DDS_GUARDS` (picker) or `DDS_GUARDS_MEMO` (§70.4.4).
- **Scoring/UI toggles (`dds_card_check`, `dds_brigade_call`)** — gate the extra actions
  (`flag_card_issue`, H2's call) in `available_actions` and scoring applicability.

### 70.2.5 Scoring

`ScoringContext.variants` is folded from `SESSION_CREATED` (missing ⇒ the schema-1 derivation, so logs
written before E1 rescore identically). `ScoringRule.applies_to_variants: Mapping[str, tuple[str, ...]] = {}`
has the semantics of `applies_to_roles` (`backend/app/domain/scoring/rules.py`): applicable iff for every
named key the session's value is listed; a non-applicable rule yields the existing zero/zero
`ScoreResult` that changes neither totals nor critical errors. Materialised in
`scoring_rules.applies_to_variants jsonb`. Typical use: picker-only `RESOURCE_SELECTION` rules get
`{dds_mode: [RESOURCE_PICKER]}`, memo rules `{dds_mode: [MEMO_STATUSES]}`, card-check rules
`{dds_card_check: [ON]}`. No evaluator changes.

## 70.3 F2 — Lessons: a stream of cards without lifting `uq_incidents_session`

### 70.3.1 Types — `backend/app/domain/lesson/` (new)

```python
class LessonState(str, Enum):
    CREATED = "CREATED"; ACTIVE = "ACTIVE"; COMPLETED = "COMPLETED"; ABORTED = "ABORTED"

class ArrivalKind(str, Enum):
    AT_OFFSET = "AT_OFFSET"                          # lesson wall ms since LESSON start ≥ offset_ms
    AFTER_PREVIOUS_112_STAGE = "AFTER_PREVIOUS_112_STAGE"   # previous card's OPERATOR_112 stage reached HANDED_OFF
    AFTER_PREVIOUS_SESSION = "AFTER_PREVIOUS_SESSION"       # previous card's session COMPLETED or ABORTED

class Arrival(BaseModel):          # frozen, extra="forbid"
    kind: ArrivalKind
    offset_ms: int | None = None   # required for AT_OFFSET, forbidden otherwise
    delay_ms: int = 0              # added after the AFTER_* condition holds

class LessonParticipant(BaseModel):
    user_id: UserId
    assigned_role_type: RoleType | None
    assigned_service_id: ServiceId | None = None     # E5; ДДС participant → service binding (§70.4.5)

class PlanEntry(BaseModel):
    position: int                  # 1..N, unique; position 1 must be AT_OFFSET
    scenario_version_id: ScenarioVersionId
    arrival: Arrival
    variants: PartialVariants | None = None           # per-card override within the version's support
    participants: tuple[UserId, ...] | None = None    # E9a hook: per-workstation tasks; None = all
    weight: float = 1.0                               # E9a hook: difficulty weight in the lesson report

class Lesson(BaseModel):
    lesson_id: LessonId
    title_ru: str
    created_by_user_id: UserId
    session_mode: SessionMode
    variants: PartialVariants                         # lesson-wide request, resolved per card
    participants: tuple[LessonParticipant, ...]
    scenario_plan: tuple[PlanEntry, ...]              # min 1
    state: LessonState
    created_at: datetime; started_at: datetime | None; completed_at: datetime | None
    report_released_at: datetime | None
```

### 70.3.2 Lesson lifecycle — `LESSON_TRANSITIONS` (`domain/lesson/lesson.py`)

| From | Trigger | To | Who may fire | Guard / effect |
|:--|:--|:--|:--|:--|
| `CREATED` | `start` | `ACTIVE` | INSTRUCTOR (the creator or an ADMIN) | every plan session is `READY`; sets `started_at` |
| `ACTIVE` | `complete` | `COMPLETED` | SYSTEM (LessonRunner) | every plan session is `COMPLETED` or `ABORTED` |
| `CREATED`, `ACTIVE` | `abort` | `ABORTED` | INSTRUCTOR, SYSTEM | aborts every non-terminal plan session through the existing `abort_session` (each appends its own `SESSION_ABORTED`) |
| `COMPLETED`, `ABORTED` | — | — | — | terminal |

Lessons have **no event log of their own**: a lesson is scheduling, not simulation. Everything that
happened in a card is in that card's session log; the lesson row carries timestamps only. The session
records its lesson in `SESSION_CREATED.{lesson_id, lesson_position}` and the arrival in
`SESSION_STARTED.lesson_arrival {kind, due_offset_ms, fired_offset_ms}` (lesson wall ms, additive).

`createLesson` (one UoW) validates the plan (each version valid, each resolved variant supported and
implemented, participants assignable under `session_mode`) and creates **every** session at once, each
through the existing `create_session` path, each ending `READY` with `lesson_id`/`lesson_position` set.
A single-session run stays possible with `lesson_id NULL` — nothing about today's path changes.

### 70.3.3 The LessonRunner (`application/lessons/lesson_runner.py`)

Beside `SimulationRunner` (`backend/app/application/simulation/runner.py`) and with the same discipline:
one asyncio task per `ACTIVE` lesson, Redis lock `lock:lesson:{id}:runner`, re-adoption of every
`ACTIVE` lesson on backend start, tick every `SIM_TICK_MS`. Each tick, in `position` order, for each
entry whose session is still `READY`: evaluate its `Arrival`; when it holds, call the existing
`start_session` **as the instructor who created the lesson** (`ActorRef(INSTRUCTOR, created_by_user_id)`,
the "closest true actor" reading `prefab_handoff.py` already uses), so `SESSION_TRANSITIONS`'
`READY --start--> ACTIVE (INSTRUCTOR)` row is untouched. `503 INFERENCE_NOT_READY` from `start_session`
is retried next tick and appends nothing. When all sessions are terminal, fire `complete`. The
per-session `SimulationRunner` then runs each started card exactly as today — N cards = N runners (N ≤ 5
in practice).

### 70.3.4 Per-card timers — schema-2 scenario key `timers`

```yaml
timers:                         # all in SESSION (running) milliseconds; defaults when absent
  accept_within_ms: 30000       # memo p.5/21: Принята / Не принята within 30 s (REQ-5254, REQ-5283)
  fill_within_ms: 180000        # room 34:47–36:24: 3 minutes to fill (REQ-6020); red header timer (REQ-3010)
  not_completed_after_ms: 172800000   # memo: 48 h → «Не завершено» (REQ-5310); authors scale it for a lesson
```

Session ms, not wall ms, so `DEADLINE` rules and deadline events are deterministic and independent of
`time_scale`. The countdown **start** of each timer: `accept_within_ms` — the leg's `HANDOFF_RECEIVED`;
`fill_within_ms` — `CALL_ANSWERED` (CALLER_VOICE) — not used under GENERATED_CARD, where no 112 stage
runs; `not_completed_after_ms` — `HANDOFF_CREATED`. A queued card is timing: in a lesson a card
*arrives* when its session starts, its legs are created at that moment (GENERATED_CARD) and its accept
timer runs whether or not a ДДС trainee has opened it (chat 23.09 14:31, REQ-5909/5910).

### 70.3.5 Deadline consequences and the flush-before-append rule

Stage automation (`backend/app/application/dds/stage_automation.py`) evaluates the timers and appends
SIMULATION `DDS_CARD_STATUS_CHANGED` events (payload §70.7) when the derived card status (§70.4.6) changes
because a deadline passed: a leg without `ACCEPTED`/`NOT_ACCEPTED` at `received + accept_within_ms`
(→ `NOT_NOTIFIED`, and the leg's `accept_missed` flag is set), any leg not `COMPLETED` at
`handoff + not_completed_after_ms` (→ `NOT_COMPLETED`).

**Flush-before-append.** Every Unit of Work that appends to a session log — a runner tick *and* every
trainee command — first appends all deadline events whose deadline is ≤ its own `now_ms`, each stamped
with its **deadline** offset (envelope `monotonic_offset_ms` and payload `deadline_offset_ms`). Hence a
deadline event always precedes any later-stamped event in `seq_no` order, offsets stay monotonic, and the
stream is identical at any tick rate (INV 7). The scoring of the *late action itself* is an ordinary
`DEADLINE` rule on trainee events (e.g. `HANDOFF_RECEIVED → DDS_SERVICE_STATUS_SET` with
`to_payload_match: {new_status: [ACCEPTED, NOT_ACCEPTED]}`, `max_offset_ms: 30000`) — no new evaluator.

### 70.3.6 Read models and screens

- `GET /api/v1/lessons/{lesson_id}` — plan, sessions, per-card `card_status`, `display_number`.
- `GET /api/v1/incidents` — the trainee's cross-session list: the ДДС «Список/Поиск происшествий»
  (ui-check D-8) and the 112 «реестр» (D-2). Rows carry the deadline offsets and the session's current
  offset; the client renders countdowns and never decides a status.
- Lesson report: the N `ScoreReport`s plus a weighted sum (`PlanEntry.weight`, 1.0 until E9a). No new
  evaluator: each card's own `DEADLINE` rules already penalise the card left waiting.
- Realtime: the list page opens one existing `/ws/sessions/{id}` per active card; a lesson-level feed is
  a later addition, not a prerequisite. `incidents.display_number` (a sequence) is the «Происшествие
  NNNNNNNN» number.

### 70.3.7 How wave-3 E9a hangs off the lesson

Distinct tasks per workstation = `PlanEntry.participants`; groups = a lesson's `participants` (a group
table is E9a's, keyed to lessons); difficulty = `ScenarioVersion.difficulty` plus `PlanEntry.weight`;
AI-suggested difficulty weights write **proposals** an instructor accepts into `weight` — scoring stays
deterministic (SPEC §2, D11). E9a needs no change to the lesson state machine or the runner.

## 70.4 F3 — Per-service response statuses, broadcast, card statuses, several ДДС trainees

### 70.4.1 `ServiceResponseStatus` — `backend/app/domain/dds/response.py` (new, E5)

| Member | `label_ru` (memo, verbatim) | Source | Kind |
|:--|:--|:--|:--|
| `ADDED` | Добавлена | REQ-5281 | technical, set by the system when the leg is created |
| `RECEIVED` | Получена службой | REQ-5282 | technical, set by the system when the ДДС opens the card |
| `ACCEPTED` | Принята | REQ-5283 | primary decision (competence: always on) |
| `NOT_ACCEPTED` | Не принята | REQ-5284 | primary decision; comment mandatory |
| `RESPONSE_STARTED` | Начало реагирования | REQ-5285 | |
| `ARRIVED` | Прибытие | REQ-5286 | |
| `WORKING` | Проведение работ | REQ-5287 | |
| `COMPLETED` | Работы завершены | REQ-5288 | terminal; reason `WITHOUT_BRIGADE` for the 103 policy (REQ-5290) |
| `REFUSED` | Отказ от выполнения работ | REQ-5289 | terminal; comment mandatory |

### 70.4.2 `SERVICE_RESPONSE_TRANSITIONS` (one step at a time, REQ-5293)

| From | Trigger | To | Who may fire | Guard |
|:--|:--|:--|:--|:--|
| *(leg created)* | — | `ADDED` | SIMULATION | at `HANDOFF_RECEIVED` |
| `ADDED` | `receive` | `RECEIVED` | SIMULATION | the ДДС opened the card (`DDS_CARD_OPENED`), or a scripted responder's first step; a trainee `set_service_status` on an `ADDED` leg fires `receive` first in the same UoW |
| `RECEIVED` | `accept` | `ACCEPTED` | TRAINEE (ДДС), SIMULATION (scripted, picker mirror) | `guard_leg_actor_bound` (§70.4.5) |
| `RECEIVED` | `decline` | `NOT_ACCEPTED` | TRAINEE, SIMULATION (scripted) | `guard_comment_present`; `guard_policy_allows_refusal` |
| `NOT_ACCEPTED` | `accept` | `ACCEPTED` | TRAINEE | correction, REQ-5327 |
| `ACCEPTED` | `start_response` | `RESPONSE_STARTED` | TRAINEE, SIMULATION | — |
| `RESPONSE_STARTED` | `arrive` | `ARRIVED` | TRAINEE, SIMULATION | — |
| `ARRIVED` | `start_work` | `WORKING` | TRAINEE, SIMULATION | — |
| `WORKING` | `complete` | `COMPLETED` | TRAINEE, SIMULATION | — |
| `ACCEPTED`, `RESPONSE_STARTED`, `ARRIVED`, `WORKING` | `refuse` | `REFUSED` | TRAINEE, SIMULATION (scripted) | `guard_comment_present`; `guard_policy_allows_refusal`; from `ACCEPTED` it is also the correction of REQ-5328 |
| `RECEIVED`, `ACCEPTED`, `RESPONSE_STARTED`, `ARRIVED`, `WORKING` | `complete_without_brigade` | `COMPLETED` (reason `WITHOUT_BRIGADE`) | TRAINEE, SIMULATION | `guard_policy_is_no_refusal` — only the 103 policy, which replaces `decline` and `refuse` (REQ-5290) |
| `COMPLETED`, `REFUSED` | — | — | — | terminal |

Every accepted transition appends one `DDS_SERVICE_STATUS_SET` and one history row. «Номер наряда» is a
free-text `order_number` on **each** status entry, optional (REQ-3041, assumption A-2); `comment_ru` is
optional except where the guard requires it (422 `COMMENT_REQUIRED`). An out-of-sequence status is the
ordinary `409 INVALID_TRANSITION` (INV 8). The pencil's dropdown is `available_actions` of the leg — the
legal next triggers only (REQ-5292/5293).

Service policy — catalog field `status_policy` (§70.6.3): `DEFAULT` | `NO_REFUSAL` (103, `AMBULANCE`).

### 70.4.3 `DDSAssignment` additions and history

`DDSAssignment` gains `response_status: ServiceResponseStatus`, `response_status_at_offset_ms: int | None`,
`order_number: str | None` (last entry's), `last_comment_ru: str | None`, `accept_missed: bool`,
`responder: LegResponder` (`TRAINEE` | `SCRIPTED`), `bound_user_id: UserId | None`. The history is the
append-only table `dds_service_status_history` (materialised from `DDS_SERVICE_STATUS_SET`; UPDATE/DELETE
rejected by trigger like `session_events`). **Broadcast**: every ДДС participant's read model contains
every leg with its full history — each notified service sees the others' statuses (owner decision; the
memo's blocks per service, REQ-5294/5295); the author and time are shown per entry.

### 70.4.4 The DDS stage in memo mode: one additive transition row, guards and actions per variant

`DDSStageState` is unchanged. `DDS_TRANSITIONS` (HLD 10 §10.8) gains **one additive row** (manager
decision on O-1, option (a) tightened); every existing row is untouched:

| From | Trigger | To | Who may fire | Guard |
|:--|:--|:--|:--|:--|
| `ACKNOWLEDGED` | `close` | `RESOLVED` | TRAINEE (DDS) — as the existing `RESOLVED --close--> CLOSED` row | `memo_all_legs_terminal`: `dds_mode = MEMO_STATUSES` **and** every leg's `ServiceResponseStatus` is terminal — `COMPLETED` (Работы завершены), `NOT_ACCEPTED` (Не принята) or `REFUSED` (Отказ от выполнения работ) |

The guard **denies in picker mode**, so picker sessions behave exactly as today. In memo mode this row
is the **only** way out of `ACKNOWLEDGED`: `RESOURCE_SELECTION`, `DISPATCHED`, `EN_ROUTE`, `ARRIVED` and
`WORKING` are never entered (the analysis's reading); per-service progress lives on the legs.

**Memo-mode stage path:** `RECEIVED --acknowledge--> ACKNOWLEDGED --close [memo_all_legs_terminal]-->
RESOLVED --close--> CLOSED`. `acknowledge` (TRAINEE) is fired inside the ДДС trainee's first primary
decision (`ACCEPTED`/`NOT_ACCEPTED`) in the same UoW — or inside their first `open_card` when the
trainee owns no leg of this card — so `DDS_ACKNOWLEDGED` and the existing acknowledge `DEADLINE` rules
keep working. The memo `close` command (`closeDdsIncident`, the existing endpoint and
`CloseIncidentRequest`) fires `close` twice in one UoW (`ACKNOWLEDGED → RESOLVED`, then
`RESOLVED → CLOSED`), appending `STAGE_STATE_CHANGED` ×2, `DDS_INCIDENT_CLOSED` and
`ROLE_STAGE_COMPLETED`; `RESOLVED` is therefore never observed at rest in memo mode. While a leg is not
terminal, `close` from `ACKNOWLEDGED` is the ordinary `409 INVALID_TRANSITION` (INV 8). Scripted
responders and stage automation drive **legs only**; they fire no stage trigger in memo mode.

**Available actions** (`DDSModule.available_actions(state, variants=…)`), memo mode — the stage-level
list; leg-level actions are the leg's own triggers (§70.4.2):

| Stage state | Actions (memo) |
|:--|:--|
| `RECEIVED` | `open_card` / Открыть карточку; `set_service_status` / Изменить статус |
| `ACKNOWLEDGED` | `set_service_status`; `send_status_update` / Отправить статус; `flag_card_issue` / Отметить ошибку в карточке (only `dds_card_check: ON`); `close` / Закрыть происшествие (enabled when `memo_all_legs_terminal` holds) |
| `RESOURCE_SELECTION` … `WORKING` | — (never entered in memo mode) |
| `RESOLVED` | `close` (transient inside the memo `close` command) |
| `CLOSED` | — |

No resource action is offered in memo mode (`select_resource`, `dispatch`, …). In picker mode the
table of HLD 10 §10.9 applies verbatim. `Permission` gains `SET_SERVICE_STATUS` (`set_service_status`
and the leg triggers) and `FLAG_CARD_ISSUE`; `open_card` uses the existing `VIEW_HANDOFF`.

**Guards** `DDS_GUARDS_MEMO`: `guard_participant_assigned_to_stage` means "any ДДС participant of the
session"; `memo_all_legs_terminal` as above (also registered in the picker guard set, where it always
denies); the resource-driven guards (`guard_at_least_one_selected_available`,
`guard_any_dispatched_reached(…)`, `guard_resolution_condition`) are unreachable in memo mode and deny
there.

**Scoring in memo mode** keys on `DDS_SERVICE_STATUS_SET` (payload `new_status`, `service_type`,
`source`), never on `RESOURCE_DISPATCHED` / `RESOURCE_STATUS_CHANGED` or the stage's
`EN_ROUTE`…`RESOLVED` changes: e.g. `DEADLINE HANDOFF_RECEIVED → DDS_SERVICE_STATUS_SET
{new_status: [ACCEPTED, NOT_ACCEPTED]}`, `WORKFLOW_ACTION DDS_SERVICE_STATUS_SET {new_status:
NOT_ACCEPTED, service_type: …}` for a competence decline; picker-only rules carry
`applies_to_variants: {dds_mode: [RESOURCE_PICKER]}`.

**Documents and tests E5a changes with the code:** the new row into HLD 10 §10.8's `DDS_TRANSITIONS`
table, the memo available-actions table into §10.9 (a second, variant-labelled table), the §10.7/§10.9
parsing test `test_dds_tables_match_the_hld.py` taught the variant-labelled table, and INV 8's
table-driven expectations (the new row allowed in memo, denied in picker; every `ACKNOWLEDGED → …`
resource trigger rejected in memo).

**Picker-mode mirroring.** In `RESOURCE_PICKER` mode the leg status is mirrored by stage automation from
the leg's `state` (SIMULATION, `source: PICKER_MIRROR`): `RECEIVED → RECEIVED`,
`ACKNOWLEDGED`/`RESOURCE_SELECTION`/`DISPATCHED → ACCEPTED`, `EN_ROUTE → RESPONSE_STARTED`,
`ARRIVED → ARRIVED`, `WORKING → WORKING`, `RESOLVED → COMPLETED`, `CLOSED` with `closure_reason RESOLVED
→ COMPLETED` (other closures leave the last mirrored status). The same map backfills migration `0012`.
The report and the list speak one vocabulary in both modes.

### 70.4.5 Several ДДС trainees and scripted responders

`session_participants.assigned_service_id` (and `LessonParticipant.assigned_service_id`): in
`MULTI_TRAINEE` the instructor binds each ДДС participant to a service; `validate` requires distinct
services. At leg creation each leg gets `responder`:

- `TRAINEE` with `bound_user_id` = the participant bound to its service; or, when **no** ДДС participant
  of the session is bound, `TRAINEE` with `bound_user_id NULL` (one trainee plays every leg — today's
  behaviour);
- otherwise `SCRIPTED`.

`guard_leg_actor_bound`: a leg-level command must come from `bound_user_id` (or any ДДС participant when
it is NULL) — else `403 FORBIDDEN_FOR_SERVICE`. Reads are unchanged: every ДДС participant sees every leg.
`role_stages.participant_user_id` stays the *primary* ДДС participant.

Scripted responders: schema-2 key `expected_response.responders: {<service_id>: [{after_ms, status,
comment_ru, order_number}]} | DEFAULT`; `DEFAULT` = `receive +0, ACCEPTED +15 000, RESPONSE_STARTED
+60 000, ARRIVED +180 000, WORKING +200 000, COMPLETED +600 000` (ms after the leg's `HANDOFF_RECEIVED`).
Fired by stage automation as SIMULATION (`source: SCRIPTED_RESPONDER`); deterministic. This is also H2's
anchor: a brigade call hangs on an `assignment_id`.

### 70.4.6 Card status — a derived projection (`backend/app/domain/dds/card_status.py`, pure)

| Member | `label_ru` | Rule (evaluated in this precedence order; first match wins) | Source |
|:--|:--|:--|:--|
| `COMPLETED` | Завершена | a handoff exists and every leg is `COMPLETED`, or the notification list is empty | REQ-5311 |
| `REFUSED` | Отказ | some leg is `NOT_ACCEPTED` or `REFUSED` (the memo's chief-specialist check is dropped, C2) | REQ-5309 |
| `NOT_COMPLETED` | Не завершено | `handoff + not_completed_after_ms` passed and some leg is not `COMPLETED` | REQ-5310 |
| `NOT_NOTIFIED` | Не оповещено | some leg has `accept_missed` (sticky once set) | REQ-5308 |
| `CHECKED` | Проверена | the instructor released the session's report (C2) | REQ-5307 |
| `WORKED` | Отработана | the handoff exists (the 112 stage reached `HANDED_OFF`, or the prefab materialised) | REQ-5306 |
| `REGISTERED` | Зарегистрирована | otherwise (the session started) | REQ-5305 |

`card_status(legs, handoff_offset, timers, now_offset, report_released) -> CardStatus` is pure; its value
is materialised into `incidents.card_status` in the same UoW as the event that changed it, and each change
is one `DDS_CARD_STATUS_CHANGED` (reason = the matched rule, `CardStatusReason`: `HANDOFF_CREATED`,
`ACCEPT_DEADLINE_MISSED`, `LEG_DECLINED_OR_REFUSED`, `NOT_COMPLETED_DEADLINE`, `ALL_LEGS_COMPLETED`,
`LEG_STATUS_CORRECTED` — the last for a change caused by the REQ-5327 correction lifting `REFUSED`). `NOT_NOTIFIED`, `REFUSED`, `NOT_COMPLETED`
render red in lists (REQ-5312). `CHECKED` is set by `releaseReportToTrainee`, which appends nothing to a
completed log (HLD 20 §20.3's rule) — it is materialised on the column only and has no event. Before E5
(no leg statuses) E4 evaluates the same function with the leg status mirrored from the stage (§70.4.4
picker map). The precedence order is assumption A-5.

## 70.5 F4 — The 112 card as versioned data

### 70.5.1 Files and loader

`reference/card-schema/v1.yaml` is today's 38 `CARD_FIELDS` (`backend/app/domain/layers/operator_card.py`)
byte-for-byte in content; `reference/card-schema/v2.yaml` is authored from «КАРТОЧКА 112.docx» and
«СКРИНШОТ КАРТОЧКИ 112ГСИ.docx» (`requirements/sources/01-qna-session-telegram/files/`). A loader in
`domain/layers/card_schema.py` parses a schema document into `CardSchema {schema_id, fields:
tuple[CardFieldSpec, ...], groups, sha256}`; `operator_card.py` keeps `set_field` and keeps the name
`CARD_FIELDS` as the v1 alias so every test that imports it passes. `set_field` validates against the
session's schema.

### 70.5.2 `CardFieldSpec` — additive properties

| Property | Type | Meaning |
|:--|:--|:--|
| `group` | `str \| None` | layout block id (`header`, `applicant`, `address`, `incident`, `questionnaire`, `services`, …) |
| `order` | `int` | order inside the group |
| `control` | `TEXT \| TEXTAREA \| NUMBER \| SELECT \| TOGGLE_SET \| CHIPS \| CHECKBOX \| PHONE` | how the UI renders it |
| `options` | `list[{code, label_ru}] \| None` | data-driven enum; replaces `_ENUM_REGISTRY` for v2; codes = classifier признак codes where they exist (F5) |
| `visible_when` | `CardCondition \| None` | when the field is shown; hidden fields are still **accepted** by `set_field` (advisory, like `required_for_handoff`) |
| `required_in_block` | `bool` | one of REQ-3014's four mandatory blocks; advisory |
| `routing_relevant` | `bool` | a change appends `RECIPIENTS_RESOLVED` (§70.6.4) |

`CardCondition` (in `card_schema.py`, **not** a new leaf of the world `Condition` language, so HLD 30
rules 26/31 are untouched) = `{all: [...]} | {any: [...]} | {not: …} | {field_path, op: EQ | NE | IN |
CONTAINS | PRESENT, value}` over the card's own values. Evaluated server-side (projection, tests) and
client-side (render), both against the same fixture file `reference/card-schema/conditions.fixtures.json`.
`ValueType` is unchanged; a v2 SELECT is `ENUM` with `enum_name: null` and `options`; a multi-select is
`STRING_LIST` with `options`. `Comparison` gains one additive member `CONTAINS` for `STRING_LIST`
fields (`CARD_FIELD_CORRECT`).

### 70.5.3 Path continuity and new paths

Rule for E3's authoring: **a v2 field that means the same as a v1 field reuses the v1 path.** Known
continuations: `address.locality/street/house/building/entrance/floor/apartment`, `caller.full_name`,
`caller.phone`, `description.text`, `people.*`, `recipients.services`, `recipients.comment`. New v2
paths (ui-check D-3…D-7): `address.country/region/okrug/district/object/code/descriptive`,
`caller.phone_aon/phone_provided/phone_on_site/foreign/status`, `incident.types` (`STRING_LIST` of the
«Что случилось» picker codes — the «добавить тип происшествия» chips), `incident.classifier_code` (the
resolved «Класс.:» row), `flags.no_contact/call_dropped/ambulance_refused/blocked`, and questionnaire
answers under `q.<type_code>.<group>` (`STRING_LIST` for toggle sets). `incident.type` (`IncidentType`)
stays in v1 only; `IncidentType` survives for schema-1 scenarios.

### 70.5.4 Which schema a session uses; the DDS side

The scenario's `reference_pack` (schema 2; schema 1 ⇒ `legacy-r1`) names the pack, the pack names the
card schema, and `SESSION_CREATED.reference_pack` records ids and shas. `OperatorCardView` gains
`card_schema` (id); `DdsWorkItem` gains `field_specs` (additive), so
`frontend/src/features/dds/card-field-labels.ts` is deleted and the ДДС sentence view (D-9) renders from
the same options. Scoring is unchanged: card evaluators work on paths and payloads only (P2).

GENERATED_CARD rendering: the prefab `card_values` of a schema-2 scenario are v2 paths, so the ДДС sees
a generated card in the v2 layout — this is E3's "generated-card mode". Whether a 112 trainee should also
fill a card from a generated *text* narrative is assumption A-7.

## 70.6 F5 — Classifier, services catalog, routing

### 70.6.1 Reference-pack layout

```
reference/                              (repo root, beside scenarios/)
├── manifest.json                       packs + per-file sha256 + source sha256 (gate-checked)
├── card-schema/
│   ├── v1.yaml                         today's 38 fields
│   ├── v2.yaml                         the organizer card
│   └── conditions.fixtures.json        CardCondition fixtures shared by backend and frontend tests
├── classifier/
│   ├── v046_24.json                    one record per classifier row (1283 rows, REQ-5701–5717)
│   └── v046_24.columns.json            routing column map: org id → name_ru, sub-columns
└── services/
    └── v1.yaml                         the catalog: six legacy ids + «СЛУЖБЫ 112» (REQ-3042/3043)
backend/tools/import_classifier.py      xlsx → classifier/*.json   (reads requirements/sources, read-only)
backend/tools/import_services.py        docx → services/v1.yaml
```

`manifest.json`:

```json
{
  "manifest_version": 1,
  "packs": {
    "legacy-r1":  {"card_schema": "v1", "services": "v1", "classifier": null},
    "v046_24-r1": {"card_schema": "v2", "services": "v1", "classifier": "v046_24"}
  },
  "files": {
    "card-schema/v1.yaml": "<sha256>", "card-schema/v2.yaml": "<sha256>",
    "classifier/v046_24.json": "<sha256>", "classifier/v046_24.columns.json": "<sha256>",
    "services/v1.yaml": "<sha256>"
  },
  "sources": {
    "classifier/v046_24.json": {"path": "requirements/sources/05-organizer-materials/Классификатор_происшествий_v_046_24_корректировка_МВД_+_Департамент (1).xlsx", "sha256": "<sha256>", "tool": "backend/tools/import_classifier.py"},
    "services/v1.yaml": {"path": "requirements/sources/01-qna-session-telegram/files/СЛУЖБЫ 112.docx", "sha256": "<sha256>", "tool": "backend/tools/import_services.py"}
  }
}
```

The gate (stdlib only) checks every file sha against `files` and every `sources` sha against the source
file; the regenerate-and-diff test needs the xlsx/docx readers and is marked like `requires_models`
(skipped when absent). Loaded once by the composition root into an immutable `ReferenceCatalog` behind
the port `application/ports/reference.py` (`ReferencePort`), file-backed adapter
`infrastructure/reference/file_catalog.py`. Not a table: read-only, ~1 MB, versioned by git, reversible to
a table later without touching the resolver.

### 70.6.2 Classifier record (`classifier/v046_24.json`)

`{code, group_no, group_ru, features: [f1, f2, f3], extra_features: [...], final_type_ru, ekp35_ru,
main_service, routing: {<org_id>: [{when: {<feature_flag>: bool, ...}, value: "карточка-112" | "<label>" |
null}]}}`. A cell is a notification iff non-empty and not «нет реагирования» (assumption A-1).

### 70.6.3 Service catalog entry (`services/v1.yaml`)

`{id: ServiceId, name_ru, full_name_ru, kind: CITY | DISTRICT | PREFECTURE | DEPARTMENT, code ("101"…) |
null, okrug | null, district | null, classifier_org_id | null, status_policy: DEFAULT | NO_REFUSAL,
display: bool, deprecated: bool, phone | null}`. The first six ids are verbatim `FIRE_RESCUE` (101),
`POLICE` (102), `AMBULANCE` (103, `NO_REFUSAL`), `GAS_SERVICE` (104), `UTILITY_EMERGENCY` (`deprecated`,
hidden from the v2 picker, C8), `EDDS`. New ids are UPPER_SNAKE (`MOSVODOKANAL`, `DDS_DISTRICT_<NAME>`,
`DDS_PREFECTURE_<OKRUG>`, `DEP_EDUCATION`, …).

`ServiceId = NewType("ServiceId", str)` replaces the `ServiceType` enum in `domain/enums.py`; every
stored snapshot, payload and fixture that says `FIRE_RESCUE` stays valid by value. `openapi.yaml`'s
`ServiceType` becomes a `string` (`minLength: 1`); the frontend's exhaustive `Record<ServiceType, …>` maps
(`frontend/src/features/dds/dds-labels.ts`) become catalog lookups (`GET /reference/services`).

### 70.6.4 Resolver and the notification list

`resolve_notification_list(classifier, catalog, card_values) -> Resolution` (`domain/routing/resolve.py`,
pure): (1) `incident.types` + questionnaire answers (or `incident.classifier_code` when set) → candidate
rows; one candidate ⇒ `classifier_code`; several ⇒ `candidate_codes` and the operator picks in «Класс.:»;
(2) per org column group, the sub-column whose feature condition holds; the org is notified iff the
cell counts (A-1); (3) «Территориальные ОИВ» non-empty ⇒ the district ДДС of `address.district` and its
prefecture ДДС (msg690); department columns are the subordination hook. `display: false` orgs go to
`informed_services` (REQ-5280), not to legs.

The application calls it inside `setCardField` when a `routing_relevant` path changes and appends
`RECIPIENTS_RESOLVED` (SIMULATION). `createHandoff` resolves once more and appends a final
`RECIPIENTS_RESOLVED {final: true}` immediately before `HANDOFF_CREATED` in the same UoW; the prefab path
(GENERATED_CARD) does the same. **Notification list = `auto_services ∪ manual_services`**:
`selectRecipientService` (TRAINEE) keeps writing only manual additions into `recipients.services`;
`deselectRecipientService` answers `409 SERVICE_REMOVAL_FORBIDDEN` for any service under a schema-v2 card
(memo p.14, REQ-5275) and stays as today under v1 (`SERVICE_DESELECTED` kept for v1 and old logs, C10).
`HandoffSnapshot.recipient_services` and `HANDOFF_CREATED.recipient_services` hold the union, so
`SERVICE_SELECTION` at `HANDOFF` needs no change; at `SESSION_END` it folds the last
`RECIPIENTS_RESOLVED` ∪ `SERVICE_SELECTED`. Legs are created per `ServiceId` of the union. The routing is a
table lookup — the LLM never sees the card (SPEC §2 holds, C11).

## 70.7 Events — new and changed (for HLD 10 §10.13 and HLD 40 §40.4, by the epic named)

| Event type | Epic | Actor | Payload keys (`name: type`) | Visible to |
|:--|:--|:--|:--|:--|
| `SESSION_CREATED` (additive keys) | E1, E2, E4 | as today | `variants: SessionVariants` (E1), `scenario_role_chain: list[RoleType]` (E1), `reference_pack: {pack_id: str, card_schema: str, card_schema_sha256: str, classifier: str \| null, classifier_sha256: str \| null, services: str, services_sha256: str}` (E2), `timers: {accept_within_ms: int, fill_within_ms: int, not_completed_after_ms: int}` (E4), `lesson_id: uuid \| null`, `lesson_position: int \| null` (E4) | INSTRUCTOR |
| `SESSION_STARTED` (additive key) | E4 | INSTRUCTOR | `lesson_arrival: {kind: ArrivalKind, due_offset_ms: int, fired_offset_ms: int} \| null` (lesson wall ms) | as today |
| `RECIPIENTS_RESOLVED` | E2 | SIMULATION | `card_id: uuid`, `card_revision_id: uuid \| null`, `pack_id: str`, `classifier_code: str \| null`, `candidate_codes: list[str]`, `main_service: ServiceId \| null`, `auto_services: list[ServiceId]`, `informed_services: list[ServiceId]`, `manual_services: list[ServiceId]`, `notification_list: list[ServiceId]`, `reasons: list[{service_id: ServiceId, source: CLASSIFIER \| TERRITORIAL \| DEPARTMENT, column: str, sub_column: str \| null}]`, `final: bool`, `at_offset_ms: int` | OPERATOR_112, INSTRUCTOR |
| `HANDOFF_CREATED` (additive keys) | E2 | TRAINEE (SIMULATION for a prefab) | `auto_recipient_services: list[ServiceId]`, `manual_recipient_services: list[ServiceId]`, `informed_services: list[ServiceId]` (`recipient_services` = the union) | as today |
| `HANDOFF_RECEIVED` (additive keys) | E5 | SIMULATION | `responder: TRAINEE \| SCRIPTED`, `bound_user_id: uuid \| null`, `initial_response_status: "ADDED"` | as today |
| `DDS_CARD_STATUS_CHANGED` | E4 | SIMULATION | `incident_id: uuid`, `previous_status: CardStatus`, `new_status: CardStatus`, `reason: CardStatusReason` (the §70.4.6 rule), `assignment_id: uuid \| null`, `service_type: ServiceId \| null`, `deadline_offset_ms: int \| null`, `at_offset_ms: int` | OPERATOR_112, DDS, INSTRUCTOR |
| `DDS_CARD_OPENED` | E5 | TRAINEE | `assignment_id: uuid`, `service_type: ServiceId`, `actor_user_id: uuid`, `at_offset_ms: int` | DDS, INSTRUCTOR |
| `DDS_SERVICE_STATUS_SET` | E5 | TRAINEE, SIMULATION | `assignment_id: uuid`, `service_type: ServiceId`, `previous_status: ServiceResponseStatus`, `new_status: ServiceResponseStatus`, `trigger: str`, `order_number: str \| null`, `comment_ru: str \| null`, `completion_reason: "WITHOUT_BRIGADE" \| null`, `source: TRAINEE \| SCRIPTED_RESPONDER \| PICKER_MIRROR \| SYSTEM`, `actor_user_id: uuid \| null`, `at_offset_ms: int` | DDS, INSTRUCTOR |
| `DDS_CARD_ISSUE_FLAGGED` | E5 | TRAINEE | `assignment_id: uuid`, `field_path: str \| null`, `issue_kind: MISSING \| WRONG \| CONTRADICTION \| OTHER`, `comment_ru: str`, `actor_user_id: uuid`, `at_offset_ms: int` | DDS, INSTRUCTOR |

`service_type` keeps its key name everywhere (payload compatibility); its type becomes `ServiceId`.
Every new `EventType` member is added to HLD 40 §40.4's additive table in the same commit as the code,
so `test_visibility_matches_protocol_table.py` keeps parsing one source of truth.

## 70.8 Migrations 0009–0012 (additive or a dropped CHECK; `0001`…`0008` never move)

| Migration | Epic | Changes |
|:--|:--|:--|
| `0009_session_variants` | E1 | `simulation_sessions.variants jsonb NOT NULL DEFAULT '{}'`; `scoring_rules.applies_to_variants jsonb NOT NULL DEFAULT '{}'`. No backfill: `'{}'` reads as the schema-1 derivation (§70.2.2). |
| `0010_service_id_open` | E2 | `dds_assignments`: drop `CHECK (service_type IN (…six…))`, add `CHECK (service_type <> '')`. No data move (six legacy ids are catalog ids). |
| `0011_lessons` | E4 | new table `lessons (id uuid PK, title_ru text NOT NULL, created_by_user_id uuid NOT NULL FK users RESTRICT, session_mode text NOT NULL CHECK, variants jsonb NOT NULL DEFAULT '{}', participants jsonb NOT NULL, scenario_plan jsonb NOT NULL, state text NOT NULL DEFAULT 'CREATED' CHECK IN (CREATED, ACTIVE, COMPLETED, ABORTED), created_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz NULL, completed_at timestamptz NULL, report_released_at timestamptz NULL, report_released_by_user_id uuid NULL FK users)`, index `ix_lessons_state`; `simulation_sessions.lesson_id uuid NULL FK lessons(id) ON DELETE RESTRICT`, `simulation_sessions.lesson_position integer NULL`, unique `uq_sessions_lesson_position (lesson_id, lesson_position)`, `CHECK ((lesson_id IS NULL) = (lesson_position IS NULL))`; `incidents.card_status text NOT NULL DEFAULT 'REGISTERED'` + `CHECK IN (REGISTERED, WORKED, CHECKED, NOT_NOTIFIED, REFUSED, NOT_COMPLETED, COMPLETED)`; sequence `incident_display_number_seq` and `incidents.display_number bigint NOT NULL DEFAULT nextval(…)` unique. Backfill `card_status` in the migration from `role_stages`/`dds_assignments`/`simulation_sessions.report_released_at` by the §70.4.6 function with the picker mirror (pure over existing columns). |
| `0012_dds_response_status` | E5 | `dds_assignments.response_status text NOT NULL DEFAULT 'ADDED'` + `CHECK IN (…nine…)`, `response_status_at_offset_ms integer NULL`, `order_number text NULL`, `last_comment_ru text NULL`, `accept_missed boolean NOT NULL DEFAULT false`, `responder text NOT NULL DEFAULT 'TRAINEE' CHECK IN (TRAINEE, SCRIPTED)`, `bound_user_id uuid NULL FK users`; new table `dds_service_status_history (id uuid PK, session_id uuid NOT NULL FK CASCADE, assignment_id uuid NOT NULL FK dds_assignments CASCADE, event_id uuid NOT NULL UNIQUE FK session_events, seq_no bigint NOT NULL, previous_status text NOT NULL, new_status text NOT NULL, order_number text NULL, comment_ru text NULL, completion_reason text NULL, source text NOT NULL, actor_type text NOT NULL, actor_user_id uuid NULL, at_offset_ms integer NOT NULL)`, index `(assignment_id, seq_no)`, UPDATE/DELETE-rejecting trigger (HLD 20 §20.9 pattern); `session_participants.assigned_service_id text NULL` + `CHECK (assigned_service_id IS NULL OR assigned_service_id <> '')` + unique `(session_id, assigned_service_id)` where not null. Backfill `response_status` from `state` by the picker mirror map (§70.4.4). |

## 70.9 Conflict picks (the analysis's §4, taken as written)

| # | Conflict | Pick |
|:--|:--|:--|
| C1 | 18.09 msg638 «ДДС проверяет корректность» vs 23.09 «не контролирует» (REQ-5915/5916) | Both, behind `dds_card_check`; default `OFF` = the latest customer answer. The competence decision (`Принята`/`Не принята` + reason) is always on. |
| C2 | Memo: «Отказ» needs a chief-specialist check; «Проверена» is a 112-side control step | No control-department role exists or is asked for. `REFUSED` is derived from a leg's `NOT_ACCEPTED`/`REFUSED` alone; `CHECKED` = instructor report release. Documented simplification. |
| C3 | 48 h «Не завершено» vs a short lesson | `timers.not_completed_after_ms` is scenario data in session ms; the memo's constant is the default, authors scale it. The UI labels the norm, not the constant. |
| C4 | 3-minute fill norm set while saying «норматива… нет» | `timers.fill_within_ms` default 180 000, a red header timer (REQ-3010) plus the scenario's own `DEADLINE` rule (`CALL_ANSWERED → HANDOFF_CREATED`). |
| C5 | SPEC §1/§13 one incident per simulation vs a stream of cards | Kept literally; the stream is a lesson of simulations (F2). |
| C6 | SPEC §7 DDS states vs the memo vocabulary | Both: the stage enum stays; memo statuses are per leg (F3). |
| C7 | «ДДС → бригада» voice call has no dated customer default; the customer says brigade contact happens «минуя 112» | Switch exists from E1, effective default `OFF` until H2/E6 ships; `ON` is `409 VARIANT_NOT_AVAILABLE` until then. Owner to confirm the default. |
| C8 | `UTILITY_EMERGENCY` distractor vs the real service list | Kept as a `deprecated` catalog entry so stored data and the demo stay valid; hidden from the v2 picker. |
| C9 | «100 % похожи» light reference UI vs D12's dense dark console | E7a reverses D12's look for the 112 card and ДДС screens (light theme, orange bar `#EC653B`, blue tags `#157DBD`, backgrounds `#EFEFEF`/`#C9CED1`); recorded as D20. |
| C10 | Memo p.14 «112 may add, not remove» vs `deselectRecipientService` + `SERVICE_DESELECTED` | Removal refused under schema v2 (`409 SERVICE_REMOVAL_FORBIDDEN`); the event type stays for v1 sessions and old logs. |
| C11 | SPEC §2 "LLM must not decide services" vs automatic routing (assessment §4.11) | No conflict: routing is a classifier lookup; the LLM never sees the card. |

## 70.10 Assumptions and evidence gaps — each with where it is checked

| # | Assumption (what the design takes as true) | Where it is checked |
|:--|:--|:--|
| A-1 | A non-empty *labelled* routing cell (`пожар: мусор`, `Травма`, …) counts as a notification, like `карточка-112`; only an empty cell or `нет реагирования` does not (manager ruling on analysis gap 4). | E2: resolver fixtures from the memo's worked examples (road damage, lift, wasp nest); one question to the organizer logged in E2's report. |
| A-2 | «Номер наряда» is free text, optional, one per status entry (REQ-3041 shows it only on the ДДС form; the memo is silent). | E5 API test: two entries with different order numbers both kept in history. |
| A-3 | Administrative «Что случилось» entries (справки, тестовый вызов, передача дежурства) produce no classifier row and no auto notification. | E3: card-schema v2 option list marks them `routing: none`; resolver test. |
| A-4 | The 3-minute fill norm's consequence is both a red timer and a scenario `DEADLINE` rule. | E4 (timer data) and E3 (red timer in the header); the rule lives in each schema-2 scenario. |
| A-5 | Card-status precedence `COMPLETED > REFUSED > NOT_COMPLETED > NOT_NOTIFIED > CHECKED > WORKED > REGISTERED`, and `NOT_NOTIFIED` is sticky once a leg missed 30 s; the memo lists the seven statuses but no precedence. | E4 unit table test over the pure function; owner review of the list screen in E7a. |
| A-6 | «СЛУЖБЫ 112»: ~25 city + ~140 district ДДС; only ~20 of 55 picker frames are transcribed (REQ-3043). | E2 transcribes every frame before generating `services/v1.yaml`; the count is asserted against the transcription, not against 140. |
| A-7 | GENERATED_CARD means "no caller, the card arrives generated, chain starts at DDS"; a 112 trainee filling a card from a generated *text* narrative is not in scope. | E3 brief; owner confirmation before E3b. |
| A-8 | Status selection is strictly one step at a time (REQ-5293); skipping (e.g. `RESPONSE_STARTED → WORKING`) is refused. | E5 INV 8 table test. |
| A-9 | Service 104's missing comments (REQ-5291) are an integration artefact of the real system, not a trainee rule: the comment stays mandatory for 104 trainees. | E5; owner review. |
| A-10 | The «Не принята» 30-s timer counts from the leg's `HANDOFF_RECEIVED` (card sent to the service), not from `DDS_CARD_OPENED`. | E4 DEADLINE fixture; REQ-5283 text «в течение 30 секунд после направления карточки». |
| A-11 | A ДДС trainee in memo mode gets no simulated brigade radio feedback unless the scenario authors `RADIO_MESSAGE_CREATED` world events; brigade voice is H2. | H2/E6 design. |
| A-12 | Playwright is not a frontend dependency today (`frontend/package.json`); E7a adds it as a frontend `devDependency` (approved in principle) and reuses the browser already cached in `~/.cache/ms-playwright` (`chromium-1187`, `chromium_headless_shell-1187` present on 2026-09-24) — no new browser download unless unavoidable; reference images are extracted from the organizer docx into the frontend test tree. | E7a: the pinned Playwright version must match the cached browser build. |
| A-13 | `openpyxl` and `python-docx` are needed only by the import tools, not by the gate (sha check is stdlib). Approved in principle in a dev/tools-only dependency group, installed with `uv sync --inexact`, never imported by `backend/app` runtime. | E2a: an import-boundary assertion that `backend/app/**` imports neither; the regen test is skip-marked without them. |

Open point O-1 (memo-mode closure) was decided by the manager: option (a) tightened — one additive `DDS_TRANSITIONS` row `ACKNOWLEDGED --close--> RESOLVED` with guard `memo_all_legs_terminal` (§70.4.4).

## 70.11 Switch matrix

| Switch | Value | Implemented by | Product default before E5 | Product default from E5 | Schema-1 scenarios |
|:--|:--|:--|:--|:--|:--|
| `card_source` | `CALLER_VOICE` | exists (I1; frozen) — E1 wires the switch | — | — | derived default when `OPERATOR_112 ∈ role_chain` |
| `card_source` | `GENERATED_CARD` | E1 (flow via the existing prefab path); E3 renders it in the v2 layout | **default** (schema 2) | **default** (schema 2) | supported iff `prefab_handoff` present |
| `dds_mode` | `RESOURCE_PICKER` | exists (I1) — E1 wires the switch | **effective default** | supported, not default | always, and the default forever (P5) |
| `dds_mode` | `MEMO_STATUSES` | E5 (`409 VARIANT_NOT_AVAILABLE` from E1 until E5) | not available | **default** (schema 2) | not supported |
| `dds_card_check` | `OFF` | E1 (no-op) | **default** | **default** | default |
| `dds_card_check` | `ON` | E5 (`flag_card_issue`; `409 VARIANT_NOT_AVAILABLE` until then) | not available | supported | supported |
| `dds_brigade_call` | `OFF` | E1 (no-op) | **default** | **default** | default |
| `dds_brigade_call` | `ON` | H2 → E6 (`409 VARIANT_NOT_AVAILABLE` until then) | not available | not available | not supported |

`IMPLEMENTED_VARIANT_VALUES` after E1: `card_source {CALLER_VOICE, GENERATED_CARD}`, `dds_mode
{RESOURCE_PICKER}`, `dds_card_check {OFF}`, `dds_brigade_call {OFF}`; E5 adds `MEMO_STATUSES` and `ON`
(card check); E6 adds brigade `ON`.

## 70.12 Contract and schemes

- `docs/hld/contracts/i3-openapi-delta.yaml` — new/changed paths and schemas (sessions create with
  variants, lessons, incidents list, reference endpoints, ДДС leg status / open / card issue,
  `CardFieldSpec` additive properties). Each epic merges its part into `docs/hld/openapi.yaml`.
- `docs/hld/puml/i3-domain.puml` — the new and changed aggregates.
- `docs/hld/puml/i3-service-response-status.puml` — §70.4.2.
- `docs/hld/puml/i3-dds-stage-memo.puml` — §70.4.4 (the DDS stage per `dds_mode`, the one additive row).
- `docs/hld/puml/i3-card-status.puml` — §70.4.6.
- `docs/hld/puml/i3-lesson-state.puml` — §70.3.2.
- `docs/hld/puml/i3-sequence-lesson-card.puml` — lesson → session start → handoff → `RECIPIENTS_RESOLVED`
  → per-service legs → deadline status event.

## 70.13 Where this document departs from the analysis's wording, and why

| Item | Analysis | Here | Reason |
|:--|:--|:--|:--|
| Voice value name | `VOICE_CALL` | `CALLER_VOICE` | the manager's binding decision F1 names it so |
| New validation rule numbers | R31–R36 | R32–R40 | HLD 30 §30.8 rule 31 and code `R31` already exist (`backend/app/domain/scenario/validation.py`) |
| Memo-mode stage | `RESOURCE_SELECTION`/`DISPATCHED` "never entered" | never entered, as the analysis says; closure through one additive `DDS_TRANSITIONS` row `ACKNOWLEDGED --close--> RESOLVED` (guard `memo_all_legs_terminal`, denies in picker mode) — the only memo closure path | manager decision on O-1 (option (a) tightened): the unchanged table reached `RESOLVED` only through `DISPATCHED` |
| Schema-1 `dds_mode` after E5 | default flips to MEMO | the flip applies to schema-2 documents only | P5: schema-1 content has no responders, and every existing DDS test would change behaviour |
| Top-level scenario keys | "new top-level keys" | recorded as an amendment of D4's "exactly the SPEC §4 keys" (D14) | D4 says *exactly*; SPEC §4 says *required*; schema 1 keeps exactly those keys |
| Deadline stamping | "stamped with the deadline offset" | plus the flush-before-append rule | keeps `seq_no` order and offsets monotonic when a trainee command lands after a deadline but before the next tick |
| Dependencies (manager decision) | — | `openpyxl` + `python-docx` in a dev/tools-only dependency group (`uv sync --inexact`; never imported by `backend/app` runtime) for E2a's import tools; Playwright as a frontend `devDependency` for E7a, reusing the browser already in `~/.cache/ms-playwright` | approved in principle by the manager (A-12, A-13) |

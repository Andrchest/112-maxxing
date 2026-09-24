# HLD 10 — Domain model (`backend/app/domain/**`)

Elaborates `docs/hld/00-decisions.md` (D1–D13) against `docs/SPEC.md` §1–§47. Nothing here re-decides
the frame. Every identifier in this document is final: a later implementer copies it literally.

Purity rule (D2): everything below is pure Python 3.12 + Pydantic v2. No FastAPI, SQLAlchemy, LiveKit,
Redis, httpx, no I/O, no wall clock, no module-level `random`. Time arrives as `monotonic_offset_ms`
(int, ms since `SESSION_STARTED`) or as an injected `Clock` port value; randomness arrives as an
`rng_factory`. Identifiers are English; only trainee-facing labels, scenario content and caller speech
are Russian.

## 10.1 Module map

```
backend/app/domain/
├── common/
│   ├── actors.py            ActorRef
│   ├── errors.py            DomainError, InvalidTransitionError, ScenarioValidationError,
│   │                        CardFieldError, GateError, ScoringEvidenceError
│   ├── ids.py               typed UUID aliases (SessionId, IncidentId, …)
│   └── state_machine.py     Transition, TransitionTable, StateMachine[S]
├── enums.py                 SessionMode, SessionState, Operator112StageState, DDSStageState,
│                            RoleType, ActorType, ServiceType, ResourceType, ResourceStatus,
│                            KnowledgeState, DisclosurePolicy, SpeechAct, IncidentType,
│                            CallerRelationship, AgeGroup, EmotionLabel, ValueType,
│                            NotificationSeverity, StatusUpdateKind, HealthStatus,
│                            ScoringCategory, EvaluatorType, GateOutcome, GateReason,
│                            WorldEventKind, EffectKind, ClosureReason
├── events/
│   ├── types.py             EventType
│   ├── session_event.py     SessionEvent, DomainEvent
│   └── catalog.py           EventSpec, EVENT_PAYLOAD_CATALOG
├── facts/
│   ├── definitions.py       FactDefinition, FactCatalogEntry, FactCatalog, RevealedFacts
│   └── gate.py              FactRequest, GateDecision, AllowedFact, UnavailableFact,
│                            AllowedFactsPackage, evaluate_fact_access
├── layers/
│   ├── world_truth.py       WorldTruth
│   ├── caller_belief.py     CallerBelief
│   ├── operator_card.py     OperatorCard, CardRevision, CardFieldSpec, CARD_FIELDS, set_field
│   ├── handoff.py           HandoffSnapshot
│   └── copies.py            instantiate_world_truth, instantiate_caller_belief,
│                            freeze_card_to_snapshot, snapshot_to_assignment
├── caller/
│   ├── profile.py           CallerProfile
│   └── emotion.py           EmotionState, EmotionRule, apply_emotion_rules
├── session/
│   ├── session.py           SimulationSession, Incident, RoleStage, SessionParticipant,
│   │                        create_session
│   ├── policy.py            SessionPolicy, SESSION_POLICIES
│   ├── transitions.py       SESSION_TRANSITIONS, OPERATOR_112_TRANSITIONS, DDS_TRANSITIONS
│   ├── guards.py            SESSION_GUARDS, OPERATOR_112_GUARDS, DDS_GUARDS
│   ├── machine.py           SESSION_STATE_MACHINE
│   └── variants.py          SessionVariants, VariantSupport, ScenarioVariants, resolve_variants,
│                            IMPLEMENTED_VARIANT_VALUES (additive, I3 E1 — HLD 70 §70.2)
├── roles/
│   ├── module.py            Permission, ActionDescriptor, RoleModule
│   ├── registry.py          ROLE_MODULES
│   ├── visibility.py        VisibilitySource, DataVisibilityPolicy
│   ├── operator112.py       Operator112Module
│   ├── dds.py               DDSModule
│   └── edds.py              EDDSModule
├── dds/
│   ├── assignment.py        DDSAssignment
│   ├── resources.py         ResourceCapability, EtaProfile, EmergencyResource,
│   │                        RESOURCE_STATUS_TRANSITIONS
│   ├── notification.py      Notification
│   └── radio.py             RadioMessage
├── world/
│   ├── conditions.py        Condition (the declarative expression language), evaluate_condition
│   ├── effects.py           MutateWorldTruth, MutateCallerBelief, CreateNotification,
│   │                        CreateRadioMessage, AlterResourceAvailability, TriggerEvent,
│   │                        ChangeCallerEmotion, Effect
│   ├── events.py            TimedEvent, ConditionalEvent, ActionTriggeredEvent,
│   │                        SeededRandomEvent, WorldEventDefinition
│   ├── rng.py               rng_for
│   ├── engine.py            WorldState, PendingAction, ScheduledTrigger, FiredEvent, advance
│   ├── apply.py             apply_effects
│   ├── eta.py               EtaModel, ScenarioDefinedEta
│   └── resource_movement.py advance_resources
├── scenario/
│   ├── version.py           Scenario, ScenarioVersion
│   ├── sections.py          WorldTruthSection, CallerKnowledgeSection, DisclosureRulesSection,
│   │                        ExpectedResponse, PrefabHandoff, ResourceSpec
│   └── validation.py        validate_scenario_version, build_fact_definitions
└── scoring/
    ├── rules.py             ScoringRule
    ├── results.py           ScoreEvidence, ScoreResult, ScoreCategoryTotal, ScoreReport
    ├── engine.py            score
    └── evaluators/          fact_obtained.py, card_field_correct.py, card_field_present.py,
                             card_contradiction.py, service_selection.py, deadline.py,
                             workflow_action.py, resource_selection.py,
                             required_status_update.py, handoff_completeness.py, registry.py
```

## 10.2 Enums (`backend/app/domain/enums.py`, except `EventType`)

All enums are `str, Enum`; the member name is the wire value.

### SessionMode (SPEC §1, D6)
`SINGLE_ROLE`, `FULL_CYCLE_SINGLE_TRAINEE`, `MULTI_TRAINEE`, `ASSESSMENT`

### SessionState (SPEC §7, exact)
`CREATED`, `READY`, `ACTIVE`, `ROLE_TRANSITION`, `COMPLETED`, `ABORTED`

### Operator112StageState (SPEC §7, exact)
`WAITING_FOR_CALL`, `RINGING`, `CONNECTED`, `INTERVIEW`, `HANDOFF_PREPARATION`, `HANDED_OFF`,
`STAGE_COMPLETED`

### DDSStageState (SPEC §7, exact)
`RECEIVED`, `ACKNOWLEDGED`, `RESOURCE_SELECTION`, `DISPATCHED`, `EN_ROUTE`, `ARRIVED`, `WORKING`,
`RESOLVED`, `CLOSED`

### RoleType (SPEC §1, §14)
`OPERATOR_112`, `DDS`, `EDDS`

### ActorType (D5)
`TRAINEE`, `INSTRUCTOR`, `SIMULATION`, `MODEL`, `SYSTEM`

### KnowledgeState (SPEC §5, exact)
`KNOWN`, `UNKNOWN`, `INCORRECT_BELIEF`, `UNCERTAIN`

### DisclosurePolicy (SPEC §5, exact)
`SPONTANEOUS`, `ON_ASK`, `ONLY_IF_EXPLICITLY_ASKED`, `NEVER_DISCLOSE`

### ServiceType (Russian System-112 receiving services)
| Member | Legacy number | `label_ru` |
|:--|:--|:--|
| `FIRE_RESCUE` | 01 | Пожарно-спасательная служба |
| `POLICE` | 02 | Полиция |
| `AMBULANCE` | 03 | Скорая медицинская помощь |
| `GAS_SERVICE` | 04 | Аварийная газовая служба |
| `UTILITY_EMERGENCY` | — | Аварийная служба ЖКХ |
| `EDDS` | — | ЕДДС муниципального образования |

`UTILITY_EMERGENCY` is the only member the frame did not name; the demo needs a wrong-but-plausible
fifth choice so that `SERVICE_SELECTION` scoring has something to penalise.

### ResourceType
`FIRE_ENGINE`, `LADDER_TRUCK`, `RESCUE_UNIT`, `AMBULANCE_UNIT`, `RESUSCITATION_UNIT`,
`POLICE_PATROL`, `GAS_EMERGENCY_UNIT`, `UTILITY_CREW`, `FIRE_CHIEF_CAR`

### ResourceStatus (SPEC §11)
`AVAILABLE`, `SELECTED`, `DISPATCHED`, `EN_ROUTE`, `ON_SCENE`, `WORKING`, `RETURNING`,
`OUT_OF_SERVICE`, `UNAVAILABLE`

### SpeechAct (SPEC §20)
`QUESTION`, `ANSWER`, `STATEMENT`, `CONFIRMATION`, `INSTRUCTION`, `GREETING`, `CLOSING`,
`REASSURANCE`, `REPEAT_REQUEST`, `UNINTELLIGIBLE`

### IncidentType (card value domain)
`FIRE`, `MEDICAL`, `CRIME`, `TRAFFIC_ACCIDENT`, `GAS_LEAK`, `UTILITY_FAILURE`, `RESCUE`, `OTHER`

### CallerRelationship (SPEC §6 "relationship to incident")
`VICTIM`, `WITNESS`, `NEIGHBOUR`, `RELATIVE`, `PASSERBY`, `OFFICIAL`, `UNKNOWN`

### AgeGroup
`CHILD`, `TEEN`, `ADULT`, `ELDERLY`

### EmotionLabel (SPEC §6)
`CALM`, `WORRIED`, `FRIGHTENED`, `PANICKED`, `ANGRY`, `CONFUSED`, `APATHETIC`

### ValueType (fact and card value typing)
`STRING`, `INTEGER`, `FLOAT`, `BOOLEAN`, `ENUM`, `STRING_LIST`

### NotificationSeverity
`INFO`, `WARNING`, `CRITICAL`

### StatusUpdateKind (DDS → incident status updates)
`ACKNOWLEDGEMENT`, `EN_ROUTE_REPORT`, `ON_SCENE_REPORT`, `SITUATION_UPDATE`,
`ADDITIONAL_FORCES_REQUESTED`, `RESOLUTION_REPORT`

### HealthStatus (D8)
`READY`, `WARMING`, `NOT_READY`, `FATAL`

### ClosureReason
`RESOLVED`, `FALSE_CALL`, `TRANSFERRED`, `CANCELLED_BY_CALLER`

### WorldEventKind (SPEC §12, exact)
`TIMED`, `CONDITIONAL`, `ACTION_TRIGGERED`, `SEEDED_RANDOM`

### EffectKind (D7)
`MUTATE_WORLD_TRUTH`, `MUTATE_CALLER_BELIEF`, `CREATE_NOTIFICATION`, `CREATE_RADIO_MESSAGE`,
`ALTER_RESOURCE_AVAILABILITY`, `TRIGGER_EVENT`, `CHANGE_CALLER_EMOTION`

### GateOutcome / GateReason (§21, D10)
`GateOutcome`: `ALLOWED`, `ALLOWED_SPONTANEOUS`, `ALLOWED_REPEAT`, `WITHHELD`, `NOT_YET`, `UNAVAILABLE`
`GateReason`: `OK`, `NEVER_DISCLOSE`, `CALLER_DOES_NOT_KNOW`, `NOT_YET_AVAILABLE`,
`REQUIRES_EXPLICIT_QUESTION`, `UNKNOWN_FACT_ID`, `ALREADY_REVEALED`

### ScoringCategory
`INFORMATION_GATHERING`, `CARD_QUALITY`, `SERVICE_ROUTING`, `TIMELINESS`, `WORKFLOW`,
`RESOURCE_MANAGEMENT`, `COMMUNICATION`

### EvaluatorType (SPEC §28, exact ten)
`FACT_OBTAINED`, `CARD_FIELD_CORRECT`, `CARD_FIELD_PRESENT`, `CARD_CONTRADICTION`,
`SERVICE_SELECTION`, `DEADLINE`, `WORKFLOW_ACTION`, `RESOURCE_SELECTION`, `REQUIRED_STATUS_UPDATE`,
`HANDOFF_COMPLETENESS`

### EventType (`backend/app/domain/events/types.py`)

SPEC §8 (28 members, exact):
`SESSION_CREATED`, `SESSION_STARTED`, `ROLE_STAGE_STARTED`, `CALL_RINGING`, `CALL_ANSWERED`,
`USER_SPEECH_STARTED`, `USER_SPEECH_ENDED`, `ASR_PARTIAL`, `ASR_FINAL`, `CALLER_RESPONSE_PLANNED`,
`CALLER_RESPONSE_GENERATED`, `CALLER_TTS_STARTED`, `CALLER_TTS_ENDED`,
`CALLER_UTTERANCE_INTERRUPTED`, `CARD_FIELD_CHANGED`, `SERVICE_SELECTED`, `HANDOFF_CREATED`,
`HANDOFF_RECEIVED`, `DDS_ACKNOWLEDGED`, `RESOURCE_SELECTED`, `RESOURCE_DISPATCHED`,
`RESOURCE_STATUS_CHANGED`, `WORLD_EVENT_TRIGGERED`, `ROLE_STAGE_COMPLETED`,
`SCORING_RULE_EVALUATED`, `SESSION_COMPLETED`, `MODEL_FALLBACK_USED`, `MODEL_ERROR`

Additive per D5 (21 members):
`SESSION_ABORTED`, `STAGE_STATE_CHANGED`, `ROLE_TRANSITION_STARTED`, `ROLE_TRANSITION_COMPLETED`,
`SERVICE_DESELECTED`, `RESOURCE_DESELECTED`, `DDS_STATUS_UPDATE_SENT`, `DDS_INCIDENT_CLOSED`,
`NOTIFICATION_CREATED`, `NOTIFICATION_ACKNOWLEDGED`, `RADIO_MESSAGE_CREATED`,
`WORLD_TRUTH_MUTATED`, `CALLER_BELIEF_MUTATED`, `CALLER_EMOTION_CHANGED`, `CALL_ENDED`,
`DIALOGUE_INTERPRETED`, `FACT_GATE_EVALUATED`, `FACTS_DELIVERED`, `TRANSPORT_DISCONNECTED`,
`TRANSPORT_RECONNECTED`, `INFERENCE_HEALTH_CHANGED`

Total: 49 members.

## 10.3 The four information layers (D3, SPEC §3)

Four types, four modules, four storage locations. No type inherits from, embeds, or holds a reference
to another layer's type. Conversion is always an explicit deep copy in exactly one named function.

### `WorldTruth` — `backend/app/domain/layers/world_truth.py`
| Field | Type | Note |
|:--|:--|:--|
| `incident_id` | `IncidentId` | |
| `revision` | `int` | starts at 0, +1 per mutation |
| `facts` | `dict[str, FactValue]` | `FactValue = str \| int \| float \| bool \| list[str] \| None` |
| `value_types` | `dict[str, ValueType]` | from the scenario, immutable after instantiation |

Written by scenario instantiation and the WorldEvent engine only (D3).

### `CallerBelief` — `backend/app/domain/layers/caller_belief.py`
| Field | Type | Note |
|:--|:--|:--|
| `incident_id` | `IncidentId` | |
| `revision` | `int` | |
| `facts` | `dict[str, FactValue]` | the caller's values, which may be wrong or `None` |
| `knowledge` | `dict[str, KnowledgeState]` | |
| `certainty` | `dict[str, float]` | 0.0–1.0 |
| `emotion` | `EmotionState` | current emotion + stress level |
| `revealed_fact_ids` | `frozenset[str]` | maintained by `FACTS_DELIVERED`, not by the gate |

### `OperatorCard` — `backend/app/domain/layers/operator_card.py`
See §10.6. Written by trainee commands only.

### `HandoffSnapshot` — `backend/app/domain/layers/handoff.py`
Immutable frozen model. See §10.7.

### Copy functions — `backend/app/domain/layers/copies.py`

```python
def instantiate_world_truth(version: ScenarioVersion, incident_id: IncidentId) -> WorldTruth: ...
def instantiate_caller_belief(version: ScenarioVersion, incident_id: IncidentId) -> CallerBelief: ...
def freeze_card_to_snapshot(
    card: OperatorCard,
    card_revision_id: CardRevisionId,
    recipient_services: tuple[ServiceType, ...],
    created_by_user_id: UserId,
    at_offset_ms: int,
) -> HandoffSnapshot: ...
def snapshot_to_assignment(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId, at_offset_ms: int
) -> DDSAssignment: ...
# additive, E9 — the fan-out §10.7's "one assignment per recipient service" asks for
def snapshot_to_assignments(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId, at_offset_ms: int
) -> tuple[DDSAssignment, ...]: ...
```

`snapshot_to_assignments` (additive, E9) is `snapshot_to_assignment` for every entry of
`recipient_services`, in that order: one `DDSAssignment` *leg* per receiving service, all
belonging to the same DDS `RoleStage` and all starting in `RECEIVED`. Its `assignment_id` carries
the service type inside the `uuid5` name, because the legs of one handoff share every other
component of that name. `snapshot_to_assignment` keeps its signature and its first-service
reading; the handoff use case persists the fan-out.

There is deliberately **no** function from `WorldTruth` to `OperatorCard`, from `WorldTruth` to
`HandoffSnapshot`, or from `WorldTruth` to `DDSAssignment`. `freeze_card_to_snapshot` performs a deep
copy of scalar values; the snapshot shares no mutable object with the card.

## 10.4 FactDefinition (D4, SPEC §5)

`backend/app/domain/facts/definitions.py`

A `FactDefinition` is not stored in the scenario file — it is **joined at load time** from the three
scenario sections keyed by the same `fact_id`:

| `FactDefinition` field | Type | Source section | Source key |
|:--|:--|:--|:--|
| `fact_id` | `str` | join key | `world_truth.facts` key |
| `world_value` | `FactValue` | `world_truth.facts[fact_id]` | `world_value` |
| `value_type` | `ValueType` | `world_truth.facts[fact_id]` | `value_type` |
| `label_ru` | `str` | `world_truth.facts[fact_id]` | `label_ru` |
| `caller_value` | `FactValue` | `caller_knowledge.facts[fact_id]` | `caller_value` |
| `knowledge` | `KnowledgeState` | `caller_knowledge.facts[fact_id]` | `knowledge` |
| `certainty` | `float` (0.0–1.0, default 1.0) | `caller_knowledge.facts[fact_id]` | `certainty` |
| `policy` | `DisclosurePolicy` | `disclosure_rules.facts[fact_id]` | `policy` |
| `aliases_ru` | `tuple[str, ...]` | `disclosure_rules.facts[fact_id]` | `aliases_ru` |
| `categories` | `tuple[str, ...]` | `disclosure_rules.facts[fact_id]` | `categories` |
| `available_after` | `AvailableAfter \| None` | `disclosure_rules.facts[fact_id]` | `available_after` |
| `enum_name` | `str \| None` (default `None`) | `world_truth.facts[fact_id]` | `enum_name` |

`AvailableAfter` = `{"sim_time_ms": int}` **or** `{"world_event_id": str}` **or** `{"condition": Condition}`
(exactly one key).

`enum_name` (E13-B4 item 0): this table previously dropped `WorldFactSpec.enum_name` at the join, so
an `ENUM`-typed value had no route to a Russian rendering (§10.12's `AllowedFact.value_ru`). Joined
through unchanged, `world_truth.facts[fact_id].enum_name`, `None` for every non-`ENUM` fact.

`build_fact_definitions(version) -> dict[str, FactDefinition]` performs the join and raises
`ScenarioValidationError` on the D4 rules (§10.15).

`FactCatalogEntry` is the **only** fact structure the interpreter LLM ever sees (D10):
`{fact_id: str, label_ru: str, aliases_ru: tuple[str, ...], categories: tuple[str, ...]}` — no values.
`FactCatalog = tuple[FactCatalogEntry, ...]`; built by `FactCatalog.from_definitions(defs)`.

## 10.5 CallerProfile and EmotionRule (SPEC §6, D4)

`backend/app/domain/caller/profile.py`

| Field | Type | Note |
|:--|:--|:--|
| `identity_ru` | `str` | e.g. "Соседка из квартиры 41" |
| `relationship` | `CallerRelationship` | SPEC §6 "relationship to incident" |
| `language` | `str` | BCP-47, `"ru-RU"` |
| `voice_id` | `str` | TTS voice identifier |
| `age_group` | `AgeGroup` | |
| `baseline_emotion` | `EmotionLabel` | scenario data, never mutated |
| `cooperativeness` | `float` 0.0–1.0 | |
| `verbosity` | `float` 0.0–1.0 | |
| `confusion` | `float` 0.0–1.0 | |
| `interruption_tendency` | `float` 0.0–1.0 | SPEC §6 "interruption tendency" |
| `speaking_rate` | `float` 0.5–2.0 | relative to the voice's nominal rate |
| `baseline_stress_level` | `float` 0.0–1.0 | SPEC §6 "stress level" baseline |
| `persona_whitelist_ru` | `tuple[str, ...]` | proper nouns the validator may allow (D10) |

`current_emotion` and `stress_level` are **not** profile fields: per D4 they live in
`CallerBelief.emotion`.

`backend/app/domain/caller/emotion.py`

```python
class EmotionState(BaseModel):
    emotion: EmotionLabel
    stress_level: float           # 0.0-1.0, clamped

class EmotionRule(BaseModel):
    rule_id: str
    trigger: EmotionTrigger       # see below
    set_emotion: EmotionLabel | None = None
    stress_delta: float = 0.0     # added, then clamped to [0.0, 1.0]
    max_applications: int | None = None

def apply_emotion_rules(
    state: EmotionState,
    rules: tuple[EmotionRule, ...],
    trigger: EmotionTrigger,
    applied_counts: Mapping[str, int],
) -> tuple[EmotionState, str | None]: ...
```

`EmotionTrigger` is a tagged union, deterministic only — no model output feeds it:
`{"kind": "WORLD_EVENT", "world_event_id": str}`,
`{"kind": "EVENT_TYPE", "event_type": EventType}`,
`{"kind": "FACT_REVEALED", "fact_id": str}`,
`{"kind": "SIM_TIME", "at_ms": int}`,
`{"kind": "INTERRUPTION_COUNT", "at_least": int}`.

Rules are applied in scenario declaration order; the first matching rule that has applications left
wins, and its `rule_id` is returned for `CALLER_EMOTION_CHANGED.emotion_rule_id`.

## 10.6 OperatorCard (SPEC §9, §3)

`backend/app/domain/layers/operator_card.py`

```python
class OperatorCard(BaseModel):
    card_id: CardId
    incident_id: IncidentId
    values: dict[str, FactValue]      # keyed by the dotted field path below
    revision_counter: int             # 0 before the first mutation

class CardRevision(BaseModel):
    revision_id: CardRevisionId
    card_id: CardId
    revision_no: int                  # 1-based, dense, per card
    field_path: str
    previous_value: FactValue
    new_value: FactValue
    actor: ActorRef                   # {actor_type: ActorType, actor_id: UserId | None}
    at_offset_ms: int

class CardFieldSpec(BaseModel):
    field_path: str
    value_type: ValueType
    enum_name: str | None             # for ValueType.ENUM
    label_ru: str
    scoring_relevant: bool
    required_for_handoff: bool        # advisory only: a missing field never blocks a handoff (§10)

CARD_FIELDS: tuple[CardFieldSpec, ...]
```

### Card mutation API (domain terms)

```python
def set_field(
    card: OperatorCard,
    field_path: str,
    new_value: FactValue,
    actor: ActorRef,
    at_offset_ms: int,
    revision_id: CardRevisionId,
) -> tuple[OperatorCard, CardRevision, DomainEvent]: ...
```

Pure: returns a new `OperatorCard`, the `CardRevision` recording
`{revision_id, field_path, previous_value, new_value, actor, at}`, and one `CARD_FIELD_CHANGED`
`DomainEvent` carrying the same five values plus `card_id` and `value_type`. Raises `CardFieldError`
when `field_path` is not in `CARD_FIELDS` or the value does not match the spec's `value_type`.
Setting a field to its current value is a no-op: no revision, no event. Only `ActorType.TRAINEE` and
`ActorType.INSTRUCTOR` may call it — ASR never does (SPEC §9, §42 test 4).

### Field list (pragmatic УКИО subset)

`✔` in **Scoring** marks paths a `ScoringRule` may reference.

| `field_path` | `value_type` | `label_ru` | Scoring |
|:--|:--|:--|:--|
| `incident.type` | ENUM(`IncidentType`) | Тип происшествия | ✔ |
| `incident.subtype` | STRING | Уточнение типа | |
| `incident.reported_at_offset_ms` | INTEGER | Время приёма вызова | |
| `address.locality` | STRING | Населённый пункт | ✔ |
| `address.street` | STRING | Улица | ✔ |
| `address.house` | STRING | Дом | ✔ |
| `address.building` | STRING | Корпус / строение | ✔ |
| `address.entrance` | STRING | Подъезд | ✔ |
| `address.floor` | INTEGER | Этаж | ✔ |
| `address.apartment` | STRING | Квартира | ✔ |
| `address.landmark` | STRING | Ориентир | |
| `address.comment` | STRING | Примечание к адресу | |
| `caller.full_name` | STRING | ФИО заявителя | ✔ |
| `caller.phone` | STRING | Телефон заявителя | ✔ |
| `caller.relationship` | ENUM(`CallerRelationship`) | Отношение к происшествию | |
| `caller.callback_possible` | BOOLEAN | Возможен обратный вызов | |
| `description.text` | STRING | Описание происшествия | ✔ |
| `people.total_affected` | INTEGER | Всего людей в опасности | ✔ |
| `people.victims_count` | INTEGER | Число пострадавших | ✔ |
| `people.trapped_count` | INTEGER | Число заблокированных | ✔ |
| `people.children_present` | BOOLEAN | Есть дети | ✔ |
| `people.evacuation_needed` | BOOLEAN | Требуется эвакуация | |
| `people.notes` | STRING | Примечания по людям | |
| `hazards.open_fire` | BOOLEAN | Открытое горение | ✔ |
| `hazards.smoke` | BOOLEAN | Задымление | ✔ |
| `hazards.gas_leak` | BOOLEAN | Утечка газа | ✔ |
| `hazards.electrical` | BOOLEAN | Электроопасность | |
| `hazards.chemical` | BOOLEAN | Химическая опасность | |
| `hazards.collapse_risk` | BOOLEAN | Угроза обрушения | |
| `hazards.other` | STRING | Иная опасность | |
| `flags.threat_to_life` | BOOLEAN | Угроза жизни | ✔ |
| `flags.mass_event` | BOOLEAN | Массовое происшествие | |
| `flags.repeat_call` | BOOLEAN | Повторное обращение | |
| `flags.requires_escalation` | BOOLEAN | Требует эскалации | |
| `flags.false_call` | BOOLEAN | Ложный вызов | ✔ |
| `notes.free_text` | STRING | Дополнительная информация | |
| `recipients.services` | STRING_LIST (`ServiceType` names) | Службы-получатели | ✔ |
| `recipients.comment` | STRING | Комментарий для служб | |

`required_for_handoff` is `True` for exactly `incident.type`, `address.locality`,
`address.street`, `address.house`, `caller.phone`, `description.text`, `flags.threat_to_life` and
`recipients.services` — advisory only, a missing field never blocks a handoff (SPEC §10).

`recipients.services` is mutated only through the dedicated service commands, which emit
`SERVICE_SELECTED` / `SERVICE_DESELECTED` **in addition to** `CARD_FIELD_CHANGED`, so both the
service evaluators and the card evaluators are self-sufficient (D5).

## 10.7 Handoff, DDS work item, resources, notifications, radio

### `HandoffSnapshot` — `backend/app/domain/layers/handoff.py`
Frozen (`model_config = ConfigDict(frozen=True)`); the DB trigger enforces the same at rest (D3).

| Field | Type |
|:--|:--|
| `snapshot_id` | `SnapshotId` |
| `incident_id` | `IncidentId` |
| `card_id` | `CardId` |
| `card_revision_id` | `CardRevisionId` (the last revision included) |
| `card_values` | `Mapping[str, FactValue]` (deep copy of `OperatorCard.values`) |
| `recipient_services` | `tuple[ServiceType, ...]` |
| `created_by_user_id` | `UserId` |
| `created_at_offset_ms` | `int` |
| `content_sha256` | `str` (over canonical JSON of `card_values` + `recipient_services`) |

### `DDSAssignment` — `backend/app/domain/dds/assignment.py`

| Field | Type |
|:--|:--|
| `assignment_id` | `AssignmentId` |
| `incident_id` | `IncidentId` |
| `role_stage_id` | `RoleStageId` |
| `snapshot_id` | `SnapshotId` |
| `service_type` | `ServiceType` (the receiving profile service) |
| `state` | `DDSStageState` |
| `received_at_offset_ms` | `int` |
| `acknowledged_at_offset_ms` | `int \| None` |
| `dispatched_at_offset_ms` | `int \| None` |
| `closed_at_offset_ms` | `int \| None` |
| `closure_reason` | `ClosureReason \| None` |
| `selected_resource_ids` | `tuple[ResourceId, ...]` |
| `dispatched_resource_ids` | `tuple[ResourceId, ...]` |

One assignment per recipient service. The assignment exposes **no** accessor to `WorldTruth`; per D3
the DDS application service is constructed without a world-truth repository.

### `EmergencyResource` — `backend/app/domain/dds/resources.py` (SPEC §11)

| Field | Type | SPEC §11 item |
|:--|:--|:--|
| `resource_id` | `ResourceId` | id |
| `service_type` | `ServiceType` | service_type |
| `resource_type` | `ResourceType` | resource_type |
| `callsign` | `str` (e.g. `"АЦ-1"`) | callsign/name |
| `name_ru` | `str` | callsign/name |
| `capabilities` | `frozenset[ResourceCapability]` | capabilities |
| `current_status` | `ResourceStatus` | current_status |
| `availability` | `ResourceAvailability` | scenario-defined availability |
| `eta` | `EtaProfile` | scenario-defined ETA/travel-time data |
| `home_station_ru` | `str` | — |
| `crew_size` | `int` | — |
| `status_changed_at_offset_ms` | `int` (default `0`) | — (the moment `current_status` was entered) |

`ResourceCapability` (str enum): `FIRE_SUPPRESSION`, `HIGH_RISE_ACCESS`, `LADDER_RESCUE`,
`TECHNICAL_RESCUE`, `SMOKE_DIVING`, `BASIC_LIFE_SUPPORT`, `ADVANCED_LIFE_SUPPORT`, `BURN_CARE`,
`PUBLIC_ORDER`, `TRAFFIC_CONTROL`, `AREA_CORDON`, `GAS_SHUTOFF`, `GAS_LEAK_DETECTION`,
`POWER_SHUTOFF`, `WATER_SUPPLY`, `COMMAND_AND_CONTROL`.

`ResourceAvailability` = `{available_from_ms: int = 0, available_until_ms: int | None = None,
initial_status: ResourceStatus = AVAILABLE}`.

`EtaProfile` = `{turnout_delay_seconds: int, travel_time_seconds: int, setup_seconds: int,
on_scene_work_seconds: int, return_time_seconds: int}`. These five values are the only ETA input;
the `EtaModel` port implementation `ScenarioDefinedEta` (D7, application layer) reads them verbatim.

### Resource status state machine — `RESOURCE_STATUS_TRANSITIONS`

| From | Trigger | To | Who may fire | Guard |
|:--|:--|:--|:--|:--|
| `AVAILABLE` | `select` | `SELECTED` | TRAINEE (DDS) | assignment state is one of `RESOURCE_SELECTION`, `EN_ROUTE`, `ARRIVED`, `WORKING` (widened, E9 — see below); resource within its availability window |
| `SELECTED` | `deselect` | `AVAILABLE` | TRAINEE (DDS) | resource not yet dispatched |
| `SELECTED` | `dispatch` | `DISPATCHED` | TRAINEE (DDS) | assignment state is one of `RESOURCE_SELECTION`, `EN_ROUTE`, `ARRIVED`, `WORKING` (widened, E9 — see below) |
| `DISPATCHED` | `depart` | `EN_ROUTE` | SIMULATION | `now_ms ≥ dispatched_at + turnout_delay_seconds·1000` |
| `EN_ROUTE` | `arrive` | `ON_SCENE` | SIMULATION | `now_ms ≥ departed_at + travel_time_seconds·1000` |
| `ON_SCENE` | `start_work` | `WORKING` | SIMULATION | `now_ms ≥ arrived_at + setup_seconds·1000` |
| `WORKING` | `finish_work` | `RETURNING` | SIMULATION | `now_ms ≥ work_started_at + on_scene_work_seconds·1000` **or** assignment reached `RESOLVED` |
| `RETURNING` | `return_to_base` | `AVAILABLE` | SIMULATION | `now_ms ≥ returning_at + return_time_seconds·1000` |
| `DISPATCHED`, `EN_ROUTE`, `ON_SCENE`, `WORKING` | `breakdown` | `OUT_OF_SERVICE` | SIMULATION | an `AlterResourceAvailability` effect targeted this resource |
| `OUT_OF_SERVICE` | `repair` | `AVAILABLE` | SIMULATION | effect with `restore = true` |
| `AVAILABLE` | `make_unavailable` | `UNAVAILABLE` | SIMULATION | outside `availability` window, or effect |
| `UNAVAILABLE` | `make_available` | `AVAILABLE` | SIMULATION | inside `availability` window, or effect |

Every fired transition emits `RESOURCE_STATUS_CHANGED`.

**Repair (E9): `dispatch_additional` was unreachable as originally written.** Its guard needs a
`SELECTED` unit, but `select` was guarded by "assignment state is `RESOURCE_SELECTION`",
`select_resource` was not an available action in `EN_ROUTE` / `ARRIVED` / `WORKING`, the only way
back to `RESOURCE_SELECTION` is from `DISPATCHED` and only before the first unit departs, and
`dispatch` takes *every* selected unit — so nothing could ever be `SELECTED` in the three states
`dispatch_additional` fires from. The demo scenario needs the reinforcement it describes
(`fire_spreads` at 180 s, `ac2_breakdown`). The smallest repair, applied above and in §10.9:
`select_resource` / `deselect_resource` become available actions in `EN_ROUTE`, `ARRIVED` and
`WORKING`, and the two unit-level guards (`select`, `dispatch`) accept an assignment state in
`{RESOURCE_SELECTION, EN_ROUTE, ARRIVED, WORKING}`. Nothing else changes: `deselect` keeps its
"not yet dispatched" guard, so reinforcement never un-sends a unit that is already moving.

### `Notification` — `backend/app/domain/dds/notification.py`
`{notification_id, incident_id, audience_role: RoleType, severity: NotificationSeverity,
title_ru: str, body_ru: str, created_at_offset_ms: int, source_world_event_id: str | None,
acknowledged_at_offset_ms: int | None}`

### `RadioMessage` — `backend/app/domain/dds/radio.py`
`{radio_message_id, incident_id, from_callsign: str, to_role: RoleType, text_ru: str,
resource_id: ResourceId | None, created_at_offset_ms: int, source_world_event_id: str | None}`

## 10.8 Generic state machine and the three transition tables (D6, SPEC §7)

`backend/app/domain/common/state_machine.py`

```python
S = TypeVar("S", bound=Enum)

class Transition(BaseModel, Generic[S]):
    source: S
    trigger: str
    target: S
    allowed_actors: frozenset[ActorType]
    allowed_roles: frozenset[RoleType]          # empty = not role-restricted
    guard_name: str | None                      # key into the guard registry
    emits: EventType | None

TransitionTable = Mapping[tuple[S, str], Transition[S]]

class StateMachine(Generic[S]):
    def __init__(
        self,
        table: TransitionTable[S],
        guards: Mapping[str, Callable[[GuardContext], bool]],
    ) -> None: ...
    def can_fire(self, state: S, trigger: str, ctx: GuardContext) -> bool: ...
    def fire(self, state: S, trigger: str, ctx: GuardContext) -> S: ...
    def available_triggers(self, state: S, ctx: GuardContext) -> tuple[str, ...]: ...
```

`fire` raises `InvalidTransitionError(state, trigger, reason)` when the `(state, trigger)` pair is
absent, the actor/role is not allowed, or the guard returns `False` (SPEC §7, §42 test 8).
`GuardContext` is a frozen value object carrying `actor: ActorRef`, `role_type: RoleType | None`,
`now_ms: int`, `session: SimulationSession`, `stage: RoleStage`, and read-only projections the guards
need (`card`, `assignment`, `resources`, `world_flags`). It never carries a repository. It also
carries `runtime: GuardRuntime` — the frozen projection of the facts a pure guard cannot derive from
the aggregate, which the application layer computes from the event log, the inference health
registry and the transport ports: `scenario_valid`, `inference_ready`, `transport_ready`,
`first_finalized_turn`, `call_connected`, `call_ended`, `resolution_condition_met` (all `bool`,
default `false`) and `transition_started_ms: int | None` (default `null`). The defaults deny, so a
guard whose runtime facts were never projected blocks its transition rather than allowing it.

The guard *callables* named by `Transition.guard_name` live in `session/guards.py` as the three
registries `SESSION_GUARDS`, `OPERATOR_112_GUARDS` and `DDS_GUARDS`, one per table above;
`session/machine.py` wires the first into `SESSION_STATE_MACHINE` and each `RoleModule` wires its
own (`EDDSModule`'s transition-less stub has no guard names to register).

### Session state machine — `SESSION_TRANSITIONS`

| From | Trigger | To | Who may fire | Guard |
|:--|:--|:--|:--|:--|
| `CREATED` | `validate` | `READY` | SYSTEM | `guard_scenario_valid_and_participants_assigned`: the scenario version passed validation, `role_chain` roles are all implemented RoleModules, and `SessionPolicy.assignment_rule` is satisfiable for the participant set |
| `CREATED` | `abort` | `ABORTED` | INSTRUCTOR, SYSTEM | — |
| `READY` | `start` | `ACTIVE` | INSTRUCTOR | `guard_inference_ready`: every required inference component is `READY`, or `REQUIRE_INFERENCE_READY` is false |
| `READY` | `abort` | `ABORTED` | INSTRUCTOR, SYSTEM | — |
| `ACTIVE` | `begin_role_transition` | `ROLE_TRANSITION` | SYSTEM | `guard_stage_terminal_and_next_exists`: the current `RoleStage` is in its terminal state and `role_chain` has a next entry |
| `ACTIVE` | `complete` | `COMPLETED` | SYSTEM | `guard_stage_terminal_and_last`: current `RoleStage` terminal and it is the last `role_chain` entry |
| `ACTIVE` | `abort` | `ABORTED` | INSTRUCTOR, SYSTEM | — |
| `ROLE_TRANSITION` | `finish_role_transition` | `ACTIVE` | SYSTEM | `guard_pause_elapsed_and_next_assigned`: `now_ms ≥ transition_started_ms + policy.transition_pause_seconds·1000` and the next stage has an assigned participant |
| `ROLE_TRANSITION` | `abort` | `ABORTED` | INSTRUCTOR, SYSTEM | — |
| `COMPLETED` | — | — | — | terminal |
| `ABORTED` | — | — | — | terminal |

`validate`/`start`/`complete` emit `SESSION_CREATED` is not one of these — `SESSION_CREATED` is emitted
by the creation use case before the machine exists. `start` emits `SESSION_STARTED`, `complete` emits
`SESSION_COMPLETED`, `abort` emits `SESSION_ABORTED`, `begin_role_transition` emits
`ROLE_TRANSITION_STARTED`, `finish_role_transition` emits `ROLE_TRANSITION_COMPLETED`.

**Simulated time does not run during a role transition** (E17 ruling R1). `begin_role_transition`
records the offset it fired at on the session (`role_transition_started_offset_ms`,
`20-db-schema.md` §20.3) and from that moment every reader of "sim now"
(`app.application.simulation.sim_time`) is frozen at it: the world engine applies nothing, and
any event appended meanwhile carries the frozen offset. `finish_role_transition` is the **one
writer of `paused_total_ms`**: it adds the wall-clock length of the interval it is closing and
clears the stamp, so the clock resumes from exactly the value it froze at — the next `RoleStage`'s
`started_at_offset_ms`, `ROLE_TRANSITION_COMPLETED` and `ROLE_STAGE_STARTED` all carry that same
offset rather than one hand-over later. Consequences: a `DEADLINE` scoring rule (§10.14) never
measures a hand-over pause, a scenario ETA is not consumed by one, and two runs of one scenario
whose pauses differ produce the same event offsets (D7 determinism rule 5).

`guard_pause_elapsed_and_next_assigned` is the one place that must *not* see the frozen clock —
a clock frozen at `transition_started_ms` could never reach `transition_started_ms + pause`. Its
`now_ms`, and the `SessionDetail.monotonic_offset_ms` countdown that mirrors it, are the same
subtraction without the freeze (`sim_time.transition_clock_ms`). There is no `pauseSession` /
`resumeSession` operation and no pause table: the intervals are `ROLE_TRANSITION_STARTED` to
`ROLE_TRANSITION_COMPLETED` in the log.

### Operator 112 stage machine — `OPERATOR_112_TRANSITIONS`

| From | Trigger | To | Who may fire | Guard |
|:--|:--|:--|:--|:--|
| `WAITING_FOR_CALL` | `ring` | `RINGING` | SIMULATION | `guard_session_active_and_transport_ready`: session is `ACTIVE` and the `CallTransport` reports the media plane can take a call — the LiveKit server is reachable and the voice-agent heartbeat (`voice:health:vad`, §40.6) is `READY` |
| `RINGING` | `answer` | `CONNECTED` | TRAINEE (OPERATOR_112) | `guard_participant_assigned_to_stage` |
| `CONNECTED` | `begin_interview` | `INTERVIEW` | SIMULATION | `guard_first_finalized_turn`: the first `ASR_FINAL` for this call has been appended |
| `INTERVIEW` | `open_handoff_preparation` | `HANDOFF_PREPARATION` | TRAINEE (OPERATOR_112) | — (an incomplete card must stay possible: SPEC §10) |
| `HANDOFF_PREPARATION` | `back_to_interview` | `INTERVIEW` | TRAINEE (OPERATOR_112) | `guard_call_still_connected` |
| `HANDOFF_PREPARATION` | `create_handoff` | `HANDED_OFF` | TRAINEE (OPERATOR_112) | `guard_at_least_one_recipient_service`: `len(card.values["recipients.services"]) ≥ 1` |
| `HANDED_OFF` | `complete_stage` | `STAGE_COMPLETED` | TRAINEE (OPERATOR_112), SIMULATION | `guard_call_ended`: `CALL_ENDED` has been appended for this call |
| `WAITING_FOR_CALL`, `RINGING`, `CONNECTED`, `INTERVIEW`, `HANDOFF_PREPARATION`, `HANDED_OFF` | `abort_stage` | `STAGE_COMPLETED` | INSTRUCTOR, SYSTEM | fired only as part of session `abort` |
| `STAGE_COMPLETED` | — | — | — | terminal |

`transport_ready` deliberately does **not** mean "the caller has joined the room": D9 has the
voice-agent join on the `voice:join` message the backend publishes *at* `CALL_RINGING`, so a guard
that waited for a participant would wait for the room this very transition names. It means what its
name says — the media plane can take a call — and is read through
`app.application.ports.call_transport_status.CallTransportStatus` (E11).

`ring` emits `CALL_RINGING`, `answer` emits `CALL_ANSWERED`, `create_handoff` emits
`HANDOFF_CREATED`, `complete_stage` emits `ROLE_STAGE_COMPLETED`; every transition additionally emits
`STAGE_STATE_CHANGED`.

### DDS stage machine — `DDS_TRANSITIONS`

| From | Trigger | To | Who may fire | Guard |
|:--|:--|:--|:--|:--|
| `RECEIVED` | `acknowledge` | `ACKNOWLEDGED` | TRAINEE (DDS) | `guard_participant_assigned_to_stage` |
| `ACKNOWLEDGED` | `open_resource_selection` | `RESOURCE_SELECTION` | TRAINEE (DDS) | — |
| `RESOURCE_SELECTION` | `dispatch` | `DISPATCHED` | TRAINEE (DDS) | `guard_at_least_one_selected_available`: at least one resource is in `SELECTED` |
| `RESOURCE_SELECTION` | `back_to_acknowledged` | `ACKNOWLEDGED` | TRAINEE (DDS) | `guard_no_resource_selected` |
| `DISPATCHED` | `open_resource_selection` | `RESOURCE_SELECTION` | TRAINEE (DDS) | `guard_additional_dispatch_allowed`: no dispatched resource has reached `EN_ROUTE` yet |
| `DISPATCHED` | `first_en_route` | `EN_ROUTE` | SIMULATION | `guard_any_dispatched_reached(EN_ROUTE)` |
| `EN_ROUTE` | `first_arrived` | `ARRIVED` | SIMULATION | `guard_any_dispatched_reached(ON_SCENE)` |
| `ARRIVED` | `work_started` | `WORKING` | SIMULATION | `guard_any_dispatched_reached(WORKING)` |
| `WORKING` | `incident_resolved` | `RESOLVED` | SIMULATION | `guard_resolution_condition`: the scenario's `expected_response.resolution_condition` evaluates true |
| `RESOLVED` | `close` | `CLOSED` | TRAINEE (DDS) | — |
| `EN_ROUTE`, `ARRIVED`, `WORKING` | `dispatch_additional` | *(self)* | TRAINEE (DDS) | `guard_at_least_one_selected_available` — a self-transition: extra units may be added without losing progress |
| `RECEIVED`…`RESOLVED` | `abort_stage` | `CLOSED` | INSTRUCTOR, SYSTEM | fired only as part of session `abort`; sets `closure_reason = CANCELLED_BY_CALLER` only if the scenario says so, otherwise leaves it `None` |
| `CLOSED` | — | — | — | terminal |

`acknowledge` emits `DDS_ACKNOWLEDGED`, `dispatch` and `dispatch_additional` emit
`RESOURCE_DISPATCHED`, `close` emits `DDS_INCIDENT_CLOSED` then `ROLE_STAGE_COMPLETED`; every
transition additionally emits `STAGE_STATE_CHANGED`. Simulation-fired triggers pass through the same
machine and are rejected the same way when invalid (D6).

## 10.9 Roles (SPEC §14, D6, D3)

`backend/app/domain/roles/module.py`

```python
class Permission(str, Enum):
    ANSWER_CALL = "ANSWER_CALL"
    END_CALL = "END_CALL"
    EDIT_CARD = "EDIT_CARD"
    SELECT_SERVICES = "SELECT_SERVICES"
    CREATE_HANDOFF = "CREATE_HANDOFF"
    VIEW_HANDOFF = "VIEW_HANDOFF"
    ACKNOWLEDGE_ASSIGNMENT = "ACKNOWLEDGE_ASSIGNMENT"
    SELECT_RESOURCES = "SELECT_RESOURCES"
    DISPATCH_RESOURCES = "DISPATCH_RESOURCES"
    SEND_STATUS_UPDATE = "SEND_STATUS_UPDATE"
    CLOSE_INCIDENT = "CLOSE_INCIDENT"
    ACKNOWLEDGE_NOTIFICATION = "ACKNOWLEDGE_NOTIFICATION"
    VIEW_RESOURCE_BOARD = "VIEW_RESOURCE_BOARD"
    VIEW_TRANSCRIPT = "VIEW_TRANSCRIPT"

class ActionDescriptor(BaseModel):
    action_id: str          # equals the state-machine trigger where one exists
    label_ru: str
    permission: Permission
    trigger: str | None     # None = a non-transition command (e.g. edit_card)

class RoleModule(Protocol):
    role_type: RoleType
    implemented: bool
    permissions: frozenset[Permission]
    state_machine: StateMachine[Any]
    visibility_policy: DataVisibilityPolicy
    ui_schema: Mapping[str, Any]

    def available_actions(self, stage_state: Enum) -> tuple[ActionDescriptor, ...]: ...
    def initial_state(self) -> Enum: ...
    def terminal_states(self) -> frozenset[Enum]: ...

ROLE_MODULES: Mapping[RoleType, RoleModule]
```

`backend/app/domain/roles/visibility.py`

```python
class VisibilitySource(str, Enum):
    OPERATOR_CARD = "OPERATOR_CARD"
    CARD_REVISIONS = "CARD_REVISIONS"
    HANDOFF_SNAPSHOT = "HANDOFF_SNAPSHOT"
    DDS_ASSIGNMENT = "DDS_ASSIGNMENT"
    RESOURCE_BOARD = "RESOURCE_BOARD"
    NOTIFICATIONS = "NOTIFICATIONS"
    RADIO_MESSAGES = "RADIO_MESSAGES"
    TRANSCRIPT = "TRANSCRIPT"
    CALL_STATE = "CALL_STATE"
    SCORE_REPORT = "SCORE_REPORT"
    WORLD_TRUTH = "WORLD_TRUTH"          # INSTRUCTOR / report context only (D11)
    CALLER_BELIEF = "CALLER_BELIEF"      # INSTRUCTOR only
    GATE_INTERNALS = "GATE_INTERNALS"    # INSTRUCTOR only

class DataVisibilityPolicy(BaseModel):
    role_type: RoleType
    sources: frozenset[VisibilitySource]          # whitelist, never a blacklist
    visible_event_types: frozenset[EventType]     # whitelist for the realtime channel

    def may_read(self, source: VisibilitySource) -> bool: ...
    def may_receive(self, event_type: EventType) -> bool: ...
```

Visibility is structural (D3): a policy that omits `WORLD_TRUTH` is paired with an application service
constructed without a world-truth repository, so the data cannot be reached even by mistake.

### `Operator112Module` — `backend/app/domain/roles/operator112.py`
- `role_type = OPERATOR_112`, `implemented = True`, `state_machine = StateMachine(OPERATOR_112_TRANSITIONS, …)`
- `permissions` = `{ANSWER_CALL, END_CALL, EDIT_CARD, SELECT_SERVICES, CREATE_HANDOFF, VIEW_TRANSCRIPT, ACKNOWLEDGE_NOTIFICATION}`
- `visibility_policy.sources` = `{OPERATOR_CARD, CARD_REVISIONS, TRANSCRIPT, CALL_STATE, NOTIFICATIONS}`
- `available_actions(state)`:

| State | Actions (`action_id` / `label_ru`) |
|:--|:--|
| `WAITING_FOR_CALL` | — |
| `RINGING` | `answer` / Ответить |
| `CONNECTED` | `edit_card` / Заполнить карточку; `end_call` / Завершить вызов |
| `INTERVIEW` | `edit_card` / Заполнить карточку; `select_services` / Выбрать службы; `open_handoff_preparation` / Подготовить передачу; `end_call` / Завершить вызов |
| `HANDOFF_PREPARATION` | `edit_card`; `select_services`; `create_handoff` / Передать в ДДС; `back_to_interview` / Вернуться к опросу; `end_call` |
| `HANDED_OFF` | `end_call` / Завершить вызов; `complete_stage` / Завершить этап |
| `STAGE_COMPLETED` | — |

### `DDSModule` — `backend/app/domain/roles/dds.py`
- `role_type = DDS`, `implemented = True`, `state_machine = StateMachine(DDS_TRANSITIONS, …)`
- `permissions` = `{VIEW_HANDOFF, ACKNOWLEDGE_ASSIGNMENT, SELECT_RESOURCES, DISPATCH_RESOURCES, SEND_STATUS_UPDATE, CLOSE_INCIDENT, VIEW_RESOURCE_BOARD, ACKNOWLEDGE_NOTIFICATION}`
- `visibility_policy.sources` = `{HANDOFF_SNAPSHOT, DDS_ASSIGNMENT, RESOURCE_BOARD, NOTIFICATIONS, RADIO_MESSAGES}` — **no** `OPERATOR_CARD`, **no** `WORLD_TRUTH`, **no** `TRANSCRIPT` (SPEC §10, §42 test 3)
- `available_actions(state)`:

| State | Actions |
|:--|:--|
| `RECEIVED` | `acknowledge` / Принять к исполнению |
| `ACKNOWLEDGED` | `open_resource_selection` / Подбор сил и средств; `send_status_update` / Отправить статус |
| `RESOURCE_SELECTION` | `select_resource` / Выбрать; `deselect_resource` / Снять; `dispatch` / Направить; `back_to_acknowledged` / Назад; `send_status_update` |
| `DISPATCHED` | `open_resource_selection` / Добавить силы; `send_status_update` |
| `EN_ROUTE` | `select_resource` / Выбрать (added, E9); `deselect_resource` / Снять (added, E9); `dispatch_additional` / Направить дополнительно; `send_status_update` |
| `ARRIVED` | `select_resource` (added, E9); `deselect_resource` (added, E9); `dispatch_additional`; `send_status_update` |
| `WORKING` | `select_resource` (added, E9); `deselect_resource` (added, E9); `dispatch_additional`; `send_status_update` |
| `RESOLVED` | `close` / Закрыть происшествие; `send_status_update` |
| `CLOSED` | — |

Two of the stage triggers above had **no endpoint** in `openapi.yaml` — `open_resource_selection`
and `back_to_acknowledged` were available actions the console could not perform. E9 closes the gap
additively with two operations that mirror the operator's `beginHandoffPreparation` /
`backToInterview` pair: `openDdsResourceSelection`
(`POST /api/v1/sessions/{session_id}/dds/resources/selection/open`) and `backToDdsAcknowledged`
(`POST …/dds/resources/selection/cancel`), both with no request body and a `DdsStageView` in
reply. `dispatch_additional` needs none of its own: it shares `dispatchDdsResources` with
`dispatch`, which is already how `openapi.yaml` describes it.

### `EDDSModule` — `backend/app/domain/roles/edds.py` (stub, SPEC §14)
- `role_type = EDDS`, `implemented = False`
- `permissions = frozenset()`, `state_machine` = a single-state machine over `DDSStageState.RECEIVED`
  with no transitions, `visibility_policy.sources = {NOTIFICATIONS, RADIO_MESSAGES}`,
  `available_actions(...) -> ()`, `ui_schema = {}`
- Registered in `ROLE_MODULES` so the extension point exists; `validate_scenario_version` rejects any
  `role_chain` containing a role whose module has `implemented is False` (D6).

## 10.10 SessionPolicy (D6, SPEC §1, §13)

`backend/app/domain/session/policy.py`

```python
class ParticipantAssignmentRule(str, Enum):
    SINGLE_STAGE_ONE_PARTICIPANT = "SINGLE_STAGE_ONE_PARTICIPANT"
    ALL_STAGES_ONE_PARTICIPANT = "ALL_STAGES_ONE_PARTICIPANT"
    ONE_PARTICIPANT_PER_STAGE = "ONE_PARTICIPANT_PER_STAGE"

class SessionPolicy(BaseModel):
    session_mode: SessionMode
    assignment_rule: ParticipantAssignmentRule
    role_chain_length: Literal["EXACTLY_ONE", "ONE_OR_MORE"]
    transition_pause_seconds: int
    show_asr_partials: bool
    report_visible_to_trainee_before_release: bool
    requires_prefab_handoff_for_dds_only: bool

SESSION_POLICIES: Mapping[SessionMode, SessionPolicy]
```

| `session_mode` | `assignment_rule` | `role_chain_length` | `transition_pause_seconds` | `show_asr_partials` | report visible before instructor release | needs `prefab_handoff` for a DDS-only chain |
|:--|:--|:--|:--|:--|:--|:--|
| `SINGLE_ROLE` | `SINGLE_STAGE_ONE_PARTICIPANT` | `EXACTLY_ONE` | 0 | `true` | `true` | `true` |
| `FULL_CYCLE_SINGLE_TRAINEE` | `ALL_STAGES_ONE_PARTICIPANT` | `ONE_OR_MORE` | 20 | `true` | `true` | `false` |
| `MULTI_TRAINEE` | `ONE_PARTICIPANT_PER_STAGE` | `ONE_OR_MORE` | 10 | `true` | `false` | `false` |
| `ASSESSMENT` | `SINGLE_STAGE_ONE_PARTICIPANT` | `ONE_OR_MORE` | 0 | `false` | `false` | `true` |

Per D6, `SINGLE_ROLE` (and `ASSESSMENT`) with a `role_chain` of `[DDS]` requires the scenario's
`expected_response.prefab_handoff`; if it is absent the session cannot be created and the API returns
`409 PREFAB_HANDOFF_REQUIRED`.

(additive, I3 E1 — HLD 70 §70.2.4) `role_chain_length` and the DDS-only prefab check read the
session's **effective** role chain: under `card_source: GENERATED_CARD` it is the scenario chain's
suffix starting at DDS, under `CALLER_VOICE` the whole chain. `SINGLE_ROLE`'s `EXACTLY_ONE` therefore
accepts the two-stage demo run as `GENERATED_CARD` (effective chain `[DDS]`), and `start_session`
materialises the prefab exactly as for a `[DDS]` chain.

### Variant switches — `backend/app/domain/session/variants.py` (additive, I3 E1)

```python
class CardSource(str, Enum):      GENERATED_CARD, CALLER_VOICE
class DdsMode(str, Enum):         MEMO_STATUSES, RESOURCE_PICKER
class DdsCardCheck(str, Enum):    OFF, ON
class DdsBrigadeCall(str, Enum):  OFF, ON

class SessionVariants(BaseModel):       # frozen, extra="forbid"
    card_source: CardSource
    dds_mode: DdsMode
    dds_card_check: DdsCardCheck
    dds_brigade_call: DdsBrigadeCall

class VariantSupport(BaseModel):        # frozen, extra="forbid"; every tuple non-empty (rule R32)
    card_source: tuple[CardSource, ...]
    dds_mode: tuple[DdsMode, ...]
    dds_card_check: tuple[DdsCardCheck, ...]
    dds_brigade_call: tuple[DdsBrigadeCall, ...]

class ScenarioVariants(BaseModel):      # the schema-2 scenario key `variants`
    supported: VariantSupport
    default: SessionVariants

PRODUCT_DEFAULT_VARIANTS: SessionVariants        # GENERATED_CARD, RESOURCE_PICKER, OFF, OFF
IMPLEMENTED_VARIANT_VALUES: Mapping[str, frozenset[str]]
def resolve_variants(requested: PartialVariants, scenario: ScenarioVariants,
                     implemented: Mapping[str, frozenset[str]]) -> SessionVariants: ...
```

Three homes, fixed precedence (HLD 70 §70.2.2, D14): the scenario declares *supported + default*
(`ScenarioVersion.scenario_variants` — the declared schema-2 key, or the schema-1 derivation), session
creation *selects* (`resolve_variants`: request value → scenario default; a value outside
`IMPLEMENTED_VARIANT_VALUES` is `VariantNotAvailableError` → `409 VARIANT_NOT_AVAILABLE`, checked
first; a value outside `supported` is `VariantNotSupportedError` → `409 VARIANT_NOT_SUPPORTED`), and
`SimulationSession.variants` plus `SESSION_CREATED.variants` *record* the result, immutable after
creation. A session stored before E1 (`simulation_sessions.variants = '{}'`) reads as the schema-1
derivation of its own stage chain. `IMPLEMENTED_VARIANT_VALUES` after E1: `card_source {CALLER_VOICE,
GENERATED_CARD}`, `dds_mode {RESOURCE_PICKER}`, `dds_card_check {OFF}`, `dds_brigade_call {OFF}`.
`RoleModule.available_actions(stage_state, *, variants=None)` takes the session's variants
(Protocol-compatible; every module ignores them until E5's memo table).

## 10.11 World event engine (SPEC §12, D7)

### Condition expression language — `backend/app/domain/world/conditions.py`

A small closed declarative structure. No `eval`, no code strings, no lambdas in scenario data.

```
Condition ::=
    {"all": [Condition, ...]}
  | {"any": [Condition, ...]}
  | {"not": Condition}
  | {"fact":     {"fact_id": str, "layer": "WORLD" | "CALLER",
                  "op": "EQ"|"NEQ"|"GT"|"GTE"|"LT"|"LTE"|"IN"|"IS_NULL"|"IS_NOT_NULL",
                  "value": FactValue | list[FactValue] | None}}
  | {"resource": {"selector": {"resource_id": str} | {"capability": str} | {"service_type": str},
                  "op": "ANY_IS"|"ALL_ARE"|"NONE_IS"|"COUNT_GTE",
                  "status": ResourceStatus, "count": int | None}}
  | {"stage":    {"role": "OPERATOR_112"|"DDS"|"EDDS",
                  "op": "IS"|"IS_NOT"|"REACHED",
                  "state": str}}
  | {"sim_time": {"op": "GTE"|"LT", "ms": int}}
  | {"action":   {"event_type": EventType, "op": "OCCURRED"|"NOT_OCCURRED"|"COUNT_GTE",
                  "count": int | None, "within_ms": int | None,
                  "payload_equals": Mapping[str, FactValue] | None}}
```

`evaluate_condition(cond: Condition, ctx: ConditionContext) -> bool` is total and pure.
`ConditionContext` carries `world_truth`, `caller_belief`, `resources`, `stage_states`,
`reached_states`, `now_ms`, and an `event_index` (counts and first/last offsets per `EventType`,
with the payload subset needed by `payload_equals`). `REACHED` is true if the stage is currently in
that state or has ever been.

`world_truth` and `caller_belief` are **optional** (E17 ruling R3). The world engine always
supplies both; the fact gate (§10.12) is evaluated inside a dialogue turn, which D3 forbids from
reaching a `WorldTruth` at all, so its context is assembled from the session event log, the
`RoleStage` rows and simulated time — a `log-only` context. A `fact` leaf against a layer the
context was not given is `False` for **every** operator, `IS_NULL` included: "I cannot see this
layer" is not "this fact has no value". Scenario validation refuses an `available_after` that
would depend on an absent layer (`30-scenario-format.md` §30.8 rule 31), so the `False` is never
reached by a valid scenario.

### Effects — `backend/app/domain/world/effects.py`

| Effect | Fields |
|:--|:--|
| `MutateWorldTruth` | `changes: Mapping[str, FactValue]` (fact_id → new value) |
| `MutateCallerBelief` | `changes: Mapping[str, CallerFactChange]` where `CallerFactChange = {value, knowledge, certainty}`; applied **only** if the owning event has `caller_observable = true` (D7) |
| `CreateNotification` | `audience_role: RoleType`, `severity: NotificationSeverity`, `title_ru: str`, `body_ru: str` |
| `CreateRadioMessage` | `from_callsign: str`, `to_role: RoleType`, `text_ru: str`, `resource_id: str \| None` |
| `AlterResourceAvailability` | `resource_id: str`, `new_status: ResourceStatus`, `restore: bool = False`, `eta_multiplier: float = 1.0` |
| `TriggerEvent` | `world_event_id: str`, `delay_ms: int = 0` |
| `ChangeCallerEmotion` | `set_emotion: EmotionLabel \| None`, `stress_delta: float = 0.0` |

`Effect = MutateWorldTruth | MutateCallerBelief | CreateNotification | CreateRadioMessage |
AlterResourceAvailability | TriggerEvent | ChangeCallerEmotion` (discriminated on `kind: EffectKind`).

### The four event kinds — `backend/app/domain/world/events.py`

All share: `world_event_id: str`, `title_ru: str`, `caller_observable: bool`,
`max_occurrences: int = 1`, `effects: tuple[Effect, ...]`.

| Kind | Extra fields |
|:--|:--|
| `TimedEvent` (`kind = TIMED`) | `at_ms: int` |
| `ConditionalEvent` (`kind = CONDITIONAL`) | `condition: Condition`, `check_after_ms: int = 0`, `cooldown_ms: int = 0` |
| `ActionTriggeredEvent` (`kind = ACTION_TRIGGERED`) | `on_event_type: EventType`, `payload_match: Mapping[str, FactValue] \| None`, `delay_ms: int = 0` |
| `SeededRandomEvent` (`kind = SEEDED_RANDOM`) | `probability: float` (0.0–1.0), `check_every_ms: int`, `window_start_ms: int = 0`, `window_end_ms: int \| None`, `condition: Condition \| None` |

`WorldEventDefinition` is the discriminated union of the four.

### `advance` — `backend/app/domain/world/engine.py`

```python
class PendingAction(BaseModel):
    event_type: EventType
    at_offset_ms: int
    payload: Mapping[str, FactValue]
    actor: ActorRef

class WorldState(BaseModel):
    incident_id: IncidentId
    world_truth: WorldTruth
    caller_belief: CallerBelief
    resources: Mapping[ResourceId, EmergencyResource]
    stage_states: Mapping[RoleType, str]
    reached_states: Mapping[RoleType, frozenset[str]]
    last_tick_ms: int
    occurrences: Mapping[str, int]          # world_event_id -> times already fired
    last_fired_ms: Mapping[str, int]
    scheduled: tuple[ScheduledTrigger, ...] # from TriggerEvent / delayed ActionTriggeredEvent
    event_index: EventIndex
    emotion_applications: Mapping[str, int]

def advance(
    state: WorldState,
    now_ms: int,
    pending_actions: Sequence[PendingAction],
    rng_factory: Callable[[str, int], random.Random],
) -> tuple[WorldState, tuple[Effect, ...]]: ...
```

Determinism rules (SPEC §12, D7, §42 test 7):
1. `pending_actions` are folded into `event_index` first, in `(at_offset_ms, event_type, seq)` order.
2. Candidate events are collected in this fixed order and, within each group, by ascending
   `world_event_id`: due `ScheduledTrigger`s → `TimedEvent`s with `at_ms ≤ now_ms` →
   `ActionTriggeredEvent`s matched this tick → `ConditionalEvent`s whose condition holds →
   `SeededRandomEvent`s whose check tick elapsed.
3. `SeededRandomEvent` draws `rng_factory(world_event_id, occurrence).random() < probability`, where
   `rng_factory(event_id, occurrence)` returns
   `random.Random(sha256(f"{session_seed}:{event_id}:{occurrence}".encode()).hexdigest())` — the seed
   never depends on evaluation order, wall clock or the number of previous draws (D7).
4. Effects are returned in candidate order; `TriggerEvent` appends to `scheduled` rather than
   recursing, so one `advance` call is finite. `MutateCallerBelief` is dropped with no trace if the
   owning event has `caller_observable = false`.
5. `session_seed` defaults to `ScenarioVersion.deterministic_seed`, may be overridden at session
   creation, and is recorded in the `SESSION_CREATED` payload.

Each fired event emits `WORLD_EVENT_TRIGGERED`; each applied effect emits its own event
(`WORLD_TRUTH_MUTATED`, `CALLER_BELIEF_MUTATED`, `NOTIFICATION_CREATED`, `RADIO_MESSAGE_CREATED`,
`RESOURCE_STATUS_CHANGED`, `CALLER_EMOTION_CHANGED`).

### `apply_effects` — `backend/app/domain/world/apply.py`

`apply_effects(state, fired, now_ms)` is the pure state transition that follows `advance`: it turns
the fired events into the new `WorldState` and the `DomainEvent`s above, `actor = SIMULATION`.
`MutateWorldTruth`, `MutateCallerBelief`, `ChangeCallerEmotion` and `AlterResourceAvailability`
change the corresponding copies (world truth and caller belief stay two independent objects, D3);
`CreateNotification` and `CreateRadioMessage` only produce their events; `TriggerEvent` is already
queued in `WorldState.scheduled`. `AlterResourceAvailability` fires
`breakdown`/`repair`/`make_unavailable`/`make_available` through `RESOURCE_STATE_MACHINE` and an
illegal one is skipped and reported, never raised; `eta_multiplier != 1` rescales the resource's
`EtaProfile`. The scenario's `EmotionRule`s run here through `apply_emotion_rules` (§10.5) for each
fired event's `WORLD_EVENT` trigger and for the tick's `SIM_TIME` trigger.

### `advance_resources` — `backend/app/domain/world/resource_movement.py`

`advance_resources(resources, now_ms, eta_model, *, assignment_resolved)` is the resource-movement
scheduler D7 asks for: it fires every SIMULATION transition of §10.7's table that is already due,
where a due time is `status_changed_at_offset_ms + <EtaModel duration>`, plus the
availability-window `make_unavailable`/`make_available`. Several transitions may fire for one
resource in one call when a long tick elapsed, each stamped with its own due time rather than with
`now_ms`; resources are walked in ascending **`callsign`** order and every firing emits
`RESOURCE_STATUS_CHANGED`.

The walk order *is* the order in which one tick's events are appended to `session_events`, so it is
part of D7 determinism rule 5 / INV 7 and may not depend on anything that differs between two runs
of one scenario: `emergency_resources.id` is `gen_random_uuid()` per session
(`20-db-schema.md` §20.5), so walking by it made two identical runs emit the same transitions in a
different sequence, while `callsign` is the scenario's own handle on a unit and is unique within a
scenario (`30-scenario-format.md` §30.8 rule 15). For the same reason, any read-back that has to
reproduce the append order — `resource_state_changes`, for instance, whose own `id` is random too —
orders by the `seq_no` of the `session_events` row a change was recorded beside, never by a row id.

## 10.12 FactAccessGate (SPEC §21, D10)

`backend/app/domain/facts/gate.py`

```python
class FactRequest(BaseModel):
    fact_id: str
    explicit: bool

class GateDecision(BaseModel):
    fact_id: str
    outcome: GateOutcome
    reason: GateReason

class AllowedFact(BaseModel):
    fact_id: str
    label_ru: str
    value: FactValue          # the CALLER value, never the world value
    value_ru: str              # `value`, rendered caller-style Russian (app.domain.facts.
                               # value_labels_ru.render_value_ru); an ENUM value is «пожар»,
                               # never the raw member name `FIRE` (E13-B4 item 0)
    certainty: float
    hedge: bool               # true when knowledge is UNCERTAIN
    spontaneous: bool

class UnavailableFact(BaseModel):
    fact_id: str
    label_ru: str
    reason: GateReason

class AllowedFactsPackage(BaseModel):
    allowed: tuple[AllowedFact, ...]
    unavailable: tuple[UnavailableFact, ...]
    withheld_count: int
    metadata: GateMetadata    # {turn_index, evaluated_at_offset_ms, spontaneous_attached: tuple[str, ...],
                              #  max_spontaneous_per_turn: int}

def evaluate_fact_access(
    requests: Sequence[FactRequest],
    definitions: Mapping[str, FactDefinition],
    caller_belief: CallerBelief,
    revealed_fact_ids: frozenset[str],
    now_ms: int,
    condition_ctx: ConditionContext,
    max_spontaneous_per_turn: int = 2,
) -> tuple[AllowedFactsPackage, GateDecision, ...]: ...
```

`world_truth` is **not** a parameter: no world value can reach the package. `FACT_GATE_EVALUATED`
carries the decisions; it is visible to `INSTRUCTOR` only.

### Decision table

Evaluated top-down per requested fact; the first matching row wins.

| # | `fact_id` known | policy | knowledge | `available_after` | explicit | already revealed | Outcome | `reason` | Released value |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| 1 | no | — | — | — | — | — | `UNAVAILABLE` | `UNKNOWN_FACT_ID` | — |
| 2 | yes | `NEVER_DISCLOSE` | any | any | any | any | `UNAVAILABLE` | `NEVER_DISCLOSE` | — |
| 3 | yes | any other | `UNKNOWN` | any | any | any | `UNAVAILABLE` | `CALLER_DOES_NOT_KNOW` | — |
| 4 | yes | any other | `KNOWN`/`INCORRECT_BELIEF`/`UNCERTAIN` | unmet | any | any | `NOT_YET` | `NOT_YET_AVAILABLE` | — |
| 5 | yes | any other | as row 4 | met or absent | any | **yes** | `ALLOWED_REPEAT` | `ALREADY_REVEALED` | `caller_value` |
| 6 | yes | `ONLY_IF_EXPLICITLY_ASKED` | as row 4 | met or absent | **no** | no | `WITHHELD` | `REQUIRES_EXPLICIT_QUESTION` | — (`withheld_count += 1`) |
| 7 | yes | `ONLY_IF_EXPLICITLY_ASKED` | as row 4 | met or absent | **yes** | no | `ALLOWED` | `OK` | `caller_value` |
| 8 | yes | `ON_ASK` | as row 4 | met or absent | any | no | `ALLOWED` | `OK` | `caller_value` |
| 9 | yes | `SPONTANEOUS` | as row 4 | met or absent | any | no | `ALLOWED` | `OK` | `caller_value` |

Knowledge-state colouring of an `ALLOWED`/`ALLOWED_REPEAT` row:
`KNOWN` → `value = caller_value` (= `world_value`), `certainty = 1.0`, `hedge = false`;
`INCORRECT_BELIEF` → `value = caller_value` (≠ `world_value`; the caller sincerely asserts it),
`certainty = definition.certainty`, `hedge = false`;
`UNCERTAIN` → `value = caller_value`, `certainty = definition.certainty`, `hedge = true`.

Spontaneous pass (after the request loop): for every definition with `policy = SPONTANEOUS`,
`knowledge != UNKNOWN`, `available_after` met, `fact_id not in revealed_fact_ids` and not already in
`allowed`, append an `AllowedFact` with `spontaneous = true` and `outcome = ALLOWED_SPONTANEOUS`, in
scenario declaration order, up to `max_spontaneous_per_turn`. Their ids are listed in
`metadata.spontaneous_attached`.

`available_after` is "met" when: it is absent; or `{"sim_time_ms": T}` and `now_ms ≥ T`; or
`{"world_event_id": E}` and `E` has fired at least once; or `{"condition": C}` and
`evaluate_condition(C, condition_ctx)` is true.

The `{"condition": C}` form is evaluated in a **log-only `ConditionContext`** (E17 ruling R3, §10.11):
the folded session event log, the `RoleStage` states, simulated time and the live `CallerBelief`,
and never a `WorldTruth` or the DDS resource board. `C` may therefore use only the `sim_time`,
`action` and `stage` leaves and `fact` with `layer: CALLER`; `fact` with `layer: WORLD` and
`resource` are refused at scenario load time (`30-scenario-format.md` §30.8 rule 31) rather than
silently never opening the fact.

Revelation is decided by code, not text (D10): the gate does **not** add to `revealed_fact_ids`. A
fact becomes revealed only when its response finished playback uninterrupted — `CALLER_TTS_ENDED`
with `completed = true` produces `FACTS_DELIVERED {fact_ids}`, and that event is the sole writer of
`CallerBelief.revealed_fact_ids` and the sole input of the `FACT_OBTAINED` evaluator (§42 test 10).

## 10.13 Event payload catalog (D5)

`backend/app/domain/events/session_event.py` (`SessionEvent`, `DomainEvent`) and
`backend/app/domain/events/catalog.py` (`EventSpec`, `EVENT_PAYLOAD_CATALOG`) — per the §10.1
module map, which wins over listing all four classes under `catalog.py` alone.

```python
class SessionEvent(BaseModel):
    id: EventId
    session_id: SessionId
    seq_no: int
    event_type: EventType
    timestamp_utc: datetime
    monotonic_offset_ms: int
    actor_type: ActorType
    actor_id: UserId | None
    correlation_id: UUID | None
    payload: Mapping[str, Any]

class DomainEvent(BaseModel):          # what a pure domain method returns; seq_no assigned on persist
    event_type: EventType
    actor: ActorRef
    monotonic_offset_ms: int
    correlation_id: UUID | None
    payload: Mapping[str, Any]

class EventSpec(BaseModel):
    event_type: EventType
    actor_types: frozenset[ActorType]
    payload_keys: Mapping[str, str]                # key -> type expression
    visible_to: frozenset[RoleType | Literal["INSTRUCTOR"]]

EVENT_PAYLOAD_CATALOG: Mapping[EventType, EventSpec]
```

`INSTRUCTOR` in the **Visible to** column is the instructor console, not a `RoleType`. "—" means the
event is never pushed over the realtime channel to a trainee (it still lands in the log and the
report). Every payload below is self-sufficient for scoring: no evaluator needs a materialized table
(D5, §42 tests 9–11).

### SPEC §8 events

| Event type | Actor type(s) | Payload keys (`name: type`) | Visible to |
|:--|:--|:--|:--|
| `SESSION_CREATED` | `SYSTEM`, `INSTRUCTOR` | `session_id: uuid`, `scenario_id: uuid`, `scenario_version_id: uuid`, `scenario_slug: str`, `scenario_version: int`, `session_mode: SessionMode`, `session_seed: str`, `time_scale: float` (additive, E5), `role_chain: list[RoleType]` (the effective chain, I3 E1), `created_by_user_id: uuid`, `variants: SessionVariants` (additive, I3 E1), `scenario_role_chain: list[RoleType]` (additive, I3 E1) | INSTRUCTOR |
| `SESSION_STARTED` | `INSTRUCTOR` | `started_at_utc: datetime`, `first_role_stage_id: uuid`, `first_role_type: RoleType` | OPERATOR_112, DDS, INSTRUCTOR |
| `ROLE_STAGE_STARTED` | `SIMULATION` | `role_stage_id: uuid`, `role_type: RoleType`, `order_index: int`, `initial_state: str`, `participant_user_id: uuid \| null` | OPERATOR_112, DDS, INSTRUCTOR |
| `CALL_RINGING` | `SIMULATION` | `call_id: uuid`, `room_name: str`, `caller_display_ru: str` (a neutral incoming-call line, **never** `CallerProfile.identity_ru` — see below), `at_offset_ms: int` | OPERATOR_112, INSTRUCTOR |
| `CALL_ANSWERED` | `TRAINEE` | `call_id: uuid`, `at_offset_ms: int`, `ring_duration_ms: int`, `answered_by_user_id: uuid` | OPERATOR_112, INSTRUCTOR |
| `USER_SPEECH_STARTED` | `TRAINEE` | `call_id: uuid`, `turn_index: int`, `at_offset_ms: int`, `vad_provider: str` | OPERATOR_112, INSTRUCTOR |
| `USER_SPEECH_ENDED` | `TRAINEE` | `call_id: uuid`, `turn_index: int`, `at_offset_ms: int`, `speech_duration_ms: int`, `endpoint_silence_ms: int` | OPERATOR_112, INSTRUCTOR |
| `ASR_PARTIAL` | `MODEL` | `call_id: uuid`, `turn_index: int`, `text: str`, `start_ms: int`, `end_ms: int`, `asr_provider: str`, `asr_model: str` | OPERATOR_112 only if `SessionPolicy.show_asr_partials`; INSTRUCTOR |
| `ASR_FINAL` | `MODEL` | `call_id: uuid`, `turn_index: int`, `transcript_segment_id: uuid`, `audio_segment_id: uuid \| null`, `text: str`, `start_ms: int`, `end_ms: int`, `confidence: float \| null`, `asr_provider: str`, `asr_model: str` | OPERATOR_112, INSTRUCTOR |
| `CALLER_RESPONSE_PLANNED` | `SIMULATION` | `call_id: uuid`, `turn_index: int`, `allowed_fact_ids: list[str]`, `spontaneous_fact_ids: list[str]`, `unavailable_fact_ids: list[str]`, `withheld_count: int`, `emotion: EmotionLabel`, `stress_level: float` | INSTRUCTOR |
| `CALLER_RESPONSE_GENERATED` | `MODEL` | `call_id: uuid`, `turn_index: int`, `utterance_ru: str`, `output_token_count: int`, `llm_provider: str`, `llm_model: str`, `validator_verdict: "PASS"\|"REGENERATED"\|"FALLBACK"`, `regeneration_count: int` | INSTRUCTOR |
| `CALLER_TTS_STARTED` | `SIMULATION` | `call_id: uuid`, `turn_index: int`, `text_sent_to_tts: str`, `tts_provider: str`, `tts_model: str`, `voice_id: str`, `voice_id_native: str` (additive, E20-G — the provider-native voice the profile's `tts.voice_map` resolved `voice_id` to; absent for a provider that resolves nothing), `at_offset_ms: int` | OPERATOR_112, INSTRUCTOR |
| `CALLER_TTS_ENDED` | `SIMULATION` | `call_id: uuid`, `turn_index: int`, `at_offset_ms: int`, `total_audio_ms: int`, `completed: bool`, `audio_segment_id: uuid \| null` | OPERATOR_112, INSTRUCTOR |
| `CALLER_UTTERANCE_INTERRUPTED` | `SIMULATION` | `call_id: uuid`, `turn_index: int`, `planned_text: str`, `delivered_text: str`, `delivered_audio_ms: int`, `total_audio_ms_generated: int`, `cutoff_latency_ms: int` | OPERATOR_112, INSTRUCTOR |
| `CARD_FIELD_CHANGED` | `TRAINEE`, `INSTRUCTOR` | `card_id: uuid`, `revision_id: uuid`, `revision_no: int`, `field_path: str`, `previous_value: FactValue`, `new_value: FactValue`, `value_type: ValueType`, `actor_user_id: uuid`, `at_offset_ms: int` | OPERATOR_112, INSTRUCTOR |
| `SERVICE_SELECTED` | `TRAINEE` | `card_id: uuid`, `revision_id: uuid`, `service_type: ServiceType`, `selected_services: list[ServiceType]`, `at_offset_ms: int` | OPERATOR_112, INSTRUCTOR |
| `HANDOFF_CREATED` | `TRAINEE` | `snapshot_id: uuid`, `incident_id: uuid`, `card_id: uuid`, `card_revision_id: uuid`, `recipient_services: list[ServiceType]`, `card_values: object` (the complete frozen card), `content_sha256: str`, `at_offset_ms: int` | OPERATOR_112, INSTRUCTOR |
| `HANDOFF_RECEIVED` | `SIMULATION` | `snapshot_id: uuid`, `assignment_id: uuid`, `role_stage_id: uuid`, `service_type: ServiceType`, `at_offset_ms: int` | DDS, INSTRUCTOR |
| `DDS_ACKNOWLEDGED` | `TRAINEE` | `assignment_id: uuid`, `at_offset_ms: int`, `latency_from_handoff_ms: int`, `actor_user_id: uuid` | DDS, INSTRUCTOR |
| `RESOURCE_SELECTED` | `TRAINEE` | `assignment_id: uuid`, `resource_id: uuid`, `callsign: str`, `service_type: ServiceType`, `resource_type: ResourceType`, `capabilities: list[str]`, `at_offset_ms: int` | DDS, INSTRUCTOR |
| `RESOURCE_DISPATCHED` | `TRAINEE` | `assignment_id: uuid`, `resource_ids: list[uuid]`, `callsigns: list[str]`, `capabilities_union: list[str]`, `eta_seconds_by_resource: object`, `service_type_by_resource: object` (additive, E9), `at_offset_ms: int`, `is_additional: bool`, `note_ru: str \| null` (additive, E17 R2) | DDS, INSTRUCTOR |
| `RESOURCE_STATUS_CHANGED` | `SIMULATION` | `resource_id: uuid`, `callsign: str`, `previous_status: ResourceStatus`, `new_status: ResourceStatus`, `trigger: str`, `assignment_id: uuid \| null`, `source_world_event_id: str \| null`, `at_offset_ms: int` | DDS, INSTRUCTOR |
| `WORLD_EVENT_TRIGGERED` | `SIMULATION` | `world_event_id: str`, `kind: WorldEventKind`, `occurrence: int`, `title_ru: str`, `caller_observable: bool`, `trigger_reason: str`, `effect_kinds: list[EffectKind]`, `at_offset_ms: int` | INSTRUCTOR |
| `ROLE_STAGE_COMPLETED` | `SIMULATION` | `role_stage_id: uuid`, `role_type: RoleType`, `final_state: str`, `duration_ms: int` | OPERATOR_112, DDS, INSTRUCTOR |
| `SCORING_RULE_EVALUATED` | `SYSTEM` | `rule_id: str`, `evaluator_type: EvaluatorType`, `category: ScoringCategory`, `points_awarded: float`, `max_points: float`, `passed: bool`, `critical: bool`, `evidence: list[object]` | INSTRUCTOR |
| `SESSION_COMPLETED` | `SIMULATION` | `at_offset_ms: int`, `final_session_state: SessionState`, `total_events: int` | OPERATOR_112, DDS, INSTRUCTOR |
| `MODEL_FALLBACK_USED` | `SYSTEM` | `component: "INTERPRETER"\|"GENERATOR"\|"VALIDATOR"\|"ASR"\|"TTS"`, `reason: str`, `attempt: int`, `fallback_kind: str`, `turn_index: int \| null` | INSTRUCTOR |
| `MODEL_ERROR` | `SYSTEM` | `component: str`, `provider: str`, `model: str`, `error_code: str`, `message: str`, `recoverable: bool`, `turn_index: int \| null` | INSTRUCTOR |

**`CALL_RINGING.caller_display_ru`** is a fixed, neutral incoming-call line
(`app.application.operator.call_flow.CALLER_DISPLAY_RU`, "Входящий вызов 112"), not the scenario
persona's `identity_ru`. The persona's identity typically contains facts the trainee is scored on
obtaining by asking — in the demo scenario it is "Соседка Ирина Петровна из квартиры 41", which
names `caller.full_name` and `address.apartment` — so putting it on the OPERATOR_112 phone widget
would move Caller Knowledge into the Operator view, which D3 separates and `openapi.yaml`'s
`CallStateView` already forbids ("nothing about the caller's hidden knowledge appears here").
`ScenarioVersionSummary.caller_display_ru`, an instructor-facing catalogue field with the same
property name, does remain `CallerProfile.identity_ru`.

### Additive events (D5)

| Event type | Actor type(s) | Payload keys | Visible to |
|:--|:--|:--|:--|
| `SESSION_ABORTED` | `INSTRUCTOR`, `SYSTEM` | `previous_state: SessionState`, `reason: str`, `at_offset_ms: int`, `aborted_by_user_id: uuid \| null` | OPERATOR_112, DDS, INSTRUCTOR |
| `STAGE_STATE_CHANGED` | `SIMULATION`, `TRAINEE`, `INSTRUCTOR` | `role_stage_id: uuid`, `role_type: RoleType`, `previous_state: str`, `new_state: str`, `trigger: str`, `fired_by_actor_type: ActorType`, `fired_by_user_id: uuid \| null`, `at_offset_ms: int` | the stage's own role, INSTRUCTOR |
| `ROLE_TRANSITION_STARTED` | `SIMULATION` | `from_role_stage_id: uuid`, `from_role_type: RoleType`, `to_role_stage_id: uuid`, `to_role_type: RoleType`, `pause_seconds: int`, `at_offset_ms: int` | OPERATOR_112, DDS, INSTRUCTOR |
| `ROLE_TRANSITION_COMPLETED` | `SIMULATION` | `to_role_stage_id: uuid`, `to_role_type: RoleType`, `incident_id: uuid`, `at_offset_ms: int` | OPERATOR_112, DDS, INSTRUCTOR |
| `SERVICE_DESELECTED` | `TRAINEE` | `card_id: uuid`, `revision_id: uuid`, `service_type: ServiceType`, `selected_services: list[ServiceType]`, `at_offset_ms: int` | OPERATOR_112, INSTRUCTOR |
| `RESOURCE_DESELECTED` | `TRAINEE` | `assignment_id: uuid`, `resource_id: uuid`, `callsign: str`, `at_offset_ms: int` | DDS, INSTRUCTOR |
| `DDS_STATUS_UPDATE_SENT` | `TRAINEE` | `assignment_id: uuid`, `update_kind: StatusUpdateKind`, `text_ru: str`, `at_offset_ms: int`, `actor_user_id: uuid` | DDS, INSTRUCTOR |
| `DDS_INCIDENT_CLOSED` | `TRAINEE` | `assignment_id: uuid`, `closure_reason: ClosureReason`, `released_resource_ids: list[uuid]`, `at_offset_ms: int`, `actor_user_id: uuid`, `comment_ru: str \| null` (additive, E17 R2) | DDS, INSTRUCTOR |
| `NOTIFICATION_CREATED` | `SIMULATION` | `notification_id: uuid`, `audience_role: RoleType`, `severity: NotificationSeverity`, `title_ru: str`, `body_ru: str`, `source_world_event_id: str \| null`, `at_offset_ms: int` | the `audience_role`, INSTRUCTOR |
| `NOTIFICATION_ACKNOWLEDGED` | `TRAINEE` | `notification_id: uuid`, `audience_role: RoleType` (additive, E9), `at_offset_ms: int`, `latency_ms: int`, `actor_user_id: uuid` | the notification's `audience_role`, INSTRUCTOR |
| `RADIO_MESSAGE_CREATED` | `SIMULATION` | `radio_message_id: uuid`, `from_callsign: str`, `to_role: RoleType`, `text_ru: str`, `resource_id: uuid \| null`, `source_world_event_id: str \| null`, `at_offset_ms: int` | the `to_role`, INSTRUCTOR |
| `WORLD_TRUTH_MUTATED` | `SIMULATION` | `revision: int`, `changes: list[{fact_id: str, previous_value: FactValue, new_value: FactValue}]`, `source_world_event_id: str`, `at_offset_ms: int` | INSTRUCTOR only |
| `CALLER_BELIEF_MUTATED` | `SIMULATION` | `revision: int`, `changes: list[{fact_id: str, previous_value: FactValue, new_value: FactValue, knowledge: KnowledgeState, certainty: float}]`, `source_world_event_id: str`, `at_offset_ms: int` | INSTRUCTOR only |
| `CALLER_EMOTION_CHANGED` | `SIMULATION` | `previous_emotion: EmotionLabel`, `new_emotion: EmotionLabel`, `previous_stress_level: float`, `new_stress_level: float`, `emotion_rule_id: str \| null`, `trigger_kind: str`, `at_offset_ms: int` | INSTRUCTOR |
| `CALL_ENDED` | `TRAINEE`, `SIMULATION` | `call_id: uuid`, `at_offset_ms: int`, `duration_ms: int`, `ended_by: ActorType`, `reason: str` | OPERATOR_112, INSTRUCTOR |
| `DIALOGUE_INTERPRETED` | `MODEL` | `turn_index: int`, `speech_act: SpeechAct`, `requested_facts: list[{fact_id: str, explicit: bool}]`, `operator_assertions: list[{fact_id: str, asserted_value: FactValue}]`, `confirmation_targets: list[str]`, `semantic_confidence: float`, `repair_retry_used: bool` | INSTRUCTOR |
| `FACT_GATE_EVALUATED` | `SIMULATION` | `turn_index: int`, `decisions: list[{fact_id: str, outcome: GateOutcome, reason: GateReason}]`, `allowed_fact_ids: list[str]`, `spontaneous_attached: list[str]`, `withheld_count: int`, `at_offset_ms: int` | INSTRUCTOR only |
| `FACTS_DELIVERED` | `SIMULATION` | `turn_index: int`, `fact_ids: list[str]`, `delivered_via: "TTS_COMPLETED"`, `at_offset_ms: int` | INSTRUCTOR |
| `TRANSPORT_DISCONNECTED` | `SYSTEM` | `call_id: uuid`, `participant_identity: str`, `reason: str`, `at_offset_ms: int` | OPERATOR_112, INSTRUCTOR |
| `TRANSPORT_RECONNECTED` | `SYSTEM` | `call_id: uuid`, `participant_identity: str`, `downtime_ms: int`, `at_offset_ms: int` | OPERATOR_112, INSTRUCTOR |
| `INFERENCE_HEALTH_CHANGED` | `SYSTEM` | `component: str`, `previous_status: HealthStatus`, `new_status: HealthStatus`, `detail: str` | INSTRUCTOR |

### Turn record (materialized, not a domain type)

The turn pipeline's events (`USER_SPEECH_STARTED` … `CALLER_TTS_ENDED` /
`CALLER_UTTERANCE_INTERRUPTED`) are additionally materialized into the `dialogue_turns` table
(`20-db-schema.md` §20.6), one row per trainee→caller turn, carrying `turn_index`, the two
transcript-segment references, the `interpretation` and `gate_output` payloads, `planned_text`,
`delivered_text`, `interrupted`, `fallback_used` and the SPEC §27 product metric
`speech_end_to_first_audio_ms`. It is a read model for the report and the latency dashboards only:
there is no domain type for it, and `score(...)` must never read it (D5, §42 tests 9–11).

## 10.14 Scoring domain (SPEC §28, D11)

### `ScoringRule` — `backend/app/domain/scoring/rules.py`

| Field | Type | SPEC §28 item |
|:--|:--|:--|
| `rule_id` | `str` (scenario-unique) | id |
| `name_ru` | `str` | name |
| `description_ru` | `str` | description |
| `category` | `ScoringCategory` | category |
| `max_points` | `float` (> 0) | max_points |
| `critical` | `bool` | critical flag |
| `evaluator_type` | `EvaluatorType` | evaluator type |
| `config` | `Mapping[str, Any]` validated by the evaluator's own Pydantic config model | evaluator configuration |
| `min_evidence` | `int` (default 1, ≥ 1) | evidence requirements |
| `applies_to_roles` | `tuple[RoleType, ...]` (default `()` — always applies) | — (additive, E15) |
| `applies_to_variants` | `Mapping[str, tuple[str, ...]]` (default `{}` — always applies) | — (additive, I3 E1) |

#### Applicability

`applies_to_roles` closes the gap `application/handoff/prefab_handoff.py` names: a `SINGLE_ROLE`
DDS run has no 112 stage, so the ten operator-card, service-selection and handoff rules of a
full-cycle scenario have nothing to score, and scoring them anyway would hand the trainee a
critical failure for a stage they never sat in (D6).

A rule with a non-empty `applies_to_roles` applies **iff at least one listed role is in the
session's role chain as recorded in the event log** — `SESSION_CREATED.role_chain` (§10.13), with
the `ROLE_STAGE_STARTED.role_type` sequence as the fallback for a log that does not start at the
beginning. The log, not `ScenarioVersion.role_chain`, is the source: a session is scored on what
actually ran. A log that records no chain at all leaves every rule applicable.

A non-applicable rule still produces a `ScoreResult`, so the report shows *why* a rule is absent
rather than silently dropping it: `points_awarded: 0.0`, `max_points: 0.0`, `passed: true`,
`critical_failure: false`, and one `ScoreEvidence` pointing at the chain-recording event with
`note_ru: "Правило не применяется: роль не участвует в сессии"`. It therefore changes neither the
totals, nor a category percentage, nor `critical_errors`, and it satisfies the ≥ 1 evidence rule
like every other result.

(additive, I3 E1 — HLD 70 §70.2.5) `applies_to_variants` has the same semantics per switch: a rule
applies iff, for every switch it names, the session's value is listed. The session's value is
`ScoringContext.variants`, folded from `SESSION_CREATED.variants`; a log that predates the key reads
as the scenario's schema-1 derivation, so it rescores identically (INV 9). A rule non-applicable by
variant yields the same zero/zero result, with `note_ru: "Правило не применяется: вариант сессии не
тот"`. Because the chain `applies_to_roles` reads is the **effective** one, the `[OPERATOR_112]`
rules become non-applicable in a `GENERATED_CARD` session without any rule change.

### Results — `backend/app/domain/scoring/results.py`

```python
class ScoreEvidence(BaseModel):
    event_id: EventId | None
    card_revision_id: CardRevisionId | None
    snapshot_id: SnapshotId | None
    seq_no: int | None
    note_ru: str
    # exactly one of event_id / card_revision_id / snapshot_id is set

class ScoreResult(BaseModel):
    rule_id: str
    evaluator_type: EvaluatorType
    category: ScoringCategory
    points_awarded: float          # may be negative (penalty)
    max_points: float
    passed: bool
    critical_failure: bool
    evidence: tuple[ScoreEvidence, ...]   # len >= rule.min_evidence, always >= 1

class ScoreCategoryTotal(BaseModel):
    category: ScoringCategory
    points_awarded: float
    max_points: float

class ScoreReport(BaseModel):
    scenario_version_id: ScenarioVersionId
    session_id: SessionId
    total_points: float
    total_max_points: float
    by_category: tuple[ScoreCategoryTotal, ...]
    critical_errors: tuple[ScoreResult, ...]
    results: tuple[ScoreResult, ...]
    computed_from_event_count: int
```

D11 cross-reference: the optional LLM explanation of a `ScoreReport` (SPEC §2, §29, epic E16-B) is
not a field here and never will be — it is generated only from an already-persisted report, stored
in its own `report_explanations` table keyed by `(session_id, audience)` and carrying the
`report_checksum` value below so a client can verify the numbers it explains did not move. The
explanation use case holds no path to `score_results`/`score_evidence` at all (structural, not a
convention): see `backend/app/application/reports/explanation/` and `backend/tests/invariants/
test_explanation_cannot_write_scores.py`.

### `score` — `backend/app/domain/scoring/engine.py`

```python
def score(
    scenario_version: ScenarioVersion,
    events: Sequence[SessionEvent],
) -> ScoreReport: ...
```

Pure: no I/O, no LLM, no clock, no materialized tables (D11, §42 tests 9–11). `events` must be
ordered by `seq_no`. Any `ScoreResult` with `points_awarded != 0` and zero evidence raises
`ScoringEvidenceError` — a hard error, never a silent zero. "Absence" evidence points at the bounding
event (the `HANDOFF_CREATED` for a field never filled, the `SESSION_COMPLETED` for an action never
taken). Each evaluation also produces one `SCORING_RULE_EVALUATED` domain event.

### The ten evaluators

`backend/app/domain/scoring/evaluators/registry.py` maps `EvaluatorType → Evaluator`. Every evaluator
implements `evaluate(rule: ScoringRule, ctx: ScoringContext) -> ScoreResult`, where `ScoringContext`
is built once from `(scenario_version, events)` and exposes the event list, per-type indexes, the
card-value timeline reconstructed from `CARD_FIELD_CHANGED`, and the handoff payload from
`HANDOFF_CREATED`.

#### 1. `FACT_OBTAINED` — `fact_obtained.py`
- Config keys: `fact_id: str`, `within_ms: int | null`, `points: float`,
  `penalty_if_missing: float = 0.0`.
- Reads: `FACTS_DELIVERED` (only — D10), bounded by `SESSION_COMPLETED`/`ROLE_STAGE_COMPLETED`.
- Points: `points` if some `FACTS_DELIVERED` contains `fact_id` and (`within_ms` is null or
  `at_offset_ms ≤ within_ms`); otherwise `penalty_if_missing`.
- Evidence: the matching `FACTS_DELIVERED` event; on failure the bounding `ROLE_STAGE_COMPLETED`
  with `note_ru` naming the fact.

#### 2. `CARD_FIELD_CORRECT` — `card_field_correct.py`
- Config keys: `field_path: str`, `expected_from_fact_id: str | null`,
  `expected_literal: FactValue | null` (exactly one of the two), `comparison:
  "EXACT" | "CASE_INSENSITIVE" | "NUMERIC_TOLERANCE" | "SET_EQUAL" | "NORMALIZED_DIGITS"`,
  `tolerance: float = 0.0`, `evaluated_at: "HANDOFF" | "SESSION_END"`, `points: float`,
  `penalty_if_wrong: float = 0.0`.
- Reads: `CARD_FIELD_CHANGED`, `HANDOFF_CREATED`.
- Points: `points` when the card value at `evaluated_at` compares equal to the expected value
  (the expected value is taken from `scenario_version.world_truth.facts[...].world_value`);
  `penalty_if_wrong` when it is set and differs; `0` when it is empty (that is
  `CARD_FIELD_PRESENT`'s business).
- Evidence: the last `CARD_FIELD_CHANGED` for `field_path` before the cutoff, else `HANDOFF_CREATED`.

#### 3. `CARD_FIELD_PRESENT` — `card_field_present.py`
- Config keys: `field_path: str`, `evaluated_at: "HANDOFF" | "SESSION_END"`, `points: float`,
  `penalty_if_missing: float = 0.0`, `treat_false_as_present: bool = true`.
- Reads: `CARD_FIELD_CHANGED`, `HANDOFF_CREATED`.
- Points: `points` when the value is non-null and (for strings/lists) non-empty; else
  `penalty_if_missing`.
- Evidence: the first `CARD_FIELD_CHANGED` for the path, else `HANDOFF_CREATED`.

#### 4. `CARD_CONTRADICTION` — `card_contradiction.py`
- Config keys: `field_path: str`, `contradicts_fact_id: str`, `comparison: same enum as #2`,
  `require_fact_delivered: bool = true`, `penalty_points: float` (negative),
  `evaluated_at: "HANDOFF" | "SESSION_END"`.
- Reads: `CARD_FIELD_CHANGED`, `FACTS_DELIVERED`, `HANDOFF_CREATED`.
- Points: `penalty_points` when the card value is non-empty **and** differs from the caller value the
  trainee was actually given (i.e. `require_fact_delivered` and a `FACTS_DELIVERED` for
  `contradicts_fact_id` exists); otherwise `0`.
- Evidence: the offending `CARD_FIELD_CHANGED` **and** the `FACTS_DELIVERED` that carried the fact.

#### 5. `SERVICE_SELECTION` — `service_selection.py`
- Config keys: `required_services: list[ServiceType]`, `forbidden_services: list[ServiceType] = []`,
  `points_per_required: float`, `penalty_per_forbidden: float = 0.0`,
  `all_or_nothing: bool = false`, `evaluated_at: "HANDOFF" | "SESSION_END"`.
- Reads: `SERVICE_SELECTED`, `SERVICE_DESELECTED`, `HANDOFF_CREATED.recipient_services`.
- Points: `points_per_required` per required service present at the cutoff (or `max_points` only when
  all are present, if `all_or_nothing`), plus `penalty_per_forbidden` per forbidden service present.
- Evidence: the `SERVICE_SELECTED` event per matched service; `HANDOFF_CREATED` for absences.

#### 6. `DEADLINE` — `deadline.py`
- Config keys: `from_event_type: EventType | "SESSION_START"`, `to_event_type: EventType`,
  `to_payload_match: object | null`, `max_offset_ms: int`, `points: float`,
  `penalty_if_late: float = 0.0`, `scale: "STEP" | "LINEAR"`, `linear_zero_ms: int | null`.
- Reads: the two named event types.
- Points: `STEP` → `points` if `Δ ≤ max_offset_ms`, else `penalty_if_late`. `LINEAR` → `points`
  at `Δ ≤ max_offset_ms`, falling linearly to `0` at `linear_zero_ms`, then `penalty_if_late`.
  If `to_event_type` never occurs: `penalty_if_late`.
- Evidence: both bounding events (or `from`-event plus `SESSION_COMPLETED` when `to` never occurred).

#### 7. `WORKFLOW_ACTION` — `workflow_action.py`
- Config keys: `event_type: EventType`, `payload_match: object | null`, `min_count: int = 1`,
  `max_count: int | null`, `required_stage_state: str | null`, `must_occur_after: EventType | null`,
  `points: float`, `penalty_if_missing: float = 0.0`, `penalty_per_excess: float = 0.0`.
- Reads: the named event type plus `STAGE_STATE_CHANGED` when `required_stage_state` is set.
- Points: `points` when the count is within `[min_count, max_count]`, the ordering constraint holds
  and (if configured) the action happened while the stage was in `required_stage_state`;
  `penalty_if_missing` below `min_count`; `penalty_per_excess` per event above `max_count`.
- Evidence: each qualifying event (capped at 5), else the bounding `ROLE_STAGE_COMPLETED`.

#### 8. `RESOURCE_SELECTION` — `resource_selection.py`
- Config keys: `required_capabilities: list[ResourceCapability] = []`,
  `min_units_by_service: object` (`ServiceType → int`), `forbidden_resource_ids: list[str] = []`,
  `must_be_dispatched: bool = true`, `points: float`, `penalty_per_missing: float = 0.0`,
  `penalty_per_forbidden: float = 0.0`.
- Reads: `RESOURCE_SELECTED`, `RESOURCE_DESELECTED`, `RESOURCE_DISPATCHED` (whose payload carries
  `capabilities_union` and `service_type` per resource, so no resource table lookup is needed).
- Points: full `points` when every required capability is covered and every per-service minimum is
  met by dispatched (or merely selected, if `must_be_dispatched` is false) resources; otherwise
  `penalty_per_missing` per unmet requirement, plus `penalty_per_forbidden` per forbidden unit.
- Evidence: the `RESOURCE_DISPATCHED` events; `DDS_INCIDENT_CLOSED` or `ROLE_STAGE_COMPLETED` for
  absences.

#### 9. `REQUIRED_STATUS_UPDATE` — `required_status_update.py`
- Config keys: `update_kind: StatusUpdateKind`, `min_count: int = 1`,
  `within_ms_of_event: EventType | null`, `within_ms: int | null`, `points: float`,
  `penalty_if_missing: float = 0.0`.
- Reads: `DDS_STATUS_UPDATE_SENT`, plus the reference event type.
- Points: `points` when at least `min_count` updates of that kind exist and, if configured, **every**
  occurrence of `within_ms_of_event` has a matching update within `within_ms` after it (H4, E20-H —
  not just the first occurrence of each; see reading 6 below); else `penalty_if_missing`.
- Evidence: one entry per `(reference event, matching update or none)` pair when timing is
  configured and at least one reference event occurred; else the qualifying `DDS_STATUS_UPDATE_SENT`
  events; else `ROLE_STAGE_COMPLETED`.

#### 10. `HANDOFF_COMPLETENESS` — `handoff_completeness.py`
- Config keys: `required_field_paths: list[str]`, `points_per_field: float`,
  `all_or_nothing: bool = false`, `penalty_per_missing: float = 0.0`,
  `treat_false_as_present: bool = true`.
- Reads: `HANDOFF_CREATED.card_values` only.
- Points: `points_per_field` per non-empty required path (or `max_points` only when all are present,
  if `all_or_nothing`), plus `penalty_per_missing` per empty one.
- Evidence: `HANDOFF_CREATED` (the snapshot id), with one `ScoreEvidence` per missing field naming
  the path in `note_ru`.

#### Readings this section did not fix (settled by E15)

Each line is a point where the prose above was silent or admitted two readings; the reading chosen
is the one closest to SPEC, and it is now the contract.

1. **Bounding event.** "The bounding `ROLE_STAGE_COMPLETED`" is the *first* `ROLE_STAGE_COMPLETED`
   of the role the rule concerns (`OPERATOR_112` for the fact and card rules, `DDS` for the
   resource and status rules), falling back to the last `ROLE_STAGE_COMPLETED` of the log and then
   to `SESSION_COMPLETED`. A log with none of the three cannot be scored: ruling R2 appends
   `SESSION_COMPLETED` *before* scoring runs, so its absence means the caller scored an unfinished
   session, and `ScoringEvidenceError` says so.
2. **`FACT_OBTAINED` delivered but late.** The evidence is that late `FACTS_DELIVERED`, not the
   stage bound: the trainee did obtain the fact, and the report should show when.
3. **`CARD_CONTRADICTION` compares against `caller_knowledge.facts[...].caller_value`** — what the
   caller believes, not `world_truth` (SPEC §3: the caller may be wrong, and an operator who
   writes down what the caller said has done nothing wrong).
4. **`DEADLINE` from `SESSION_START`** is offset `0` by definition (`monotonic_offset_ms` is
   measured from session start, §10.13); the `SESSION_STARTED` event — or `SESSION_CREATED` — is
   used as evidence only. A `LINEAR` rule without `linear_zero_ms`, or with one at or below
   `max_offset_ms`, has no ramp and behaves as `STEP`.
5. **`WORKFLOW_ACTION` above `max_count`** scores `penalty_per_excess × (count − max_count)`, and
   nothing else — the excess replaces `points`, it is not added to them.
6. **`REQUIRED_STATUS_UPDATE` timing opens one window per qualifying reference event** (H4,
   E20-H — supersedes the earlier "first update against the first reference" reading, which made
   the rule unsatisfiable in a real session the instant any *earlier* occurrence of
   `within_ms_of_event` existed, e.g. the DDS's first `RESOURCE_STATUS_CHANGED` being `DISPATCHED`
   long before the arrival the rule actually means, reproduced live by E20-C's §46 walk:
   `"Задержка от RESOURCE_STATUS_CHANGED: 279160 мс при норме 60000 мс"`). Now: **every** occurrence
   of `within_ms_of_event` in the log opens its own `[t, t + within_ms]` window, and the timing half
   is satisfied only when **each** window has at least one matching update with `0 ≤ Δ ≤ within_ms`
   (`Δ` = update offset − reference offset; a report sent before the thing it reports on still does
   not count, SPEC §13). One update may satisfy more than one window if its offset falls in several
   at once — pairing is "does a match exist", not an exclusive one-to-one assignment. A reference
   event type that never occurred at all leaves the timing half vacuously satisfied (there is no
   window to miss) and the count half (`min_count`) deciding, unchanged from before.
7. **`RESOURCE_SELECTION` unmet count** is `len(missing capabilities) + Σ(minimum − dispatched)`
   per short service; capabilities are the union of `RESOURCE_DISPATCHED.capabilities_union` and
   the per-unit `RESOURCE_SELECTED.capabilities` (the latter alone when
   `must_be_dispatched: false`).
8. **`all_or_nothing`** (`SERVICE_SELECTION`, `HANDOFF_COMPLETENESS`) awards `rule.max_points`,
   not `points_per_required × n` / `points_per_field × n`, when everything is present.
9. **A session with no `HANDOFF_CREATED`** (a DDS-only run) scores every `HANDOFF_COMPLETENESS`
   path as missing and every `evaluated_at: HANDOFF` cutoff as the end of the log; the evidence is
   the bounding event. Combined with `applies_to_roles`, such a scenario marks those rules
   non-applicable instead.
10. **`report_checksum`** covers `(rule_id, points_awarded, max_points, passed, critical_failure)`
    per result in rule order plus `total_points` / `total_max_points` — canonical JSON, sorted
    keys, no whitespace, floats as fixed two-decimal strings, SHA-256. Evidence, notes and
    `computed_from_event_count` are deliberately out of scope: this is the checksum
    `rescoreSession` compares to answer "are the numbers the same".

## 10.15 Scenario domain types (SPEC §4, D4)

`backend/app/domain/scenario/version.py`

```python
class Scenario(BaseModel):
    scenario_id: ScenarioId
    slug: str
    title_ru: str

class ScenarioVersion(BaseModel):
    id: ScenarioVersionId
    schema_version: int
    scenario_id: ScenarioId
    version: int
    title: str
    description: str
    difficulty: int
    deterministic_seed: str
    role_chain: tuple[RoleType, ...]
    world_truth: WorldTruthSection
    caller_profile: CallerProfile
    caller_knowledge: CallerKnowledgeSection
    disclosure_rules: DisclosureRulesSection
    expected_response: ExpectedResponse
    available_resources: tuple[ResourceSpec, ...]
    world_events: tuple[WorldEventDefinition, ...]
    scoring_rules: tuple[ScoringRule, ...]
    variants: ScenarioVariants | None = None      # schema 2 only (additive, I3 E1)
```

The top-level key names are exactly SPEC §4 for `schema_version: 1`; `schema_version: 2` adds the
optional key `variants` (D14 amends D4; the later schema-2 keys `timers`, `reference_pack` and
`expected_response.responders` stay refused until E4/E2/E5b). `scenario_variants` is the declared key
or its derivation (HLD 70 §70.2.2); a dump omits an absent `variants` and an empty
`applies_to_variants`, so a schema-1 document's `content_sha256` is unchanged. `validate_scenario_version` implements the complete D4
load-time list; the rules and the YAML shape are specified in `docs/hld/30-scenario-format.md` §30.4.

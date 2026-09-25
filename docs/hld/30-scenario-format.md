# HLD 30 — Scenario file format

Source files: `scenarios/examples/<slug>/v<N>.yaml`, one file per version, version-controlled
(SPEC §4, D4). They are parsed by the Pydantic models of `backend/app/domain/scenario/` and the JSON
Schema is exported to `scenarios/schemas/scenario_version.schema.json`; `make gate` fails if the
committed schema is stale (D4).

Identifiers, keys and enum members are English. Only `*_ru` fields, `label_ru`, `aliases_ru`,
`title_ru`, `text_ru`, `body_ru`, `name_ru` and caller/persona text are Russian.

## 30.1 Top-level keys (SPEC §4, exactly these)

| Key | YAML type | Required | Meaning |
|:--|:--|:--|:--|
| `id` | string (UUID) | yes | stable identity of this version |
| `schema_version` | integer | yes | format revision; the loader rejects an unknown value |
| `scenario_id` | string (UUID) | yes | the owning `Scenario` |
| `version` | integer ≥ 1 | yes | version number within the scenario |
| `title` | string | yes | short English title used in logs |
| `description` | string | yes | what the exercise trains |
| `difficulty` | integer 1–5 | yes | |
| `deterministic_seed` | string | yes | default `session_seed` (D7) |
| `role_chain` | list of `RoleType` | yes | ordered; each entry becomes one `RoleStage` |
| `world_truth` | mapping | yes | §30.2 |
| `caller_profile` | mapping | yes | §30.3 |
| `caller_knowledge` | mapping | yes | §30.2 |
| `disclosure_rules` | mapping | yes | §30.2 |
| `expected_response` | mapping | yes | §30.5 |
| `available_resources` | list | yes | §30.4 |
| `world_events` | list | yes (may be empty) | §30.6 |
| `scoring_rules` | list | yes | §30.7 |
| `variants` *(additive, I3 E1)* | mapping | no — `schema_version: 2` only | §30.10 |
| `reference_pack` *(additive, I3 E2a)* | string | no — `schema_version: 2` only | §30.11 |
| `timers` *(additive, I3 E4a)* | mapping | no — `schema_version: 2` only | §30.12 |
| `provenance` *(additive, I3 E8)* | mapping | no — `schema_version: 2` only | §30.13 |

Additional top-level keys are rejected (`extra="forbid"`). `schema_version` is `1` or `2`
(`SUPPORTED_SCHEMA_VERSIONS`). A `schema_version: 1` document has exactly the SPEC §4 keys above;
`schema_version: 2` adds the optional keys `variants` (D14 amends D4, HLD 70 §70.2) and
`reference_pack` (I3 E2a, HLD 70 §70.5.4, §70.6.1) and `timers` (I3 E4a, HLD 70 §70.3.4), and the
nested `expected_response.responders` (I3 E5b, HLD 70 §70.4.5 — §30.5 below). *(Additive, I3 E8.)*
Schema 2 also accepts the optional metadata key `provenance` (§30.13).

## 30.2 The three fact sections

The three sections are keyed by the same `fact_id` and joined at load time into one `FactDefinition`
per fact (D4, `10-domain-model.md` §10.4). A `fact_id` is a dotted lowercase path
(`^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$`) and is scenario-local — it is not a card `field_path`, although
scoring rules relate the two.

### `world_truth`
```yaml
world_truth:
  scene_summary_ru: "..."          # instructor-only prose, never reaches the caller LLM
  facts:
    <fact_id>:
      world_value: <scalar | list | null>
      value_type: STRING | INTEGER | FLOAT | BOOLEAN | ENUM | STRING_LIST
      label_ru: "<Russian label used in the fact catalog and the report>"
      enum_name: <string>          # required when value_type is ENUM
```

### `caller_knowledge`
```yaml
caller_knowledge:
  facts:
    <fact_id>:
      caller_value: <scalar | list | null>
      knowledge: KNOWN | UNKNOWN | INCORRECT_BELIEF | UNCERTAIN
      certainty: <float 0.0..1.0>   # optional, default 1.0
```

### `disclosure_rules`
```yaml
disclosure_rules:
  facts:
    <fact_id>:
      policy: SPONTANEOUS | ON_ASK | ONLY_IF_EXPLICITLY_ASKED | NEVER_DISCLOSE
      aliases_ru: ["...", "..."]    # optional, default []
      categories: ["address", ...]  # optional, default []
      available_after:              # optional; exactly one key
        sim_time_ms: <int>
        # or  world_event_id: <string>
        # or  condition: <Condition, §30.6.1> — sim_time / action / stage / fact(layer: CALLER)
        #     only; a WORLD fact or a resource leaf is rejected by rule 31 (§30.8)
```

`aliases_ru` and `categories` reach the interpreter LLM inside the fact catalog; **values never do**
(D10).

## 30.3 `caller_profile` (SPEC §6)

```yaml
caller_profile:
  identity_ru: "Соседка из квартиры 41"
  relationship: VICTIM | WITNESS | NEIGHBOUR | RELATIVE | PASSERBY | OFFICIAL | UNKNOWN
  language: "ru-RU"
  voice_id: "ru_female_01"        # SCENARIO-LOGICAL voice id (see below), never a vendor voice name
  age_group: CHILD | TEEN | ADULT | ELDERLY
  baseline_emotion: CALM | WORRIED | FRIGHTENED | PANICKED | ANGRY | CONFUSED | APATHETIC
  cooperativeness: 0.0..1.0
  verbosity: 0.0..1.0
  confusion: 0.0..1.0
  interruption_tendency: 0.0..1.0
  speaking_rate: 0.5..2.0
  baseline_stress_level: 0.0..1.0
  persona_whitelist_ru: ["Ирина", "Петровна"]
  emotion_rules:
    - rule_id: <string, unique in this list>
      trigger:
        kind: WORLD_EVENT | EVENT_TYPE | FACT_REVEALED | SIM_TIME | INTERRUPTION_COUNT
        # plus exactly one of: world_event_id | event_type | fact_id | at_ms | at_least
      set_emotion: <EmotionLabel>   # optional
      stress_delta: <float>         # optional, default 0.0
      max_applications: <int|null>  # optional
```

`current_emotion` and `stress_level` are **not** scenario keys: they are runtime state on
`CallerBelief` and move only through `emotion_rules` (D4).

`voice_id` is a **scenario-logical** voice id (`ru_female_adult_01`) — a casting decision that
outlives whichever TTS provider a deployment selects — and is never a provider's native voice
name; the active model profile's `tts.voice_map` / `tts.default_voice` (HLD 60 §2.1) map it onto
the selected provider's native voice, and an id the map does not name resolves to
`tts.default_voice` with a warning rather than failing the call (E20-G).

## 30.4 `available_resources` (SPEC §11)

```yaml
available_resources:
  - resource_id: <string, unique in this list>
    service_type: FIRE_RESCUE | POLICE | AMBULANCE | GAS_SERVICE | UTILITY_EMERGENCY | EDDS
    resource_type: FIRE_ENGINE | LADDER_TRUCK | RESCUE_UNIT | AMBULANCE_UNIT |
                   RESUSCITATION_UNIT | POLICE_PATROL | GAS_EMERGENCY_UNIT |
                   UTILITY_CREW | FIRE_CHIEF_CAR
    callsign: "АЦ-1"
    name_ru: "Автоцистерна ПСЧ-1"
    home_station_ru: "ПСЧ-1"
    crew_size: 6
    capabilities: [FIRE_SUPPRESSION, WATER_SUPPLY]
    availability:
      available_from_ms: 0
      available_until_ms: null
      initial_status: AVAILABLE
    eta:
      turnout_delay_seconds: 30
      travel_time_seconds: 180
      setup_seconds: 30
      on_scene_work_seconds: 300
      return_time_seconds: 240
```

All five `eta` values are required; the `ScenarioDefinedEta` implementation of the `EtaModel` port
reads them verbatim and no external maps API is involved (SPEC §11, D7).

## 30.5 `expected_response`

```yaml
expected_response:
  required_services: [FIRE_RESCUE, AMBULANCE]
  optional_services: [POLICE]
  required_resource_capabilities: [FIRE_SUPPRESSION, HIGH_RISE_ACCESS, BASIC_LIFE_SUPPORT]
  min_units_by_service:
    FIRE_RESCUE: 2
    AMBULANCE: 1
  resolution_condition: <Condition>        # guard for the DDS `incident_resolved` trigger
  prefab_handoff:                          # optional; required for a DDS-only role_chain (D6)
    recipient_services: [FIRE_RESCUE, AMBULANCE]
    card_values:
      <card field_path>: <value>
  responders: DEFAULT                      # schema 2 only (I3 E5b); or a script per service:
  # responders:
  #   POLICE:
  #     - { after_ms: 0, status: RECEIVED }
  #     - { after_ms: 20000, status: NOT_ACCEPTED, comment_ru: "Не наша компетенция" }
```

`responders` (I3 E5b, HLD 70 §70.4.5) scripts the notified services no ДДС participant is bound to
(`session_participants.assigned_service_id`): `DEFAULT` = `receive +0, ACCEPTED +15 000,
RESPONSE_STARTED +60 000, ARRIVED +180 000, WORKING +200 000, COMPLETED +600 000` ms after the leg's
`HANDOFF_RECEIVED`, or per service a list of `{after_ms, status, comment_ru, order_number}` entries;
a service the map does not name walks `DEFAULT`. Each entry names the `ServiceResponseStatus` the
leg moves to, one `SERVICE_RESPONSE_TRANSITIONS` step at a time (a leg still `ADDED` is first moved
to `RECEIVED` at the same offset). Stage automation fires the steps in memo mode as SIMULATION
(`source: SCRIPTED_RESPONDER`), each stamped with its due offset (INV 7); it is the only reader of
the key at runtime (INV 3).

*(Additive, I3 E6c — `80-telephony.md` §80.3.3, §80.4.1, rule 42.)* Under `dds_brigade_call: ON` the
script of a leg the trainee plays is the brigade's timeline, voiced by the service head on a ДДС call
and never applied. Two optional keys serve it, both only in a document supporting `ON`: an entry's
`report` — `ON_REQUEST` (the default; left out of the canonical dump while default, D4) or `CALL_IN`
(the brigade rings the ДДС when the step falls due) — and a service's persona override, for which the
service's script may be written as the object `{persona: <persona id of the pack>, steps: [...]}`
instead of the bare list, e.g. `FIRE_RESCUE: {persona: BRIGADE_101, steps: [{after_ms: 0, status:
RECEIVED}, {after_ms: 15000, status: ACCEPTED, report: CALL_IN}]}`. At runtime the key's readers stay
runner-side (`responder_scripts`, INV 3): stage automation, the head's `ResponderContextLoader`, and a
persona-id-only probe `startDdsCall` is handed.

`prefab_handoff.card_values` keys must be `field_path`s from `CARD_FIELDS`
(`10-domain-model.md` §10.6). The prefab is deliberately imperfect where the exercise wants it to be —
it stands in for an operator who already made mistakes.

## 30.6 `world_events` (SPEC §12)

### 30.6.1 The `Condition` structure

The same closed declarative structure as `10-domain-model.md` §10.11 — no expressions, no code
strings, no `eval`:

```yaml
# leaves
{ fact:     { fact_id: <str>, layer: WORLD|CALLER, op: EQ|NEQ|GT|GTE|LT|LTE|IN|IS_NULL|IS_NOT_NULL, value: <...> } }
{ resource: { selector: { resource_id: <str> } | { capability: <str> } | { service_type: <str> },
              op: ANY_IS|ALL_ARE|NONE_IS|COUNT_GTE, status: <ResourceStatus>, count: <int|null> } }
{ stage:    { role: OPERATOR_112|DDS|EDDS, op: IS|IS_NOT|REACHED, state: <str> } }
{ sim_time: { op: GTE|LT, ms: <int> } }
{ action:   { event_type: <EventType>, op: OCCURRED|NOT_OCCURRED|COUNT_GTE,
              count: <int|null>, within_ms: <int|null>, payload_equals: <mapping|null> } }
# combinators
{ all: [ <Condition>, ... ] }
{ any: [ <Condition>, ... ] }
{ not: <Condition> }
```

### 30.6.2 Common keys

Every world event has: `world_event_id` (string, unique), `kind`, `title_ru`, `caller_observable`
(bool), `max_occurrences` (int, default 1) and `effects` (list).

### 30.6.3 The four kinds

```yaml
# 1. TimedEvent — fires once the simulation clock passes at_ms
- world_event_id: fire_spreads
  kind: TIMED
  at_ms: 180000
  title_ru: "Огонь распространяется в комнату"
  caller_observable: true
  effects: [ ... ]

# 2. ConditionalEvent — fires when condition holds (re-checked each tick after check_after_ms)
- world_event_id: gas_cylinder_hazard
  kind: CONDITIONAL
  check_after_ms: 0
  cooldown_ms: 0
  condition: { all: [ ... ] }
  title_ru: "Газовый баллон на балконе нагревается"
  caller_observable: false
  effects: [ ... ]

# 3. ActionTriggeredEvent — fires when a matching SessionEvent is appended
- world_event_id: second_report_balcony
  kind: ACTION_TRIGGERED
  on_event_type: HANDOFF_CREATED
  payload_match: null
  delay_ms: 60000
  title_ru: "Повторное сообщение: человек на балконе"
  caller_observable: false
  effects: [ ... ]

# 4. SeededRandomEvent — draws from the session-seeded RNG every check_every_ms
- world_event_id: ac2_breakdown
  kind: SEEDED_RANDOM
  probability: 0.25
  check_every_ms: 30000
  window_start_ms: 0
  window_end_ms: 600000
  condition: { resource: { selector: { resource_id: ac2 }, op: ANY_IS, status: EN_ROUTE } }
  title_ru: "Отказ техники в пути"
  caller_observable: false
  effects: [ ... ]
```

### 30.6.4 Effect YAML shapes

```yaml
- { kind: MUTATE_WORLD_TRUTH, changes: { <fact_id>: <value> } }
- { kind: MUTATE_CALLER_BELIEF,
    changes: { <fact_id>: { value: <v>, knowledge: <KnowledgeState>, certainty: <float> } } }
- { kind: CREATE_NOTIFICATION, audience_role: DDS, severity: INFO|WARNING|CRITICAL,
    title_ru: "...", body_ru: "..." }
- { kind: CREATE_RADIO_MESSAGE, from_callsign: "АЦ-1", to_role: DDS, text_ru: "...",
    resource_id: <str|null> }
- { kind: ALTER_RESOURCE_AVAILABILITY, resource_id: <str>, new_status: <ResourceStatus>,
    restore: false, eta_multiplier: 1.0 }
- { kind: TRIGGER_EVENT, world_event_id: <str>, delay_ms: 0 }
- { kind: CHANGE_CALLER_EMOTION, set_emotion: <EmotionLabel|null>, stress_delta: <float> }
```

`MUTATE_CALLER_BELIEF` on an event with `caller_observable: false` is dropped at runtime (D7); the
loader warns about that combination but does not reject it.

## 30.7 `scoring_rules`

```yaml
scoring_rules:
  - rule_id: <string, unique>
    name_ru: "..."
    description_ru: "..."
    category: INFORMATION_GATHERING | CARD_QUALITY | SERVICE_ROUTING | TIMELINESS |
              WORKFLOW | RESOURCE_MANAGEMENT | COMMUNICATION
    max_points: <float > 0>
    critical: <bool>
    evaluator_type: <one of the ten>
    min_evidence: 1
    applies_to_roles: []   # optional: OPERATOR_112 | DDS; empty (the default) = always applies
    applies_to_variants: {}   # optional (additive, I3 E1): {<switch>: [<value>, ...]}; empty = always
    config: { ... }     # shape depends on evaluator_type
```

`applies_to_roles` names the roles a rule scores. A rule with a non-empty list applies only when at
least one listed role is in the session's role chain **as the event log records it**
(`SESSION_CREATED.role_chain`, falling back to the `ROLE_STAGE_STARTED` types). A rule that does not
apply yields `points_awarded: 0`, `max_points: 0`, `passed: true`, `critical_failure: false` and one
piece of evidence pointing at that chain-recording event, so it changes neither the total, nor a
category percentage, nor the critical-error list. This is what keeps a `SINGLE_ROLE` DDS run from
being scored against the ten 112-stage rules it never had a chance to satisfy (§10.14
"Applicability", D6).

`applies_to_variants` (additive, I3 E1, HLD 70 §70.2.5) names variant values a rule scores, keyed by
switch (`card_source`, `dds_mode`, `dds_card_check`, `dds_brigade_call`). A rule applies only when,
for every switch it names, the session's value (`SESSION_CREATED.variants`; for a log that predates
the key, the scenario's derived default) is listed; otherwise it yields the same zero/zero result as
above. Typical use: `{dds_mode: [RESOURCE_PICKER]}` on picker-only rules.

One example per evaluator type (config keys are the exhaustive list from
`10-domain-model.md` §10.14):

```yaml
  # 1
  - rule_id: fact_victim_inside
    name_ru: "Выяснено, что в квартире есть человек"
    description_ru: "Оператор прямо спросил, остался ли кто-то внутри."
    category: INFORMATION_GATHERING
    max_points: 10
    critical: true
    evaluator_type: FACT_OBTAINED
    applies_to_roles: [OPERATOR_112]
    config: { fact_id: people.victim_01.inside, within_ms: 180000,
              points: 10, penalty_if_missing: 0 }

  # 2
  - rule_id: card_house_correct
    name_ru: "Номер дома записан верно"
    description_ru: "address.house в карточке совпадает с истиной."
    category: CARD_QUALITY
    max_points: 8
    critical: true
    evaluator_type: CARD_FIELD_CORRECT
    applies_to_roles: [OPERATOR_112]
    config: { field_path: address.house, expected_from_fact_id: address.house,
              expected_literal: null, comparison: NORMALIZED_DIGITS, tolerance: 0,
              evaluated_at: HANDOFF, points: 8, penalty_if_wrong: -4 }

  # 3
  - rule_id: card_phone_present
    name_ru: "Телефон заявителя заполнен"
    description_ru: "caller.phone не пуст на момент передачи."
    category: CARD_QUALITY
    max_points: 3
    critical: false
    evaluator_type: CARD_FIELD_PRESENT
    applies_to_roles: [OPERATOR_112]
    config: { field_path: caller.phone, evaluated_at: HANDOFF, points: 3,
              penalty_if_missing: 0, treat_false_as_present: true }

  # 4
  - rule_id: card_no_false_floor
    name_ru: "Этаж не противоречит полученной информации"
    description_ru: "Штраф, если в карточке этаж отличается от сообщённого заявителем."
    category: CARD_QUALITY
    max_points: 4
    critical: false
    evaluator_type: CARD_CONTRADICTION
    applies_to_roles: [OPERATOR_112]
    config: { field_path: address.floor, contradicts_fact_id: address.floor,
              comparison: EXACT, require_fact_delivered: true,
              penalty_points: -4, evaluated_at: HANDOFF }

  # 5
  - rule_id: services_fire_and_ambulance
    name_ru: "Выбраны пожарная охрана и скорая"
    description_ru: "Обе службы указаны получателями, полиция допустима."
    category: SERVICE_ROUTING
    max_points: 12
    critical: true
    evaluator_type: SERVICE_SELECTION
    applies_to_roles: [OPERATOR_112]
    config: { required_services: [FIRE_RESCUE, AMBULANCE],
              forbidden_services: [UTILITY_EMERGENCY],
              points_per_required: 6, penalty_per_forbidden: -3,
              all_or_nothing: false, evaluated_at: HANDOFF }

  # 6
  - rule_id: deadline_handoff
    name_ru: "Карточка передана в ДДС вовремя"
    description_ru: "От ответа на вызов до HANDOFF_CREATED не более 4 минут."
    category: TIMELINESS
    max_points: 10
    critical: false
    evaluator_type: DEADLINE
    applies_to_roles: [OPERATOR_112]
    config: { from_event_type: CALL_ANSWERED, to_event_type: HANDOFF_CREATED,
              to_payload_match: null, max_offset_ms: 240000, points: 10,
              penalty_if_late: -5, scale: LINEAR, linear_zero_ms: 360000 }
    # I4 E31: instead of the literal `max_offset_ms`, a norm may name a per-card timer —
    # `max_offset_timer: accept_within_ms | fill_within_ms` (R44) — read from the session's
    # recorded `SESSION_CREATED.timers` (§30.12). The tickets' memo decision rules do.

  # 7
  - rule_id: workflow_answered_call
    name_ru: "Вызов принят"
    description_ru: "Оператор ответил на вызов ровно один раз."
    category: WORKFLOW
    max_points: 2
    critical: true
    evaluator_type: WORKFLOW_ACTION
    applies_to_roles: [OPERATOR_112]
    config: { event_type: CALL_ANSWERED, payload_match: null, min_count: 1,
              max_count: 1, required_stage_state: null, must_occur_after: null,
              points: 2, penalty_if_missing: -2, penalty_per_excess: 0 }

  # 8
  - rule_id: resources_fire_high_rise
    name_ru: "Направлены силы с автолестницей"
    description_ru: "Минимум две пожарные единицы, одна из них с доступом на высоту."
    category: RESOURCE_MANAGEMENT
    max_points: 12
    critical: true
    evaluator_type: RESOURCE_SELECTION
    applies_to_roles: [DDS]
    config: { required_capabilities: [FIRE_SUPPRESSION, HIGH_RISE_ACCESS],
              min_units_by_service: { FIRE_RESCUE: 2, AMBULANCE: 1 },
              forbidden_resource_ids: [], must_be_dispatched: true,
              points: 12, penalty_per_missing: -4, penalty_per_forbidden: 0 }

  # 9
  - rule_id: status_on_scene_report
    name_ru: "Доклад о прибытии на место"
    description_ru: "ДДС отправил доклад в течение минуты после прибытия."
    category: COMMUNICATION
    max_points: 5
    critical: false
    evaluator_type: REQUIRED_STATUS_UPDATE
    applies_to_roles: [DDS]
    config: { update_kind: ON_SCENE_REPORT, min_count: 1,
              within_ms_of_event: RESOURCE_STATUS_CHANGED, within_ms: 60000,
              points: 5, penalty_if_missing: -2 }

  # 10
  - rule_id: handoff_minimum_fields
    name_ru: "Полнота переданной карточки"
    description_ru: "Ключевые поля заполнены в момент передачи."
    category: CARD_QUALITY
    max_points: 12
    critical: false
    evaluator_type: HANDOFF_COMPLETENESS
    applies_to_roles: [OPERATOR_112]
    config: { required_field_paths: [incident.type, address.locality, address.street,
                                     address.house, address.apartment, description.text],
              points_per_field: 2, all_or_nothing: false,
              penalty_per_missing: 0, treat_false_as_present: true }
```

## 30.8 Load-time validation (D4, complete list)

A scenario that fails any of these cannot start a session; `validate_scenario_version` raises
`ScenarioValidationError` listing every violation, and `make gate` runs the same validation over
`scenarios/examples/**`.

1. `schema_version` is a supported value; no unknown top-level or nested keys (`extra="forbid"`).
2. Every fact id in `caller_knowledge.facts` exists in `world_truth.facts`.
3. Every fact id in `disclosure_rules.facts` exists in `world_truth.facts`.
4. Every fact id in `world_truth.facts` has an entry in both other sections (the join is total).
5. `knowledge: KNOWN` ⇒ `caller_value == world_value`.
6. `knowledge: UNKNOWN` ⇒ `caller_value is None`.
7. `knowledge: INCORRECT_BELIEF` ⇒ `caller_value` is not None **and** `caller_value != world_value`.
8. `knowledge: UNCERTAIN` ⇒ `caller_value` is not None and `certainty < 1.0`.
9. `certainty` is within 0.0–1.0.
10. Each `caller_value` and `world_value` matches the fact's `value_type` (and `enum_name` when ENUM).
11. Every fact id referenced by a `scoring_rules[*].config` key (`fact_id`, `expected_from_fact_id`,
    `contradicts_fact_id`) exists.
12. Every fact id referenced by a `world_events[*]` effect or condition exists.
13. Every fact id referenced by `expected_response` and by `available_after.condition` exists.
14. Every card `field_path` referenced by scoring rules and by `prefab_handoff.card_values` exists in
    `CARD_FIELDS`, and the mapped value matches that field's `value_type`. Since I3 E3a the check is
    against the card schema of the document's own pack (`reference_pack`, `legacy-r1` ⇒ `v1` =
    `CARD_FIELDS`; `v046_24-r1` ⇒ `v2`), and a prefab value of a field with `options` must be one of
    their codes (HLD 70 §70.2.3 R38's card half). An unknown pack is rule 38's alone.
15. `available_resources[*].resource_id` values are unique; `callsign` values are unique.
16. Every `resource_id` referenced by a world event or a scoring rule exists in `available_resources`.
17. Every capability in `expected_response.required_resource_capabilities` is covered by at least one
    resource in `available_resources`.
18. `role_chain` is non-empty, has no duplicates, and every entry is a registered `RoleModule` with
    `implemented is True` (so `EDDS` is rejected, D6).
19. Every `scoring_rules[*].rule_id` is unique and `max_points > 0`; `min_evidence >= 1`.
20. Every `scoring_rules[*].config` validates against its `evaluator_type`'s config model, and every
    role in `scoring_rules[*].applies_to_roles` is a `RoleType` member.
21. `world_events[*].world_event_id` values are unique.
22. The world-event graph has no unconditional cycle: following `TRIGGER_EVENT` effects and
    `ActionTriggeredEvent` links must not form a cycle in which every edge has `delay_ms == 0` and no
    guarding condition.
23. Every `world_event_id` referenced by a `TRIGGER_EVENT` effect or an `available_after` clause exists.
24. `SeededRandomEvent.probability` is within 0.0–1.0 and `check_every_ms > 0`; if `window_end_ms` is
    set it is greater than `window_start_ms`.
25. `TimedEvent.at_ms >= 0`; `ConditionalEvent.check_after_ms >= 0`; `ActionTriggeredEvent.delay_ms >= 0`.
26. Every `Condition` parses into the closed structure of §30.6.1 — no string expressions.
27. `caller_profile.emotion_rules[*].rule_id` values are unique and every referenced
    `world_event_id` / `fact_id` exists.
28. `expected_response.resolution_condition` is present and parses.
29. If `role_chain` is `[DDS]` (or otherwise starts at DDS), `expected_response.prefab_handoff` is
    present — otherwise `SINGLE_ROLE`/`ASSESSMENT` on that chain is rejected at session creation (D6).
30. `deterministic_seed` is a non-empty string.
31. A fact's `available_after.condition` uses only the leaves the fact gate can evaluate:
    `sim_time`, `action`, `stage`, and `fact` with `layer: CALLER`. `fact` with `layer: WORLD` and
    `resource` are refused — the gate runs inside a dialogue turn, which D3 gives the caller-belief
    layer, the session event log and simulated time and **no `WorldTruth`** and no resource board
    (§10.11, §10.12). `evaluate_condition` is total, so such a clause would not fail loudly: it
    would simply never be met and the fact would silently never open.

Rule 1 is extended and rules 32–36 and 40 are added by I3 E1 (HLD 70 §70.2.3; numbers 37–39 belong to
E2 and E4). Rules 32–36 check a `schema_version: 2` document's variants — declared, or derived when
the key is omitted; a schema-1 document's variants are always derived from the document itself and
are not re-checked (P5).

1. *(extended)* `schema_version ∈ {1, 2}`; a key introduced by schema 2 (`variants`, `timers`,
   `reference_pack`, `expected_response.responders`) in a schema-1 document is refused
   (`variants` from E1, `reference_pack` from E2a, `timers` from E4a and `responders` from E5b are
   accepted in schema 2).
32. `variants.default` ∈ `variants.supported`, every `supported` list non-empty and duplicate-free.
33. `CALLER_VOICE` supported ⇒ `OPERATOR_112 ∈ role_chain` and the three fact sections non-empty.
34. `GENERATED_CARD` supported ⇒ `expected_response.prefab_handoff` present (rule 29's check, reached
    through the variant).
35. `RESOURCE_PICKER` supported ⇒ `available_resources` non-empty and `resolution_condition` present.
36. `MEMO_STATUSES` supported ⇒ `expected_response.responders` present or the key `responders:
    DEFAULT` written explicitly (active from E5b). Every script in the map must be playable: each
    entry one SIMULATION step of `SERVICE_RESPONSE_TRANSITIONS` from `ADDED` under the service's
    catalog `status_policy`, `after_ms` non-decreasing, a non-blank `comment_ru` on `NOT_ACCEPTED`
    / `REFUSED`, no empty list.
40. Every `scoring_rules[*].applies_to_variants` key is a `SessionVariants` field and every value a
    member of that switch's enum.

Rules 37 and 38 are added by I3 E2a (HLD 70 §70.2.3, D18). `validate_scenario_version(version, *,
role_modules=…, reference=…)` receives the reference pack the way it receives `role_modules` and stays
pure; its default is the six legacy services under pack `legacy-r1`, and every production caller
(import, `validateScenarioFile`, `createSession`, `make scenarios`) passes the pack loaded from
`reference/`. Service ids are no longer enum members (`ServiceType` → `ServiceId`), so rule 37 is
the check the enum used to make at parse time.

37. Every service id in `expected_response.*` (`required_services`, `optional_services`,
    `min_units_by_service` keys, `prefab_handoff.recipient_services`),
    `available_resources[*].service_type` and the `SERVICE_SELECTION` / `RESOURCE_SELECTION` scoring
    configs (`required_services`, `forbidden_services`, `min_units_by_service` keys) exists in the
    service catalog of the document's pack (`reference_pack`, `legacy-r1` when absent), and so
    does every key of `expected_response.responders` (E5b).
38. `reference_pack` names a pack of `reference/manifest.json`. The card-path half — every path in
    rule 14's scope exists in *that pack's* card schema — is rule 14 itself since I3 E3a added card
    schema `v2` (pack `v046_24-r1`).

Rule 39 is added by I3 E4a (HLD 70 §70.2.3, §70.3.4, D15). A non-positive timer is already refused
when the document is parsed and is reported as rule 39 too; the cross-field half is the validator's.

39. `timers.*` are positive integers; `timers.accept_within_ms < timers.not_completed_after_ms`
    (after the defaults of §30.12 are applied to absent keys).

Rule 43 is added by I3 E8 (§30.13); numbers 41 and 42 are the telephony HLD's
(`80-telephony.md`, E6b/E6c). Rule 1 is extended once more: `provenance` in a schema-1 document is
refused.

Rule 41 is added by I3 E6b (`80-telephony.md` §80.5, D25): `dds_brigade_call: ON` — "the ДДС has a
phone" — is a memo-mode variant. Its session half is `resolve_variants`': a session resolving to
`ON` with `dds_mode: RESOURCE_PICKER` is refused with `409 VARIANT_NOT_SUPPORTED`. Rule 42 is added
by I3 E6c (`80-telephony.md` §80.4.1, §80.5): the persona override and a script step's `report`.

41. `variants.supported.dds_brigade_call` contains `ON` ⇒ `variants.supported.dds_mode` contains
    `MEMO_STATUSES` and `expected_response.responders` is present (or `responders: DEFAULT`).
42. `expected_response.responders[service_id].persona`, when present, names a persona of the
    document's reference pack (`reference/personas/<id>.yaml` of the pack in the manifest); a
    step's `report` is `ON_REQUEST` or `CALL_IN`; and `persona` / a `CALL_IN` step appear only in a
    schema-2 document whose `variants.supported.dds_brigade_call` contains `ON`.

43. `provenance`, when present, is well formed — exactly the keys `source` (`TICKET`), `ticket`
    (integer), `call` (integer) and `generation_candidate` (boolean), strictly typed; a malformed key
    is reported as rule 43, not rule 1 — and names a call that exists: for `source: TICKET`,
    `1 ≤ ticket ≤ 32` and `1 ≤ call ≤ 3` (the organizer's 32 tickets × 3 calls, REQ-5203/REQ-5206).

Rule 44 is added by I4 E31 (`71-i4-wave4.md` §71.8, D34). The design text names it "R43"; that
number was already rule 43 above (I3 E8), so the timer rule is numbered 44.

44. A `DEADLINE` rule's `config.max_offset_timer`, when present, names a per-card timer the
    evaluator can read from `SESSION_CREATED.timers`: `accept_within_ms` or `fill_within_ms`
    (§30.12). A config with both `max_offset_ms` and `max_offset_timer`, or neither, does not
    validate against `DEADLINE` and is rule 20's.

## 30.9 Demo scenario sketch — "Пожар в квартире"

`scenarios/examples/apartment-fire/v1.yaml`, abridged: the fact table, resources and events are
complete in structure; only prose is shortened. Designed for a 10–15 minute run.

```yaml
id: 3f6c1a20-0e1a-4b1e-9d2a-0a7c5b2f1d11
schema_version: 1
scenario_id: 9c2a77bc-4e3d-4a1a-9a71-2cf0a1e4b501
version: 1
title: "Apartment fire, Smolensk, Nikolaeva 27"
description: "Neighbour reports smoke from a ninth-floor block; one elderly resident is inside."
difficulty: 3
deterministic_seed: "apartment-fire-v1"
role_chain: [OPERATOR_112, DDS]

world_truth:
  scene_summary_ru: >
    Горит кухня в квартире 45 на 4-м этаже 9-этажного дома по улице Николаева, 27.
    В квартире находится 78-летняя женщина. На балконе стоит газовый баллон.
  facts:
    incident.type:            { world_value: FIRE, value_type: ENUM, enum_name: IncidentType, label_ru: "Тип происшествия" }
    incident.smoke_visible:   { world_value: true, value_type: BOOLEAN, label_ru: "Видно дым" }
    incident.fire_source:     { world_value: KITCHEN, value_type: ENUM, enum_name: FireSource, label_ru: "Очаг возгорания" }
    incident.cause:           { world_value: "неисправная электропроводка", value_type: STRING, label_ru: "Причина пожара" }
    incident.floor_count:     { world_value: 9, value_type: INTEGER, label_ru: "Этажность дома" }
    address.locality:         { world_value: "Смоленск", value_type: STRING, label_ru: "Населённый пункт" }
    address.street:           { world_value: "улица Николаева", value_type: STRING, label_ru: "Улица" }
    address.house:            { world_value: "27", value_type: STRING, label_ru: "Дом" }
    address.entrance:         { world_value: "3", value_type: STRING, label_ru: "Подъезд" }
    address.floor:            { world_value: 4, value_type: INTEGER, label_ru: "Этаж" }
    address.apartment:        { world_value: "45", value_type: STRING, label_ru: "Квартира" }
    address.landmark:         { world_value: "напротив продуктового магазина", value_type: STRING, label_ru: "Ориентир" }
    caller.full_name:         { world_value: "Соколова Ирина Петровна", value_type: STRING, label_ru: "ФИО заявителя" }
    caller.phone:             { world_value: "+79101234567", value_type: STRING, label_ru: "Телефон заявителя" }
    people.victim_01.inside:  { world_value: true, value_type: BOOLEAN, label_ru: "Человек в квартире" }
    people.victim_01.age:     { world_value: 78, value_type: INTEGER, label_ru: "Возраст пострадавшей" }
    people.total_inside:      { world_value: 1, value_type: INTEGER, label_ru: "Человек в квартире, всего" }
    hazards.gas_cylinder:     { world_value: true, value_type: BOOLEAN, label_ru: "Газовый баллон на балконе" }
    hazards.electrical:       { world_value: true, value_type: BOOLEAN, label_ru: "Электроопасность" }

caller_knowledge:
  facts:
    incident.type:            { caller_value: FIRE, knowledge: KNOWN }
    incident.smoke_visible:   { caller_value: true, knowledge: KNOWN }
    incident.fire_source:     { caller_value: null, knowledge: UNKNOWN }
    incident.cause:           { caller_value: null, knowledge: UNKNOWN }
    incident.floor_count:     { caller_value: 9, knowledge: KNOWN }
    address.locality:         { caller_value: "Смоленск", knowledge: KNOWN }
    address.street:           { caller_value: "улица Николаева", knowledge: KNOWN }
    address.house:            { caller_value: "27", knowledge: KNOWN }
    address.entrance:         { caller_value: "3", knowledge: KNOWN }
    address.floor:            { caller_value: 5, knowledge: INCORRECT_BELIEF }
    address.apartment:        { caller_value: "45", knowledge: KNOWN }
    address.landmark:         { caller_value: "напротив магазина", knowledge: UNCERTAIN, certainty: 0.6 }
    caller.full_name:         { caller_value: "Соколова Ирина Петровна", knowledge: KNOWN }
    caller.phone:             { caller_value: "+79101234567", knowledge: KNOWN }
    people.victim_01.inside:  { caller_value: true, knowledge: KNOWN }
    people.victim_01.age:     { caller_value: 80, knowledge: UNCERTAIN, certainty: 0.4 }
    people.total_inside:      { caller_value: 1, knowledge: UNCERTAIN, certainty: 0.5 }
    hazards.gas_cylinder:     { caller_value: null, knowledge: UNKNOWN }
    hazards.electrical:       { caller_value: false, knowledge: INCORRECT_BELIEF }

disclosure_rules:
  facts:
    incident.type:            { policy: SPONTANEOUS, categories: [incident], aliases_ru: ["что случилось", "что происходит"] }
    incident.smoke_visible:   { policy: SPONTANEOUS, categories: [incident], aliases_ru: ["дым", "задымление"] }
    incident.fire_source:     { policy: NEVER_DISCLOSE, categories: [incident], aliases_ru: ["очаг", "что горит", "откуда горит"] }
    incident.cause:           { policy: NEVER_DISCLOSE, categories: [incident], aliases_ru: ["причина", "из-за чего"] }
    incident.floor_count:     { policy: ON_ASK, categories: [address], aliases_ru: ["сколько этажей", "этажность"] }
    address.locality:         { policy: ON_ASK, categories: [address], aliases_ru: ["город", "населённый пункт"] }
    address.street:           { policy: ON_ASK, categories: [address], aliases_ru: ["улица", "адрес"] }
    address.house:            { policy: ON_ASK, categories: [address], aliases_ru: ["дом", "номер дома"] }
    address.entrance:         { policy: ON_ASK, categories: [address], aliases_ru: ["подъезд"] }
    address.floor:            { policy: ON_ASK, categories: [address], aliases_ru: ["этаж", "какой этаж"] }
    address.apartment:        { policy: ON_ASK, categories: [address], aliases_ru: ["квартира", "номер квартиры"] }
    address.landmark:         { policy: ON_ASK, categories: [address], aliases_ru: ["ориентир", "рядом с чем"] }
    caller.full_name:         { policy: ON_ASK, categories: [caller], aliases_ru: ["как вас зовут", "фамилия", "представьтесь"] }
    caller.phone:             { policy: ON_ASK, categories: [caller], aliases_ru: ["телефон", "номер телефона"] }
    people.victim_01.inside:  { policy: ONLY_IF_EXPLICITLY_ASKED, categories: [people],
                                aliases_ru: ["кто-то внутри", "остался ли кто", "есть ли люди в квартире"] }
    people.victim_01.age:     { policy: ONLY_IF_EXPLICITLY_ASKED, categories: [people], aliases_ru: ["возраст", "сколько лет"] }
    people.total_inside:      { policy: ON_ASK, categories: [people], aliases_ru: ["сколько человек", "сколько людей"] }
    hazards.gas_cylinder:     { policy: ON_ASK, categories: [hazards], aliases_ru: ["баллон", "газ", "опасные предметы"],
                                available_after: { world_event_id: gas_cylinder_hazard } }
    hazards.electrical:       { policy: ON_ASK, categories: [hazards], aliases_ru: ["электричество", "проводка"] }
```

Knowledge-state coverage: `KNOWN` (e.g. `address.house`), `UNKNOWN` (`incident.fire_source`),
`INCORRECT_BELIEF` (`address.floor`, `hazards.electrical`), `UNCERTAIN` (`people.victim_01.age`,
`address.landmark`, `people.total_inside`).
Disclosure-policy coverage: `SPONTANEOUS` (`incident.type`), `ON_ASK` (the address block),
`ONLY_IF_EXPLICITLY_ASKED` (`people.victim_01.inside`), `NEVER_DISCLOSE` (`incident.fire_source`).

The two SPEC §5 examples appear literally: `people.victim_01.inside` is
`world_value: true / caller_value: true / knowledge: KNOWN / policy: ONLY_IF_EXPLICITLY_ASKED`, and
`incident.fire_source` is `world_value: KITCHEN / caller_value: null / knowledge: UNKNOWN /
policy: NEVER_DISCLOSE`. If the trainee asks about the source of the fire, the caller says she does
not know, and `KITCHEN` never enters the LLM context.

```yaml
caller_profile:
  identity_ru: "Соседка Ирина Петровна из квартиры 41"
  relationship: NEIGHBOUR
  language: "ru-RU"
  voice_id: "ru_female_adult_01"
  age_group: ADULT
  baseline_emotion: FRIGHTENED
  cooperativeness: 0.8
  verbosity: 0.5
  confusion: 0.4
  interruption_tendency: 0.3
  speaking_rate: 1.15
  baseline_stress_level: 0.6
  persona_whitelist_ru: ["Ирина", "Петровна", "Соколова"]
  emotion_rules:
    - rule_id: panic_on_spread
      trigger: { kind: WORLD_EVENT, world_event_id: fire_spreads }
      set_emotion: PANICKED
      stress_delta: 0.3
      max_applications: 1
    - rule_id: calm_after_dispatch
      trigger: { kind: EVENT_TYPE, event_type: RESOURCE_DISPATCHED }
      set_emotion: WORRIED
      stress_delta: -0.2
      max_applications: 1

available_resources:
  - { resource_id: ac1,  service_type: FIRE_RESCUE, resource_type: FIRE_ENGINE,      callsign: "АЦ-1",  name_ru: "Автоцистерна ПСЧ-1",        home_station_ru: "ПСЧ-1", crew_size: 6, capabilities: [FIRE_SUPPRESSION, WATER_SUPPLY, SMOKE_DIVING], availability: { available_from_ms: 0, available_until_ms: null, initial_status: AVAILABLE }, eta: { turnout_delay_seconds: 30, travel_time_seconds: 150, setup_seconds: 30, on_scene_work_seconds: 240, return_time_seconds: 180 } }
  - { resource_id: ac2,  service_type: FIRE_RESCUE, resource_type: FIRE_ENGINE,      callsign: "АЦ-2",  name_ru: "Автоцистерна ПСЧ-3",        home_station_ru: "ПСЧ-3", crew_size: 6, capabilities: [FIRE_SUPPRESSION, WATER_SUPPLY],               availability: { available_from_ms: 0, available_until_ms: null, initial_status: AVAILABLE }, eta: { turnout_delay_seconds: 40, travel_time_seconds: 210, setup_seconds: 30, on_scene_work_seconds: 240, return_time_seconds: 210 } }
  - { resource_id: al1,  service_type: FIRE_RESCUE, resource_type: LADDER_TRUCK,     callsign: "АЛ-1",  name_ru: "Автолестница ПСЧ-1",        home_station_ru: "ПСЧ-1", crew_size: 3, capabilities: [HIGH_RISE_ACCESS, LADDER_RESCUE],             availability: { available_from_ms: 0, available_until_ms: null, initial_status: AVAILABLE }, eta: { turnout_delay_seconds: 40, travel_time_seconds: 180, setup_seconds: 60, on_scene_work_seconds: 240, return_time_seconds: 200 } }
  - { resource_id: asa1, service_type: FIRE_RESCUE, resource_type: RESCUE_UNIT,      callsign: "АСА-1", name_ru: "Аварийно-спасательный автомобиль", home_station_ru: "ПСЧ-1", crew_size: 4, capabilities: [TECHNICAL_RESCUE, SMOKE_DIVING],      availability: { available_from_ms: 0, available_until_ms: null, initial_status: AVAILABLE }, eta: { turnout_delay_seconds: 35, travel_time_seconds: 200, setup_seconds: 30, on_scene_work_seconds: 240, return_time_seconds: 200 } }
  - { resource_id: nk1,  service_type: FIRE_RESCUE, resource_type: FIRE_CHIEF_CAR,   callsign: "НК-1",  name_ru: "Автомобиль начальника караула", home_station_ru: "ПСЧ-1", crew_size: 2, capabilities: [COMMAND_AND_CONTROL],                    availability: { available_from_ms: 0, available_until_ms: null, initial_status: AVAILABLE }, eta: { turnout_delay_seconds: 20, travel_time_seconds: 140, setup_seconds: 20, on_scene_work_seconds: 300, return_time_seconds: 160 } }
  - { resource_id: smp11, service_type: AMBULANCE,  resource_type: AMBULANCE_UNIT,   callsign: "СМП-11", name_ru: "Бригада СМП №11",          home_station_ru: "Подстанция 1", crew_size: 3, capabilities: [BASIC_LIFE_SUPPORT],                  availability: { available_from_ms: 0, available_until_ms: null, initial_status: AVAILABLE }, eta: { turnout_delay_seconds: 25, travel_time_seconds: 180, setup_seconds: 20, on_scene_work_seconds: 300, return_time_seconds: 200 } }
  - { resource_id: smp12, service_type: AMBULANCE,  resource_type: AMBULANCE_UNIT,   callsign: "СМП-12", name_ru: "Бригада СМП №12",          home_station_ru: "Подстанция 2", crew_size: 3, capabilities: [BASIC_LIFE_SUPPORT],                  availability: { available_from_ms: 120000, available_until_ms: null, initial_status: UNAVAILABLE }, eta: { turnout_delay_seconds: 25, travel_time_seconds: 260, setup_seconds: 20, on_scene_work_seconds: 300, return_time_seconds: 260 } }
  - { resource_id: rb1,  service_type: AMBULANCE,   resource_type: RESUSCITATION_UNIT, callsign: "РБ-1", name_ru: "Реанимационная бригада",   home_station_ru: "Подстанция 1", crew_size: 4, capabilities: [ADVANCED_LIFE_SUPPORT, BURN_CARE],  availability: { available_from_ms: 0, available_until_ms: null, initial_status: AVAILABLE }, eta: { turnout_delay_seconds: 30, travel_time_seconds: 230, setup_seconds: 25, on_scene_work_seconds: 300, return_time_seconds: 230 } }
  - { resource_id: pps204, service_type: POLICE,    resource_type: POLICE_PATROL,    callsign: "ППС-204", name_ru: "Патруль ППС 204",         home_station_ru: "ОП №1", crew_size: 2, capabilities: [PUBLIC_ORDER, AREA_CORDON],                  availability: { available_from_ms: 0, available_until_ms: null, initial_status: AVAILABLE }, eta: { turnout_delay_seconds: 15, travel_time_seconds: 160, setup_seconds: 15, on_scene_work_seconds: 360, return_time_seconds: 160 } }
  - { resource_id: dps31, service_type: POLICE,     resource_type: POLICE_PATROL,    callsign: "ДПС-31", name_ru: "Экипаж ДПС 31",            home_station_ru: "ОБ ДПС", crew_size: 2, capabilities: [TRAFFIC_CONTROL, AREA_CORDON],              availability: { available_from_ms: 0, available_until_ms: null, initial_status: AVAILABLE }, eta: { turnout_delay_seconds: 15, travel_time_seconds: 200, setup_seconds: 15, on_scene_work_seconds: 300, return_time_seconds: 200 } }
  - { resource_id: ags1, service_type: GAS_SERVICE, resource_type: GAS_EMERGENCY_UNIT, callsign: "АГС-1", name_ru: "Аварийная газовая бригада", home_station_ru: "Горгаз", crew_size: 3, capabilities: [GAS_SHUTOFF, GAS_LEAK_DETECTION],          availability: { available_from_ms: 0, available_until_ms: null, initial_status: AVAILABLE }, eta: { turnout_delay_seconds: 45, travel_time_seconds: 240, setup_seconds: 30, on_scene_work_seconds: 240, return_time_seconds: 240 } }

expected_response:
  required_services: [FIRE_RESCUE, AMBULANCE]
  optional_services: [POLICE, GAS_SERVICE]
  required_resource_capabilities: [FIRE_SUPPRESSION, HIGH_RISE_ACCESS, BASIC_LIFE_SUPPORT]
  min_units_by_service: { FIRE_RESCUE: 2, AMBULANCE: 1 }
  resolution_condition:
    all:
      - { resource: { selector: { capability: FIRE_SUPPRESSION }, op: ANY_IS, status: WORKING } }
      - { sim_time: { op: GTE, ms: 540000 } }
  prefab_handoff:
    recipient_services: [FIRE_RESCUE, AMBULANCE]
    card_values:
      incident.type: FIRE
      address.locality: "Смоленск"
      address.street: "улица Николаева"
      address.house: "27"
      address.entrance: "3"
      address.floor: 5            # deliberately the caller's wrong floor
      address.apartment: "45"
      description.text: "Задымление и открытое горение в квартире, в квартире человек."
      people.trapped_count: 1
      flags.threat_to_life: true
      recipients.services: [FIRE_RESCUE, AMBULANCE]

world_events:
  # TIMED — the fire spreads three minutes in
  - world_event_id: fire_spreads
    kind: TIMED
    at_ms: 180000
    title_ru: "Огонь перекинулся в комнату"
    caller_observable: true
    max_occurrences: 1
    effects:
      - { kind: MUTATE_WORLD_TRUTH, changes: { incident.smoke_visible: true } }
      - { kind: MUTATE_CALLER_BELIEF, changes: { incident.smoke_visible: { value: true, knowledge: KNOWN, certainty: 1.0 } } }
      - { kind: CREATE_NOTIFICATION, audience_role: DDS, severity: WARNING,
          title_ru: "Развитие пожара", body_ru: "Горение распространилось на комнату, требуется усиление." }
      - { kind: CHANGE_CALLER_EMOTION, set_emotion: PANICKED, stress_delta: 0.3 }

  # ACTION_TRIGGERED — a second caller reports a person on the balcony one minute after the handoff
  - world_event_id: second_report_balcony
    kind: ACTION_TRIGGERED
    on_event_type: HANDOFF_CREATED
    payload_match: null
    delay_ms: 60000
    title_ru: "Повторное сообщение: человек на балконе"
    caller_observable: false
    max_occurrences: 1
    effects:
      - { kind: MUTATE_WORLD_TRUTH, changes: { people.total_inside: 2 } }
      - { kind: CREATE_NOTIFICATION, audience_role: DDS, severity: CRITICAL,
          title_ru: "Повторное сообщение", body_ru: "Очевидцы сообщают о человеке на балконе 4-го этажа." }

  # CONDITIONAL — the gas cylinder becomes a hazard only if help is slow
  - world_event_id: gas_cylinder_hazard
    kind: CONDITIONAL
    check_after_ms: 0
    cooldown_ms: 0
    title_ru: "Газовый баллон на балконе нагревается"
    caller_observable: true
    max_occurrences: 1
    condition:
      all:
        - { sim_time: { op: GTE, ms: 420000 } }
        - { not: { resource: { selector: { capability: FIRE_SUPPRESSION }, op: ANY_IS, status: WORKING } } }
    effects:
      - { kind: MUTATE_WORLD_TRUTH, changes: { hazards.gas_cylinder: true } }
      - { kind: MUTATE_CALLER_BELIEF, changes: { hazards.gas_cylinder: { value: true, knowledge: KNOWN, certainty: 1.0 } } }
      - { kind: CREATE_NOTIFICATION, audience_role: DDS, severity: CRITICAL,
          title_ru: "Угроза взрыва", body_ru: "На балконе горящей квартиры газовый баллон." }
      - { kind: CHANGE_CALLER_EMOTION, set_emotion: PANICKED, stress_delta: 0.2 }

  # SEEDED_RANDOM — a vehicle may break down on the way
  - world_event_id: ac2_breakdown
    kind: SEEDED_RANDOM
    probability: 0.25
    check_every_ms: 30000
    window_start_ms: 0
    window_end_ms: 600000
    title_ru: "Отказ техники в пути"
    caller_observable: false
    max_occurrences: 1
    condition: { resource: { selector: { resource_id: ac2 }, op: ANY_IS, status: EN_ROUTE } }
    effects:
      - { kind: ALTER_RESOURCE_AVAILABILITY, resource_id: ac2, new_status: OUT_OF_SERVICE, restore: false, eta_multiplier: 1.0 }
      - { kind: CREATE_RADIO_MESSAGE, from_callsign: "АЦ-2", to_role: DDS, resource_id: ac2,
          text_ru: "АЦ-2, неисправность в пути, следование прекращаю." }
      - { kind: CREATE_NOTIFICATION, audience_role: DDS, severity: WARNING,
          title_ru: "АЦ-2 вышла из строя", body_ru: "Требуется замена расчёта." }

scoring_rules:
  # the ten rules of §30.7, verbatim
```

Intended demo arc: ring → answer → the caller spontaneously says there is a fire and smoke; the
trainee must ask for the address (`27`, which the caller states correctly and which the trainee may
mistype as `72`), must ask **explicitly** whether anyone is inside to unlock
`people.victim_01.inside`, and gets a wrong floor (5 instead of 4) and a wrong electrical assessment
from a sincere caller. Fire source and cause are never obtainable. Handoff at ~4 minutes, DDS
acknowledges, dispatches `ac1` + `al1` + `smp11`, the fire spreads at T+3:00, a second report arrives
one minute after the handoff, the gas cylinder threat appears only if suppression has not started by
T+7:00, and `ac2` may break down if it was dispatched. Resolution at T+9:00 once a suppression unit is
`WORKING`.

## 30.10 `variants` — schema 2 (additive, I3 E1)

```yaml
variants:
  supported:                        # per switch, the values a session may select (non-empty lists)
    card_source: [CALLER_VOICE, GENERATED_CARD]
    dds_mode: [RESOURCE_PICKER]
    dds_card_check: ['OFF']
    dds_brigade_call: ['OFF']
  default:                          # one value per switch, each in `supported`
    card_source: GENERATED_CARD
    dds_mode: RESOURCE_PICKER
    dds_card_check: 'OFF'
    dds_brigade_call: 'OFF'
```

The scenario is the first of the three homes of HLD 70 §70.2.2; session creation selects within
`supported` (`409 VARIANT_NOT_SUPPORTED`), an unimplemented value is `409 VARIANT_NOT_AVAILABLE`, and
`SESSION_CREATED.variants` records the result. A document without the key — every schema-1 document —
gets a derived value: `card_source` supports `CALLER_VOICE` iff `OPERATOR_112 ∈ role_chain` and
`GENERATED_CARD` iff `expected_response.prefab_handoff` is present (or the chain starts at DDS, which
rule 29 ties to a prefab); `dds_mode` `[RESOURCE_PICKER]`; `dds_card_check` `[OFF, ON]`;
`dds_brigade_call` `[OFF]`. The schema-1 default is `CALLER_VOICE` when supported (today's
behaviour), else `GENERATED_CARD`, and `RESOURCE_PICKER`, `OFF`, `OFF`; a schema-2 document without
the key takes the product default (`GENERATED_CARD`, `RESOURCE_PICKER`, `OFF`, `OFF`) wherever the
derived support allows it. Under `GENERATED_CARD` a session runs the `role_chain` suffix starting at
DDS on the scenario's `prefab_handoff`.

## 30.11 `reference_pack` — schema 2 (additive, I3 E2a)

```yaml
reference_pack: legacy-r1          # a pack id of reference/manifest.json
```

The reference pack (HLD 70 §70.6.1, D18) is the sha-pinned `reference/` directory: the card schema,
the service catalog («СЛУЖБЫ 112») and the classifier a scenario's sessions use. A schema-1 document
— and a schema-2 document that omits the key — uses `legacy-r1` (card schema `v1` = today's
`CARD_FIELDS`, service catalog `v1`, no classifier). Rule 38 refuses an unknown pack and rule 37
checks every service id against the pack's catalog. `createSession` records the pack's ids and file
sha256 in `SESSION_CREATED.reference_pack`; a stored version naming a pack the running manifest
lacks cannot start a session (`409 REFERENCE_PACK_UNKNOWN`). A dump omits an absent key, so a
schema-1 document's `content_sha256` is unchanged (P5).

Since I3 E3a the manifest has a second pack, `v046_24-r1` (card schema `v2` — the organizer's card,
`reference/card-schema/v2.yaml` —, service catalog `v1`, classifier `v046_24`). A document on it
writes its `prefab_handoff.card_values`, `CARD_FIELD_*` and `HANDOFF_COMPLETENESS` paths in v2
paths (rule 14 checks them against v2), and its sessions' cards are v2 cards: `setCardField`
validates against v2 and the card and ДДС views carry v2's field specs (HLD 70 §70.5.4). The
committed example is `scenarios/examples/street-rubbish-fire/v1.yaml` (`GENERATED_CARD`).

## 30.12 `timers` — schema 2 (additive, I3 E4a)

```yaml
timers:                         # all in SESSION (running) milliseconds; defaults when absent
  accept_within_ms: 30000       # Принята / Не принята within 30 s of the leg's HANDOFF_RECEIVED
  fill_within_ms: 180000        # 3 minutes to fill the card, from CALL_ANSWERED (CALLER_VOICE only)
  not_completed_after_ms: 172800000   # 48 h → «Не завершено», from the handoff; authors scale it
```

The per-card timers of HLD 70 §70.3.4 (D15). Every absent key — and an absent `timers` — takes its
default, which is also what every schema-1 document gets (`ScenarioVersion.card_timers`). They are
**session** milliseconds, not wall milliseconds, so the deadline consequences are deterministic and
independent of `time_scale`. `createSession` records the resolved timers in `SESSION_CREATED.timers`
— since I4 E31 the scenario's timers with the instructor's per-key override applied
(`SessionCreateRequest.timers`, `PlanEntry.timers`; scenario ← override, R39 on the result);
the card-status projection (HLD 70 §70.4.6) reads them from there: a leg without a primary decision
at `received + accept_within_ms` turns the card `NOT_NOTIFIED`, a leg not completed at
`handoff + not_completed_after_ms` turns it `NOT_COMPLETED` — each a SIMULATION
`DDS_CARD_STATUS_CHANGED` stamped with the deadline offset. The *scoring* of a late action stays an
ordinary `DEADLINE` rule in `scoring_rules`; with `max_offset_timer` (I4 E31, rule 44) its norm is
the recorded timer, so an overridden timer moves the score and the card status together. Rule 39 checks the key; a dump omits an absent key, so a
schema-1 document's `content_sha256` is unchanged (P5).

## 30.13 `provenance` — schema 2 (additive, I3 E8)

```yaml
provenance:                     # optional; metadata only — no machine reads it at runtime
  source: TICKET                # ProvenanceSource: the organizer's tickets «Билеты- задачи по C 112»
  ticket: 17                    # 1–32 (one «БИЛЕТ» per page)
  call: 2                       # 1–3 (the ticket table's row «№»)
  generation_candidate: true    # a candidate for later generation (owner, I3)
```

Where a scenario's content was authored from, and whether it is a candidate for later generation
(the owner's «переводим в сценарии с пометкой, о возможном переводе в генерацию»). The model is
`ScenarioProvenance` (`backend/app/domain/scenario/sections.py`, frozen, `extra="forbid"`, strict
types); rule 43 checks it (§30.8) and rule 1 refuses it in a schema-1 document. A dump omits an
absent key, so the `content_sha256` of every document without it is unchanged (P5). Nothing in a
session reads the key: it is catalog metadata for authors and for a future generator.

The 96 ticket scenarios live in `scenarios/tickets/ticket-NN-call-M/v1.yaml` (one per call,
`generation_candidate: true`), with special variants beside their base
(`…-decline`: a competence decline scripted through `expected_response.responders`;
`…-card-error`: a deliberately imperfect prefab card with `dds_card_check: ON` by default); the
index is `scenarios/tickets/README.md`. They load through the same `<slug>/v<N>.yaml` convention
(`python -m app.tools.validate_scenarios scenarios/tickets`, `app.tools.import_scenarios
scenarios/tickets`).

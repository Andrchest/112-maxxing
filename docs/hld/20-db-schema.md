# HLD 20 — PostgreSQL schema

PostgreSQL 16, SQLAlchemy 2 (async, `asyncpg`), Alembic with one linear history (SPEC §30, D5).
ORM classes live in `backend/app/db/models/`; mapping to and from the domain types of
`docs/hld/10-domain-model.md` lives in `backend/app/infrastructure/persistence/`. The domain layer
never imports any of this (D2).

Conventions used throughout:
- Primary keys are `uuid` with `DEFAULT gen_random_uuid()` (extension `pgcrypto`), except
  `scoring_rules`, whose PK is composite and scenario-scoped.
- Timestamps are `timestamptz`; `created_at` defaults to `now()`. Simulation-relative times are
  `integer` milliseconds named `*_offset_ms` (D5).
- Every enum is stored as `text` with a `CHECK (col IN (…))` constraint listing exactly the members
  from `10-domain-model.md` §10.2. Native PG enums are deliberately avoided: adding a member must not
  require a type-altering migration during the project's build-out.
- `ON DELETE` is `CASCADE` down the session aggregate and `RESTRICT` towards reference data, so a
  scenario version in use can never be deleted out from under a session.

## 20.1 Table inventory

| # | Table | SPEC §30 | Kind |
|:--|:--|:--|:--|
| 1 | `users` | ✔ | reference data |
| 2 | `scenarios` | ✔ | reference data |
| 3 | `scenario_versions` | ✔ | reference data, immutable once locked |
| 4 | `simulation_sessions` | ✔ | aggregate root, materialized |
| 5 | `session_participants` | ✔ | aggregate |
| 6 | `role_stages` | ✔ | materialized from the event log |
| 7 | `incidents` | ✔ | aggregate |
| 8 | `incident_cards` | ✔ | materialized from `incident_card_revisions` |
| 9 | `incident_card_revisions` | ✔ | append-only audit |
| 10 | `handoff_snapshots` | ✔ | immutable |
| 11 | `dds_assignments` | ✔ | materialized from the event log |
| 12 | `emergency_resources` | ✔ | per-session instances of scenario resource specs |
| 13 | `resource_state_changes` | ✔ | append-only audit |
| 14 | `session_events` | ✔ | **the audit source**, append-only |
| 15 | `transcript_segments` | ✔ | materialized |
| 16 | `audio_segments` | ✔ | file index |
| 17 | `scoring_rules` | ✔ | reference data (projection of the scenario version) |
| 18 | `score_results` | ✔ | derived, recomputable from `session_events` |
| 19 | `score_evidence` | ✔ | derived |
| 20 | `inference_metrics` | ✔ | telemetry |
| 21 | `incident_world_states` | additive (D3) | 1 row / incident, engine-written |
| 22 | `incident_caller_beliefs` | additive (D3) | 1 row / incident, engine-written |
| 23 | `notifications` | additive (D5) | materialized from the event log |
| 24 | `dialogue_turns` | additive (ratified; `50-voice-pipeline.md` §9, `60-inference-ops.md`) | materialized turn record |
| 25 | `recording_purge_audit` | additive (ratified; `50-voice-pipeline.md` §9.2) | retention audit |
| 26 | `world_engine_states` | additive (E6; D7) | 1 row / incident, engine-written bookkeeping |
| 27 | `report_explanations` | additive (E16; D11, SPEC §2, §29) | the optional LLM prose about a stored `ScoreReport` |
| 28 | `lessons` | additive (I3 E4a; D15, `70-i3-alignment.md` §70.3) | scheduling of N ordinary sessions; no event log of its own |

Materialized tables exist for efficient reads only. `session_events` is authoritative; scoring reads
`(scenario_versions.content, ordered session_events)` and nothing else (D5, SPEC §28, §42 tests 9–11).
`RadioMessage` has **no** table: D5 authorises exactly three additive tables, so radio traffic is
persisted as `RADIO_MESSAGE_CREATED` rows in `session_events` and served from an in-memory read model
built from the log. Flagged in the report for the manager to ratify.

## 20.2 Reference data

### `users`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `username` | `text` | no | |
| `password_hash` | `text` | no | |
| `display_name_ru` | `text` | no | |
| `role` | `text` | no | `'TRAINEE'` |
| `is_active` | `boolean` | no | `true` |
| `created_at` | `timestamptz` | no | `now()` |

PK `(id)`. Unique `uq_users_username (username)`. `CHECK (role IN ('TRAINEE','INSTRUCTOR','ADMIN'))` (D8).

### `scenarios`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `slug` | `text` | no | |
| `title_ru` | `text` | no | |
| `created_at` | `timestamptz` | no | `now()` |

PK `(id)`. Unique `uq_scenarios_slug (slug)`.

### `scenario_versions`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `scenario_id` | `uuid` | no | |
| `version` | `integer` | no | |
| `schema_version` | `integer` | no | |
| `title` | `text` | no | |
| `description` | `text` | no | `''` |
| `difficulty` | `smallint` | no | `1` |
| `deterministic_seed` | `text` | no | |
| `role_chain` | `text[]` | no | |
| `content` | `jsonb` | no | |
| `content_sha256` | `text` | no | |
| `source_path` | `text` | yes | |
| `locked_at` | `timestamptz` | yes | |
| `created_at` | `timestamptz` | no | `now()` |

PK `(id)`. FK `scenario_id → scenarios(id) ON DELETE RESTRICT`.
Unique `uq_scenario_versions_scenario_version (scenario_id, version)`.
Index `ix_scenario_versions_scenario (scenario_id)`.
`CHECK (difficulty BETWEEN 1 AND 5)`.

**JSONB:** `content` holds the entire validated ScenarioVersion document (SPEC §4 keys). It is
versioned configuration, not relational identity, so SPEC §30's "JSONB is allowed for
versioned/configurable payload portions" applies exactly. `role_chain`, `difficulty`,
`deterministic_seed` and the `scoring_rules` projection are additionally promoted to columns/tables
because sessions and reports reference them relationally.

**Immutability trigger (D4, §42 test 6):**
```sql
CREATE FUNCTION trg_scenario_versions_locked() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.locked_at IS NOT NULL
     AND (NEW.content IS DISTINCT FROM OLD.content
          OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256) THEN
    RAISE EXCEPTION 'scenario_versions % is locked since %', OLD.id, OLD.locked_at
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER scenario_versions_locked_guard
  BEFORE UPDATE ON scenario_versions
  FOR EACH ROW EXECUTE FUNCTION trg_scenario_versions_locked();
```
`locked_at` is set in the same transaction that creates the first session referencing the version.

### `scoring_rules`
Reference data projected from `scenario_versions.content.scoring_rules` at import time, so
`score_results` can carry a real FK.

| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `scenario_version_id` | `uuid` | no | |
| `rule_id` | `text` | no | |
| `name_ru` | `text` | no | |
| `description_ru` | `text` | no | `''` |
| `category` | `text` | no | |
| `max_points` | `numeric(8,2)` | no | |
| `critical` | `boolean` | no | `false` |
| `evaluator_type` | `text` | no | |
| `config` | `jsonb` | no | `'{}'::jsonb` |
| `min_evidence` | `smallint` | no | `1` |
| `order_index` | `integer` | no | |
| `applies_to_roles` | `jsonb` | no | `'[]'::jsonb` |
| `applies_to_variants` *(additive, I3 E1)* | `jsonb` | no | `'{}'::jsonb` |

PK `(scenario_version_id, rule_id)`. FK `scenario_version_id → scenario_versions(id) ON DELETE CASCADE`.
`CHECK (max_points > 0)`, `CHECK (min_evidence >= 1)`,
`CHECK (category IN ('INFORMATION_GATHERING','CARD_QUALITY','SERVICE_ROUTING','TIMELINESS','WORKFLOW','RESOURCE_MANAGEMENT','COMMUNICATION'))`,
`CHECK (evaluator_type IN ('FACT_OBTAINED','CARD_FIELD_CORRECT','CARD_FIELD_PRESENT','CARD_CONTRADICTION','SERVICE_SELECTION','DEADLINE','WORKFLOW_ACTION','RESOURCE_SELECTION','REQUIRED_STATUS_UPDATE','HANDOFF_COMPLETENESS'))`.

**JSONB:** `config` is per-evaluator and has ten different shapes; it is validated by the evaluator's
Pydantic model, never queried relationally. `applies_to_roles` is a `RoleType[]` array (migration
`0005_scoring_rule_applies_to_roles`, epic E15-B): `[]` (the default) means the rule always
applies; a non-empty list scores only sessions whose role chain — as recorded in the event log,
not this column — includes at least one listed role (`10-domain-model.md` §10.14 "Applicability",
R7). `applies_to_variants` (migration `0009_session_variants`, I3 E1, HLD 70 §70.2.5) is a
`{switch: [value, …]}` object with the same semantics per variant switch: `{}` (the default) always
applies; the session's values come from `SESSION_CREATED.variants`, never from this column.

## 20.3 Session aggregate

### `simulation_sessions`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `scenario_version_id` | `uuid` | no | |
| `session_mode` | `text` | no | |
| `state` | `text` | no | `'CREATED'` |
| `session_seed` | `text` | no | |
| `time_scale` *(additive, E5)* | `numeric(4,2)` | no | `1` |
| `created_by_user_id` | `uuid` | no | |
| `next_seq_no` | `bigint` | no | `1` |
| `started_at` | `timestamptz` | yes | |
| `paused_total_ms` | `integer` | no | `0` |
| `role_transition_started_offset_ms` *(additive, E17)* | `integer` | yes | |
| `completed_at` | `timestamptz` | yes | |
| `abort_reason` | `text` | yes | |
| `created_at` | `timestamptz` | no | `now()` |
| `report_released_at` *(additive, E16)* | `timestamptz` | yes | |
| `report_released_by_user_id` *(additive, E16)* | `uuid` | yes | |
| `variants` *(additive, I3 E1)* | `jsonb` | no | `'{}'::jsonb` |
| `lesson_id` *(additive, I3 E4a)* | `uuid` | yes | |
| `lesson_position` *(additive, I3 E4a)* | `integer` | yes | |

PK `(id)`. FK `scenario_version_id → scenario_versions(id) ON DELETE RESTRICT`;
FK `lesson_id → lessons(id) ON DELETE RESTRICT` *(additive, I3 E4a)*;
FK `created_by_user_id → users(id) ON DELETE RESTRICT`;
FK `report_released_by_user_id → users(id) ON DELETE RESTRICT` *(additive, E16)*.
Index `ix_sessions_state (state)`, `ix_sessions_scenario_version (scenario_version_id)`.
`CHECK (session_mode IN ('SINGLE_ROLE','FULL_CYCLE_SINGLE_TRAINEE','MULTI_TRAINEE','ASSESSMENT'))`,
`CHECK (state IN ('CREATED','READY','ACTIVE','ROLE_TRANSITION','COMPLETED','ABORTED'))`,
`CHECK (time_scale >= 0.1 AND time_scale <= 10)` *(additive, E5)*,
`CHECK ((report_released_at IS NULL) = (report_released_by_user_id IS NULL))` *(additive, E16)*,
`CHECK (role_transition_started_offset_ms IS NULL OR role_transition_started_offset_ms >= 0)`
*(additive, E17)*,
`CHECK ((lesson_id IS NULL) = (lesson_position IS NULL))` *(additive, I3 E4a)*;
unique `uq_sessions_lesson_position (lesson_id, lesson_position)` *(additive, I3 E4a)*.

`lesson_id` / `lesson_position` are additive in I3 E4a (migration `0011_lessons`, HLD 70 §70.3.2):
the lesson a session is a card of and its plan position, both or neither — a single session has
neither. Written once at creation (`SESSION_CREATED.{lesson_id, lesson_position}` records the same)
and never updated.

The two release columns (migration `0006_report_release_explain`, epic E16) hold **whether an
instructor has released this session's report to its trainees**. They are deliberately not the
same thing as `SessionPolicy.report_visible_to_trainee_before_release`
(`10-domain-model.md` §10.10, D6), which is a static per-*mode* constant saying whether a release
is needed at all: `MULTI_TRAINEE` and `ASSESSMENT` gate the report on one,
`SINGLE_ROLE` and `FULL_CYCLE_SINGLE_TRAINEE` do not. `releaseReportToTrainee` is idempotent —
the conditional `UPDATE … WHERE report_released_at IS NULL` is what makes a second call return the
first release unchanged — and emits **no event** (`openapi.yaml` `x-emits: []`): who looked at a
report afterwards is not part of what happened in the simulation, and appending to a `COMPLETED`
session's log would change the very input `rescoreSession` replays (SPEC §28, D5).

`time_scale` is additive in E5: `openapi.yaml`'s `SessionCreateRequest` and `SessionDetail` both
make it part of a session and `SimulationSession` carries it, so `simulation_sessions` is its home.
It is `numeric`, not a float, because the API schema's `minimum: 0.1` / `maximum: 10` are decimal
steps that must round-trip exactly (migration `0002_session_time_scale`).

`variants` is additive in I3 E1 (migration `0009_session_variants`, HLD 70 §70.2.2): the resolved
`SessionVariants` (`{card_source, dds_mode, dds_card_check, dds_brigade_call}`), a materialised copy
of `SESSION_CREATED.variants` like `time_scale`, written once at creation and never updated. No
backfill: `'{}'` — every row created before E1 — reads as the schema-1 derivation of the session's own
stage chain, which is how that session ran.

`started_at` + `paused_total_ms` is what sim time is recomputed from after a restart (D7, §42 test 13).

`paused_total_ms` has exactly **one writer** (E17 ruling R1): `finish_role_transition`, which adds
the wall-clock length of the `ROLE_TRANSITION` interval it closes. Simulated time does not run
during a role transition (`10-domain-model.md`, session state machine), and
`role_transition_started_offset_ms` (migration `0007_role_transition_offset`) is the offset the
*currently open* transition began at — `NULL` outside one. It is the fact the freeze needs, held
on the row so that a sim-time read costs no log scan; the same number is in the log, on
`ROLE_TRANSITION_STARTED`, and the wall instant it stands for is
`started_at + paused_total_ms + role_transition_started_offset_ms`. There is no pause table and no
`pauseSession` operation: the intervals are derivable from `ROLE_TRANSITION_STARTED` /
`ROLE_TRANSITION_COMPLETED`.

### `session_participants`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | no | |
| `user_id` | `uuid` | no | |
| `assigned_role_type` | `text` | yes | |
| `joined_at` | `timestamptz` | no | `now()` |

PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`;
FK `user_id → users(id) ON DELETE RESTRICT`.
Unique `uq_participants_session_user (session_id, user_id)`.
`CHECK (assigned_role_type IS NULL OR assigned_role_type IN ('OPERATOR_112','DDS','EDDS'))`.

### `role_stages`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | no | |
| `incident_id` | `uuid` | no | |
| `role_type` | `text` | no | |
| `order_index` | `integer` | no | |
| `state` | `text` | no | |
| `participant_user_id` | `uuid` | yes | |
| `started_at_offset_ms` | `integer` | yes | |
| `completed_at_offset_ms` | `integer` | yes | |

PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`;
FK `incident_id → incidents(id) ON DELETE CASCADE`;
FK `participant_user_id → users(id) ON DELETE RESTRICT`.
Unique `uq_role_stages_session_order (session_id, order_index)`.
Index `ix_role_stages_session_state (session_id, state)`.
`CHECK (role_type IN ('OPERATOR_112','DDS','EDDS'))`. `state` carries either an
`Operator112StageState` or a `DDSStageState` member; the CHECK lists the union of both enums.

Materialized from `ROLE_STAGE_STARTED` / `STAGE_STATE_CHANGED` / `ROLE_STAGE_COMPLETED`.

### `incidents`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | no | |
| `scenario_version_id` | `uuid` | no | |
| `created_at_offset_ms` | `integer` | no | `0` |
| `closed_at_offset_ms` | `integer` | yes | |
| `closure_reason` | `text` | yes | |
| `card_status` *(additive, I3 E4a)* | `text` | no | `'REGISTERED'` |
| `display_number` *(additive, I3 E4a)* | `bigint` | no | `nextval('incident_display_number_seq')` |

PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`;
FK `scenario_version_id → scenario_versions(id) ON DELETE RESTRICT`.
Unique `uq_incidents_session (session_id)` — one session, one incident (SPEC §13, §42 test 5): the
uniqueness constraint is what makes "role changes do not create a new incident" structural.
Unique `uq_incidents_display_number (display_number)` *(additive, I3 E4a)*.
`CHECK (closure_reason IS NULL OR closure_reason IN ('RESOLVED','FALSE_CALL','TRANSFERRED','CANCELLED_BY_CALLER'))`,
`CHECK (card_status IN ('REGISTERED','WORKED','CHECKED','NOT_NOTIFIED','REFUSED','NOT_COMPLETED','COMPLETED'))`
*(additive, I3 E4a)*.

`card_status` and `display_number` are additive in I3 E4a (migration `0011_lessons`, HLD 70 §70.3.6,
§70.4.6). `card_status` is a **read model**: the derived card status, materialised by the event
store in the same Unit of Work as the `DDS_CARD_STATUS_CHANGED` it records (the flush-before-append
rule, HLD 70 §70.3.5); `CHECKED` alone is written by the report release, with no event (§20.3's
release rule). `score()` never reads it (D5). The migration backfills it for every existing incident
by the §70.4.6 function with the §70.4.4 picker mirror, over existing columns only. `display_number`
comes from the sequence `incident_display_number_seq` — the «Происшествие NNNNNNNN» number of the
lists; every existing incident gets one when the column is added.

### `lessons` (additive, I3 E4a)
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | |
| `title_ru` | `text` | no | |
| `created_by_user_id` | `uuid` | no | |
| `session_mode` | `text` | no | |
| `variants` | `jsonb` | no | `'{}'::jsonb` |
| `participants` | `jsonb` | no | |
| `scenario_plan` | `jsonb` | no | |
| `state` | `text` | no | `'CREATED'` |
| `created_at` | `timestamptz` | no | `now()` |
| `started_at` | `timestamptz` | yes | |
| `completed_at` | `timestamptz` | yes | |
| `report_released_at` | `timestamptz` | yes | |
| `report_released_by_user_id` | `uuid` | yes | |

PK `(id)`. FK `created_by_user_id → users(id) ON DELETE RESTRICT`;
FK `report_released_by_user_id → users(id) ON DELETE RESTRICT`.
Index `ix_lessons_state (state)`.
`CHECK (session_mode IN ('SINGLE_ROLE','FULL_CYCLE_SINGLE_TRAINEE','MULTI_TRAINEE','ASSESSMENT'))`,
`CHECK (state IN ('CREATED','ACTIVE','COMPLETED','ABORTED'))`.

A lesson (занятие, D15) owns N ordinary sessions (`simulation_sessions.lesson_id`), all created at
lesson creation and started by the `LessonRunner` per `scenario_plan` arrivals. It is scheduling,
not simulation: no event log of its own — everything that happens in a card is in that card's
session log. `participants`, `scenario_plan` (the `PlanEntry` list) and `variants` (the lesson-wide
`VariantsRequest`) are jsonb documents written whole at creation; only `state` and the timestamps
change afterwards. `completed_at` is when the lesson reached `COMPLETED` or `ABORTED`.

### `world_engine_states` (additive, E6)
The world event engine (D7) carries state that is neither a fact about the world nor a fact about
the caller: how often each world event has already fired, when it last fired, which future firings
a `TriggerEvent` has queued, how often each `EmotionRule` has been applied, which stage states have
ever been reached, and how far simulated time has been advanced. D3 forbids merging that into
`incident_world_states` — that table holds **facts** only — so the bookkeeping is a 1:1 satellite of
`incidents` with its own table.

| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `incident_id` | `uuid` | no | |
| `last_tick_ms` | `integer` | no | `0` |
| `last_folded_seq_no` | `bigint` | no | `0` |
| `bookkeeping` | `jsonb` | no | `'{}'::jsonb` |
| `updated_at` | `timestamptz` | no | `now()` |

PK `(incident_id)`. FK `incident_id → incidents(id) ON DELETE CASCADE`.

**JSONB:** `bookkeeping` is `{occurrences, last_fired_ms, scheduled, emotion_applications,
reached_states}`. Its keys are scenario-defined (`world_event_id`s and emotion rule ids), so there is
no fixed column set to model — the same reason §20.4 gives for its own jsonb columns.

`EventIndex` is deliberately **absent**: it is a pure fold of the session's own action events
(`10-domain-model.md` §10.11 determinism rule 1) and is re-derived from `session_events` on every
load, so the event log stays the single source of what happened (D5). `last_folded_seq_no` is the
boundary between "already folded into the index" and "a `PendingAction` for the next tick", which is
also what makes a backend restart bit-identical to an uninterrupted run (SPEC §39).

Written only by session creation (the zeroed row) and by the `tick_session` use case. A tick that
fires nothing, folds nothing and moves no resource writes **no** row at all — every draw is indexed
by absolute simulated time, so re-examining a check tick re-draws the same number.

## 20.4 The four information layers (D3)

### `incident_world_states` (additive, D3)
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `incident_id` | `uuid` | no | |
| `revision` | `integer` | no | `0` |
| `facts` | `jsonb` | no | `'{}'::jsonb` |
| `value_types` | `jsonb` | no | `'{}'::jsonb` |
| `updated_at` | `timestamptz` | no | `now()` |

PK `(incident_id)`. FK `incident_id → incidents(id) ON DELETE CASCADE`.

**JSONB:** the fact set is scenario-defined and differs per scenario; there is no fixed column set to
model. Relational identity stays explicit through `incident_id`.
Written only by scenario instantiation and the WorldEvent engine. No role read model except the
instructor/report context reaches this table (D3, D11).

### `incident_caller_beliefs` (additive, D3)
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `incident_id` | `uuid` | no | |
| `revision` | `integer` | no | `0` |
| `facts` | `jsonb` | no | `'{}'::jsonb` |
| `knowledge` | `jsonb` | no | `'{}'::jsonb` |
| `certainty` | `jsonb` | no | `'{}'::jsonb` |
| `emotion` | `jsonb` | no | |
| `revealed_fact_ids` | `text[]` | no | `'{}'` |
| `updated_at` | `timestamptz` | no | `now()` |

PK `(incident_id)`. FK `incident_id → incidents(id) ON DELETE CASCADE`.
**JSONB:** same reason as above; `emotion` is `{"emotion": …, "stress_level": …}`.
`revealed_fact_ids` is a real array because `FACT_OBTAINED` and the gate both filter on membership.

### `incident_cards`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `incident_id` | `uuid` | no | |
| `values` | `jsonb` | no | `'{}'::jsonb` |
| `revision_counter` | `integer` | no | `0` |
| `updated_at` | `timestamptz` | no | `now()` |

PK `(id)`. FK `incident_id → incidents(id) ON DELETE CASCADE`.
Unique `uq_incident_cards_incident (incident_id)`.

**JSONB:** `values` is keyed by the dotted `field_path`s of `CARD_FIELDS` (`10-domain-model.md` §10.6)
— since I3 E3a, of the session's card schema (`v1` = `CARD_FIELDS`, or `v2` for a scenario on pack
`v046_24-r1`, HLD 70 §70.5.4). No column records the schema: it is the scenario version's
`reference_pack_id`, recorded in `SESSION_CREATED.reference_pack` (no migration).
Keeping it JSONB rather than 38 columns means a card-field addition is a code change, not a migration,
while `incident_card_revisions` keeps `field_path` relational and queryable. This is a materialized
view of `incident_card_revisions`; the revisions are the audit record (SPEC §9: "The final card is
NOT enough").

### `incident_card_revisions`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `card_id` | `uuid` | no | |
| `revision_no` | `integer` | no | |
| `field_path` | `text` | no | |
| `previous_value` | `jsonb` | yes | |
| `new_value` | `jsonb` | yes | |
| `value_type` | `text` | no | |
| `actor_type` | `text` | no | |
| `actor_user_id` | `uuid` | yes | |
| `at_offset_ms` | `integer` | no | |
| `session_event_id` | `uuid` | yes | |
| `created_at` | `timestamptz` | no | `now()` |

PK `(id)`. FK `card_id → incident_cards(id) ON DELETE CASCADE`;
FK `actor_user_id → users(id) ON DELETE RESTRICT`;
FK `session_event_id → session_events(id) ON DELETE RESTRICT`.
Unique `uq_card_revisions_card_no (card_id, revision_no)`.
Index `ix_card_revisions_card_path (card_id, field_path, revision_no)`.
`CHECK (actor_type IN ('TRAINEE','INSTRUCTOR'))` — SPEC §9/§42 test 4: neither `MODEL` nor
`SIMULATION` can write a card revision, and the database is where that is enforced.

**JSONB:** `previous_value` / `new_value` are heterogeneous scalars (string, integer, boolean, array
of service names), so one typed column is impossible without a type-tagged tuple.

**Append-only trigger:** see §20.9; `incident_card_revisions` rejects UPDATE and DELETE.

### `handoff_snapshots`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `incident_id` | `uuid` | no | |
| `card_id` | `uuid` | no | |
| `card_revision_id` | `uuid` | yes | |
| `card_values` | `jsonb` | no | |
| `recipient_services` | `text[]` | no | |
| `content_sha256` | `text` | no | |
| `created_by_user_id` | `uuid` | no | |
| `created_at_offset_ms` | `integer` | no | |
| `created_at` | `timestamptz` | no | `now()` |

PK `(id)`. FK `incident_id → incidents(id) ON DELETE CASCADE`;
FK `card_id → incident_cards(id) ON DELETE RESTRICT`;
FK `card_revision_id → incident_card_revisions(id) ON DELETE RESTRICT`;
FK `created_by_user_id → users(id) ON DELETE RESTRICT`.
Index `ix_handoff_snapshots_incident (incident_id, created_at_offset_ms)`.

**JSONB:** `card_values` is a by-value deep copy of the card at handoff time. It is intentionally a
copy and not a join: the snapshot must keep "72" even if the card is later corrected to "27"
(SPEC §3, §10).
`card_revision_id` is nullable because a handoff of a completely untouched card is legal — the
omission must be able to propagate (SPEC §10).

**Immutability trigger:** see §20.9; UPDATE and DELETE are rejected (D3, D5).

## 20.5 DDS and resources

### `dds_assignments`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `incident_id` | `uuid` | no | |
| `role_stage_id` | `uuid` | no | |
| `snapshot_id` | `uuid` | no | |
| `service_type` | `text` | no | |
| `state` | `text` | no | `'RECEIVED'` |
| `received_at_offset_ms` | `integer` | no | |
| `acknowledged_at_offset_ms` | `integer` | yes | |
| `dispatched_at_offset_ms` | `integer` | yes | |
| `closed_at_offset_ms` | `integer` | yes | |
| `closure_reason` | `text` | yes | |

PK `(id)`. FK `incident_id → incidents(id) ON DELETE CASCADE`;
FK `role_stage_id → role_stages(id) ON DELETE CASCADE`;
FK `snapshot_id → handoff_snapshots(id) ON DELETE RESTRICT`.
Unique `uq_dds_assignments_stage_service (role_stage_id, service_type)`.
Index `ix_dds_assignments_incident (incident_id)`.
`CHECK (service_type <> '')` *(changed, I3 E2a — was `service_type IN ('FIRE_RESCUE','POLICE','AMBULANCE','GAS_SERVICE','UTILITY_EMERGENCY','EDDS')`)*,
`CHECK (state IN ('RECEIVED','ACKNOWLEDGED','RESOURCE_SELECTION','DISPATCHED','EN_ROUTE','ARRIVED','WORKING','RESOLVED','CLOSED'))`.

`service_type` is a service-catalog id (`ServiceId`, HLD 70 §70.6.3, D18). Migration
`0010_service_id_open` (I3 E2a) drops the six-member CHECK and adds `CHECK (service_type <> '')` under
the same name `ck_dds_assignments_service_type`; no data moves, because the six legacy ids are the
catalog's first six entries. Its downgrade restores the six-member CHECK (and fails if a leg for any
other catalog service was stored since). The catalog itself is not a table: it is the sha-pinned
reference pack `reference/` (HLD 70 §70.6.1), loaded by the composition root.

There is no FK from `dds_assignments` to `incident_cards`: the DDS side reaches the trainee's data
only through `snapshot_id` (SPEC §10, §42 test 3). Materialized from the event log.

### `emergency_resources`
Per-session instances created from `scenario_versions.content.available_resources` when the incident
is instantiated, so that resource state is session-scoped and two concurrent sessions never collide.

| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | no | |
| `scenario_resource_id` | `text` | no | |
| `service_type` | `text` | no | |
| `resource_type` | `text` | no | |
| `callsign` | `text` | no | |
| `name_ru` | `text` | no | |
| `capabilities` | `text[]` | no | `'{}'` |
| `current_status` | `text` | no | `'AVAILABLE'` |
| `home_station_ru` | `text` | no | `''` |
| `crew_size` | `smallint` | no | `1` |
| `availability` | `jsonb` | no | |
| `eta` | `jsonb` | no | |
| `status_changed_at_offset_ms` | `integer` | no | `0` |
| `assignment_id` | `uuid` | yes | |

PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`;
FK `assignment_id → dds_assignments(id) ON DELETE SET NULL`.
Unique `uq_resources_session_scenario_id (session_id, scenario_resource_id)`,
unique `uq_resources_session_callsign (session_id, callsign)`.
Index `ix_resources_session_service_status (session_id, service_type, current_status)`,
GIN index `ix_resources_capabilities (capabilities)` for capability queries.
`CHECK (current_status IN ('AVAILABLE','SELECTED','DISPATCHED','EN_ROUTE','ON_SCENE','WORKING','RETURNING','OUT_OF_SERVICE','UNAVAILABLE'))`.

**JSONB:** `availability` (`{available_from_ms, available_until_ms, initial_status}`) and `eta`
(`{turnout_delay_seconds, travel_time_seconds, setup_seconds, on_scene_work_seconds,
return_time_seconds}`) are scenario-configured payload blocks read as a whole by the engine.

### `resource_state_changes`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `resource_id` | `uuid` | no | |
| `assignment_id` | `uuid` | yes | |
| `previous_status` | `text` | yes | |
| `new_status` | `text` | no | |
| `trigger` | `text` | no | |
| `source_world_event_id` | `text` | yes | |
| `at_offset_ms` | `integer` | no | |
| `session_event_id` | `uuid` | yes | |

PK `(id)`. FK `resource_id → emergency_resources(id) ON DELETE CASCADE`;
FK `assignment_id → dds_assignments(id) ON DELETE SET NULL`;
FK `session_event_id → session_events(id) ON DELETE RESTRICT`.
Index `ix_resource_state_changes_resource (resource_id, at_offset_ms)`.
Append-only audit; feeds the report's resource timeline (SPEC §29).

### `notifications` (additive, D5)
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `incident_id` | `uuid` | no | |
| `audience_role` | `text` | no | |
| `severity` | `text` | no | `'INFO'` |
| `title_ru` | `text` | no | |
| `body_ru` | `text` | no | `''` |
| `source_world_event_id` | `text` | yes | |
| `created_at_offset_ms` | `integer` | no | |
| `acknowledged_at_offset_ms` | `integer` | yes | |
| `acknowledged_by_user_id` | `uuid` | yes | |

PK `(id)`. FK `incident_id → incidents(id) ON DELETE CASCADE`;
FK `acknowledged_by_user_id → users(id) ON DELETE RESTRICT`.
Index `ix_notifications_incident_role (incident_id, audience_role, created_at_offset_ms)`.
`CHECK (audience_role IN ('OPERATOR_112','DDS','EDDS'))`,
`CHECK (severity IN ('INFO','WARNING','CRITICAL'))`.
Materialized from `NOTIFICATION_CREATED` / `NOTIFICATION_ACKNOWLEDGED`.

## 20.6 Event log, transcript and audio

### `session_events` — the audit source
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | no | |
| `seq_no` | `bigint` | no | |
| `event_type` | `text` | no | |
| `timestamp_utc` | `timestamptz` | no | `now()` |
| `monotonic_offset_ms` | `integer` | no | |
| `actor_type` | `text` | no | |
| `actor_id` | `uuid` | yes | |
| `correlation_id` | `uuid` | yes | |
| `payload` | `jsonb` | no | `'{}'::jsonb` |

Columns are exactly SPEC §8. PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`;
FK `actor_id → users(id) ON DELETE RESTRICT`.
Unique `uq_session_events_session_seq (session_id, seq_no)` (D5).
Index `ix_session_events_session_seq (session_id, seq_no)` (the replay/resume read path),
`ix_session_events_session_type (session_id, event_type)` (the scoring read path),
`ix_session_events_correlation (correlation_id) WHERE correlation_id IS NOT NULL`.
`CHECK (actor_type IN ('TRAINEE','INSTRUCTOR','SIMULATION','MODEL','SYSTEM'))`;
`CHECK (event_type IN (…))` listing all 49 `EventType` members of `10-domain-model.md` §10.2.

**JSONB:** `payload` has 49 different shapes (the catalog in `10-domain-model.md` §10.13). It is the
one place a document column is unavoidable, and SPEC §30 permits it because identity
(`session_id`, `seq_no`, `event_type`, `actor_id`) stays relational.

**Immutability trigger:** see §20.9; UPDATE and DELETE are rejected (SPEC §8, D5).

### `transcript_segments`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | no | |
| `audio_segment_id` | `uuid` | yes | |
| `speaker` | `text` | no | |
| `start_ms` | `integer` | no | |
| `end_ms` | `integer` | no | |
| `text` | `text` | no | |
| `is_final` | `boolean` | no | `true` |
| `confidence` | `real` | yes | |
| `asr_provider` | `text` | yes | |
| `asr_model` | `text` | yes | |
| `turn_index` | `integer` | yes | |

Columns are exactly SPEC §19. PK `(id)`.
FK `session_id → simulation_sessions(id) ON DELETE CASCADE`;
FK `audio_segment_id → audio_segments(id) ON DELETE SET NULL`.
Index `ix_transcript_segments_session_start (session_id, start_ms)`.
`CHECK (speaker IN ('TRAINEE','CALLER'))`, `CHECK (end_ms >= start_ms)`.
Materialized from `ASR_FINAL` and `CALLER_TTS_STARTED`/`CALLER_TTS_ENDED`.

### `audio_segments`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | no | |
| `speaker` | `text` | no | |
| `file_path` | `text` | yes | |
| `format` | `text` | no | `'wav'` |
| `start_ms` | `integer` | no | |
| `end_ms` | `integer` | no | |
| `sample_rate` | `integer` | no | `16000` |
| `num_channels` | `integer` | no | `1` |
| `byte_offset` | `bigint` | no | |
| `byte_length` | `bigint` | no | |
| `purged_at` | `timestamptz` | yes | |
| `created_at` | `timestamptz` | no | `now()` |

PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`.
Index `ix_audio_segments_session_start (session_id, start_ms)`.
`CHECK (speaker IN ('TRAINEE','CALLER'))`, `CHECK (end_ms >= start_ms)`.
`file_path` is nullable so the retention purge can null it and keep the row as an audit record (D9).
`byte_offset` / `byte_length` locate the segment inside the file named by `file_path`; there is no
separate duration column — duration is derived as `end_ms - start_ms`.

### `dialogue_turns` (additive)
One row per trainee→caller turn. It is a materialized read model of the turn pipeline's events
(`USER_SPEECH_STARTED` … `CALLER_TTS_ENDED` / `CALLER_UTTERANCE_INTERRUPTED`), written by the
voice-agent process in the same Unit of Work as those appends. Scoring never reads it (D5); the
report and the latency dashboards do.

| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | no | |
| `role_stage_id` | `uuid` | no | |
| `turn_index` | `integer` | no | |
| `user_speech_started_offset_ms` | `integer` | no | |
| `user_speech_ended_offset_ms` | `integer` | yes | |
| `operator_transcript_segment_id` | `uuid` | yes | |
| `caller_transcript_segment_id` | `uuid` | yes | |
| `interpretation` | `jsonb` | no | `'{}'::jsonb` |
| `gate_output` | `jsonb` | no | `'{}'::jsonb` |
| `planned_text` | `text` | yes | |
| `delivered_text` | `text` | yes | |
| `interrupted` | `boolean` | no | `false` |
| `fallback_used` | `boolean` | no | `false` |
| `speech_end_to_first_audio_ms` | `integer` | yes | |
| `correlation_id` | `uuid` | yes | |
| `created_at` | `timestamptz` | no | `now()` |

PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`;
FK `role_stage_id → role_stages(id) ON DELETE CASCADE`;
FK `operator_transcript_segment_id → transcript_segments(id) ON DELETE SET NULL`;
FK `caller_transcript_segment_id → transcript_segments(id) ON DELETE SET NULL`.
Unique `uq_dialogue_turns_session_index (session_id, turn_index)`.
Index `ix_dialogue_turns_session (session_id, turn_index)`,
`ix_dialogue_turns_correlation (correlation_id) WHERE correlation_id IS NOT NULL`.

`operator_transcript_segment_id` is nullable only for a turn whose ASR never finalized (a failure
path, SPEC §39); `caller_transcript_segment_id` is nullable whenever the caller never spoke back.

**JSONB:** `interpretation` is the SPEC §20 structured output
(`speech_act`, `requested_facts[{fact_id, explicit}]`, `operator_assertions`, `confirmation_targets`,
`semantic_confidence`); `gate_output` is the `AllowedFactsPackage` decision record
(`allowed_fact_ids`, `unavailable`, `withheld_count`, `metadata`). Both are variable-shape model/gate
payloads, never queried relationally.

`speech_end_to_first_audio_ms` is the SPEC §27 critical product metric, stored on the turn and null
when no caller audio was produced (`60-inference-ops.md`).

### `recording_purge_audit` (additive)
Retention audit for SPEC §41 / D9. One row per purged audio segment. The purge nulls
`audio_segments.file_path`; this table is the record of what was deleted, because a completed
session's event log is closed.

| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `purged_at` | `timestamptz` | no | `now()` |
| `actor_type` | `text` | no | `'SYSTEM'` |
| `actor_user_id` | `uuid` | yes | |
| `session_id` | `uuid` | no | |
| `audio_segment_id` | `uuid` | no | |
| `file_path_was` | `text` | no | |
| `bytes` | `bigint` | no | |
| `retention_days` | `integer` | no | |
| `reason` | `text` | no | |

PK `(id)`. FK `actor_user_id → users(id) ON DELETE SET NULL`;
FK `session_id → simulation_sessions(id) ON DELETE CASCADE`;
FK `audio_segment_id → audio_segments(id) ON DELETE RESTRICT`.
Index `ix_recording_purge_audit_session (session_id, purged_at)`.
`actor_type` is `SYSTEM` for the scheduled/system purge and `INSTRUCTOR` when an administrator ran it
manually; `actor_user_id` is null exactly when `actor_type = 'SYSTEM'`.
`CHECK (actor_type IN ('TRAINEE','INSTRUCTOR','SIMULATION','MODEL','SYSTEM'))` (`10-domain-model.md`
`ActorType`), `CHECK (reason IN ('RETENTION_WINDOW','MANUAL_REQUEST','ADMIN_DELETE'))`.

### `inference_metrics`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | yes | |
| `request_id` | `text` | no | |
| `component` | `text` | no | |
| `provider` | `text` | no | |
| `model` | `text` | no | |
| `model_version` | `text` | yes | |
| `turn_index` | `integer` | yes | |
| `input_tokens` | `integer` | yes | |
| `input_duration_ms` | `integer` | yes | |
| `output_tokens` | `integer` | yes | |
| `output_audio_ms` | `integer` | yes | |
| `started_at` | `timestamptz` | no | |
| `first_output_at` | `timestamptz` | yes | |
| `finished_at` | `timestamptz` | yes | |
| `ttft_ms` | `integer` | yes | |
| `total_latency_ms` | `integer` | yes | |
| `tokens_per_second` | `real` | yes | |
| `realtime_factor` | `real` | yes | |
| `gpu_memory_mb` | `integer` | yes | |
| `fallback_count` | `smallint` | no | `0` |
| `retry_count` | `smallint` | no | `0` |
| `status` | `text` | no | `'OK'` |
| `error_kind` | `text` | yes | |

Columns are SPEC §27 plus `status` / `error_kind` (migration `0004_inference_metric_status`, E12): `50-voice-pipeline.md` §2.6 defines both on `InferenceMetric`, and without them a timed-out or failed call is indistinguishable from a successful one in telemetry (SPEC §42 invariant 14 would be unobservable there). `CHECK (status IN ('OK','TIMEOUT','ERROR','CANCELLED'))`. PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`.
Unique `uq_inference_metrics_request (request_id)`.
Index `ix_inference_metrics_session_component (session_id, component, started_at)`.
`CHECK (component IN ('ASR','LLM_INTERPRETER','LLM_GENERATOR','TTS','VAD'))`.
Telemetry, never read by scoring.

## 20.7 Scoring output

### `score_results`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | no | |
| `scenario_version_id` | `uuid` | no | |
| `rule_id` | `text` | no | |
| `evaluator_type` | `text` | no | |
| `category` | `text` | no | |
| `points_awarded` | `numeric(8,2)` | no | |
| `max_points` | `numeric(8,2)` | no | |
| `passed` | `boolean` | no | |
| `critical_failure` | `boolean` | no | `false` |
| `computed_at` | `timestamptz` | no | `now()` |

PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`;
FK `(scenario_version_id, rule_id) → scoring_rules(scenario_version_id, rule_id) ON DELETE RESTRICT`.
Unique `uq_score_results_session_rule (session_id, rule_id)` — re-scoring replaces the row and must
reproduce identical numbers (SPEC §28, §42 test 9).
Index `ix_score_results_session_category (session_id, category)`.
No `CHECK` constrains `max_points` here (checked at E15-B): a rule whose `applies_to_roles` (§20.2)
excludes this session's role chain scores `points_awarded = 0, max_points = 0` (R7), which a
`> 0` check would reject.

### `score_evidence`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `score_result_id` | `uuid` | no | |
| `session_event_id` | `uuid` | yes | |
| `card_revision_id` | `uuid` | yes | |
| `snapshot_id` | `uuid` | yes | |
| `seq_no` | `bigint` | yes | |
| `note_ru` | `text` | no | |

PK `(id)`. FK `score_result_id → score_results(id) ON DELETE CASCADE`;
FK `session_event_id → session_events(id) ON DELETE RESTRICT`;
FK `card_revision_id → incident_card_revisions(id) ON DELETE RESTRICT`;
FK `snapshot_id → handoff_snapshots(id) ON DELETE RESTRICT`.
Index `ix_score_evidence_result (score_result_id)`.
```sql
CONSTRAINT ck_score_evidence_exactly_one CHECK (
  (session_event_id IS NOT NULL)::int
+ (card_revision_id IS NOT NULL)::int
+ (snapshot_id     IS NOT NULL)::int = 1)
```
Every `score_results` row must have at least one `score_evidence` row. Because PostgreSQL has no
deferred "at least one child" constraint, the invariant is enforced in the domain
(`ScoringEvidenceError`, `10-domain-model.md` §10.14) and asserted by the §42 test 11 invariant test;
the repository writes result and evidence in one transaction (D5).

## 20.8 `seq_no` allocation protocol (D5)

Every event append runs inside the use case's single Unit of Work transaction:

```sql
BEGIN;

-- 1. take the row lock and allocate the next number(s)
SELECT next_seq_no
  FROM simulation_sessions
 WHERE id = :session_id
   FOR NO KEY UPDATE;

UPDATE simulation_sessions
   SET next_seq_no = next_seq_no + :event_count
 WHERE id = :session_id
RETURNING next_seq_no - :event_count AS first_seq_no;

-- 2. persist the materialized state changes of this use case
--    (incident_cards, role_stages, dds_assignments, emergency_resources, …)

-- 3. append the events with the reserved numbers
INSERT INTO session_events
  (session_id, seq_no, event_type, timestamp_utc, monotonic_offset_ms,
   actor_type, actor_id, correlation_id, payload)
VALUES
  (:session_id, :first_seq_no + 0, …),
  (:session_id, :first_seq_no + 1, …);

COMMIT;
-- after commit only: PUBLISH to Redis channel session:{id}:events
```

The row lock serialises concurrent appenders (backend and voice-agent process), so
`UNIQUE(session_id, seq_no)` can never be violated and the sequence has no gaps. Publishing happens
strictly after commit, so a subscriber can always re-read the event from PostgreSQL.

**Lock mode and lock order (E20, R14).** Step 1's mode is `FOR NO KEY UPDATE`, not `FOR UPDATE`.
Every table the voice agent writes beside its events — `audio_segments`, `transcript_segments`,
`dialogue_turns`, `inference_metrics` — has a foreign key to `simulation_sessions.id`, and
PostgreSQL takes a `FOR KEY SHARE` lock on the **referenced** row for each such insert. Step 2 of
this very transaction therefore runs before step 1 for an appender that writes those rows first, so
with `FOR UPDATE` — which conflicts with `FOR KEY SHARE` — step 1 became a lock *upgrade*, and two
concurrent appends of one call deadlocked on it (`DeadlockDetectedError` on exactly this statement;
it ended E19-E3's first real LiveKit run after two turns). `FOR NO KEY UPDATE` is the mode the
`UPDATE` on the next line takes anyway, still conflicts with itself — so allocation stays strictly
serialised — and is compatible with `FOR KEY SHARE`, so no cycle can form.

`SessionRepository.get_for_update` (§20.3) uses the same mode, so `simulation_sessions` has **one**
lock mode for every writer in both processes. The order, where a writer takes both, is: the
session-row lock first, then this allocation — which is what every command, the `SimulationRunner`
tick and its `after_tick` hooks already do. Regression test:
`backend/tests/integration/persistence/test_seq_lock_order.py`.

## 20.9 Immutability triggers

One shared rejection function, attached to the three append-only/immutable tables:

```sql
CREATE FUNCTION trg_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'table % is append-only (% rejected)', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'restrict_violation';
END $$;

CREATE TRIGGER session_events_append_only
  BEFORE UPDATE OR DELETE ON session_events
  FOR EACH ROW EXECUTE FUNCTION trg_reject_mutation();

CREATE TRIGGER handoff_snapshots_immutable
  BEFORE UPDATE OR DELETE ON handoff_snapshots
  FOR EACH ROW EXECUTE FUNCTION trg_reject_mutation();

CREATE TRIGGER incident_card_revisions_append_only
  BEFORE UPDATE OR DELETE ON incident_card_revisions
  FOR EACH ROW EXECUTE FUNCTION trg_reject_mutation();
```

`scenario_versions` has its own conditional trigger (§20.2) because ordinary metadata updates and the
`locked_at` write itself must stay legal while `content` freezes.

Cascade note: `ON DELETE CASCADE` from `simulation_sessions` reaches these tables at row level, and a
`BEFORE DELETE` row trigger would block it. Deleting a session is therefore an administrative
operation that runs `SET session_replication_role = replica` (or `ALTER TABLE … DISABLE TRIGGER`) in a
dedicated maintenance command; ordinary application code has no delete path to any of the three.


## 20.10 Post-session report (additive, E16)

### `report_explanations`
| Column | PG type | Null | Default |
|:--|:--|:--|:--|
| `id` | `uuid` | no | `gen_random_uuid()` |
| `session_id` | `uuid` | no | |
| `audience` | `text` | no | |
| `text_ru` | `text` | no | |
| `generated_at` | `timestamptz` | no | `now()` |
| `llm_provider` | `text` | no | |
| `llm_model` | `text` | no | |
| `score_report_checksum` | `text` | no | |

PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`.
`UNIQUE uq_report_explanations_session_id_audience (session_id, audience)`.
`CHECK (audience IN ('TRAINEE','INSTRUCTOR'))`.

The optional LLM explanation of an **already computed** `ScoreReport` (SPEC §2, §29; D11: "stored
separately, and cannot write to score tables"). The columns are exactly `openapi.yaml`'s
`ReportExplanation` plus the row id.

Three properties this schema is shaped to give:

- **No path to the numbers.** There is deliberately no foreign key to `score_results`: the
  explanation references the report it explains by *value* — `score_report_checksum`, the output
  of `app.domain.scoring.engine.report_checksum` for that report — so a client can verify that the
  numbers did not move while the prose was written. The "explanation cannot write score tables"
  invariant itself is structural, not a database grant: the use case is constructed with a
  read-only score reader and has no write method to reach (`backend/tests/invariants/`).
- **One explanation per audience.** `UNIQUE (session_id, audience)` is what makes a second
  `generateReportExplanation` without `regenerate: true` a `409 EXPLANATION_ALREADY_EXISTS`
  rather than a duplicate row, and what makes `regenerate: true` an
  `INSERT … ON CONFLICT DO UPDATE`.
- **Disposable.** The row is derived, cheap to regenerate, and carries nothing the simulation
  depends on; deleting a session takes it along (`CASCADE`).

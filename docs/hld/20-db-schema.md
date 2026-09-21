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

PK `(scenario_version_id, rule_id)`. FK `scenario_version_id → scenario_versions(id) ON DELETE CASCADE`.
`CHECK (max_points > 0)`, `CHECK (min_evidence >= 1)`,
`CHECK (category IN ('INFORMATION_GATHERING','CARD_QUALITY','SERVICE_ROUTING','TIMELINESS','WORKFLOW','RESOURCE_MANAGEMENT','COMMUNICATION'))`,
`CHECK (evaluator_type IN ('FACT_OBTAINED','CARD_FIELD_CORRECT','CARD_FIELD_PRESENT','CARD_CONTRADICTION','SERVICE_SELECTION','DEADLINE','WORKFLOW_ACTION','RESOURCE_SELECTION','REQUIRED_STATUS_UPDATE','HANDOFF_COMPLETENESS'))`.

**JSONB:** `config` is per-evaluator and has ten different shapes; it is validated by the evaluator's
Pydantic model, never queried relationally. `applies_to_roles` is a `RoleType[]` array (migration
`0005_scoring_rule_applies_to_roles`, epic E15-B): `[]` (the default) means the rule always
applies; a non-empty list scores only sessions whose role chain — as recorded in the event log,
not this column — includes at least one listed role (`10-domain-model.md` §10.14 "Applicability",
R7).

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
| `completed_at` | `timestamptz` | yes | |
| `abort_reason` | `text` | yes | |
| `created_at` | `timestamptz` | no | `now()` |

PK `(id)`. FK `scenario_version_id → scenario_versions(id) ON DELETE RESTRICT`;
FK `created_by_user_id → users(id) ON DELETE RESTRICT`.
Index `ix_sessions_state (state)`, `ix_sessions_scenario_version (scenario_version_id)`.
`CHECK (session_mode IN ('SINGLE_ROLE','FULL_CYCLE_SINGLE_TRAINEE','MULTI_TRAINEE','ASSESSMENT'))`,
`CHECK (state IN ('CREATED','READY','ACTIVE','ROLE_TRANSITION','COMPLETED','ABORTED'))`,
`CHECK (time_scale >= 0.1 AND time_scale <= 10)` *(additive, E5)*.

`time_scale` is additive in E5: `openapi.yaml`'s `SessionCreateRequest` and `SessionDetail` both
make it part of a session and `SimulationSession` carries it, so `simulation_sessions` is its home.
It is `numeric`, not a float, because the API schema's `minimum: 0.1` / `maximum: 10` are decimal
steps that must round-trip exactly (migration `0002_session_time_scale`).

`started_at` + `paused_total_ms` is what sim time is recomputed from after a restart (D7, §42 test 13).

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

PK `(id)`. FK `session_id → simulation_sessions(id) ON DELETE CASCADE`;
FK `scenario_version_id → scenario_versions(id) ON DELETE RESTRICT`.
Unique `uq_incidents_session (session_id)` — one session, one incident (SPEC §13, §42 test 5): the
uniqueness constraint is what makes "role changes do not create a new incident" structural.
`CHECK (closure_reason IS NULL OR closure_reason IN ('RESOLVED','FALSE_CALL','TRANSFERRED','CANCELLED_BY_CALLER'))`.

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

**JSONB:** `values` is keyed by the dotted `field_path`s of `CARD_FIELDS` (`10-domain-model.md` §10.6).
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
`CHECK (service_type IN ('FIRE_RESCUE','POLICE','AMBULANCE','GAS_SERVICE','UTILITY_EMERGENCY','EDDS'))`,
`CHECK (state IN ('RECEIVED','ACKNOWLEDGED','RESOURCE_SELECTION','DISPATCHED','EN_ROUTE','ARRIVED','WORKING','RESOLVED','CLOSED'))`.

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
   FOR UPDATE;

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

The `FOR UPDATE` row lock serialises concurrent appenders (backend and voice-agent process), so
`UNIQUE(session_id, seq_no)` can never be violated and the sequence has no gaps. Publishing happens
strictly after commit, so a subscriber can always re-read the event from PostgreSQL.

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

"""baseline: all 25 tables of 20-db-schema.md §20.1, plus the §20.9 immutability triggers

Hand-written from `docs/hld/20-db-schema.md`, which is the single owner of every table, column,
index, constraint and trigger. Table creation order follows the foreign-key dependency order;
`downgrade()` drops in the exact reverse order plus the trigger functions, so
`alembic downgrade base` leaves the database empty.

The enum member lists of the `TEXT + CHECK` columns are rendered from the domain enums
(`app.domain.enums`, `app.domain.events.types`) through `app.db.base.enum_check`, so this
migration and the ORM models are generated from one source (HLD §20 conventions). A later epic
that adds an enum member owes a new migration with the corresponding `ALTER TABLE ... DROP/ADD
CONSTRAINT`; this baseline is not re-run against an existing database.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import JSONB_T, TEXT_ARRAY_T, TIMESTAMPTZ_T, UUID_T, enum_check
from app.db.models.events import (
    INFERENCE_COMPONENTS,
    PURGE_REASONS,
    SPEAKERS,
)
from app.db.models.layers import CARD_REVISION_ACTOR_TYPES
from app.db.models.reference import USER_ROLES
from app.db.models.session import ROLE_STAGE_STATES
from app.domain.enums import (
    ActorType,
    ClosureReason,
    DDSStageState,
    EvaluatorType,
    NotificationSeverity,
    ResourceStatus,
    RoleType,
    ScoringCategory,
    ServiceType,
    SessionMode,
    SessionState,
)
from app.domain.events.types import EventType

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --------------------------------------------------------------------------------------------
# §20.9 — one shared rejection function attached to the three append-only/immutable tables, and
# `scenario_versions`' own conditional lock trigger (§20.2, D4).
# --------------------------------------------------------------------------------------------

REJECT_MUTATION_FUNCTION = """
CREATE FUNCTION trg_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'table % is append-only (% rejected)', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'restrict_violation';
END $$;
"""

SCENARIO_VERSIONS_LOCKED_FUNCTION = """
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
"""

APPEND_ONLY_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("session_events_append_only", "session_events"),
    ("handoff_snapshots_immutable", "handoff_snapshots"),
    ("incident_card_revisions_append_only", "incident_card_revisions"),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ---------------------------------------------------------------------------------------
    # §20.2 Reference data
    # ---------------------------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name_ru", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'TRAINEE'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint(enum_check("role", USER_ROLES), name="role"),
    )

    op.create_table(
        "scenarios",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title_ru", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_scenarios"),
        sa.UniqueConstraint("slug", name="uq_scenarios_slug"),
    )

    op.create_table(
        "scenario_versions",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scenario_id", UUID_T, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("difficulty", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("deterministic_seed", sa.Text(), nullable=False),
        sa.Column("role_chain", TEXT_ARRAY_T, nullable=False),
        sa.Column("content", JSONB_T, nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("locked_at", TIMESTAMPTZ_T, nullable=True),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_scenario_versions"),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
            ondelete="RESTRICT",
            name="fk_scenario_versions_scenario_id_scenarios",
        ),
        sa.UniqueConstraint("scenario_id", "version", name="uq_scenario_versions_scenario_version"),
        sa.CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty"),
    )
    op.create_index("ix_scenario_versions_scenario", "scenario_versions", ["scenario_id"])

    op.create_table(
        "scoring_rules",
        sa.Column("scenario_version_id", UUID_T, nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("name_ru", sa.Text(), nullable=False),
        sa.Column("description_ru", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("max_points", sa.Numeric(8, 2), nullable=False),
        sa.Column("critical", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("evaluator_type", sa.Text(), nullable=False),
        sa.Column("config", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("min_evidence", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("scenario_version_id", "rule_id", name="pk_scoring_rules"),
        sa.ForeignKeyConstraint(
            ["scenario_version_id"],
            ["scenario_versions.id"],
            ondelete="CASCADE",
            name="fk_scoring_rules_scenario_version_id_scenario_versions",
        ),
        sa.CheckConstraint("max_points > 0", name="max_points"),
        sa.CheckConstraint("min_evidence >= 1", name="min_evidence"),
        sa.CheckConstraint(enum_check("category", ScoringCategory), name="category"),
        sa.CheckConstraint(enum_check("evaluator_type", EvaluatorType), name="evaluator_type"),
    )

    # ---------------------------------------------------------------------------------------
    # §20.3 Session aggregate
    # ---------------------------------------------------------------------------------------
    op.create_table(
        "simulation_sessions",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scenario_version_id", UUID_T, nullable=False),
        sa.Column("session_mode", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'CREATED'")),
        sa.Column("session_seed", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", UUID_T, nullable=False),
        sa.Column("next_seq_no", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("started_at", TIMESTAMPTZ_T, nullable=True),
        sa.Column("paused_total_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completed_at", TIMESTAMPTZ_T, nullable=True),
        sa.Column("abort_reason", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_simulation_sessions"),
        sa.ForeignKeyConstraint(
            ["scenario_version_id"],
            ["scenario_versions.id"],
            ondelete="RESTRICT",
            name="fk_simulation_sessions_scenario_version_id_scenario_versions",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_simulation_sessions_created_by_user_id_users",
        ),
        sa.CheckConstraint(enum_check("session_mode", SessionMode), name="session_mode"),
        sa.CheckConstraint(enum_check("state", SessionState), name="state"),
    )
    op.create_index("ix_sessions_state", "simulation_sessions", ["state"])
    op.create_index("ix_sessions_scenario_version", "simulation_sessions", ["scenario_version_id"])

    op.create_table(
        "session_participants",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID_T, nullable=False),
        sa.Column("user_id", UUID_T, nullable=False),
        sa.Column("assigned_role_type", sa.Text(), nullable=True),
        sa.Column("joined_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_session_participants"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_session_participants_session_id_simulation_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_session_participants_user_id_users",
        ),
        sa.UniqueConstraint("session_id", "user_id", name="uq_participants_session_user"),
        sa.CheckConstraint(
            enum_check("assigned_role_type", RoleType, nullable=True),
            name="assigned_role_type",
        ),
    )

    op.create_table(
        "incidents",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID_T, nullable=False),
        sa.Column("scenario_version_id", UUID_T, nullable=False),
        sa.Column(
            "created_at_offset_ms", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("closed_at_offset_ms", sa.Integer(), nullable=True),
        sa.Column("closure_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_incidents"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_incidents_session_id_simulation_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_version_id"],
            ["scenario_versions.id"],
            ondelete="RESTRICT",
            name="fk_incidents_scenario_version_id_scenario_versions",
        ),
        sa.UniqueConstraint("session_id", name="uq_incidents_session"),
        sa.CheckConstraint(
            enum_check("closure_reason", ClosureReason, nullable=True),
            name="closure_reason",
        ),
    )

    op.create_table(
        "role_stages",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID_T, nullable=False),
        sa.Column("incident_id", UUID_T, nullable=False),
        sa.Column("role_type", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("participant_user_id", UUID_T, nullable=True),
        sa.Column("started_at_offset_ms", sa.Integer(), nullable=True),
        sa.Column("completed_at_offset_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_role_stages"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_role_stages_session_id_simulation_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
            name="fk_role_stages_incident_id_incidents",
        ),
        sa.ForeignKeyConstraint(
            ["participant_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_role_stages_participant_user_id_users",
        ),
        sa.UniqueConstraint("session_id", "order_index", name="uq_role_stages_session_order"),
        sa.CheckConstraint(enum_check("role_type", RoleType), name="role_type"),
        sa.CheckConstraint(enum_check("state", ROLE_STAGE_STATES), name="state"),
    )
    op.create_index("ix_role_stages_session_state", "role_stages", ["session_id", "state"])

    # ---------------------------------------------------------------------------------------
    # §20.6 `session_events` — created before the tables that reference it
    # ---------------------------------------------------------------------------------------
    op.create_table(
        "session_events",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID_T, nullable=False),
        sa.Column("seq_no", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("timestamp_utc", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.Column("monotonic_offset_ms", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", UUID_T, nullable=True),
        sa.Column("correlation_id", UUID_T, nullable=True),
        sa.Column("payload", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("id", name="pk_session_events"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_session_events_session_id_simulation_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], ondelete="RESTRICT", name="fk_session_events_actor_id_users"
        ),
        sa.UniqueConstraint("session_id", "seq_no", name="uq_session_events_session_seq"),
        sa.CheckConstraint(enum_check("actor_type", ActorType), name="actor_type"),
        sa.CheckConstraint(enum_check("event_type", EventType), name="event_type"),
    )
    op.create_index("ix_session_events_session_seq", "session_events", ["session_id", "seq_no"])
    op.create_index(
        "ix_session_events_session_type", "session_events", ["session_id", "event_type"]
    )
    op.create_index(
        "ix_session_events_correlation",
        "session_events",
        ["correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )

    # ---------------------------------------------------------------------------------------
    # §20.4 The four information layers
    # ---------------------------------------------------------------------------------------
    op.create_table(
        "incident_world_states",
        sa.Column("incident_id", UUID_T, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("facts", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("value_types", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("incident_id", name="pk_incident_world_states"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
            name="fk_incident_world_states_incident_id_incidents",
        ),
    )

    op.create_table(
        "incident_caller_beliefs",
        sa.Column("incident_id", UUID_T, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("facts", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("knowledge", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("certainty", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("emotion", JSONB_T, nullable=False),
        sa.Column(
            "revealed_fact_ids", TEXT_ARRAY_T, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("updated_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("incident_id", name="pk_incident_caller_beliefs"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
            name="fk_incident_caller_beliefs_incident_id_incidents",
        ),
    )

    op.create_table(
        "incident_cards",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", UUID_T, nullable=False),
        sa.Column("values", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("revision_counter", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_incident_cards"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
            name="fk_incident_cards_incident_id_incidents",
        ),
        sa.UniqueConstraint("incident_id", name="uq_incident_cards_incident"),
    )

    op.create_table(
        "incident_card_revisions",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("card_id", UUID_T, nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("field_path", sa.Text(), nullable=False),
        sa.Column("previous_value", JSONB_T, nullable=True),
        sa.Column("new_value", JSONB_T, nullable=True),
        sa.Column("value_type", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_user_id", UUID_T, nullable=True),
        sa.Column("at_offset_ms", sa.Integer(), nullable=False),
        sa.Column("session_event_id", UUID_T, nullable=True),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_incident_card_revisions"),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["incident_cards.id"],
            ondelete="CASCADE",
            name="fk_incident_card_revisions_card_id_incident_cards",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_incident_card_revisions_actor_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["session_event_id"],
            ["session_events.id"],
            ondelete="RESTRICT",
            name="fk_incident_card_revisions_session_event_id_session_events",
        ),
        sa.UniqueConstraint("card_id", "revision_no", name="uq_card_revisions_card_no"),
        sa.CheckConstraint(
            enum_check("actor_type", CARD_REVISION_ACTOR_TYPES),
            name="actor_type",
        ),
    )
    op.create_index(
        "ix_card_revisions_card_path",
        "incident_card_revisions",
        ["card_id", "field_path", "revision_no"],
    )

    op.create_table(
        "handoff_snapshots",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", UUID_T, nullable=False),
        sa.Column("card_id", UUID_T, nullable=False),
        sa.Column("card_revision_id", UUID_T, nullable=True),
        sa.Column("card_values", JSONB_T, nullable=False),
        sa.Column("recipient_services", TEXT_ARRAY_T, nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", UUID_T, nullable=False),
        sa.Column("created_at_offset_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_handoff_snapshots"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
            name="fk_handoff_snapshots_incident_id_incidents",
        ),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["incident_cards.id"],
            ondelete="RESTRICT",
            name="fk_handoff_snapshots_card_id_incident_cards",
        ),
        sa.ForeignKeyConstraint(
            ["card_revision_id"],
            ["incident_card_revisions.id"],
            ondelete="RESTRICT",
            name="fk_handoff_snapshots_card_revision_id_incident_card_revisions",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_handoff_snapshots_created_by_user_id_users",
        ),
    )
    op.create_index(
        "ix_handoff_snapshots_incident",
        "handoff_snapshots",
        ["incident_id", "created_at_offset_ms"],
    )

    # ---------------------------------------------------------------------------------------
    # §20.5 DDS, resources and notifications
    # ---------------------------------------------------------------------------------------
    op.create_table(
        "dds_assignments",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", UUID_T, nullable=False),
        sa.Column("role_stage_id", UUID_T, nullable=False),
        sa.Column("snapshot_id", UUID_T, nullable=False),
        sa.Column("service_type", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'RECEIVED'")),
        sa.Column("received_at_offset_ms", sa.Integer(), nullable=False),
        sa.Column("acknowledged_at_offset_ms", sa.Integer(), nullable=True),
        sa.Column("dispatched_at_offset_ms", sa.Integer(), nullable=True),
        sa.Column("closed_at_offset_ms", sa.Integer(), nullable=True),
        sa.Column("closure_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dds_assignments"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
            name="fk_dds_assignments_incident_id_incidents",
        ),
        sa.ForeignKeyConstraint(
            ["role_stage_id"],
            ["role_stages.id"],
            ondelete="CASCADE",
            name="fk_dds_assignments_role_stage_id_role_stages",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["handoff_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_dds_assignments_snapshot_id_handoff_snapshots",
        ),
        sa.UniqueConstraint(
            "role_stage_id", "service_type", name="uq_dds_assignments_stage_service"
        ),
        sa.CheckConstraint(enum_check("service_type", ServiceType), name="service_type"),
        sa.CheckConstraint(enum_check("state", DDSStageState), name="state"),
    )
    op.create_index("ix_dds_assignments_incident", "dds_assignments", ["incident_id"])

    op.create_table(
        "emergency_resources",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID_T, nullable=False),
        sa.Column("scenario_resource_id", sa.Text(), nullable=False),
        sa.Column("service_type", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("callsign", sa.Text(), nullable=False),
        sa.Column("name_ru", sa.Text(), nullable=False),
        sa.Column("capabilities", TEXT_ARRAY_T, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "current_status", sa.Text(), nullable=False, server_default=sa.text("'AVAILABLE'")
        ),
        sa.Column("home_station_ru", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("crew_size", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("availability", JSONB_T, nullable=False),
        sa.Column("eta", JSONB_T, nullable=False),
        sa.Column(
            "status_changed_at_offset_ms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("assignment_id", UUID_T, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_emergency_resources"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_emergency_resources_session_id_simulation_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["dds_assignments.id"],
            ondelete="SET NULL",
            name="fk_emergency_resources_assignment_id_dds_assignments",
        ),
        sa.UniqueConstraint(
            "session_id", "scenario_resource_id", name="uq_resources_session_scenario_id"
        ),
        sa.UniqueConstraint("session_id", "callsign", name="uq_resources_session_callsign"),
        sa.CheckConstraint(
            enum_check("current_status", ResourceStatus),
            name="current_status",
        ),
    )
    op.create_index(
        "ix_resources_session_service_status",
        "emergency_resources",
        ["session_id", "service_type", "current_status"],
    )
    op.create_index(
        "ix_resources_capabilities",
        "emergency_resources",
        ["capabilities"],
        postgresql_using="gin",
    )

    op.create_table(
        "resource_state_changes",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("resource_id", UUID_T, nullable=False),
        sa.Column("assignment_id", UUID_T, nullable=True),
        sa.Column("previous_status", sa.Text(), nullable=True),
        sa.Column("new_status", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("source_world_event_id", sa.Text(), nullable=True),
        sa.Column("at_offset_ms", sa.Integer(), nullable=False),
        sa.Column("session_event_id", UUID_T, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_resource_state_changes"),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["emergency_resources.id"],
            ondelete="CASCADE",
            name="fk_resource_state_changes_resource_id_emergency_resources",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["dds_assignments.id"],
            ondelete="SET NULL",
            name="fk_resource_state_changes_assignment_id_dds_assignments",
        ),
        sa.ForeignKeyConstraint(
            ["session_event_id"],
            ["session_events.id"],
            ondelete="RESTRICT",
            name="fk_resource_state_changes_session_event_id_session_events",
        ),
    )
    op.create_index(
        "ix_resource_state_changes_resource",
        "resource_state_changes",
        ["resource_id", "at_offset_ms"],
    )

    op.create_table(
        "notifications",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", UUID_T, nullable=False),
        sa.Column("audience_role", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default=sa.text("'INFO'")),
        sa.Column("title_ru", sa.Text(), nullable=False),
        sa.Column("body_ru", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("source_world_event_id", sa.Text(), nullable=True),
        sa.Column("created_at_offset_ms", sa.Integer(), nullable=False),
        sa.Column("acknowledged_at_offset_ms", sa.Integer(), nullable=True),
        sa.Column("acknowledged_by_user_id", UUID_T, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
            name="fk_notifications_incident_id_incidents",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_notifications_acknowledged_by_user_id_users",
        ),
        sa.CheckConstraint(enum_check("audience_role", RoleType), name="audience_role"),
        sa.CheckConstraint(enum_check("severity", NotificationSeverity), name="severity"),
    )
    op.create_index(
        "ix_notifications_incident_role",
        "notifications",
        ["incident_id", "audience_role", "created_at_offset_ms"],
    )

    # ---------------------------------------------------------------------------------------
    # §20.6 Transcript, audio, dialogue turns, retention audit and telemetry
    # ---------------------------------------------------------------------------------------
    op.create_table(
        "audio_segments",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID_T, nullable=False),
        sa.Column("speaker", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("format", sa.Text(), nullable=False, server_default=sa.text("'wav'")),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False, server_default=sa.text("16000")),
        sa.Column("num_channels", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("byte_offset", sa.BigInteger(), nullable=False),
        sa.Column("byte_length", sa.BigInteger(), nullable=False),
        sa.Column("purged_at", TIMESTAMPTZ_T, nullable=True),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_audio_segments"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_audio_segments_session_id_simulation_sessions",
        ),
        sa.CheckConstraint(enum_check("speaker", SPEAKERS), name="speaker"),
        sa.CheckConstraint("end_ms >= start_ms", name="end_ms"),
    )
    op.create_index("ix_audio_segments_session_start", "audio_segments", ["session_id", "start_ms"])

    op.create_table(
        "transcript_segments",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID_T, nullable=False),
        sa.Column("audio_segment_id", UUID_T, nullable=True),
        sa.Column("speaker", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("confidence", sa.REAL(), nullable=True),
        sa.Column("asr_provider", sa.Text(), nullable=True),
        sa.Column("asr_model", sa.Text(), nullable=True),
        sa.Column("turn_index", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_transcript_segments"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_transcript_segments_session_id_simulation_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["audio_segment_id"],
            ["audio_segments.id"],
            ondelete="SET NULL",
            name="fk_transcript_segments_audio_segment_id_audio_segments",
        ),
        sa.CheckConstraint(enum_check("speaker", SPEAKERS), name="speaker"),
        sa.CheckConstraint("end_ms >= start_ms", name="end_ms"),
    )
    op.create_index(
        "ix_transcript_segments_session_start", "transcript_segments", ["session_id", "start_ms"]
    )

    op.create_table(
        "dialogue_turns",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID_T, nullable=False),
        sa.Column("role_stage_id", UUID_T, nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("user_speech_started_offset_ms", sa.Integer(), nullable=False),
        sa.Column("user_speech_ended_offset_ms", sa.Integer(), nullable=True),
        sa.Column("operator_transcript_segment_id", UUID_T, nullable=True),
        sa.Column("caller_transcript_segment_id", UUID_T, nullable=True),
        sa.Column("interpretation", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("gate_output", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("planned_text", sa.Text(), nullable=True),
        sa.Column("delivered_text", sa.Text(), nullable=True),
        sa.Column("interrupted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("speech_end_to_first_audio_ms", sa.Integer(), nullable=True),
        sa.Column("correlation_id", UUID_T, nullable=True),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_dialogue_turns"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_dialogue_turns_session_id_simulation_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["role_stage_id"],
            ["role_stages.id"],
            ondelete="CASCADE",
            name="fk_dialogue_turns_role_stage_id_role_stages",
        ),
        sa.ForeignKeyConstraint(
            ["operator_transcript_segment_id"],
            ["transcript_segments.id"],
            ondelete="SET NULL",
            name="fk_dialogue_turns_operator_segment_transcript_segments",
        ),
        sa.ForeignKeyConstraint(
            ["caller_transcript_segment_id"],
            ["transcript_segments.id"],
            ondelete="SET NULL",
            name="fk_dialogue_turns_caller_segment_transcript_segments",
        ),
        sa.UniqueConstraint("session_id", "turn_index", name="uq_dialogue_turns_session_index"),
    )
    op.create_index("ix_dialogue_turns_session", "dialogue_turns", ["session_id", "turn_index"])
    op.create_index(
        "ix_dialogue_turns_correlation",
        "dialogue_turns",
        ["correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )

    op.create_table(
        "recording_purge_audit",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("purged_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.Column("actor_type", sa.Text(), nullable=False, server_default=sa.text("'SYSTEM'")),
        sa.Column("actor_user_id", UUID_T, nullable=True),
        sa.Column("session_id", UUID_T, nullable=False),
        sa.Column("audio_segment_id", UUID_T, nullable=False),
        sa.Column("file_path_was", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_recording_purge_audit"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_recording_purge_audit_actor_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_recording_purge_audit_session_id_simulation_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["audio_segment_id"],
            ["audio_segments.id"],
            ondelete="RESTRICT",
            name="fk_recording_purge_audit_audio_segment_id_audio_segments",
        ),
        sa.CheckConstraint(enum_check("actor_type", ActorType), name="actor_type"),
        sa.CheckConstraint(enum_check("reason", PURGE_REASONS), name="reason"),
    )
    op.create_index(
        "ix_recording_purge_audit_session", "recording_purge_audit", ["session_id", "purged_at"]
    )

    op.create_table(
        "inference_metrics",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID_T, nullable=True),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("component", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("turn_index", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("input_duration_ms", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("output_audio_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", TIMESTAMPTZ_T, nullable=False),
        sa.Column("first_output_at", TIMESTAMPTZ_T, nullable=True),
        sa.Column("finished_at", TIMESTAMPTZ_T, nullable=True),
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_per_second", sa.REAL(), nullable=True),
        sa.Column("realtime_factor", sa.REAL(), nullable=True),
        sa.Column("gpu_memory_mb", sa.Integer(), nullable=True),
        sa.Column("fallback_count", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("retry_count", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id", name="pk_inference_metrics"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_inference_metrics_session_id_simulation_sessions",
        ),
        sa.UniqueConstraint("request_id", name="uq_inference_metrics_request"),
        sa.CheckConstraint(enum_check("component", INFERENCE_COMPONENTS), name="component"),
    )
    op.create_index(
        "ix_inference_metrics_session_component",
        "inference_metrics",
        ["session_id", "component", "started_at"],
    )

    # ---------------------------------------------------------------------------------------
    # §20.7 Scoring output
    # ---------------------------------------------------------------------------------------
    op.create_table(
        "score_results",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID_T, nullable=False),
        sa.Column("scenario_version_id", UUID_T, nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("evaluator_type", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("points_awarded", sa.Numeric(8, 2), nullable=False),
        sa.Column("max_points", sa.Numeric(8, 2), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column(
            "critical_failure", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("computed_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_score_results"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_sessions.id"],
            ondelete="CASCADE",
            name="fk_score_results_session_id_simulation_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_version_id", "rule_id"],
            ["scoring_rules.scenario_version_id", "scoring_rules.rule_id"],
            ondelete="RESTRICT",
            name="fk_score_results_scoring_rules",
        ),
        sa.UniqueConstraint("session_id", "rule_id", name="uq_score_results_session_rule"),
    )
    op.create_index(
        "ix_score_results_session_category", "score_results", ["session_id", "category"]
    )

    op.create_table(
        "score_evidence",
        sa.Column("id", UUID_T, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("score_result_id", UUID_T, nullable=False),
        sa.Column("session_event_id", UUID_T, nullable=True),
        sa.Column("card_revision_id", UUID_T, nullable=True),
        sa.Column("snapshot_id", UUID_T, nullable=True),
        sa.Column("seq_no", sa.BigInteger(), nullable=True),
        sa.Column("note_ru", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_score_evidence"),
        sa.ForeignKeyConstraint(
            ["score_result_id"],
            ["score_results.id"],
            ondelete="CASCADE",
            name="fk_score_evidence_score_result_id_score_results",
        ),
        sa.ForeignKeyConstraint(
            ["session_event_id"],
            ["session_events.id"],
            ondelete="RESTRICT",
            name="fk_score_evidence_session_event_id_session_events",
        ),
        sa.ForeignKeyConstraint(
            ["card_revision_id"],
            ["incident_card_revisions.id"],
            ondelete="RESTRICT",
            name="fk_score_evidence_card_revision_id_incident_card_revisions",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["handoff_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_score_evidence_snapshot_id_handoff_snapshots",
        ),
        sa.CheckConstraint(
            "(session_event_id IS NOT NULL)::int"
            " + (card_revision_id IS NOT NULL)::int"
            " + (snapshot_id     IS NOT NULL)::int = 1",
            name="exactly_one",
        ),
    )
    op.create_index("ix_score_evidence_result", "score_evidence", ["score_result_id"])

    # ---------------------------------------------------------------------------------------
    # §20.9 Immutability triggers and §20.2 scenario-version lock trigger
    # ---------------------------------------------------------------------------------------
    op.execute(REJECT_MUTATION_FUNCTION)
    for trigger_name, table_name in APPEND_ONLY_TRIGGERS:
        op.execute(
            f"CREATE TRIGGER {trigger_name} "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            f"FOR EACH ROW EXECUTE FUNCTION trg_reject_mutation()"
        )

    op.execute(SCENARIO_VERSIONS_LOCKED_FUNCTION)
    op.execute(
        "CREATE TRIGGER scenario_versions_locked_guard "
        "BEFORE UPDATE ON scenario_versions "
        "FOR EACH ROW EXECUTE FUNCTION trg_scenario_versions_locked()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS scenario_versions_locked_guard ON scenario_versions")
    op.execute("DROP FUNCTION IF EXISTS trg_scenario_versions_locked()")
    for trigger_name, table_name in reversed(APPEND_ONLY_TRIGGERS):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS trg_reject_mutation()")

    for table_name in (
        "score_evidence",
        "score_results",
        "inference_metrics",
        "recording_purge_audit",
        "dialogue_turns",
        "transcript_segments",
        "audio_segments",
        "notifications",
        "resource_state_changes",
        "emergency_resources",
        "dds_assignments",
        "handoff_snapshots",
        "incident_card_revisions",
        "incident_cards",
        "incident_caller_beliefs",
        "incident_world_states",
        "session_events",
        "role_stages",
        "incidents",
        "session_participants",
        "simulation_sessions",
        "scoring_rules",
        "scenario_versions",
        "scenarios",
        "users",
    ):
        op.drop_table(table_name)

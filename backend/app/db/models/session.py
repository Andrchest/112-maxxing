"""Session aggregate tables (HLD `20-db-schema.md` §20.3).

`simulation_sessions`, `session_participants`, `role_stages`, `incidents`, `world_engine_states`.

`world_engine_states` (additive, E6) is a 1:1 satellite of `incidents`, which is why it lives
here rather than in `layers.py`: it is explicitly **not** a fifth information layer. World truth
holds facts about the world; the engine's bookkeeping — occurrence counters, queued triggers,
how far simulated time has been advanced — is not a fact about anything and D3 forbids merging
the two.
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import GEN_RANDOM_UUID, JSONB_T, NOW, TIMESTAMPTZ_T, UUID_T, Base, enum_check
from app.domain.enums import (
    ClosureReason,
    DDSStageState,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)

#: `role_stages.state` carries either an `Operator112StageState` or a `DDSStageState` member; the
#: CHECK lists the union of both enums (HLD §20.3).
ROLE_STAGE_STATES: tuple[str, ...] = tuple(
    dict.fromkeys(
        [member.value for member in Operator112StageState]
        + [member.value for member in DDSStageState]
    )
)


class SimulationSession(Base):
    """`simulation_sessions` — the aggregate root (HLD §20.3, D5, D7)."""

    __tablename__ = "simulation_sessions"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    scenario_version_id = sa.Column(
        UUID_T, sa.ForeignKey("scenario_versions.id", ondelete="RESTRICT"), nullable=False
    )
    session_mode = sa.Column(sa.Text(), nullable=False)
    state = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'CREATED'"))
    session_seed = sa.Column(sa.Text(), nullable=False)
    #: Additive in E5: `openapi.yaml`'s `SessionCreateRequest`/`SessionDetail` both carry
    #: `time_scale` and the domain aggregate holds it, so the session row is its home. `numeric`
    #: (not float) because 0.1 steps must round-trip exactly; the CHECK mirrors the schema's
    #: `minimum: 0.1` / `maximum: 10` (HLD §20.3, "(additive, E5)").
    time_scale = sa.Column(sa.Numeric(4, 2), nullable=False, server_default=sa.text("1"))
    created_by_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    next_seq_no = sa.Column(sa.BigInteger(), nullable=False, server_default=sa.text("1"))
    started_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    paused_total_ms = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    completed_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    abort_reason = sa.Column(sa.Text(), nullable=True)
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.Index("ix_sessions_state", "state"),
        sa.Index("ix_sessions_scenario_version", "scenario_version_id"),
        sa.CheckConstraint(enum_check("session_mode", SessionMode), name="session_mode"),
        sa.CheckConstraint(enum_check("state", SessionState), name="state"),
        sa.CheckConstraint("time_scale >= 0.1 AND time_scale <= 10", name="time_scale"),
    )


class SessionParticipant(Base):
    """`session_participants` (HLD §20.3)."""

    __tablename__ = "session_participants"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id = sa.Column(UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    assigned_role_type = sa.Column(sa.Text(), nullable=True)
    joined_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.UniqueConstraint("session_id", "user_id", name="uq_participants_session_user"),
        sa.CheckConstraint(
            enum_check("assigned_role_type", RoleType, nullable=True), name="assigned_role_type"
        ),
    )


class RoleStage(Base):
    """`role_stages` — materialized from the event log (HLD §20.3)."""

    __tablename__ = "role_stages"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    incident_id = sa.Column(
        UUID_T, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    role_type = sa.Column(sa.Text(), nullable=False)
    order_index = sa.Column(sa.Integer(), nullable=False)
    state = sa.Column(sa.Text(), nullable=False)
    participant_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    started_at_offset_ms = sa.Column(sa.Integer(), nullable=True)
    completed_at_offset_ms = sa.Column(sa.Integer(), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("session_id", "order_index", name="uq_role_stages_session_order"),
        sa.Index("ix_role_stages_session_state", "session_id", "state"),
        sa.CheckConstraint(enum_check("role_type", RoleType), name="role_type"),
        sa.CheckConstraint(enum_check("state", ROLE_STAGE_STATES), name="state"),
    )


class Incident(Base):
    """`incidents` — one session, one incident (HLD §20.3, SPEC §13)."""

    __tablename__ = "incidents"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    scenario_version_id = sa.Column(
        UUID_T, sa.ForeignKey("scenario_versions.id", ondelete="RESTRICT"), nullable=False
    )
    created_at_offset_ms = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    closed_at_offset_ms = sa.Column(sa.Integer(), nullable=True)
    closure_reason = sa.Column(sa.Text(), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("session_id", name="uq_incidents_session"),
        sa.CheckConstraint(
            enum_check("closure_reason", ClosureReason, nullable=True), name="closure_reason"
        ),
    )


class WorldEngineState(Base):
    """`world_engine_states` — the world event engine's bookkeeping (additive, E6; D3, D7).

    One row per incident, written only by `tick_session` and created zeroed by session creation.
    `bookkeeping` is a single jsonb document (`occurrences`, `last_fired_ms`, `scheduled`,
    `emotion_applications`, `reached_states`) because its shape is scenario-defined — the keys are
    `world_event_id`s and emotion rule ids — exactly the reason §20.4 gives for its own jsonb
    columns. `EventIndex` is absent on purpose: it is re-folded from `session_events` on load, so
    the event log stays the single source of what happened (D5).
    """

    __tablename__ = "world_engine_states"

    incident_id = sa.Column(
        UUID_T, sa.ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    last_tick_ms = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    last_folded_seq_no = sa.Column(sa.BigInteger(), nullable=False, server_default=sa.text("0"))
    bookkeeping = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    updated_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

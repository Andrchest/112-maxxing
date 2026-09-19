"""Session aggregate tables (HLD `20-db-schema.md` §20.3).

`simulation_sessions`, `session_participants`, `role_stages`, `incidents`.
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import GEN_RANDOM_UUID, NOW, TIMESTAMPTZ_T, UUID_T, Base, enum_check
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

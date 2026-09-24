"""dds_calls: the ДДС phone line's read model (I3 E6b, HLD `80-telephony.md` §80.3.1, §80.7, D23).

Additive only (P1): one new table,

* `dds_calls (id uuid PK (= call_id), session_id FK simulation_sessions ON DELETE CASCADE, kind,
  direction, assignment_id FK dds_assignments ON DELETE CASCADE, service_type, dialed, endpoint,
  room UNIQUE, persona_id, actor_user_id FK users ON DELETE RESTRICT, state DEFAULT 'DIALING',
  answered_by, selection_reason, started_event_id UNIQUE FK session_events, started_at_offset_ms,
  answered_at_offset_ms, ended_at_offset_ms, end_reason)`, with the enum CHECKs and the three
  consistency CHECKs of §80.7 (`SERVICE_HEAD` ⇔ a leg; `ENDED` ⇔ an end offset; `ENDED` ⇔ an end
  reason);
* index `ix_dds_calls_session (session_id, started_at_offset_ms)` and the partial index
  `ix_dds_calls_live (session_id, actor_user_id) WHERE state <> 'ENDED'` (one line per workstation).

A read model written in the same Unit of Work as the `DDS_CALL_*` event it mirrors and rebuildable
from them (INV 13). No backfill: no ДДС call exists before E6b. The enum members are inlined (a
migration never imports an app constant a later epic may change; same rule as `0010`–`0012`).

Numbered `0014` by manager decision: `0013` is I3 E9a's (`0013_trainee_groups`), and HLD 80 §80.7
and HLD 90's E6b row say so.

Revision ID: 0014_dds_calls
Revises: 0013_trainee_groups
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import UUID_T, enum_check

revision: str = "0014_dds_calls"
down_revision: str | None = "0013_trainee_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "dds_calls"
_KINDS = ("SERVICE_HEAD", "CLAIMANT", "OPERATOR_112")
_DIRECTIONS = ("OUTBOUND", "INBOUND")
_ENDPOINTS = ("BROWSER", "SIP")
_STATES = ("DIALING", "RINGING", "CONNECTED", "ENDED")
_ANSWERED_BY = ("AI", "TRAINEE")
_END_REASONS = ("HANGUP", "NO_ANSWER", "BUSY", "ABORT", "TRANSPORT_LOST")


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "session_id",
            UUID_T,
            sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column(
            "assignment_id",
            UUID_T,
            sa.ForeignKey("dds_assignments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("service_type", sa.Text(), nullable=True),
        sa.Column("dialed", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("room", sa.Text(), nullable=False),
        sa.Column("persona_id", sa.Text(), nullable=True),
        sa.Column(
            "actor_user_id",
            UUID_T,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'DIALING'")),
        sa.Column("answered_by", sa.Text(), nullable=True),
        sa.Column("selection_reason", sa.Text(), nullable=False),
        sa.Column(
            "started_event_id",
            UUID_T,
            sa.ForeignKey("session_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("started_at_offset_ms", sa.Integer(), nullable=False),
        sa.Column("answered_at_offset_ms", sa.Integer(), nullable=True),
        sa.Column("ended_at_offset_ms", sa.Integer(), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("room", name="uq_dds_calls_room"),
        sa.UniqueConstraint("started_event_id", name="uq_dds_calls_started_event_id"),
        sa.CheckConstraint(enum_check("kind", _KINDS), name="kind"),
        sa.CheckConstraint(enum_check("direction", _DIRECTIONS), name="direction"),
        sa.CheckConstraint(enum_check("endpoint", _ENDPOINTS), name="endpoint"),
        sa.CheckConstraint(enum_check("state", _STATES), name="state"),
        sa.CheckConstraint(
            enum_check("answered_by", _ANSWERED_BY, nullable=True), name="answered_by"
        ),
        sa.CheckConstraint(
            enum_check("end_reason", _END_REASONS, nullable=True), name="end_reason"
        ),
        sa.CheckConstraint(
            "(kind = 'SERVICE_HEAD') = (assignment_id IS NOT NULL)", name="service_head_leg"
        ),
        sa.CheckConstraint("(state = 'ENDED') = (ended_at_offset_ms IS NOT NULL)", name="ended_at"),
        sa.CheckConstraint("(state = 'ENDED') = (end_reason IS NOT NULL)", name="ended_reason"),
    )
    op.create_index("ix_dds_calls_session", _TABLE, ["session_id", "started_at_offset_ms"])
    op.create_index(
        "ix_dds_calls_live",
        _TABLE,
        ["session_id", "actor_user_id"],
        postgresql_where=sa.text("state <> 'ENDED'"),
    )


def downgrade() -> None:
    op.drop_index("ix_dds_calls_live", table_name=_TABLE)
    op.drop_index("ix_dds_calls_session", table_name=_TABLE)
    op.drop_table(_TABLE)

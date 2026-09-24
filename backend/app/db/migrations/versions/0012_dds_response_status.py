"""dds_response_status: the memo's per-leg response status, its append-only history and the ДДС
participant → service binding column (I3 E5a, HLD `70-i3-alignment.md` §70.4.3, §70.4.5, §70.8,
D16).

Additive only (P1):

* `dds_assignments.response_status text NOT NULL DEFAULT 'ADDED'` with its nine-member CHECK,
  `response_status_at_offset_ms`, `order_number`, `last_comment_ru`, `accept_missed boolean NOT
  NULL DEFAULT false`, `responder text NOT NULL DEFAULT 'TRAINEE'` with its CHECK, and
  `bound_user_id` (FK `users`, `RESTRICT`);
* new table `dds_service_status_history` — one row per `DDS_SERVICE_STATUS_SET`, `event_id` unique
  and FK `session_events`, index `(assignment_id, seq_no)`, and the §20.9 UPDATE/DELETE-rejecting
  trigger over the baseline's shared `trg_reject_mutation()`;
* `session_participants.assigned_service_id text NULL`, `CHECK (… IS NULL OR … <> '')`, and the
  partial unique index `(session_id, assigned_service_id) WHERE assigned_service_id IS NOT NULL`.

**Backfill.** `response_status` of every existing leg is §70.4.4's picker map of its `state` — the
same map stage automation mirrors live picker legs with — pure over existing columns, no event
read or written:

* `RECEIVED → RECEIVED`; `ACKNOWLEDGED` / `RESOURCE_SELECTION` / `DISPATCHED → ACCEPTED`;
  `EN_ROUTE → RESPONSE_STARTED`; `ARRIVED`, `WORKING` unchanged; `RESOLVED → COMPLETED`;
* `CLOSED` with a closure reason → `COMPLETED` (a trainee closure is reachable only from
  `RESOLVED`, whose mirror is already `COMPLETED`); `CLOSED` without one (an abort) keeps the last
  status the leg had provably reached: `ACCEPTED` when it was acknowledged, else `RECEIVED`;
* `response_status_at_offset_ms` is the offset the backfilled status is known from
  (`received_at_offset_ms`, `acknowledged_at_offset_ms`, `closed_at_offset_ms`), `NULL` where the
  columns do not say. No history row is written: a history row needs the event that recorded it.

The map is inlined rather than imported: a migration never imports an app constant a later epic
may change (same rule as `0010`, `0011`).

Revision ID: 0012_dds_response_status
Revises: 0011_lessons
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from app.db.base import UUID_T, enum_check

revision: str = "0012_dds_response_status"
down_revision: str | None = "0011_lessons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESPONSE_STATUSES = (
    "ADDED",
    "RECEIVED",
    "ACCEPTED",
    "NOT_ACCEPTED",
    "RESPONSE_STARTED",
    "ARRIVED",
    "WORKING",
    "COMPLETED",
    "REFUSED",
)
_RESPONDERS = ("TRAINEE", "SCRIPTED")
_HISTORY = "dds_service_status_history"
_HISTORY_TRIGGER = "dds_service_status_history_append_only"

# §70.4.4's picker map, inlined.
_MIRROR = {
    "RECEIVED": "RECEIVED",
    "ACKNOWLEDGED": "ACCEPTED",
    "RESOURCE_SELECTION": "ACCEPTED",
    "DISPATCHED": "ACCEPTED",
    "EN_ROUTE": "RESPONSE_STARTED",
    "ARRIVED": "ARRIVED",
    "WORKING": "WORKING",
    "RESOLVED": "COMPLETED",
}


def upgrade() -> None:
    op.add_column(
        "dds_assignments",
        sa.Column("response_status", sa.Text(), nullable=False, server_default=sa.text("'ADDED'")),
    )
    op.create_check_constraint(
        "response_status",
        "dds_assignments",
        sa.text(enum_check("response_status", _RESPONSE_STATUSES)),
    )
    op.add_column(
        "dds_assignments", sa.Column("response_status_at_offset_ms", sa.Integer(), nullable=True)
    )
    op.add_column("dds_assignments", sa.Column("order_number", sa.Text(), nullable=True))
    op.add_column("dds_assignments", sa.Column("last_comment_ru", sa.Text(), nullable=True))
    op.add_column(
        "dds_assignments",
        sa.Column("accept_missed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "dds_assignments",
        sa.Column("responder", sa.Text(), nullable=False, server_default=sa.text("'TRAINEE'")),
    )
    op.create_check_constraint(
        "responder", "dds_assignments", sa.text(enum_check("responder", _RESPONDERS))
    )
    op.add_column(
        "dds_assignments",
        sa.Column(
            "bound_user_id",
            UUID_T,
            sa.ForeignKey(
                "users.id",
                ondelete="RESTRICT",
                name="fk_dds_assignments_bound_user_id_users",
            ),
            nullable=True,
        ),
    )

    op.create_table(
        _HISTORY,
        sa.Column("id", UUID_T, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "session_id",
            UUID_T,
            sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            UUID_T,
            sa.ForeignKey("dds_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            UUID_T,
            sa.ForeignKey("session_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("seq_no", sa.BigInteger(), nullable=False),
        sa.Column("previous_status", sa.Text(), nullable=False),
        sa.Column("new_status", sa.Text(), nullable=False),
        sa.Column("order_number", sa.Text(), nullable=True),
        sa.Column("comment_ru", sa.Text(), nullable=True),
        sa.Column("completion_reason", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_user_id", UUID_T, nullable=True),
        sa.Column("at_offset_ms", sa.Integer(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_dds_service_status_history_event"),
    )
    op.create_index(
        "ix_dds_service_status_history_assignment", _HISTORY, ["assignment_id", "seq_no"]
    )
    op.execute(
        f"CREATE TRIGGER {_HISTORY_TRIGGER} BEFORE UPDATE OR DELETE ON {_HISTORY} "
        f"FOR EACH ROW EXECUTE FUNCTION trg_reject_mutation()"
    )

    op.add_column(
        "session_participants", sa.Column("assigned_service_id", sa.Text(), nullable=True)
    )
    op.create_check_constraint(
        "assigned_service_id",
        "session_participants",
        sa.text("assigned_service_id IS NULL OR assigned_service_id <> ''"),
    )
    op.create_index(
        "uq_participants_session_service",
        "session_participants",
        ["session_id", "assigned_service_id"],
        unique=True,
        postgresql_where=sa.text("assigned_service_id IS NOT NULL"),
    )

    _backfill_response_status(op.get_bind())


def downgrade() -> None:
    op.drop_index("uq_participants_session_service", table_name="session_participants")
    op.drop_constraint("assigned_service_id", "session_participants", type_="check")
    op.drop_column("session_participants", "assigned_service_id")
    op.execute(f"DROP TRIGGER IF EXISTS {_HISTORY_TRIGGER} ON {_HISTORY}")
    op.drop_index("ix_dds_service_status_history_assignment", table_name=_HISTORY)
    op.drop_table(_HISTORY)
    op.drop_constraint(
        "fk_dds_assignments_bound_user_id_users", "dds_assignments", type_="foreignkey"
    )
    op.drop_column("dds_assignments", "bound_user_id")
    op.drop_constraint("responder", "dds_assignments", type_="check")
    op.drop_column("dds_assignments", "responder")
    op.drop_column("dds_assignments", "accept_missed")
    op.drop_column("dds_assignments", "last_comment_ru")
    op.drop_column("dds_assignments", "order_number")
    op.drop_column("dds_assignments", "response_status_at_offset_ms")
    op.drop_constraint("response_status", "dds_assignments", type_="check")
    op.drop_column("dds_assignments", "response_status")


# ---------------------------------------------------------------------------------------------
# Backfill (§70.4.4's picker map, over existing columns)
# ---------------------------------------------------------------------------------------------


def _backfill_response_status(bind: sa.Connection) -> None:
    for leg in bind.execute(
        sa.text(
            "SELECT id, state, received_at_offset_ms, acknowledged_at_offset_ms,"
            " closed_at_offset_ms, closure_reason FROM dds_assignments"
        )
    ).all():
        status, at_offset_ms = _mirrored(leg)
        bind.execute(
            sa.text(
                "UPDATE dds_assignments SET response_status = :status,"
                " response_status_at_offset_ms = :at WHERE id = :id"
            ),
            {"status": status, "at": at_offset_ms, "id": leg.id},
        )


def _mirrored(leg: Any) -> tuple[str, int | None]:
    """The leg's backfilled `(response_status, response_status_at_offset_ms)`."""
    state = str(leg.state)
    acknowledged = leg.acknowledged_at_offset_ms
    if state == "CLOSED":
        if leg.closure_reason is not None:
            return "COMPLETED", leg.closed_at_offset_ms
        if acknowledged is not None:
            return "ACCEPTED", acknowledged
        return "RECEIVED", leg.received_at_offset_ms
    status = _MIRROR.get(state, "RECEIVED")
    if status == "RECEIVED":
        return status, leg.received_at_offset_ms
    if status == "ACCEPTED":
        return status, acknowledged
    return status, None

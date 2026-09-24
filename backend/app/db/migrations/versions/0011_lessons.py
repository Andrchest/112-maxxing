"""lessons: the `lessons` table, the lesson columns of `simulation_sessions`, and the card-status
read model of `incidents` (I3 E4a, HLD `70-i3-alignment.md` §70.3, §70.4.6, §70.8, D15).

Additive only (P1):

* new table `lessons` (+ `ix_lessons_state`);
* `simulation_sessions.lesson_id` (FK `lessons`, `RESTRICT`) and `lesson_position`, unique
  `uq_sessions_lesson_position (lesson_id, lesson_position)`, both-or-neither CHECK;
* `incidents.card_status text NOT NULL DEFAULT 'REGISTERED'` with its seven-member CHECK;
* sequence `incident_display_number_seq` and `incidents.display_number bigint NOT NULL DEFAULT
  nextval(...)`, unique — every existing incident gets its number when the column is added.

**Backfill.** `card_status` of every existing incident is computed here by the §70.4.6 function
with the §70.4.4 picker mirror, pure over existing columns — no event is read and none is written:

* a session that never started stays `REGISTERED`;
* the legs are its `dds_assignments` rows; a leg's status is the picker mirror of its `state`
  (`CLOSED` with `closure_reason RESOLVED` → `COMPLETED`; `CLOSED` is reachable only from
  `RESOLVED`, so any other closure leaves `COMPLETED` too), and its primary decision is
  `acknowledged_at_offset_ms` (`ACCEPTED ≡ DDS_ACKNOWLEDGED` until E5);
* the handoff exists iff a leg does, at the earliest `received_at_offset_ms`;
* "now" is the session's last `session_events.monotonic_offset_ms`;
* the timers are the defaults (30 s, 48 h): no scenario could declare `timers` before this
  revision;
* `simulation_sessions.report_released_at` is the `CHECKED` fact.

The precedence (`COMPLETED > REFUSED > NOT_COMPLETED > NOT_NOTIFIED > CHECKED > WORKED >
REGISTERED`, A-5) and the mirror are inlined rather than imported: a migration never imports an app
constant a later epic may change (same rule as `0010`).

Revision ID: 0011_lessons
Revises: 0010_service_id_open
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from app.db.base import JSONB_T, TIMESTAMPTZ_T, UUID_T, enum_check

revision: str = "0011_lessons"
down_revision: str | None = "0010_service_id_open"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SESSION_MODES = ("SINGLE_ROLE", "FULL_CYCLE_SINGLE_TRAINEE", "MULTI_TRAINEE", "ASSESSMENT")
_LESSON_STATES = ("CREATED", "ACTIVE", "COMPLETED", "ABORTED")
_CARD_STATUSES = (
    "REGISTERED",
    "WORKED",
    "CHECKED",
    "NOT_NOTIFIED",
    "REFUSED",
    "NOT_COMPLETED",
    "COMPLETED",
)
_SEQUENCE = "incident_display_number_seq"

# §70.4.4's picker mirror, inlined.
_MIRROR = {
    "RECEIVED": "RECEIVED",
    "ACKNOWLEDGED": "ACCEPTED",
    "RESOURCE_SELECTION": "ACCEPTED",
    "DISPATCHED": "ACCEPTED",
    "EN_ROUTE": "RESPONSE_STARTED",
    "ARRIVED": "ARRIVED",
    "WORKING": "WORKING",
    "RESOLVED": "COMPLETED",
    "CLOSED": "COMPLETED",
}
_ACCEPT_WITHIN_MS = 30_000
_NOT_COMPLETED_AFTER_MS = 172_800_000


def upgrade() -> None:
    op.create_table(
        "lessons",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("title_ru", sa.Text(), nullable=False),
        sa.Column(
            "created_by_user_id",
            UUID_T,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("session_mode", sa.Text(), nullable=False),
        sa.Column("variants", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("participants", JSONB_T, nullable=False),
        sa.Column("scenario_plan", JSONB_T, nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'CREATED'")),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", TIMESTAMPTZ_T, nullable=True),
        sa.Column("completed_at", TIMESTAMPTZ_T, nullable=True),
        sa.Column("report_released_at", TIMESTAMPTZ_T, nullable=True),
        sa.Column(
            "report_released_by_user_id",
            UUID_T,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.CheckConstraint(enum_check("session_mode", _SESSION_MODES), name="session_mode"),
        sa.CheckConstraint(enum_check("state", _LESSON_STATES), name="state"),
    )
    op.create_index("ix_lessons_state", "lessons", ["state"])

    op.add_column(
        "simulation_sessions",
        sa.Column(
            "lesson_id", UUID_T, sa.ForeignKey("lessons.id", ondelete="RESTRICT"), nullable=True
        ),
    )
    op.add_column("simulation_sessions", sa.Column("lesson_position", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        "uq_sessions_lesson_position", "simulation_sessions", ["lesson_id", "lesson_position"]
    )
    op.create_check_constraint(
        "lesson_position_together",
        "simulation_sessions",
        sa.text("(lesson_id IS NULL) = (lesson_position IS NULL)"),
    )

    op.add_column(
        "incidents",
        sa.Column("card_status", sa.Text(), nullable=False, server_default=sa.text("'REGISTERED'")),
    )
    op.create_check_constraint(
        "card_status", "incidents", sa.text(enum_check("card_status", _CARD_STATUSES))
    )
    op.execute(sa.text(f"CREATE SEQUENCE {_SEQUENCE}"))
    op.add_column(
        "incidents",
        sa.Column(
            "display_number",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text(f"nextval('{_SEQUENCE}'::regclass)"),
        ),
    )
    op.create_unique_constraint("uq_incidents_display_number", "incidents", ["display_number"])

    _backfill_card_status(op.get_bind())


def downgrade() -> None:
    op.drop_constraint("uq_incidents_display_number", "incidents", type_="unique")
    op.drop_column("incidents", "display_number")
    op.execute(sa.text(f"DROP SEQUENCE {_SEQUENCE}"))
    op.drop_constraint("card_status", "incidents", type_="check")
    op.drop_column("incidents", "card_status")
    op.drop_constraint("lesson_position_together", "simulation_sessions", type_="check")
    op.drop_constraint("uq_sessions_lesson_position", "simulation_sessions", type_="unique")
    op.drop_column("simulation_sessions", "lesson_position")
    op.drop_column("simulation_sessions", "lesson_id")
    op.drop_index("ix_lessons_state", table_name="lessons")
    op.drop_table("lessons")


# ---------------------------------------------------------------------------------------------
# Backfill (§70.4.6 with the picker mirror, over existing columns)
# ---------------------------------------------------------------------------------------------


def _backfill_card_status(bind: sa.Connection) -> None:
    sessions = bind.execute(
        sa.text(
            "SELECT i.id AS incident_id, s.started_at, s.report_released_at,"
            " (SELECT max(e.monotonic_offset_ms) FROM session_events e"
            "   WHERE e.session_id = s.id) AS last_offset_ms"
            " FROM incidents i JOIN simulation_sessions s ON s.id = i.session_id"
        )
    ).all()
    legs_by_incident: dict[Any, list[Any]] = {}
    for leg in bind.execute(
        sa.text(
            "SELECT incident_id, state, received_at_offset_ms, acknowledged_at_offset_ms,"
            " closure_reason FROM dds_assignments"
        )
    ).all():
        legs_by_incident.setdefault(leg.incident_id, []).append(leg)

    for row in sessions:
        status = _card_status(
            started=row.started_at is not None,
            legs=legs_by_incident.get(row.incident_id, []),
            now_ms=int(row.last_offset_ms or 0),
            report_released=row.report_released_at is not None,
        )
        if status != "REGISTERED":
            bind.execute(
                sa.text("UPDATE incidents SET card_status = :status WHERE id = :id"),
                {"status": status, "id": row.incident_id},
            )


def _leg_status(leg: Any) -> str:
    if leg.state == "CLOSED" and leg.closure_reason is not None:
        return "COMPLETED"
    return _MIRROR.get(str(leg.state), "RECEIVED")


def _accept_missed(leg: Any, now_ms: int) -> bool:
    deadline = int(leg.received_at_offset_ms) + _ACCEPT_WITHIN_MS
    if now_ms < deadline:
        return False
    decided = leg.acknowledged_at_offset_ms
    return decided is None or int(decided) >= deadline


def _card_status(*, started: bool, legs: list[Any], now_ms: int, report_released: bool) -> str:
    if not started:
        return "REGISTERED"
    statuses = [_leg_status(leg) for leg in legs]
    handoff_ms = min((int(leg.received_at_offset_ms) for leg in legs), default=None)
    if handoff_ms is not None and all(status == "COMPLETED" for status in statuses):
        return "COMPLETED"
    if any(status in ("NOT_ACCEPTED", "REFUSED") for status in statuses):
        return "REFUSED"
    if (
        handoff_ms is not None
        and now_ms >= handoff_ms + _NOT_COMPLETED_AFTER_MS
        and any(status != "COMPLETED" for status in statuses)
    ):
        return "NOT_COMPLETED"
    if any(_accept_missed(leg, now_ms) for leg in legs):
        return "NOT_NOTIFIED"
    if report_released:
        return "CHECKED"
    if handoff_ms is not None:
        return "WORKED"
    return "REGISTERED"

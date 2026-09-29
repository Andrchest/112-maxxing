"""audit_log.action gains LOGIN_THROTTLED (I7 E51, G5; ТЗ ¶295 «Защита от несанкционированного
доступа»; `app.application.ports.audit_log.AuditAction`).

Additive only (P1): the `action` `CHECK` is replaced with the same list plus one member — no
column, no index, no backfill. `audit_log_append_only` (0016) is untouched.

The CHECK list is inlined rather than imported, same rule as `0016`/`0019`: a migration never
imports an app constant a later epic may change.

Revision ID: 0021_login_throttled_audit_action
Revises: 0020_lesson_shuffle_seed
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.db.base import enum_check

revision: str = "0021_login_throttled_audit_action"
down_revision: str | None = "0020_lesson_shuffle_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "audit_log"
_CONSTRAINT = "action"
_OLD_ACTIONS = ("HTTP_REQUEST", "LOGIN_SUCCEEDED", "LOGIN_FAILED", "ACCESS_DENIED", "WS_CONNECTED")
_NEW_ACTIONS = (*_OLD_ACTIONS, "LOGIN_THROTTLED")


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, enum_check("action", _NEW_ACTIONS))


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, enum_check("action", _OLD_ACTIONS))

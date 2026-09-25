"""audit_log: the cross-cutting audit of user actions (I4 E25, HLD `71-i4-wave4.md` §71.2,
HLD 20 §20.6, D31).

Additive only (P1): one new table and one trigger,

* `audit_log` — one row per audited request, refused request, WebSocket connect or login attempt;
  indexes `(ts)` and `(user_id, ts)`; `CHECK`s on `role` (nullable), `action` and `outcome`;
  `user_id` FK `users` `RESTRICT`. No request or response body has a column;
* `audit_log_append_only` — the §20.9 `BEFORE UPDATE OR DELETE` trigger over the baseline's shared
  `trg_reject_mutation()`, so the application has no path to change or remove an entry
  (ТЗ ¶297: security journals are kept at least six months, `SIM_AUDIT_RETENTION_DAYS` ≥ 183).

No backfill: the table starts empty. The CHECK lists are inlined rather than imported: a migration
never imports an app constant a later epic may change (same rule as `0010`, `0011`, `0012`).

Revision ID: 0016_audit_log
Revises: 0015_users_sip_ha1
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import JSONB_T, TIMESTAMPTZ_T, UUID_T, enum_check

revision: str = "0016_audit_log"
down_revision: str | None = "0015_users_sip_ha1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "audit_log"
_TRIGGER = "audit_log_append_only"
_ROLES = ("TRAINEE", "INSTRUCTOR", "ADMIN")
_ACTIONS = ("HTTP_REQUEST", "LOGIN_SUCCEEDED", "LOGIN_FAILED", "ACCESS_DENIED", "WS_CONNECTED")
_OUTCOMES = ("OK", "DENIED", "ERROR")


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", UUID_T, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ts", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "user_id",
            UUID_T,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("operation_id", sa.Text(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("path_template", sa.Text(), nullable=False),
        sa.Column("target_ids", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("client_ip", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.CheckConstraint(enum_check("role", _ROLES, nullable=True), name="role"),
        sa.CheckConstraint(enum_check("action", _ACTIONS), name="action"),
        sa.CheckConstraint(enum_check("outcome", _OUTCOMES), name="outcome"),
    )
    op.create_index("ix_audit_log_ts", _TABLE, ["ts"])
    op.create_index("ix_audit_log_user_ts", _TABLE, ["user_id", "ts"])
    op.execute(
        f"CREATE TRIGGER {_TRIGGER} BEFORE UPDATE OR DELETE ON {_TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION trg_reject_mutation()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE}")
    op.drop_index("ix_audit_log_user_ts", table_name=_TABLE)
    op.drop_index("ix_audit_log_ts", table_name=_TABLE)
    op.drop_table(_TABLE)

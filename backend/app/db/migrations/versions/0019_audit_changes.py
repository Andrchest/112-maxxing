"""audit_changes: the «было → стало» list on `audit_log` (I7 E43, Q-E15-3; ТЗ ¶246, ¶296; HLD
`71-i4-wave4.md` §71.19.43, HLD 20 `audit_log`).

Additive only (P1): one nullable JSONB column,

* `audit_log.changes` — a JSON array of `{field, before, after}` a mutating use case reported for
  the request (`AuditChangeCollector`); `NULL` when the request changed nothing it reports (every
  read, every refusal, every row written before this revision).

The table stays append-only: `audit_log_append_only` (0016) is untouched and keeps refusing every
UPDATE and DELETE — the middleware writes the row once, already carrying its changes. No backfill.

Revision ID: 0019_audit_changes
Revises: 0018_training_materials
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import JSONB_T

revision: str = "0019_audit_changes"
down_revision: str | None = "0018_training_materials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "audit_log"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("changes", JSONB_T, nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "changes")

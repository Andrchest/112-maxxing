"""lesson_shuffle_seed: «Случайный порядок карточек» on `lessons` (I7 E53, G12a; ТЗ ¶340; HLD
`71-i4-wave4.md` §71.19.53, HLD 20 §20.12.53).

Additive only (P1): one nullable BIGINT column,

* `lessons.shuffle_seed` — the seed `createLesson` permuted the plan's cards with, once, when the
  instructor ticked «Случайный порядок карточек»; `NULL` for the instructor's own order and for
  every lesson created before this revision. The permuted plan itself is `scenario_plan` as
  before, so nothing reads the seed to decide anything (it is the record of the draw). No backfill.

A column rather than a key inside an existing jsonb document: `variants` is the lesson-wide
`VariantsRequest` and `scenario_plan` a list of `PlanEntry`, both closed shapes (`extra="forbid"`).

Revision ID: 0020_lesson_shuffle_seed
Revises: 0019_audit_changes
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_lesson_shuffle_seed"
down_revision: str | None = "0019_audit_changes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "lessons"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("shuffle_seed", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "shuffle_seed")

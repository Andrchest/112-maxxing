"""training_materials: the instructor's methodical-materials reference base (I4 E34, HLD
`71-i4-wave4.md` §71.11, HLD `20-db-schema.md` §20.12, ТЗ ¶227, ¶256, ¶387, ¶370).

Additive only (P1): one new table, metadata only. The bytes live at
`Settings.data_dir/materials/<sha256>` (identical bytes stored once, the same pattern as
recordings under `data_dir`) — `sha256` is indexed but not unique, because two uploads of the
same bytes under a different `title_ru` are two distinct rows over one stored file.

`archived_at` hides a material from a trainee's «Справочная база» without deleting the file
(reference data, no retention). No assignment column: whom a material is assigned to is owner
question Q-E13-1 (§71.11).

Revision ID: 0018_training_materials
Revises: 0017_result_comments_scenario_archive
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import GEN_RANDOM_UUID, NOW, TIMESTAMPTZ_T, UUID_T

revision: str = "0018_training_materials"
down_revision: str | None = "0017_result_comments_scenario_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "training_materials"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID),
        sa.Column("title_ru", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_by", UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=NOW),
        sa.Column("archived_at", TIMESTAMPTZ_T, nullable=True),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        sa.CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
    )
    op.create_index("ix_training_materials_sha256", _TABLE, ["sha256"])
    op.create_index("ix_training_materials_created", _TABLE, ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_training_materials_created", table_name=_TABLE)
    op.drop_index("ix_training_materials_sha256", table_name=_TABLE)
    op.drop_table(_TABLE)

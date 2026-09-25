"""`training_materials` — the instructor's methodical-materials reference base
(HLD `20-db-schema.md` §20.12, I4 E34, migration `0018_training_materials`).

Metadata only: the bytes live at `Settings.data_dir/materials/<sha256>` (identical bytes stored
once — the same pattern as recordings). `archived_at` hides a row from a trainee's «Справочная
база» without deleting the file; there is no assignment column (owner question Q-E13-1).
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import GEN_RANDOM_UUID, NOW, TIMESTAMPTZ_T, UUID_T, Base


class TrainingMaterial(Base):
    """`training_materials` (§20.12)."""

    __tablename__ = "training_materials"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    title_ru = sa.Column(sa.Text(), nullable=False)
    file_name = sa.Column(sa.Text(), nullable=False)
    content_type = sa.Column(sa.Text(), nullable=False)
    size_bytes = sa.Column(sa.BigInteger(), nullable=False)
    sha256 = sa.Column(sa.Text(), nullable=False)
    uploaded_by = sa.Column(UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
    archived_at = sa.Column(TIMESTAMPTZ_T, nullable=True)

    __table_args__ = (
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        sa.CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        sa.Index("ix_training_materials_sha256", "sha256"),
        sa.Index("ix_training_materials_created", "created_at"),
    )

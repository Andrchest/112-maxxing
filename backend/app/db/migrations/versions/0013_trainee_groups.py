"""trainee_groups: instructor-managed trainee groups, the lesson's group and its weight proposals
(I3 E9a, HLD `70-i3-alignment.md` §70.3.7, HLD `20-db-schema.md` §20.2, §20.3).

Additive only (P1):

* new table `trainee_groups (id, name_ru, created_by_user_id, created_at)` with a non-empty-name
  CHECK;
* new table `trainee_group_members (group_id, user_id)`, primary key both, FK `trainee_groups`
  `ON DELETE CASCADE` and `users` `RESTRICT`, index on `user_id`;
* `lessons.group_id` (FK `trainee_groups`, `ON DELETE SET NULL`) — the group a lesson was created
  for, for the record: the lesson's own `participants` stay authoritative;
* `lessons.weight_proposals jsonb NULL` — the latest `WeightProposalSet`, never applied until the
  instructor accepts it into `scenario_plan[*].weight`.

No backfill: every existing lesson has no group and no proposals, and its weights are unchanged.

Revision ID: 0013_trainee_groups
Revises: 0012_dds_response_status
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import JSONB_T, TIMESTAMPTZ_T, UUID_T

revision: str = "0013_trainee_groups"
down_revision: str | None = "0012_dds_response_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trainee_groups",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("name_ru", sa.Text(), nullable=False),
        sa.Column(
            "created_by_user_id",
            UUID_T,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("name_ru <> ''", name="name_ru_not_empty"),
    )
    op.create_table(
        "trainee_group_members",
        sa.Column(
            "group_id",
            UUID_T,
            sa.ForeignKey("trainee_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
        ),
    )
    op.create_index("ix_trainee_group_members_user", "trainee_group_members", ["user_id"])

    op.add_column(
        "lessons",
        sa.Column(
            "group_id",
            UUID_T,
            sa.ForeignKey("trainee_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("lessons", sa.Column("weight_proposals", JSONB_T, nullable=True))


def downgrade() -> None:
    op.drop_column("lessons", "weight_proposals")
    op.drop_column("lessons", "group_id")
    op.drop_index("ix_trainee_group_members_user", table_name="trainee_group_members")
    op.drop_table("trainee_group_members")
    op.drop_table("trainee_groups")

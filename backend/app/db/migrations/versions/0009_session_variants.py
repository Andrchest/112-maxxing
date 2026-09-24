"""session variants: `simulation_sessions.variants` and `scoring_rules.applies_to_variants`
(I3 E1, HLD `70-i3-alignment.md` §70.2, §70.8, D14).

Additive only (P1). `simulation_sessions.variants jsonb NOT NULL DEFAULT '{}'` is the materialised
copy of `SESSION_CREATED.variants`, like `time_scale`; `scoring_rules.applies_to_variants jsonb
NOT NULL DEFAULT '{}'` is the rule's variant applicability, like `applies_to_roles` (`0005`).

No backfill: `'{}'` reads as the schema-1 derivation (§70.2.2) — a session created before this
migration ran exactly as that derivation says, and a rule without the key always applies.

Revision ID: 0009_session_variants
Revises: 0008_purge_audit_actor_admin
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import JSONB_T

revision: str = "0009_session_variants"
down_revision: str | None = "0008_purge_audit_actor_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "simulation_sessions",
        sa.Column("variants", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "scoring_rules",
        sa.Column(
            "applies_to_variants",
            JSONB_T,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("scoring_rules", "applies_to_variants")
    op.drop_column("simulation_sessions", "variants")

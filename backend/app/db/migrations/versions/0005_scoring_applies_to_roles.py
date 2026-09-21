"""scoring_rules: the additive `applies_to_roles` column (E15-B, HLD `10-domain-model.md` §10.14
"Applicability", `20-db-schema.md` §20.7, `30-scenario-format.md` §30.7, SPEC §28).

R7 closes the gap `prefab_handoff.py:32-37` leaves open: a `ScoringRule` may now name the
`RoleType`s it applies to (empty = always applies, the existing behaviour of every rule that
predates this column). A rule with a non-empty list is skipped — not failed, not scored zero
against a real attempt — on a session whose role chain never included any of the listed roles
(§10.14 "Applicability").

`score_results` was checked for a `CHECK (max_points > 0)`-style constraint that a not-applicable
`ScoreResult{max_points: 0}` would violate (R7's zero/zero result). None exists: only
`scoring_rules.max_points` (the *rule's own* declared points, always positive) carries that CHECK,
and it is untouched here — a not-applicable result's `max_points = 0` is a property of the
*ScoreResult* row, not of the rule it came from. `score_results` has no CHECK constraint at all in
`0001_baseline.py`, so there is nothing to relax.

Revision ID: 0005_scoring_applies_to_roles
Revises: 0004_inference_metric_status
Create Date: 2026-09-22

`revision` is 29 characters, not the fuller `0005_scoring_rule_applies_to_roles` (34): alembic
stores it in `alembic_version.version_num`, `varchar(32)`, and the longer id truncated silently
wrong (`StringDataRightTruncationError` on every DB-backed test).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import JSONB_T

revision: str = "0005_scoring_applies_to_roles"
down_revision: str | None = "0004_inference_metric_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scoring_rules",
        sa.Column(
            "applies_to_roles",
            JSONB_T,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("scoring_rules", "applies_to_roles")

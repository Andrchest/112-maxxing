"""Report release state and the LLM explanation store (E16; SPEC §29, §2; HLD D11, D6,
`20-db-schema.md` §20.3 / §20.10).

Two additions, one migration (E16 ruling R9 — the epic writes exactly one):

1. `simulation_sessions.report_released_at` / `.report_released_by_user_id` — the per-session
   runtime fact `ReportReleaseView` needs. `SessionPolicy.report_visible_to_trainee_before_release`
   (D6, `10-domain-model.md` §10.10) is a **static per-mode constant**, not state: it says whether
   a mode needs a release at all. Whether an instructor has actually released *this* session is a
   separate fact and lives here. Both columns are nullable because "not released" is the state
   every session starts in; they move together (see the CHECK).
2. `report_explanations` — the store D11's "stored separately" sentence asks for: prose generated
   from an already persisted `ScoreReport`, carrying the `score_report_checksum` it was generated
   from so a client can verify the numbers did not move (SPEC §2 — the LLM may explain, never
   compute). `UNIQUE (session_id, audience)` is what makes a second
   `generateReportExplanation` without `regenerate: true` a `409 EXPLANATION_ALREADY_EXISTS`
   rather than a duplicate row.

There is deliberately **no** foreign key from `report_explanations` to `score_results`: the
explanation references the report by *checksum*, a value, not by a row it could cascade into. The
"explanation cannot write score tables" invariant is structural (the use case is constructed with
a read-only score reader, `backend/tests/invariants/`), and this schema keeps the two apart.

Revision ID: 0006_report_release_explain
Revises: 0005_scoring_applies_to_roles
Create Date: 2026-09-22

The revision id is `0006_report_release_explain` (27 characters, under the `varchar(32)` limit of
`alembic_version.version_num` — the same trap `0005` documents); the module file was renamed to
match it (E16-D), restoring the `0001`-`0005` convention that filename == revision id.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import GEN_RANDOM_UUID, NOW, TIMESTAMPTZ_T, UUID_T

revision: str = "0006_report_release_explain"
down_revision: str | None = "0005_scoring_applies_to_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `ReportExplanation.audience` (`openapi.yaml`) — the enum is the contract's, spelled literally.
_AUDIENCES = ("TRAINEE", "INSTRUCTOR")


def upgrade() -> None:
    op.add_column(
        "simulation_sessions",
        sa.Column("report_released_at", TIMESTAMPTZ_T, nullable=True),
    )
    op.add_column(
        "simulation_sessions",
        sa.Column(
            "report_released_by_user_id",
            UUID_T,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "report_released_together",
        "simulation_sessions",
        "(report_released_at IS NULL) = (report_released_by_user_id IS NULL)",
    )

    op.create_table(
        "report_explanations",
        sa.Column(
            "id",
            UUID_T,
            primary_key=True,
            server_default=GEN_RANDOM_UUID,
        ),
        sa.Column(
            "session_id",
            UUID_T,
            sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("text_ru", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            TIMESTAMPTZ_T,
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("llm_provider", sa.Text(), nullable=False),
        sa.Column("llm_model", sa.Text(), nullable=False),
        sa.Column("score_report_checksum", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "session_id", "audience", name="uq_report_explanations_session_id_audience"
        ),
        sa.CheckConstraint(
            "audience IN (" + ", ".join(f"'{value}'" for value in _AUDIENCES) + ")",
            name="audience",
        ),
    )


def downgrade() -> None:
    op.drop_table("report_explanations")
    op.drop_constraint("report_released_together", "simulation_sessions", type_="check")
    op.drop_column("simulation_sessions", "report_released_by_user_id")
    op.drop_column("simulation_sessions", "report_released_at")

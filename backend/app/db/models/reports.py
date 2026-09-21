"""Post-session report storage (HLD `20-db-schema.md` §20.10, additive in E16; SPEC §29, §2, D11).

`report_explanations` — the LLM's optional prose about an already-computed `ScoreReport`. It is a
table of its own precisely because D11 says "stored separately, and cannot write to score tables":
nothing here references `score_results`, and the link back to the numbers is the *value*
`score_report_checksum`, echoed so a client can verify that the numbers it already holds are the
ones the prose is about (SPEC §2 — the LLM may explain, never compute).

`UNIQUE (session_id, audience)` is what makes a second `generateReportExplanation` without
`regenerate: true` a `409 EXPLANATION_ALREADY_EXISTS` rather than a second row.
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import GEN_RANDOM_UUID, NOW, TIMESTAMPTZ_T, UUID_T, Base, enum_check

#: `ReportExplanation.audience` (`openapi.yaml`) — spelled from the contract, not from a domain
#: enum: the audience is a property of the *explanation request*, not of the simulation.
EXPLANATION_AUDIENCES: tuple[str, ...] = ("TRAINEE", "INSTRUCTOR")


class ReportExplanation(Base):
    """`report_explanations` — one stored explanation per `(session, audience)` (HLD §20.10)."""

    __tablename__ = "report_explanations"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    audience = sa.Column(sa.Text(), nullable=False)
    text_ru = sa.Column(sa.Text(), nullable=False)
    generated_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
    llm_provider = sa.Column(sa.Text(), nullable=False)
    llm_model = sa.Column(sa.Text(), nullable=False)
    score_report_checksum = sa.Column(sa.Text(), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint(
            "session_id", "audience", name="uq_report_explanations_session_id_audience"
        ),
        sa.CheckConstraint(enum_check("audience", EXPLANATION_AUDIENCES), name="audience"),
    )

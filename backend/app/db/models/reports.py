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


# --- I4 E32 instructor misc (`71-i4-wave4.md` §71.9, HLD 20 §20.11.2, `0017_…`) -----------------


class ResultComment(Base):
    """`result_comments` — instructor feedback on a session or a lesson result, append-only.

    Exactly one of `session_id` / `lesson_id` is set (the migration's `exactly_one_target`
    `CHECK`). An edit is a new row whose `replaces_comment_id` points at the row it supersedes;
    nothing here is ever `UPDATE`d — the table is guarded by the same `trg_reject_mutation()`
    trigger as `audit_log` (§20.9).
    """

    __tablename__ = "result_comments"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=True
    )
    lesson_id = sa.Column(UUID_T, sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True)
    author_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    text = sa.Column(sa.Text(), nullable=False)
    replaces_comment_id = sa.Column(
        UUID_T, sa.ForeignKey("result_comments.id", ondelete="RESTRICT"), nullable=True
    )
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.CheckConstraint(
            "(session_id IS NULL) <> (lesson_id IS NULL)", name="exactly_one_target"
        ),
        sa.CheckConstraint("length(text) > 0", name="text_not_empty"),
        sa.Index(
            "ix_result_comments_session",
            "session_id",
            "created_at",
            postgresql_where=sa.text("session_id IS NOT NULL"),
        ),
        sa.Index(
            "ix_result_comments_lesson",
            "lesson_id",
            "created_at",
            postgresql_where=sa.text("lesson_id IS NOT NULL"),
        ),
    )


# --- end I4 E32 -----------------------------------------------------------------------------

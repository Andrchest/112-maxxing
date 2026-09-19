"""Scoring output (HLD `20-db-schema.md` §20.7).

`score_results`, `score_evidence` — derived, recomputable from `(scenario_versions.content,
ordered session_events)` and nothing else (D5, SPEC §28).
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import GEN_RANDOM_UUID, NOW, TIMESTAMPTZ_T, UUID_T, Base


class ScoreResult(Base):
    """`score_results` — one row per scoring rule per session (HLD §20.7)."""

    __tablename__ = "score_results"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    scenario_version_id = sa.Column(UUID_T, nullable=False)
    rule_id = sa.Column(sa.Text(), nullable=False)
    evaluator_type = sa.Column(sa.Text(), nullable=False)
    category = sa.Column(sa.Text(), nullable=False)
    points_awarded = sa.Column(sa.Numeric(8, 2), nullable=False)
    max_points = sa.Column(sa.Numeric(8, 2), nullable=False)
    passed = sa.Column(sa.Boolean(), nullable=False)
    critical_failure = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text("false"))
    computed_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["scenario_version_id", "rule_id"],
            ["scoring_rules.scenario_version_id", "scoring_rules.rule_id"],
            ondelete="RESTRICT",
            name="fk_score_results_scoring_rules",
        ),
        sa.UniqueConstraint("session_id", "rule_id", name="uq_score_results_session_rule"),
        sa.Index("ix_score_results_session_category", "session_id", "category"),
    )


class ScoreEvidence(Base):
    """`score_evidence` — exactly one reference per evidence row (HLD §20.7)."""

    __tablename__ = "score_evidence"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    score_result_id = sa.Column(
        UUID_T, sa.ForeignKey("score_results.id", ondelete="CASCADE"), nullable=False
    )
    session_event_id = sa.Column(
        UUID_T, sa.ForeignKey("session_events.id", ondelete="RESTRICT"), nullable=True
    )
    card_revision_id = sa.Column(
        UUID_T, sa.ForeignKey("incident_card_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    snapshot_id = sa.Column(
        UUID_T, sa.ForeignKey("handoff_snapshots.id", ondelete="RESTRICT"), nullable=True
    )
    seq_no = sa.Column(sa.BigInteger(), nullable=True)
    note_ru = sa.Column(sa.Text(), nullable=False)

    __table_args__ = (
        sa.Index("ix_score_evidence_result", "score_result_id"),
        sa.CheckConstraint(
            "(session_event_id IS NOT NULL)::int"
            " + (card_revision_id IS NOT NULL)::int"
            " + (snapshot_id     IS NOT NULL)::int = 1",
            name="exactly_one",
        ),
    )

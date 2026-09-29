"""ML audit history and durable automatic-work leases, separate from official scores."""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import JSONB_T, NOW, TIMESTAMPTZ_T, UUID_T, Base


class MLAuditRun(Base):
    __tablename__ = "ml_audit_runs"

    id = sa.Column(UUID_T, primary_key=True)
    session_id = sa.Column(
        UUID_T,
        sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    input_checksum = sa.Column(sa.Text(), nullable=False)
    rubric_checksum = sa.Column(sa.Text(), nullable=False)
    engine_key = sa.Column(sa.Text(), nullable=False)
    generated_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
    report = sa.Column(JSONB_T, nullable=False)
    __table_args__ = (
        sa.Index("ix_ml_audit_runs_lookup", "session_id", "input_checksum", "generated_at"),
    )


class MLAuditJob(Base):
    __tablename__ = "ml_audit_jobs"

    session_id = sa.Column(
        UUID_T,
        sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    attempts = sa.Column(sa.Integer(), nullable=False, server_default="0")
    done = sa.Column(sa.Boolean(), nullable=False, server_default=sa.false())
    lease_token = sa.Column(UUID_T, nullable=True)
    available_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
    __table_args__ = (sa.CheckConstraint("attempts >= 0", name="attempts_nonnegative"),)

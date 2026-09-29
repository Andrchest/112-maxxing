"""Separate ML audit history and restart-safe work leases.

Revision ID: 0022_ml_audit
Revises: 0021_login_throttled_audit_action
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_ml_audit"
down_revision = "0021_login_throttled_audit_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ml_audit_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("input_checksum", sa.Text(), nullable=False),
        sa.Column("rubric_checksum", sa.Text(), nullable=False),
        sa.Column("engine_key", sa.Text(), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("report", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_ml_audit_runs_lookup", "ml_audit_runs", ["session_id", "input_checksum", "generated_at"]
    )
    op.create_table(
        "ml_audit_jobs",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
    )


def downgrade() -> None:
    op.drop_table("ml_audit_jobs")
    op.drop_index("ix_ml_audit_runs_lookup", table_name="ml_audit_runs")
    op.drop_table("ml_audit_runs")

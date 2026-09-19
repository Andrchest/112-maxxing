"""session time_scale: simulation_sessions.time_scale numeric(4,2) NOT NULL DEFAULT 1

Additive (E5). `openapi.yaml`'s `SessionCreateRequest` and `SessionDetail` both make `time_scale`
part of a session and `SimulationSession` carries it, so `simulation_sessions` is its home; the
baseline table of `20-db-schema.md` §20.3 predates that and has no column for it.

`numeric(4, 2)` rather than a float: the API schema's `minimum: 0.1` / `maximum: 10` are decimal
steps and must round-trip exactly. The CHECK is that range, literally.

Revision ID: 0002_session_time_scale
Revises: 0001_baseline
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_session_time_scale"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "simulation_sessions",
        sa.Column("time_scale", sa.Numeric(4, 2), nullable=False, server_default=sa.text("1")),
    )
    # Spelled out rather than `op.create_check_constraint(...)`: the constraint name must be the
    # one `app.db.base.NAMING_CONVENTION` renders for the model's `name="time_scale"`, and the
    # operation object does not carry that convention.
    op.execute(
        "ALTER TABLE simulation_sessions ADD CONSTRAINT ck_simulation_sessions_time_scale"
        " CHECK (time_scale >= 0.1 AND time_scale <= 10)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE simulation_sessions"
        " DROP CONSTRAINT IF EXISTS ck_simulation_sessions_time_scale"
    )
    op.drop_column("simulation_sessions", "time_scale")

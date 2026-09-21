"""world_engine_states: the world event engine's per-incident bookkeeping

Additive (E6, D3, D7). The pure engine of `app.domain.world` carries state that is neither a fact
about the world nor a fact about the caller — occurrence counters, `last_fired_ms`, queued
`ScheduledTrigger`s, emotion-rule application counts, reached stage states and how far simulated
time has been advanced. D3 forbids merging that into `incident_world_states` (world truth holds
facts only), so it gets its own 1:1 satellite of `incidents`.

`EventIndex` is deliberately not a column: it is a pure fold of the session's own action events
(§10.11 determinism rule 1) and is rebuilt from `session_events` on load, so the event log stays
the single source of what happened (D5). `last_folded_seq_no` is the boundary between "already
folded" and "a `PendingAction` for the next tick".

Revision ID: 0003_world_engine_state
Revises: 0002_session_time_scale
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import JSONB_T, TIMESTAMPTZ_T, UUID_T

revision: str = "0003_world_engine_state"
down_revision: str | None = "0002_session_time_scale"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "world_engine_states",
        sa.Column("incident_id", UUID_T, nullable=False),
        sa.Column("last_tick_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "last_folded_seq_no", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("bookkeeping", JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", TIMESTAMPTZ_T, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("incident_id", name="pk_world_engine_states"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
            name="fk_world_engine_states_incident_id_incidents",
        ),
    )


def downgrade() -> None:
    op.drop_table("world_engine_states")

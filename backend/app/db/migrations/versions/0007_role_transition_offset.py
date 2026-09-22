"""The open role transition's start offset (E17 ruling R1; HLD `20-db-schema.md` §20.3, D7).

`20-db-schema.md` says `"started_at" + "paused_total_ms" is what sim time is recomputed from after
a restart (D7, §42 test 13)`, but until E17 nothing ever wrote `paused_total_ms`: the hand-over
pause between two role stages counted as elapsed simulated time. Ruling R1 gave the column its one
writer — `finish_role_transition` adds the wall-clock length of the `ROLE_TRANSITION` interval —
and froze the simulated clock for the duration of that interval.

Freezing needs one fact the session row did not carry: **the offset the open transition began
at**. It is in the log too (`ROLE_TRANSITION_STARTED.monotonic_offset_ms`), but a sim-time read
happens on every tick and every trainee command, and none of those should have to scan the log to
learn what time it is. Hence one nullable integer column, `NULL` exactly when no transition is
open. No new table and no new API: the pause intervals themselves stay derivable from
`ROLE_TRANSITION_STARTED` / `ROLE_TRANSITION_COMPLETED`, and there is no `pauseSession` operation
in `openapi.yaml` to add one for.

An *offset* rather than a `role_transition_started_at` wall stamp, because the two are the same
instant — `started_at + paused_total_ms + role_transition_started_offset_ms` — and the offset form
keeps the domain aggregate clock-free.

Existing rows get `NULL`, which is correct for every one of them: a session parked in
`ROLE_TRANSITION` across this migration falls back to its own `ROLE_TRANSITION_STARTED` offset
(`SimulationSession.finish_role_transition` reads `GuardRuntime.transition_started_ms` when the
column is `NULL`), so no session is stranded.

Revision ID: 0007_role_transition_offset
Revises: 0006_report_release_explain
Create Date: 2026-09-22

The revision id is `0007_role_transition_offset` (26 characters, under the `varchar(32)` limit of
`alembic_version.version_num`), and the module file is named after it — the `0001`-`0006`
convention.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_role_transition_offset"
down_revision: str | None = "0006_report_release_explain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "simulation_sessions",
        sa.Column("role_transition_started_offset_ms", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "role_transition_offset_non_negative",
        "simulation_sessions",
        "role_transition_started_offset_ms IS NULL OR role_transition_started_offset_ms >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("role_transition_offset_non_negative", "simulation_sessions", type_="check")
    op.drop_column("simulation_sessions", "role_transition_started_offset_ms")

"""inference_metrics: the status and error_kind of `InferenceMetric` (E12)

`50-voice-pipeline.md` §2.6 defines `InferenceMetric` with `status` ("OK" | "TIMEOUT" | "ERROR" |
"CANCELLED") and `error_kind`, and says in the same code block: "Persisted to `inference_metrics`;
column names are the field names." `20-db-schema.md` §20.6 predates that type — its column list
says "Columns are exactly SPEC §27", and SPEC §27 enumerates latency fields only — so the two
columns the port has always carried had no home.

Without them a failed or cancelled model call is indistinguishable from a successful one in the
telemetry table, which makes SPEC §42 item 14 ("a model failure does not erase simulation data")
unobservable in the place operators would look for it: the `MODEL_ERROR` event says *that* a call
failed, and this row says how long it took to fail and which stage it was. Both columns are
nullable-or-defaulted, so every existing row keeps its meaning: an already-written metric is one
that was recorded, i.e. `OK`.

Revision ID: 0004_inference_metric_status
Revises: 0003_world_engine_state
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import enum_check
from app.db.models.events import METRIC_STATUSES

revision: str = "0004_inference_metric_status"
down_revision: str | None = "0003_world_engine_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inference_metrics",
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'OK'")),
    )
    op.add_column("inference_metrics", sa.Column("error_kind", sa.Text(), nullable=True))
    op.create_check_constraint(
        "status", "inference_metrics", sa.text(enum_check("status", METRIC_STATUSES))
    )


def downgrade() -> None:
    # The name is the *convention's* argument, not the generated identifier: `alembic.ini`'s
    # naming convention expands it to `ck_inference_metrics_status`, and passing the expanded
    # form here would make it expand a second time.
    op.drop_constraint("status", "inference_metrics", type_="check")
    op.drop_column("inference_metrics", "error_kind")
    op.drop_column("inference_metrics", "status")

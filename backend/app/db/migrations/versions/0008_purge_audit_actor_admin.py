"""recording_purge_audit.actor_type gains ADMIN (E20-E R11).

`purgeRecordings` (`POST /api/v1/admin/recordings/purge`) is ADMIN-only (`routers/admin.py`'s
`AdminDep`), but `recording_purge_audit.actor_type`'s `CHECK` constraint was built from the
domain-wide `ActorType` (`TRAINEE|INSTRUCTOR|SIMULATION|MODEL|SYSTEM`, `app.domain.enums`), which
has no `ADMIN` member — `app.application.recording.purge_recordings.PurgeRecordings` folded every
authenticated caller into `INSTRUCTOR` as a result (see that module's own former "HLD gap"
docstring, fixed alongside this migration).

This migration widens the column's own `CHECK` to `RECORDING_PURGE_ACTOR_TYPES`
(`app.db.models.events`) — `ActorType` plus `ADMIN` — without touching `ActorType` itself or any
other table's `actor_type` column: D5's actor model everywhere else is unchanged, only this one
audit row's own domain grows. No existing row's value changes: every one written so far is
`SYSTEM` or `INSTRUCTOR`, both still members of the widened set.

Revision ID: 0008_purge_audit_actor_admin
Revises: 0007_role_transition_offset
Create Date: 2026-09-22

The revision id is `0008_purge_audit_actor_admin` (29 characters, under the `varchar(32)` limit of
`alembic_version.version_num`), and the module file is named after it — the `0001`-`0007`
convention.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import enum_check
from app.db.models.events import RECORDING_PURGE_ACTOR_TYPES
from app.domain.enums import ActorType

revision: str = "0008_purge_audit_actor_admin"
down_revision: str | None = "0007_role_transition_offset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The name is the convention's argument, not the generated identifier: `alembic.ini`'s naming
    # convention expands it to `ck_recording_purge_audit_actor_type`, and passing the expanded
    # form here would make it expand a second time (same note as `0004`'s `downgrade`).
    op.drop_constraint("actor_type", "recording_purge_audit", type_="check")
    op.create_check_constraint(
        "actor_type",
        "recording_purge_audit",
        sa.text(enum_check("actor_type", RECORDING_PURGE_ACTOR_TYPES)),
    )


def downgrade() -> None:
    op.drop_constraint("actor_type", "recording_purge_audit", type_="check")
    op.create_check_constraint(
        "actor_type",
        "recording_purge_audit",
        sa.text(enum_check("actor_type", ActorType)),
    )

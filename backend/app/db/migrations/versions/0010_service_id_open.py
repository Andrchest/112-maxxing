"""service id open: `dds_assignments.service_type` is a catalog id, not one of six enum members
(I3 E2a, HLD `70-i3-alignment.md` §70.6.3, §70.8, D18).

A dropped CHECK (P1): `CHECK (service_type IN ('FIRE_RESCUE', …six…))` becomes
`CHECK (service_type <> '')`, under the same constraint name. No data moves — the six legacy ids are
the first six entries of the service catalog (`reference/services/v1.yaml`), so every existing row
is already a valid catalog id.

`downgrade()` restores the six-member CHECK; it fails, by design, if a leg for any other catalog
service has been stored since.

Revision ID: 0010_service_id_open
Revises: 0009_session_variants
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import enum_check

revision: str = "0010_service_id_open"
down_revision: str | None = "0009_session_variants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The convention's argument, not the generated identifier: the naming convention expands it to
# `ck_dds_assignments_service_type` (same note as `0004`/`0008`).
_CONSTRAINT = "service_type"

# The six-member CHECK `downgrade()` restores, inlined (a migration never imports an app constant
# a later epic may change) — the same list as `0001_baseline`.
_LEGACY_SERVICE_TYPES: tuple[str, ...] = (
    "FIRE_RESCUE",
    "POLICE",
    "AMBULANCE",
    "GAS_SERVICE",
    "UTILITY_EMERGENCY",
    "EDDS",
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "dds_assignments", type_="check")
    op.create_check_constraint(_CONSTRAINT, "dds_assignments", sa.text("service_type <> ''"))


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "dds_assignments", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "dds_assignments",
        sa.text(enum_check("service_type", _LEGACY_SERVICE_TYPES)),
    )

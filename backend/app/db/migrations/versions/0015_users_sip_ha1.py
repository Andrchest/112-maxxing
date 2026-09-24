"""users.sip_ha1: an optional per-user SIP Digest HA1 (I3 E6e, HLD `80-telephony.md` §80.7, D22).

Additive only (P1): one nullable column and one CHECK on `users`,

* `users.sip_ha1 text NULL` — `MD5(username:realm:password)` in lowercase hex, set by the admin
  command `python -m app.tools.set_sip_password`; `NULL` ⇒ the deployment SIP password
  (`SIM_SIP_PASSWORD`) applies to that user, exactly as before E6e;
* `CHECK (sip_ha1 IS NULL OR sip_ha1 ~ '^[0-9a-f]{32}$')`.

No backfill: every existing account keeps `NULL`, i.e. the deployment password. The HA1 is bound to
`SIM_SIP_REALM`: a realm change invalidates every stored value (the RUNBOOK says so). The column is
a credential digest — it is never logged, never rendered by a user view, and only
`GET /api/v1/telephony/sip-credentials/{username}` (the gateway's service credential) returns it.

Revision ID: 0015_users_sip_ha1
Revises: 0014_dds_calls
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_users_sip_ha1"
down_revision: str | None = "0014_dds_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"
_CHECK = "sip_ha1_hex"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("sip_ha1", sa.Text(), nullable=True))
    op.create_check_constraint(_CHECK, _TABLE, "sip_ha1 IS NULL OR sip_ha1 ~ '^[0-9a-f]{32}$'")


def downgrade() -> None:
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, "sip_ha1")

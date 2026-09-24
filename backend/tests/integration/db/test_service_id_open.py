"""Migration `0010_service_id_open` (I3 E2a; HLD `70-i3-alignment.md` §70.6.3, §70.8, D18).

`dds_assignments.service_type` is a service-catalog id now: the six-member CHECK is gone and
`CHECK (service_type <> '')` took its name, so a leg for any catalog service can be stored while
the empty string still cannot.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_the_service_type_check_only_refuses_the_empty_string(
    db_session: AsyncSession,
) -> None:
    definition = (
        await db_session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = 'ck_dds_assignments_service_type'"
            )
        )
    ).scalar_one()
    assert "<> ''" in definition
    assert "FIRE_RESCUE" not in definition

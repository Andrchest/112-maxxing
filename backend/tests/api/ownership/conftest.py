"""Fixtures for the I5 E39 ownership tests — the report package's full 112 -> DDS chain (for the
operations that need a `COMPLETED` or `ROLE_TRANSITION` session), plus a second instructor.

The chain fixtures are re-bound by name exactly as `tests/api/reports/conftest.py` binds them
(`pytest_plugins` cannot register a module already loaded as a real conftest).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.application.ports.user_repository import UserRole
from app.application.testing.fakes import FakePasswordHasher
from app.domain.common.ids import UserId

from tests.api.reports import conftest as _reports_fixtures

pytestmark = pytest.mark.integration

#: Test-only credentials of the second instructor — never a source default.
INSTRUCTOR2 = "instructor2"
INSTRUCTOR2_PASSWORD = "instructor-two-pw"

# -- the chain, re-bound from the report package -------------------------------------------------
api_settings = _reports_fixtures.api_settings
_api_settings_base = _reports_fixtures._api_settings_base
flow = _reports_fixtures.flow
ringing = _reports_fixtures.ringing
connected = _reports_fixtures.connected
interview = _reports_fixtures.interview
uow_factory = _reports_fixtures.uow_factory
clock = _reports_fixtures.clock
container = _reports_fixtures.container
idempotency = _reports_fixtures.idempotency
prepared = _reports_fixtures.prepared
handed_off = _reports_fixtures.handed_off
in_transition = _reports_fixtures.in_transition
dds_active = _reports_fixtures.dds_active
resolved = _reports_fixtures.resolved
completed = _reports_fixtures.completed


@pytest.fixture
async def instructor2(
    client: httpx.AsyncClient, unit_of_work: Any, hasher: FakePasswordHasher
) -> tuple[UserId, str]:
    """A second INSTRUCTOR account and its bearer token: the "other instructor" of every test."""
    async with unit_of_work() as uow:
        stored = await uow.users.upsert(
            user_id=UserId(uuid4()),
            username=INSTRUCTOR2,
            display_name_ru="Инструктор 2",
            user_role=UserRole.INSTRUCTOR,
            password_hash=hasher.hash(INSTRUCTOR2_PASSWORD),
            is_active=True,
        )
        await uow.commit()
    response = await client.post(
        "/api/v1/auth/login", json={"username": INSTRUCTOR2, "password": INSTRUCTOR2_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return stored.user_id, str(response.json()["access_token"])

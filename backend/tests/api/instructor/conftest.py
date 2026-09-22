"""Fixtures for the instructor API tests (E17-A) — the whole 112 -> DDS chain, re-exported.

`tests.api.reports.conftest` already assembles every state the chain passes through (`flow`
`ACTIVE`/`OPERATOR_112`, `in_transition` `ROLE_TRANSITION`, `dds_active` `ACTIVE`/`DDS`,
`resolved`, `completed` `COMPLETED`) and this package needs no state the report tests do not
already build, so the whole chain is bound here by name exactly as `tests/api/reports/conftest.py`
does from `tests/api/dds`, `tests/api/handoff` and `tests/api/operator` — `pytest_plugins` cannot
register a module that is already loaded as a real conftest.

This package's own addition is `overview()`, the one HTTP call `getInstructorSessionOverview`
tests need, plus `created_session_id`: a `READY` session with nobody started yet, which is the
one state the report chain never stops at (the report needs `COMPLETED`; the overview does not).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.domain.common.ids import UserId

from tests.api import conftest as _api_fixtures
from tests.api.reports import conftest as _reports_fixtures

pytestmark = pytest.mark.integration

OperatorFlow = _reports_fixtures.OperatorFlow

# -- the API base (real Postgres, real Redis, the production container) ------------------------
client = _api_fixtures.client
clean_database = _api_fixtures.clean_database
tokens = _api_fixtures.tokens
users = _api_fixtures.users
hasher = _api_fixtures.hasher
inference = _api_fixtures.inference
publisher = _api_fixtures.publisher
redis_client = _api_fixtures.redis_client
demo_version_id = _api_fixtures.demo_version_id
unit_of_work = _api_fixtures.unit_of_work
auth = _api_fixtures.auth

# -- the whole chain, every state it passes through ----------------------------------------------
api_settings = _reports_fixtures.api_settings
_api_settings_base = _reports_fixtures._api_settings_base
uow_factory = _reports_fixtures.uow_factory
clock = _reports_fixtures.clock
container = _reports_fixtures.container
idempotency = _reports_fixtures.idempotency
flow = _reports_fixtures.flow
ringing = _reports_fixtures.ringing
connected = _reports_fixtures.connected
interview = _reports_fixtures.interview
prepared = _reports_fixtures.prepared
handed_off = _reports_fixtures.handed_off
in_transition = _reports_fixtures.in_transition
dds_active = _reports_fixtures.dds_active
resolved = _reports_fixtures.resolved
completed = _reports_fixtures.completed


async def overview(flow: OperatorFlow, *, token: str | None = None) -> httpx.Response:
    """`getInstructorSessionOverview` as the instructor unless another token is given."""
    return await flow.client.get(
        f"/api/v1/instructor/sessions/{flow.session_id}/overview",
        headers=auth(token or flow.instructor_token),
    )


async def created_session_id(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: Any,
) -> str:
    """A session `createSession` just produced — `READY`, nobody started, no stages live yet."""
    created = await _api_fixtures.create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [
            _api_fixtures.participant(users["trainee1"], "OPERATOR_112"),
            _api_fixtures.participant(users["trainee2"], "DDS"),
        ],
        session_mode="MULTI_TRAINEE",
    )
    assert created["state"] == "READY"
    return str(created["id"])

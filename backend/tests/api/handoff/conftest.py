"""Fixtures for the handoff / role-transition API tests (E9) — real HTTP, a movable clock.

Two things these tests need that `tests/api/operator/conftest.py` does not provide.

**A clock a test can move.** `continueToNextStage`'s guard is
`now_ms >= transition_started_ms + policy.transition_pause_seconds * 1000`, and
`MULTI_TRAINEE`'s pause is ten seconds (§10.10). A suite that waited for it would take ten
seconds per test and would still be racing the wall clock, so the container here is built on a
`FakeClock` — the same instance the Unit of Work stamps events with — and a test advances it
explicitly. That also makes the *negative* case exact: calling before the pause elapses is
`409 INVALID_TRANSITION` because the pause has genuinely not elapsed, not because the test was
quick.

**A DDS-only scenario.** The committed demo's `role_chain` is `[OPERATOR_112, DDS]`, and D6's
prefab handoff only applies to a chain that *starts* at DDS. `dds_only_version_id` writes a
mutated demo document straight through the repository, exactly as
`tests/integration/sessions/conftest.py`'s `raw_version` does, so the prefab path can be driven
over real HTTP.

Everything else — the migrated database, real Redis, the five accounts, the ASGI client and the
`OperatorFlow` helper with its `advance_call_flow` / `append_asr` levers — is re-exported from
the two conftests above, by name rather than through `pytest_plugins` (which cannot register a
module already loaded as a real conftest).
"""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from app.api.container import Container
from app.application.scenarios.import_scenarios import canonical_content, content_digest
from app.application.testing.fakes import (
    FakeClock,
    FakeInferenceReadiness,
    FakePasswordHasher,
    InMemoryEventPublisher,
    InMemoryIdempotencyStore,
)
from app.config.settings import Settings
from app.db.session import create_session_factory
from app.domain.common.ids import ScenarioId, ScenarioVersionId, UserId
from app.domain.scenario.version import ScenarioVersion
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork, unit_of_work_factory
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth, create_demo_session, participant
from tests.api.operator import conftest as _operator_fixtures
from tests.fixtures.scenarios import demo_document

pytestmark = pytest.mark.integration

OperatorFlow = _operator_fixtures.OperatorFlow

idempotency = _operator_fixtures.idempotency
flow = _operator_fixtures.flow
ringing = _operator_fixtures.ringing
connected = _operator_fixtures.connected
interview = _operator_fixtures.interview
uow_factory = _operator_fixtures.uow_factory


@pytest.fixture(scope="package", autouse=True)
async def _remove_this_packages_scenarios(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """Leave the scenario catalog without this package's extra rows in it.

    `scenarios` is reference data that survives the per-test `TRUNCATE simulation_sessions
    CASCADE` (`tests/api/conftest.py`), and `tests/api/test_scenarios.py` asserts on the size of
    the *whole* catalog — so the three `role_chain` variants written here have to go. The whole
    table is truncated rather than the three slugs deleted, exactly as `isolated_scenario_catalog`
    does and for the same reason: `demo_version_id` is self-healing, so the next test that wants
    the demo scenario re-imports it without noticing, while a targeted `DELETE` would have to
    know every table that references a `scenario_versions` row.

    Package scope makes this run right after the last test here, by which time the
    function-scoped `clean_database` has already removed every session referencing a version.
    """
    yield
    async with migrated_engine.begin() as connection:
        await connection.execute(sa.text("TRUNCATE TABLE scenarios RESTART IDENTITY CASCADE"))


@pytest.fixture
def clock() -> FakeClock:
    """The one clock the container and its Unit of Work share; tests move it by hand."""
    return FakeClock()


@pytest.fixture
def container(
    api_settings: Settings,
    migrated_engine: AsyncEngine,
    redis_client: Redis,
    publisher: InMemoryEventPublisher,
    hasher: FakePasswordHasher,
    inference: FakeInferenceReadiness,
    idempotency: InMemoryIdempotencyStore,
    clock: FakeClock,
) -> Container:
    """`tests.api.operator.conftest.container` with the movable clock (see the module docstring)."""
    session_factory = create_session_factory(migrated_engine)
    return Container(
        api_settings,
        engine=migrated_engine,
        session_factory=session_factory,
        redis=redis_client,
        publisher=publisher,
        clock=clock,
        unit_of_work=unit_of_work_factory(session_factory, clock, publisher),
        hasher=hasher,
        inference=inference,
        idempotency=idempotency,
        owns_engine=False,
        owns_redis=False,
    )


# ---------------------------------------------------------------------------------------------
# The 112 stage, driven to the point each test starts from
# ---------------------------------------------------------------------------------------------

#: What the demo operator types, and what they get wrong. Three deliberate imperfections, each
#: load-bearing for an assertion somewhere in this package or in INV 3:
#:
#: * `address.house` is the CALLER's "72" — world truth says "27" (SPEC §3);
#: * `address.floor` is never sent at all, so an omitted *optional* fact stays omitted;
#: * `caller.phone` is never sent either, and it **is** `required_for_handoff`, so
#:   `missing_field_paths` has something real to name (SPEC §10: "the omission propagates").
CARD_ENTRIES: tuple[tuple[str, Any], ...] = (
    ("incident.type", "FIRE"),
    ("address.locality", "Смоленск"),
    ("address.street", "улица Николаева"),
    ("address.house", "72"),
    ("description.text", "Горит квартира, сильный дым"),
    ("flags.threat_to_life", True),
)


async def fill_card(flow: OperatorFlow) -> None:
    """Type the card the demo operator types — the caller's house number, and no floor."""
    for field_path, value in CARD_ENTRIES:
        response = await flow.set_field(field_path, value)
        assert response.status_code == 200, response.text


async def prepare_handoff(flow: OperatorFlow, *services: str) -> None:
    """Select the recipient services and open the handoff-preparation screen."""
    for service in services:
        response = await flow.select(service)
        assert response.status_code == 200, response.text
    response = await flow.post("/operator/handoff/prepare")
    assert response.status_code == 200, response.text


@pytest.fixture
async def prepared(interview: OperatorFlow) -> OperatorFlow:
    """`interview`, with the card filled, FIRE_RESCUE + AMBULANCE selected, stage
    `HANDOFF_PREPARATION`."""
    await fill_card(interview)
    await prepare_handoff(interview, "FIRE_RESCUE", "AMBULANCE")
    return interview


@pytest.fixture
async def handed_off(prepared: OperatorFlow) -> OperatorFlow:
    """`prepared`, with `createHandoff` done — stage `HANDED_OFF`, two assignment legs."""
    response = await prepared.post("/operator/handoff", json={})
    assert response.status_code == 201, response.text
    return prepared


@pytest.fixture
async def in_transition(handed_off: OperatorFlow) -> OperatorFlow:
    """`handed_off`, with the call ended and the 112 stage completed — `ROLE_TRANSITION`."""
    ended = await handed_off.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    assert ended.status_code == 200, ended.text
    completed = await handed_off.post("/operator/stage/complete")
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "ROLE_TRANSITION"
    return handed_off


@pytest.fixture
async def dds_active(in_transition: OperatorFlow, clock: FakeClock) -> OperatorFlow:
    """`in_transition`, with the pause elapsed and `continueToNextStage` fired — DDS is live."""
    clock.advance_ms(11_000)
    response = await in_transition.post("/stage/continue", token=in_transition.dds_token)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "ACTIVE"
    return in_transition


# ---------------------------------------------------------------------------------------------
# A DDS-only scenario, for the prefab handoff (D6)
# ---------------------------------------------------------------------------------------------


async def raw_role_chain_version(
    unit_of_work: Any, slug: str, role_chain: list[str]
) -> ScenarioVersionId:
    """Insert the demo document with a different `role_chain`, straight through the repository.

    The same shape as `tests/integration/sessions/conftest.py`'s `raw_version`, and **self-healing
    for the same reason `demo_version_id` is**: `scenarios` is reference data that survives the
    per-test `TRUNCATE simulation_sessions CASCADE`, so a second test asking for the same slug
    must get the row the first one wrote rather than a unique-constraint violation.
    """
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(slug)
        version_row = (
            await uow.scenarios.find_version(stored.scenario_id, 1) if stored is not None else None
        )
        await uow.commit()
    if version_row is not None:
        return version_row.scenario_version_id

    document: dict[str, Any] = copy.deepcopy(demo_document())
    document["id"] = str(uuid4())
    document["scenario_id"] = str(uuid4())
    document["role_chain"] = role_chain

    version = ScenarioVersion(**document)
    content = canonical_content(version)
    async with unit_of_work() as uow:
        await uow.scenarios.add_scenario(
            ScenarioId(UUID(document["scenario_id"])), slug, version.title
        )
        await uow.scenarios.add_version(version, content, content_digest(content))
        # `ImportScenarios` always pairs `add_version` with this (§20.2): without it,
        # `score_results` (epic E15-B) has no `scoring_rules` row to satisfy its
        # `(scenario_version_id, rule_id)` FK, even though the version's own `content` still
        # carries the ten demo rules `score()` reads from.
        await uow.scenarios.add_scoring_rules(version.id, version.scoring_rules)
        await uow.commit()
    return version.id


@pytest.fixture
async def dds_only_version_id(unit_of_work: Any) -> ScenarioVersionId:
    """The demo document with `role_chain: [DDS]` — the chain D6's prefab handoff exists for."""
    return await raw_role_chain_version(unit_of_work, "dds-only-prefab", ["DDS"])


@pytest.fixture
async def dds_only_session(
    client: Any,
    tokens: dict[str, str],
    users: dict[str, UserId],
    dds_only_version_id: ScenarioVersionId,
) -> UUID:
    """A started `SINGLE_ROLE` session on the DDS-only scenario, played by `trainee2`."""
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        dds_only_version_id,
        [participant(users["trainee2"], "DDS")],
        session_mode="SINGLE_ROLE",
    )
    session_id = UUID(detail["id"])
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    return session_id


async def read_assignments(uow_factory: Any, session_id: UUID) -> list[dict[str, Any]]:
    """The session's `dds_assignments` rows, oldest first — the legs, straight from the table."""
    async with uow_factory() as uow:
        assert isinstance(uow, SqlAlchemyUnitOfWork)
        result = await uow.session.execute(
            sa.text(
                "SELECT a.* FROM dds_assignments a JOIN role_stages s ON s.id = a.role_stage_id"
                " WHERE s.session_id = :session_id ORDER BY a.received_at_offset_ms, a.id"
            ),
            {"session_id": session_id},
        )
        rows = [dict(row._mapping) for row in result.all()]
        await uow.commit()
    return rows

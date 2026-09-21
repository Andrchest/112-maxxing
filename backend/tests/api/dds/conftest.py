"""Fixtures for the DDS API tests (E9-B) — real HTTP, a real database, a movable clock.

Everything up to "the DDS stage is live" already exists: `tests/api/handoff/conftest.py` drives
the 112 stage over real HTTP (card filled with the caller's "72", `FIRE_RESCUE` + `AMBULANCE`
selected, handoff created, call ended, stage completed, role transition finished), and its
`FakeClock` container is what makes a four-hundred-second incident testable in milliseconds.
This module re-exports that chain by name and adds the DDS-side levers on top.

Two things the helpers below exist for:

* **the board has no fixed ids.** `emergency_resources.id` is generated per session, so a test
  names a unit by its callsign — "АЦ-1", "СМП-11" — exactly as the console does, and
  `resource_id` resolves it through `listDdsResources`;
* **simulated time is the test's to spend.** `at(flow, clock, ms)` puts the clock at an absolute
  session offset and ticks once, which is how the suite walks units `DISPATCHED -> EN_ROUTE ->
  ON_SCENE -> WORKING` without sleeping. The tick comes from `runner.tick_now`, the same call
  every command endpoint makes, so the `after_tick` hooks — including the DDS stage automation —
  run exactly as they do in production.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import SessionId
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.handoff import conftest as _handoff_fixtures

pytestmark = pytest.mark.integration

OperatorFlow = _handoff_fixtures.OperatorFlow

# The 112 half, verbatim from the handoff package: session -> ringing -> interview -> handoff ->
# transition -> the DDS stage is `ACTIVE` and in `RECEIVED`.
clock = _handoff_fixtures.clock
container = _handoff_fixtures.container
idempotency = _handoff_fixtures.idempotency
flow = _handoff_fixtures.flow
ringing = _handoff_fixtures.ringing
connected = _handoff_fixtures.connected
interview = _handoff_fixtures.interview
prepared = _handoff_fixtures.prepared
handed_off = _handoff_fixtures.handed_off
in_transition = _handoff_fixtures.in_transition
dds_active = _handoff_fixtures.dds_active
uow_factory = _handoff_fixtures.uow_factory
dds_only_version_id = _handoff_fixtures.dds_only_version_id
dds_only_session = _handoff_fixtures.dds_only_session

_remove_this_packages_scenarios = _handoff_fixtures._remove_this_packages_scenarios

#: When `dds_active` hands the session over, in session-offset milliseconds. The chain advances
#: the `FakeClock` by 11 s to let `MULTI_TRAINEE`'s ten-second transition pause elapse.
HANDOVER_MS = 11_000


# ---------------------------------------------------------------------------------------------
# DDS calls
# ---------------------------------------------------------------------------------------------


async def dds_post(flow: OperatorFlow, suffix: str, json: Any = None) -> httpx.Response:
    """POST as the DDS trainee."""
    return await flow.post(suffix, token=flow.dds_token, json=json)


async def dds_get(flow: OperatorFlow, suffix: str, params: Any = None) -> httpx.Response:
    """GET as the DDS trainee."""
    return await flow.get(suffix, token=flow.dds_token, params=params)


async def acknowledge(flow: OperatorFlow) -> dict[str, Any]:
    """`acknowledgeDdsAssignment`, asserting it worked."""
    response = await dds_post(flow, "/dds/acknowledge")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def open_selection(flow: OperatorFlow) -> dict[str, Any]:
    """`openDdsResourceSelection` (additive, E9)."""
    response = await dds_post(flow, "/dds/resources/selection/open")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def board(flow: OperatorFlow, **params: Any) -> list[dict[str, Any]]:
    """`listDdsResources`, as the console reads it."""
    response = await dds_get(flow, "/dds/resources", params=params or None)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def resource_id(flow: OperatorFlow, callsign: str) -> str:
    """The session-local id of the unit with this callsign (unique per scenario, §30 rule 15)."""
    for item in await board(flow):
        if item["callsign"] == callsign:
            return str(item["resource_id"])
    raise AssertionError(f"no resource {callsign!r} on the board")


async def select(flow: OperatorFlow, callsign: str) -> httpx.Response:
    """`selectDdsResource` by callsign."""
    return await dds_post(
        flow, "/dds/resources/select", {"resource_id": await resource_id(flow, callsign)}
    )


async def deselect(flow: OperatorFlow, callsign: str) -> httpx.Response:
    """`deselectDdsResource` by callsign."""
    return await dds_post(
        flow, "/dds/resources/deselect", {"resource_id": await resource_id(flow, callsign)}
    )


async def dispatch(flow: OperatorFlow, note_ru: str | None = None) -> dict[str, Any]:
    """`dispatchDdsResources`, asserting it worked."""
    response = await dds_post(flow, "/dds/resources/dispatch", {"note_ru": note_ru})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def work_item(flow: OperatorFlow) -> dict[str, Any]:
    """`getDdsWorkItem`."""
    response = await dds_get(flow, "/dds/work-item")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def notifications(flow: OperatorFlow, **params: Any) -> list[dict[str, Any]]:
    """`listNotifications` as the DDS trainee."""
    response = await dds_get(flow, "/dds/notifications", params=params or None)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def event_types(flow: OperatorFlow, token: str | None = None) -> list[str]:
    """Every event of the session, in `seq_no` order, as the instructor sees them."""
    response = await flow.get(
        "/events", token=token or flow.instructor_token, params={"limit": 1000}
    )
    assert response.status_code == 200, response.text
    return [item["event_type"] for item in response.json()["items"]]


async def events_of(flow: OperatorFlow, event_type: str) -> list[dict[str, Any]]:
    """Every event of one type, with its payload, as the instructor sees them."""
    response = await flow.get("/events", token=flow.instructor_token, params={"limit": 1000})
    assert response.status_code == 200, response.text
    return [item for item in response.json()["items"] if item["event_type"] == event_type]


# ---------------------------------------------------------------------------------------------
# Simulated time
# ---------------------------------------------------------------------------------------------


async def session_offset_ms(flow: OperatorFlow) -> int:
    """Where the session clock stands right now, in session-offset milliseconds (SPEC §39).

    `SessionDetail.monotonic_offset_ms` is the server's own answer to that question, derived from
    persisted state, so a test never has to reconstruct it from the `FakeClock`'s internals.
    """
    response = await flow.get("", token=flow.instructor_token)
    assert response.status_code == 200, response.text
    return int(response.json()["monotonic_offset_ms"])


async def at(flow: OperatorFlow, clock: FakeClock, offset_ms: int) -> None:
    """Put the session clock at `offset_ms` and tick once, `after_tick` hooks included.

    Absolute rather than relative on purpose: a test then reads as the timeline it is asserting on
    ("at 190 s the reinforcement goes out"), and the ETA arithmetic of the demo scenario is all in
    absolute session offsets. The tick is `runner.tick_now`, the very call every command endpoint
    makes, so the DDS stage automation runs here exactly as it does in production.
    """
    current = await session_offset_ms(flow)
    assert offset_ms >= current, f"the clock cannot go back from {current} ms to {offset_ms} ms"
    clock.advance_ms(offset_ms - current)
    await flow.container.runner.tick_now(SessionId(flow.session_id))


# ---------------------------------------------------------------------------------------------
# Raw rows, for the columns no endpoint exposes
# ---------------------------------------------------------------------------------------------


async def assignment_rows(uow_factory: Any, session_id: UUID) -> list[dict[str, Any]]:
    """The session's `dds_assignments` legs, oldest first."""
    return await _handoff_fixtures.read_assignments(uow_factory, session_id)


async def state_change_rows(uow_factory: Any, session_id: UUID) -> list[dict[str, Any]]:
    """`resource_state_changes` for this session, oldest first — including the two E9 columns."""
    async with uow_factory() as uow:
        assert isinstance(uow, SqlAlchemyUnitOfWork)
        result = await uow.session.execute(
            sa.text(
                "SELECT c.*, r.callsign FROM resource_state_changes c"
                " JOIN emergency_resources r ON r.id = c.resource_id"
                " WHERE r.session_id = :session_id ORDER BY c.at_offset_ms, c.id"
            ),
            {"session_id": session_id},
        )
        rows = [dict(row._mapping) for row in result.all()]
        await uow.commit()
    return rows


async def resource_rows(uow_factory: Any, session_id: UUID) -> dict[str, dict[str, Any]]:
    """`emergency_resources` by callsign — the live board including `assignment_id`."""
    async with uow_factory() as uow:
        assert isinstance(uow, SqlAlchemyUnitOfWork)
        result = await uow.session.execute(
            sa.text("SELECT * FROM emergency_resources WHERE session_id = :session_id"),
            {"session_id": session_id},
        )
        rows = {row._mapping["callsign"]: dict(row._mapping) for row in result.all()}
        await uow.commit()
    return rows

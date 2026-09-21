"""`stage_automation` — the DDS stage's SIMULATION triggers, over the real tick loop (D6, D7).

D6: "simulation → `first_en_route`, `first_arrived`, `work_started`, `incident_resolved`.
Simulation triggers pass through the same state machine and are rejected the same way when
invalid." These tests drive one unit with a deliberately slow ETA — АГС-1, 45 s turnout and 240 s
travel — and assert the stage at both sides of every threshold, so "the stage follows the board"
is pinned as an *ordering*, not merely as an end state.

The negative half of each pair is the load-bearing one, and is what the brief's second sabotage
check breaks: a `stage_automation` that fired `first_en_route` unconditionally would move the
stage at 30 s, before any unit has departed, and
`test_the_stage_stays_in_dispatched_until_a_unit_departs` fails.

The automation runs as an `after_tick` hook of the `SimulationRunner`, so nothing here calls it
directly: `at(...)` advances the clock and calls `runner.tick_now`, which is the same call every
command endpoint makes.
"""

from __future__ import annotations

import pytest
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import SessionId

from tests.api.dds.conftest import (
    OperatorFlow,
    acknowledge,
    assignment_rows,
    at,
    board,
    dispatch,
    event_types,
    open_selection,
    select,
    work_item,
)

pytestmark = pytest.mark.integration

#: Turnout 45 s, travel 240 s, setup 30 s, on-scene work 240 s — the slowest unit of the demo,
#: which is what gives every threshold a comfortable gap to assert on both sides of.
SLOW_UNIT = "АГС-1"


@pytest.fixture
async def one_unit_dispatched(dds_active: OperatorFlow) -> OperatorFlow:
    """`dds_active` with `SLOW_UNIT` alone dispatched, at about 11 s."""
    await acknowledge(dds_active)
    await open_selection(dds_active)
    assert (await select(dds_active, SLOW_UNIT)).status_code == 200
    result = await dispatch(dds_active)
    assert result["stage"]["stage_state"] == "DISPATCHED"
    return dds_active


async def _state(flow: OperatorFlow) -> str:
    return str((await work_item(flow))["state"])


async def _status(flow: OperatorFlow, callsign: str) -> str:
    return next(
        item["current_status"] for item in await board(flow) if item["callsign"] == callsign
    )


async def test_the_stage_stays_in_dispatched_until_a_unit_departs(
    one_unit_dispatched: OperatorFlow, clock: FakeClock
) -> None:
    """`guard_any_dispatched_reached(EN_ROUTE)` — at 30 s the turnout delay has not elapsed."""
    await at(one_unit_dispatched, clock, 30_000)

    assert await _status(one_unit_dispatched, SLOW_UNIT) == "DISPATCHED"
    assert await _state(one_unit_dispatched) == "DISPATCHED"


async def test_the_stage_follows_the_board_through_every_threshold(
    one_unit_dispatched: OperatorFlow, clock: FakeClock
) -> None:
    """One assertion per side of each of the three thresholds, in simulated time."""
    flow, advance = one_unit_dispatched, clock

    await at(flow, advance, 60_000)  # turnout 45 s elapsed
    assert await _status(flow, SLOW_UNIT) == "EN_ROUTE"
    assert await _state(flow) == "EN_ROUTE"

    await at(flow, advance, 290_000)  # travel 240 s from 56 s => on scene at 296 s
    assert await _status(flow, SLOW_UNIT) == "EN_ROUTE"
    assert await _state(flow) == "EN_ROUTE"

    await at(flow, advance, 300_000)
    assert await _status(flow, SLOW_UNIT) == "ON_SCENE"
    assert await _state(flow) == "ARRIVED"

    await at(flow, advance, 330_000)  # setup 30 s
    assert await _status(flow, SLOW_UNIT) == "WORKING"
    assert await _state(flow) == "WORKING"


async def test_the_stage_does_not_resolve_before_the_scenarios_condition_holds(
    one_unit_dispatched: OperatorFlow, clock: FakeClock
) -> None:
    """`guard_resolution_condition`: the gas unit has no `FIRE_SUPPRESSION`, so nothing resolves.

    Simulated time is past the scenario's 540 s threshold here, and the stage is `WORKING` — the
    only thing still missing is the *other* half of the `all` condition, which is exactly what
    the verdict handed to the guard has to be able to say.
    """
    await at(one_unit_dispatched, clock, 545_000)

    assert await _state(one_unit_dispatched) == "WORKING"


async def test_the_automation_is_idempotent(
    one_unit_dispatched: OperatorFlow, clock: FakeClock
) -> None:
    """A second tick at the same instant fires nothing: the machine has nothing left to accept."""
    await at(one_unit_dispatched, clock, 60_000)
    before = await event_types(one_unit_dispatched)

    await one_unit_dispatched.container.runner.tick_now(SessionId(one_unit_dispatched.session_id))

    assert await event_types(one_unit_dispatched) == before


async def test_a_unit_nobody_dispatched_cannot_drive_the_stage(
    dds_active: OperatorFlow, clock: FakeClock
) -> None:
    """Analyst R6: the stage guards see only the units attached to this stage's legs.

    СМП-12 starts `UNAVAILABLE` and becomes `AVAILABLE` on its own schedule at 120 s — a board
    movement that must not be mistaken for "a dispatched unit reached something".
    """
    await acknowledge(dds_active)
    await open_selection(dds_active)

    await at(dds_active, clock, 130_000)

    assert await _status(dds_active, "СМП-12") == "AVAILABLE"
    assert await _state(dds_active) == "RESOURCE_SELECTION"


async def test_every_leg_mirrors_the_state_the_automation_produced(
    one_unit_dispatched: OperatorFlow, clock: FakeClock, uow_factory: object
) -> None:
    """R1: the stage is the authority and each `dds_assignments` row is a copy of it."""
    await at(one_unit_dispatched, clock, 330_000)

    rows = await assignment_rows(uow_factory, one_unit_dispatched.session_id)

    assert {row["state"] for row in rows} == {"WORKING"}


async def test_the_stage_events_the_automation_appends_are_simulation_authored(
    one_unit_dispatched: OperatorFlow, clock: FakeClock
) -> None:
    """A unit arriving is not something the trainee did (SPEC §8)."""
    await at(one_unit_dispatched, clock, 60_000)

    response = await one_unit_dispatched.get(
        "/events", token=one_unit_dispatched.instructor_token, params={"limit": 1000}
    )
    assert response.status_code == 200, response.text
    stage_events = [
        item for item in response.json()["items"] if item["event_type"] == "STAGE_STATE_CHANGED"
    ]
    assert stage_events[-1]["payload"]["trigger"] == "first_en_route"
    assert stage_events[-1]["actor_type"] == "SIMULATION"

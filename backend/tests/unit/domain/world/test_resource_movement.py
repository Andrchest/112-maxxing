"""`advance_resources`, `RESOURCE_GUARDS` and `ScenarioDefinedEta` (HLD §10.7, D7)."""

from __future__ import annotations

from app.domain.common.ids import ResourceId
from app.domain.dds.resources import (
    RESOURCE_GUARDS,
    RESOURCE_STATUS_TRANSITIONS,
    EmergencyResource,
)
from app.domain.enums import ResourceStatus
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent
from app.domain.world.apply import apply_effects
from app.domain.world.effects import AlterResourceAvailability
from app.domain.world.engine import FiredEvent
from app.domain.world.eta import ScenarioDefinedEta
from app.domain.world.resource_movement import advance_resources

from tests.unit.domain.world._builders import demo_scenario, demo_world_state, resource_board

ETA = ScenarioDefinedEta()

# `ac1` (АЦ-1) of the demo scenario: turnout 30 s, travel 150 s, setup 30 s, work 240 s,
# return 180 s — so the due offsets from a dispatch at t = 0 are these five.
AC1_DUE_MS = (30_000, 180_000, 210_000, 450_000, 630_000)
AC1_CHAIN = (
    ResourceStatus.EN_ROUTE,
    ResourceStatus.ON_SCENE,
    ResourceStatus.WORKING,
    ResourceStatus.RETURNING,
    ResourceStatus.AVAILABLE,
)


def _board(
    **statuses: ResourceStatus,
) -> tuple[dict[ResourceId, EmergencyResource], dict[str, ResourceId]]:
    return resource_board(demo_scenario(), statuses=statuses)


def _trail(events: list[DomainEvent], key: ResourceId) -> list[tuple[str, int]]:
    return [
        (str(event.payload["new_status"]), event.monotonic_offset_ms)
        for event in events
        if event.payload["resource_id"] == key
    ]


def test_every_guard_name_in_the_table_is_registered() -> None:
    named = {
        transition.guard_name
        for transition in RESOURCE_STATUS_TRANSITIONS.values()
        if transition.guard_name is not None
    }
    assert named <= set(RESOURCE_GUARDS)
    assert set(RESOURCE_GUARDS) == named


def test_scenario_defined_eta_reads_the_profile_verbatim() -> None:
    board, keys = _board()
    resource = board[keys["ac1"]]
    assert ETA.turnout_delay_ms(resource) == resource.eta.turnout_delay_seconds * 1000
    assert ETA.travel_time_ms(resource) == resource.eta.travel_time_seconds * 1000
    assert ETA.setup_ms(resource) == resource.eta.setup_seconds * 1000
    assert ETA.on_scene_work_ms(resource) == resource.eta.on_scene_work_seconds * 1000
    assert ETA.return_time_ms(resource) == resource.eta.return_time_seconds * 1000


def test_progression_step_by_step_matches_the_scenario_eta_profile() -> None:
    board, keys = _board(ac1=ResourceStatus.DISPATCHED)
    key = keys["ac1"]
    now = 0
    reached: list[ResourceStatus] = []
    while now < 700_000:
        now += 1_000
        board, events = advance_resources(board, now, ETA, assignment_resolved=False)  # type: ignore[assignment]
        for event in events:
            if event.payload["resource_id"] == key:
                reached.append(ResourceStatus(event.payload["new_status"]))
                validate_payload(event.event_type, event.payload)
    assert reached == list(AC1_CHAIN)
    assert board[key].current_status is ResourceStatus.AVAILABLE


def test_one_big_tick_equals_many_small_ticks() -> None:
    board, keys = _board(ac1=ResourceStatus.DISPATCHED)
    key = keys["ac1"]
    big, big_events = advance_resources(board, 630_000, ETA, assignment_resolved=False)
    assert _trail(big_events, key) == [
        (status.value, due) for status, due in zip(AC1_CHAIN, AC1_DUE_MS, strict=True)
    ]
    assert big[key].current_status is ResourceStatus.AVAILABLE

    small = board
    small_events: list[DomainEvent] = []
    now = 0
    while now < 630_000:
        now += 500
        small, events = advance_resources(small, now, ETA, assignment_resolved=False)  # type: ignore[assignment]
        small_events.extend(events)
    assert _trail(small_events, key) == _trail(big_events, key)
    assert small[key].model_dump() == big[key].model_dump()


def test_assignment_resolved_ends_the_on_scene_work_early() -> None:
    board, keys = _board(ac1=ResourceStatus.WORKING)
    key = keys["ac1"]
    moved, events = advance_resources(board, 1_000, ETA, assignment_resolved=True)
    assert moved[key].current_status is ResourceStatus.RETURNING
    assert _trail(events, key) == [("RETURNING", 1_000)]
    unresolved, _ = advance_resources(board, 1_000, ETA, assignment_resolved=False)
    assert unresolved[key].current_status is ResourceStatus.WORKING


def test_availability_window_opens_and_closes_the_board() -> None:
    board, keys = _board()
    key = keys["smp12"]  # available_from_ms = 120 000, initial status UNAVAILABLE
    assert board[key].current_status is ResourceStatus.UNAVAILABLE
    early, events = advance_resources(board, 119_000, ETA, assignment_resolved=False)
    assert early[key].current_status is ResourceStatus.UNAVAILABLE
    assert _trail(events, key) == []
    late, events = advance_resources(board, 120_000, ETA, assignment_resolved=False)
    assert late[key].current_status is ResourceStatus.AVAILABLE
    assert _trail(events, key) == [("AVAILABLE", 120_000)]


def test_a_broken_down_resource_stops_moving_until_it_is_repaired() -> None:
    state = demo_world_state(statuses={"ac1": ResourceStatus.EN_ROUTE})
    key = state.resource_keys["ac1"]
    breakdown = AlterResourceAvailability(
        resource_id="ac1", new_status=ResourceStatus.OUT_OF_SERVICE
    )
    fired = FiredEvent(
        world_event_id="fire_spreads",
        occurrence=0,
        at_ms=10_000,
        caller_observable=False,
        effects=(breakdown,),
    )
    broken = apply_effects(state, [fired], 10_000).state
    stuck, events = advance_resources(broken.resources, 600_000, ETA, assignment_resolved=False)
    assert stuck[key].current_status is ResourceStatus.OUT_OF_SERVICE
    assert _trail(events, key) == []

    repair = AlterResourceAvailability(
        resource_id="ac1", new_status=ResourceStatus.AVAILABLE, restore=True
    )
    repaired = apply_effects(
        broken.model_copy(update={"resources": stuck}),
        [fired.model_copy(update={"effects": (repair,), "at_ms": 600_000})],
        600_000,
    ).state
    assert repaired.resources[key].current_status is ResourceStatus.AVAILABLE


def test_resources_are_walked_in_ascending_callsign_order() -> None:
    board, _keys = _board(
        ac1=ResourceStatus.DISPATCHED,
        ac2=ResourceStatus.DISPATCHED,
        al1=ResourceStatus.DISPATCHED,
    )
    _moved, events = advance_resources(board, 40_000, ETA, assignment_resolved=False)
    ordered = [str(event.payload["callsign"]) for event in events]
    assert ordered == sorted(ordered)


def test_the_walk_order_does_not_depend_on_the_runtime_resource_ids() -> None:
    """D7 determinism rule 5 / INV 7, at its source (E17-B2).

    `emergency_resources.id` is `gen_random_uuid()` per session (`20-db-schema.md` §20.5), so two
    runs of one scenario hold the same units under different keys. Walking the board by that key
    made the two runs append the same transitions in a different sequence — a real INV 7 hole,
    found by the E17-B hand-over determinism test. The walk is by `callsign`, which the scenario
    owns and §30.8 rule 15 makes unique, so the sequence below is the same for any keying.
    """
    statuses = {
        "ac1": ResourceStatus.DISPATCHED,
        "ac2": ResourceStatus.DISPATCHED,
        "al1": ResourceStatus.DISPATCHED,
        "asa1": ResourceStatus.DISPATCHED,
    }
    version = demo_scenario()
    board, _keys = resource_board(version, statuses=statuses)

    # The same units under keys drawn in a different — here, deliberately reversed — id order.
    rekeyed_ids = sorted((resource.resource_id for resource in board.values()), reverse=True)
    rekeyed = {
        new_key: resource.model_copy(update={"resource_id": new_key})
        for new_key, resource in zip(
            rekeyed_ids, [board[key] for key in sorted(board, key=str)], strict=True
        )
    }

    _m1, first = advance_resources(board, 40_000, ETA, assignment_resolved=False)
    _m2, second = advance_resources(rekeyed, 40_000, ETA, assignment_resolved=False)

    def trail(events: list[DomainEvent]) -> list[tuple[str, str, int]]:
        return [
            (
                str(event.payload["callsign"]),
                str(event.payload["new_status"]),
                event.monotonic_offset_ms,
            )
            for event in events
        ]

    assert trail(first) == trail(second)
    assert [row[0] for row in trail(first)] == sorted(row[0] for row in trail(first))

"""INV 7 — "Identical seed and actions produce identical deterministic world events"
(SPEC §42 item 7, HLD §10.11 determinism rules 1-5, D7).

The scenario is the committed demo (`scenarios/examples/apartment-fire/v1.yaml`), instantiated
through the real copy functions. The same timestamped `PendingAction` script is replayed twice with
the same session seed but in **different tick partitions** (500 ms ticks against 2 000 ms ticks);
the two runs must produce the identical `FiredEvent` stream, `at_ms` included. A different seed must
produce a different stream — the demo scenario's `SEEDED_RANDOM` event (`ac2_breakdown`,
probability 0.25 every 30 s inside a 600 s window) is what makes the seed observable, so the script
holds `ac2` in `EN_ROUTE` (its firing condition) and runs the whole 600 s window.

Partition independence holds exactly here because every event kind in this script keys off absolute
simulation time: `TimedEvent.at_ms`, the delayed `ActionTriggeredEvent`'s
`action.at_offset_ms + delay_ms`, the `ConditionalEvent`'s `sim_time` threshold and the
`SeededRandomEvent`'s absolute check-tick index are all multiples of both tick sizes.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from app.domain.common.actors import ActorRef
from app.domain.enums import ActorType, ResourceStatus
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.world.engine import PendingAction, WorldState, advance
from app.domain.world.rng import rng_for
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.simulation._support import SimHarness, build_session, truncate_all
from tests.unit.domain.world._builders import demo_world_state

HORIZON_MS = 600_000
TRAINEE = ActorRef(actor_type=ActorType.TRAINEE)

SCRIPT: tuple[PendingAction, ...] = (
    PendingAction(
        event_type=EventType.CALL_ANSWERED, at_offset_ms=2_000, payload={}, actor=TRAINEE
    ),
    PendingAction(
        event_type=EventType.CARD_FIELD_CHANGED,
        at_offset_ms=60_000,
        payload={"field_path": "address.house"},
        actor=TRAINEE,
    ),
    PendingAction(
        event_type=EventType.HANDOFF_CREATED,
        at_offset_ms=120_000,
        payload={"recipient_services": ["FIRE_RESCUE", "AMBULANCE"]},
        actor=TRAINEE,
    ),
    PendingAction(
        event_type=EventType.RESOURCE_DISPATCHED,
        at_offset_ms=150_000,
        payload={"resource_ids": ["ac1", "ac2"]},
        actor=TRAINEE,
    ),
)
"""Every offset is a multiple of both tick sizes, so the script never blurs the comparison."""


def _run(seed: str, tick_ms: int) -> list[tuple[str, int, int]]:
    """Replay `SCRIPT` in `tick_ms` ticks and return the `(world_event_id, occurrence, at_ms)`
    stream."""
    state: WorldState = demo_world_state(statuses={"ac2": ResourceStatus.EN_ROUTE})
    rng_factory = rng_for(seed)
    stream: list[tuple[str, int, int]] = []
    now = 0
    while now < HORIZON_MS:
        previous, now = now, now + tick_ms
        due = [action for action in SCRIPT if previous < action.at_offset_ms <= now]
        state, _effects = advance(state, now, due, rng_factory)
        stream.extend(
            (event.world_event_id, event.occurrence, event.at_ms) for event in state.fired
        )
    return stream


def test_identical_seed_and_actions_give_the_identical_stream_in_any_tick_partition() -> None:
    fine = _run("apartment-fire-v1", 500)
    coarse = _run("apartment-fire-v1", 2_000)
    assert fine == coarse
    assert fine == _run("apartment-fire-v1", 500)  # and the run is reproducible


def test_the_whole_demo_scenario_is_exercised_by_the_script() -> None:
    fired = {entry[0] for entry in _run("apartment-fire-v1", 500)}
    assert fired == {
        "fire_spreads",
        "second_report_balcony",
        "gas_cylinder_hazard",
        "ac2_breakdown",
    }


def test_a_different_seed_gives_a_different_stream() -> None:
    assert _run("apartment-fire-v1", 500) != _run("another-session-seed", 500)


def test_only_the_seeded_random_event_differs_between_seeds() -> None:
    """The deterministic kinds are seed-independent; `ac2_breakdown` is what the seed moves."""

    def without_random(stream: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
        return [entry for entry in stream if entry[0] != "ac2_breakdown"]

    first = _run("apartment-fire-v1", 500)
    second = _run("another-session-seed", 500)
    assert without_random(first) == without_random(second)
    assert [e for e in first if e[0] == "ac2_breakdown"] != [
        e for e in second if e[0] == "ac2_breakdown"
    ]


# ---------------------------------------------------------------------------------------------
# Runner level (E6-B): the same invariant through the real use case, repositories and database
# ---------------------------------------------------------------------------------------------
#
# The cases above pin determinism in the pure engine. These pin it where SPEC §42 item 7 is
# actually claimed — end to end: two *separate sessions* of the same scenario, created and started
# by the real use cases, given the same seed and the same timestamped action events, must produce
# the identical stream of persisted SIMULATION events. Everything that could smuggle non-determinism
# in on the way — `uuid4` ids, dictionary iteration order, the tick partition, two different
# incident rows — is between the engine and these assertions.
#
# The comparison is `(event_type, payload-without-ids, simulated offset)`: the two sessions
# legitimately differ in every UUID they contain (their own incident, their own eleven resource
# rows), and nothing else.

runner_level = pytest.mark.integration

HORIZON_TICKS = 20
TICK_MS = 30_000
"""20 ticks of 30 s cover the demo's whole 600 s `SEEDED_RANDOM` window."""

INJECTED: tuple[tuple[EventType, int, dict[str, object]], ...] = (
    (EventType.CALL_ANSWERED, 2_000, {"call_id": "00000000-0000-4000-8000-000000000011"}),
    (EventType.HANDOFF_CREATED, 120_000, {"snapshot_id": "00000000-0000-4000-8000-000000000012"}),
)
"""The same script for every session under test, at the same simulated offsets."""


@pytest.fixture(autouse=True)
async def _clean_database(migrated_engine: AsyncEngine):
    await truncate_all(migrated_engine)
    yield
    await truncate_all(migrated_engine)


def _without_ids(payload: dict[str, object]) -> dict[str, object]:
    """Drop every key whose value is a UUID: those are per-session identities, not behaviour."""
    kept: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, str) and key.endswith("_id"):
            try:
                UUID(value)
            except ValueError:
                kept[key] = value
            continue
        kept[key] = value
    return kept


async def _simulation_stream(harness: SimHarness) -> list[tuple[str, int, tuple]]:
    """Every SIMULATION event of the session as `(event_type, sim offset, sorted payload)`."""
    events = await harness.events()
    return [
        (
            event.event_type.value,
            event.monotonic_offset_ms,
            tuple(sorted(_without_ids(dict(event.payload)).items(), key=lambda item: item[0])),
        )
        for event in events
        if event.actor_type is ActorType.SIMULATION
    ]


async def _run_session(
    engine: AsyncEngine, *, namespace: int, seed: str, import_scenario: bool
) -> SimHarness:
    """One demo session driven `HORIZON_TICKS` ticks with the shared injected action script."""
    harness = await build_session(
        engine, namespace=namespace, session_seed=seed, import_scenario=import_scenario
    )
    # `ac2` is parked EN_ROUTE because that is `ac2_breakdown`'s own firing condition — the one
    # place the demo scenario lets the seed be observed at all.
    await harness.set_resource_status("ac2", ResourceStatus.EN_ROUTE, 0)
    for event_type, offset_ms, payload in INJECTED:
        await harness.append(
            DomainEvent(
                event_type=event_type,
                actor=TRAINEE,
                monotonic_offset_ms=offset_ms,
                payload=payload,
            )
        )
    for _ in range(HORIZON_TICKS):
        await harness.advance_and_tick(TICK_MS)
    return harness


@runner_level
async def test_two_sessions_with_one_seed_and_one_script_produce_one_stream(
    migrated_engine: AsyncEngine,
) -> None:
    """SPEC §42 item 7, end to end: same seed + same actions ⇒ identical persisted event stream."""
    first = await _run_session(
        migrated_engine, namespace=11, seed="inv7-runner", import_scenario=True
    )
    second = await _run_session(
        migrated_engine, namespace=12, seed="inv7-runner", import_scenario=False
    )
    left, right = await _simulation_stream(first), await _simulation_stream(second)

    assert left, "the run produced no SIMULATION events at all"
    assert left == right
    # The two sessions really are two: same behaviour, different identities.
    assert first.session_id != second.session_id
    assert first.incident_id != second.incident_id


@runner_level
async def test_a_different_seed_changes_the_stream(migrated_engine: AsyncEngine) -> None:
    """The seed is load-bearing: `ac2_breakdown` is the demo's one seeded event."""
    first = await _run_session(
        migrated_engine, namespace=21, seed="inv7-runner", import_scenario=True
    )
    other = await _run_session(
        migrated_engine, namespace=22, seed="a-different-seed", import_scenario=False
    )
    assert await _simulation_stream(first) != await _simulation_stream(other)


@runner_level
async def test_the_seed_reaches_only_the_seeded_event_and_what_causally_follows_it(
    migrated_engine: AsyncEngine,
) -> None:
    """`ac2_breakdown` is the one place the seed enters; the seed-independent events do not move.

    `fire_spreads` (TIMED at 180 s) and `second_report_balcony` (ACTION_TRIGGERED, 60 s after the
    injected `HANDOFF_CREATED`) key off absolute time and the injected script alone, so they must
    be identical under both seeds. `gas_cylinder_hazard` deliberately is **not** in that set: its
    condition is "no FIRE_SUPPRESSION unit is WORKING", and whether `ac2` breaks down decides
    whether `ac2` ever reaches `WORKING` — a real causal chain from the seeded draw, not a
    determinism leak. INV 7 asks that the same seed give the same stream, which
    `test_two_sessions_with_one_seed_and_one_script_produce_one_stream` pins; it does not ask that
    a different seed change nothing downstream.
    """
    first = await _run_session(
        migrated_engine, namespace=31, seed="inv7-runner", import_scenario=True
    )
    other = await _run_session(
        migrated_engine, namespace=32, seed="a-different-seed", import_scenario=False
    )

    def fired(stream: list[tuple[str, int, tuple]]) -> list[tuple[str, int]]:
        return [
            (dict(payload)["world_event_id"], offset)  # type: ignore[misc]
            for event_type, offset, payload in stream
            if event_type == EventType.WORLD_EVENT_TRIGGERED.value
        ]

    seed_independent = {"fire_spreads", "second_report_balcony"}
    left = fired(await _simulation_stream(first))
    right = fired(await _simulation_stream(other))
    assert [row for row in left if row[0] in seed_independent] == [
        row for row in right if row[0] in seed_independent
    ]
    assert [row for row in left if row[0] == "ac2_breakdown"] != [
        row for row in right if row[0] == "ac2_breakdown"
    ]

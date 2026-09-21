"""`apply_dialogue_emotion_trigger` (HLD §10.5, SPEC §6, §23, D4, R7).

The model never sets the emotion — these are the *only* dialogue-side writes, and each one is a
deterministic `EmotionRule` applied by the existing pure `apply_emotion_rules`. The test that
matters most is the `max_applications` one: the counter lives in
`world_engine_states.emotion_applications`, the same mapping `app.domain.world.apply` uses, so a
rule capped at one application cannot fire once per code path.

E13 calls this for no trigger yet (R7): `FACT_REVEALED` and `INTERRUPTION_COUNT` fire from events
E14 owns, so the function is exercised directly here.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from app.application.dialogue.emotion_updates import apply_dialogue_emotion_trigger
from app.application.testing.fakes import FakeClock
from app.domain.caller.emotion import EventTypeTrigger, FactRevealedTrigger, WorldEventTrigger
from app.domain.enums import EmotionLabel
from app.domain.events.types import EventType

from tests.unit.application.dialogue.conftest import DialogueStore, InMemoryDialogueUnitOfWork

Factory = Callable[[], InMemoryDialogueUnitOfWork]

#: The demo scenario's two rules: `panic_on_spread` (WORLD_EVENT) and `calm_after_dispatch`
#: (EVENT_TYPE `RESOURCE_DISPATCHED`), both capped at one application.
SPREAD = WorldEventTrigger(world_event_id="fire_spreads")
DISPATCH = EventTypeTrigger(event_type=EventType.RESOURCE_DISPATCHED)


async def test_a_matching_rule_changes_the_belief_and_appends_the_event(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory
) -> None:
    change = await apply_dialogue_emotion_trigger(
        uow_factory,  # type: ignore[arg-type]
        store.session.id,
        SPREAD,
        clock=clock,
        trigger_kind="WORLD_EVENT",
    )

    assert change is not None
    assert change.emotion_rule_id == "panic_on_spread"
    assert change.new.emotion is EmotionLabel.PANICKED
    assert store.caller_belief.emotion.emotion is EmotionLabel.PANICKED
    assert store.event_types == ["CALLER_EMOTION_CHANGED"]


async def test_the_payload_is_the_shape_world_apply_emits(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory
) -> None:
    """R7: "the same payload shape `world/apply.py` emits" — the §10.13 catalog row."""
    await apply_dialogue_emotion_trigger(
        uow_factory,  # type: ignore[arg-type]
        store.session.id,
        SPREAD,
        clock=clock,
        trigger_kind="WORLD_EVENT",
        offset_ms=1234,
    )

    payload = store.payloads("CALLER_EMOTION_CHANGED")[0]
    assert set(payload) == {
        "previous_emotion",
        "new_emotion",
        "previous_stress_level",
        "new_stress_level",
        "emotion_rule_id",
        "trigger_kind",
        "at_offset_ms",
    }
    assert payload["previous_emotion"] == "FRIGHTENED"
    assert payload["new_emotion"] == "PANICKED"
    assert payload["emotion_rule_id"] == "panic_on_spread"
    assert payload["trigger_kind"] == "WORLD_EVENT"
    assert payload["at_offset_ms"] == 1234


async def test_the_stress_delta_is_applied_and_clamped(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory
) -> None:
    """`panic_on_spread` adds 0.3 to a baseline of 0.6 — 0.9, and never above 1.0."""
    change = await apply_dialogue_emotion_trigger(
        uow_factory,  # type: ignore[arg-type]
        store.session.id,
        SPREAD,
        clock=clock,
        trigger_kind="WORLD_EVENT",
    )

    assert change is not None
    assert change.new.stress_level == pytest.approx(0.9)
    assert 0.0 <= change.new.stress_level <= 1.0


async def test_no_matching_rule_writes_nothing(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory
) -> None:
    before = store.caller_belief

    change = await apply_dialogue_emotion_trigger(
        uow_factory,  # type: ignore[arg-type]
        store.session.id,
        FactRevealedTrigger(fact_id="address.street"),
        clock=clock,
        trigger_kind="FACT_REVEALED",
    )

    assert change is None
    assert store.caller_belief is before
    assert store.events == []


async def test_max_applications_is_bounded_by_the_engines_own_counter(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory
) -> None:
    """R7: one counter, in `world_engine_states.emotion_applications` — never a second one."""
    first = await apply_dialogue_emotion_trigger(
        uow_factory,  # type: ignore[arg-type]
        store.session.id,
        SPREAD,
        clock=clock,
        trigger_kind="WORLD_EVENT",
    )
    assert first is not None
    assert store.engine_state.emotion_applications == {"panic_on_spread": 1}

    second = await apply_dialogue_emotion_trigger(
        uow_factory,  # type: ignore[arg-type]
        store.session.id,
        SPREAD,
        clock=clock,
        trigger_kind="WORLD_EVENT",
    )

    assert second is None
    assert store.engine_state.emotion_applications == {"panic_on_spread": 1}
    assert store.event_types == ["CALLER_EMOTION_CHANGED"]


async def test_a_counter_the_world_engine_already_advanced_is_respected(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory
) -> None:
    """The world engine fired the rule during a tick; the dialogue side must not fire it again."""
    store.engine_state = store.engine_state.model_copy(
        update={"emotion_applications": {"panic_on_spread": 1}}
    )

    change = await apply_dialogue_emotion_trigger(
        uow_factory,  # type: ignore[arg-type]
        store.session.id,
        SPREAD,
        clock=clock,
        trigger_kind="WORLD_EVENT",
    )

    assert change is None


async def test_an_event_type_trigger_also_matches(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory
) -> None:
    change = await apply_dialogue_emotion_trigger(
        uow_factory,  # type: ignore[arg-type]
        store.session.id,
        DISPATCH,
        clock=clock,
        trigger_kind="EVENT_TYPE",
    )

    assert change is not None
    assert change.emotion_rule_id == "calm_after_dispatch"
    assert change.new.emotion is EmotionLabel.WORRIED


async def test_the_offset_falls_back_to_the_clock(
    store: DialogueStore, clock: FakeClock, uow_factory: Factory
) -> None:
    clock.advance_ms(7_000)

    await apply_dialogue_emotion_trigger(
        uow_factory,  # type: ignore[arg-type]
        store.session.id,
        SPREAD,
        clock=clock,
        trigger_kind="WORLD_EVENT",
    )

    assert store.payloads("CALLER_EMOTION_CHANGED")[0]["at_offset_ms"] == 7_000

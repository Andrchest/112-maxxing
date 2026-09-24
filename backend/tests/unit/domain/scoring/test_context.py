"""`app.domain.scoring.context` — the read model every evaluator sees (HLD §10.14, D3, D5, D10).

The three rulings this module owns are asserted here rather than through an evaluator, because
they are properties of the *input*: `SCORING_*` events are dropped, the card timeline is the
trainee's work only, and a dispatched unit's service comes from the unit.
"""

from __future__ import annotations

import pytest
from app.domain.enums import ActorType, RoleType, ServiceId
from app.domain.events.types import EventType
from app.domain.scoring.context import UnorderedEventLogError, build_context

from tests.unit.domain.scoring._event_log_builders import (
    GOOD_CARD_VALUES,
    HANDOFF_MS,
    dds_only_log,
    demo_scenario,
    good_log,
    with_previous_scoring_events,
)


def test_events_are_indexed_by_type_in_seq_order() -> None:
    ctx = build_context(demo_scenario(), good_log())

    deliveries = ctx.of_type(EventType.FACTS_DELIVERED)

    assert deliveries
    assert [event.seq_no for event in deliveries] == sorted(event.seq_no for event in deliveries)
    assert ctx.first_of_type(EventType.CALL_ANSWERED) is not None


def test_scoring_events_are_dropped_and_not_counted() -> None:
    """Ruling R2: `score()` never reads its own previous output."""
    events = good_log()
    rescored = with_previous_scoring_events(events)

    ctx = build_context(demo_scenario(), rescored)

    assert len(rescored) > len(events)
    assert ctx.computed_from_event_count == len(events)
    assert ctx.of_type(EventType.SCORING_RULE_EVALUATED) == ()


def test_unordered_input_raises_rather_than_being_re_sorted() -> None:
    events = list(good_log())
    swapped = [*events[:5], events[6], events[5], *events[7:]]

    with pytest.raises(UnorderedEventLogError):
        build_context(demo_scenario(), swapped)


def test_duplicate_seq_no_raises() -> None:
    events = list(good_log())

    with pytest.raises(UnorderedEventLogError):
        build_context(demo_scenario(), [*events, events[-1]])


def test_card_timeline_is_trainee_authored_only() -> None:
    """Ruling R5: the instructor's prefab card is never scored as the trainee's work (D3)."""
    prefab = dds_only_log()
    assert any(
        event.event_type is EventType.CARD_FIELD_CHANGED
        and event.actor_type is ActorType.INSTRUCTOR
        for event in prefab
    )

    ctx = build_context(demo_scenario(), prefab)

    assert ctx.card_changes == ()
    assert ctx.card_value_at("address.house", ctx.cutoff_seq_no("SESSION_END")) is None


def test_card_value_at_reads_the_value_at_the_cutoff() -> None:
    ctx = build_context(demo_scenario(), good_log())
    cutoff = ctx.cutoff_seq_no("HANDOFF")

    assert ctx.handoff_event is not None
    assert cutoff == ctx.handoff_event.seq_no
    assert ctx.card_value_at("address.house", cutoff) == GOOD_CARD_VALUES["address.house"]
    assert ctx.card_value_at("address.house", 0) is None


def test_handoff_card_values_come_from_the_handoff_payload() -> None:
    ctx = build_context(demo_scenario(), good_log())

    assert ctx.handoff_event is not None
    assert ctx.handoff_event.monotonic_offset_ms == HANDOFF_MS
    assert ctx.handoff_card_values["address.apartment"] == "45"


def test_deliveries_carry_their_offsets_in_order() -> None:
    ctx = build_context(demo_scenario(), good_log())

    victim = ctx.deliveries_of("people.victim_01.inside")

    assert len(victim) == 1
    assert victim[0].at_offset_ms == 60_000
    assert ctx.deliveries_of("nothing.like.this") == ()


def test_dispatched_unit_service_comes_from_the_unit_not_the_leg() -> None:
    """Ruling R6: `service_type_by_resource`, never the assignment leg."""
    ctx = build_context(demo_scenario(), good_log())

    services = sorted(unit.service_type for unit in ctx.dispatched_units if unit.service_type)

    assert services == ["AMBULANCE", "FIRE_RESCUE", "FIRE_RESCUE"]
    assert "HIGH_RISE_ACCESS" in ctx.dispatched_capabilities


def test_role_chain_comes_from_session_created() -> None:
    ctx = build_context(demo_scenario(), good_log())

    assert ctx.role_chain == (RoleType.OPERATOR_112, RoleType.DDS)
    assert ctx.role_chain_event is not None
    assert ctx.role_chain_event.event_type is EventType.SESSION_CREATED


def test_dds_only_role_chain_is_dds_alone() -> None:
    ctx = build_context(demo_scenario(), dds_only_log())

    assert ctx.role_chain == (RoleType.DDS,)
    assert ctx.handoff_event is None


def test_bounding_events_are_available_for_absence_evidence() -> None:
    ctx = build_context(demo_scenario(), good_log())

    assert ctx.session_completed is not None
    assert (
        ctx.stage_bound(RoleType.OPERATOR_112) is ctx.stage_completed_by_role[RoleType.OPERATOR_112]
    )
    assert ctx.stage_bound(RoleType.EDDS) is not None


def test_selected_units_drop_a_deselected_one() -> None:
    ctx = build_context(demo_scenario(), good_log())

    assert {unit.service_type for unit in ctx.selected_units} == {
        ServiceId("FIRE_RESCUE"),
        ServiceId("AMBULANCE"),
    }

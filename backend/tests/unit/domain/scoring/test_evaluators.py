"""The ten `evaluate(...)` functions (HLD `10-domain-model.md` §10.14, SPEC §28).

Each evaluator gets a pass case, a fail/penalty case and an absence case whose evidence points at
a bounding event; the ones with a numeric edge (`DEADLINE`'s two scales, `FACT_OBTAINED`'s
`within_ms`, `REQUIRED_STATUS_UPDATE`'s `within_ms`) get the boundary itself, `== limit`, because
that is where an off-by-one changes a trainee's grade.

Rules are built from the committed demo scenario's own ten rules wherever possible and overridden
key by key otherwise, so no test invents a config shape the gate does not validate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from app.domain.common.ids import EventId
from app.domain.enums import LEGACY_SERVICE_IDS, EvaluatorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring.context import ScoringContext, build_context
from app.domain.scoring.errors import ScoringEvidenceError
from app.domain.scoring.evaluators.registry import EVALUATORS, parse_rule_config
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule

from tests.unit.domain.scoring._event_log_builders import (
    CALL_ANSWERED_MS,
    DEADLINE_LIMIT_MS,
    DEADLINE_ZERO_MS,
    GOOD_CARD_VALUES,
    GOOD_DELIVERIES,
    GOOD_UNITS,
    ON_SCENE_MS,
    VICTIM_FACT_MS,
    dds_only_log,
    demo_scenario,
    det_uuid,
    good_log,
    mutate,
)

SCENARIO = demo_scenario()
DEMO_RULES: Mapping[str, ScoringRule] = {rule.rule_id: rule for rule in SCENARIO.scoring_rules}


def rule_with(rule_id: str, **config_overrides: Any) -> ScoringRule:
    """The demo rule `rule_id` with some config keys replaced."""
    base = DEMO_RULES[rule_id]
    return base.model_copy(update={"config": {**base.config, **config_overrides}})


def run(rule: ScoringRule, events: Sequence[SessionEvent]) -> ScoreResult:
    """Evaluate one rule against one log, exactly as `score()` dispatches it."""
    ctx: ScoringContext = build_context(SCENARIO, events)
    return EVALUATORS[rule.evaluator_type](rule, parse_rule_config(rule), ctx)


def evidence_events(result: ScoreResult, events: Sequence[SessionEvent]) -> list[EventType]:
    by_id = {event.id: event for event in events}
    return [by_id[item.event_id].event_type for item in result.evidence if item.event_id in by_id]


# ---------------------------------------------------------------------------------------------
# 1. FACT_OBTAINED
# ---------------------------------------------------------------------------------------------


def test_fact_obtained_awards_points_for_a_delivered_fact() -> None:
    events = good_log()

    result = run(DEMO_RULES["fact_victim_inside"], events)

    assert result.points_awarded == 10.0
    assert result.passed
    assert evidence_events(result, events) == [EventType.FACTS_DELIVERED]


def test_fact_obtained_at_exactly_the_within_ms_limit_still_counts() -> None:
    events = good_log()

    result = run(rule_with("fact_victim_inside", within_ms=VICTIM_FACT_MS), events)

    assert result.passed


def test_fact_obtained_one_millisecond_past_the_limit_does_not() -> None:
    events = good_log()

    result = run(rule_with("fact_victim_inside", within_ms=VICTIM_FACT_MS - 1), events)

    assert not result.passed
    assert result.points_awarded == 0.0


def test_fact_obtained_never_delivered_points_at_the_bounding_stage_event() -> None:
    events = mutate("fact_never_delivered")

    result = run(DEMO_RULES["fact_victim_inside"], events)

    assert not result.passed
    assert evidence_events(result, events) == [EventType.ROLE_STAGE_COMPLETED]


def test_fact_obtained_delivered_late_points_at_the_late_delivery() -> None:
    events = mutate("fact_delivered_late")

    result = run(DEMO_RULES["fact_victim_inside"], events)

    assert not result.passed
    assert evidence_events(result, events) == [EventType.FACTS_DELIVERED]


def test_fact_obtained_penalty_is_applied_when_configured() -> None:
    result = run(
        rule_with("fact_victim_inside", penalty_if_missing=-5.0),
        mutate("fact_never_delivered"),
    )

    assert result.points_awarded == -5.0


def test_fact_obtained_ignores_caller_text_entirely() -> None:
    """D10: `FACTS_DELIVERED` only, never a transcript or a TTS payload (§42 test 10)."""
    wordy = good_log(caller_text="совершенно другой текст, без единого совпадения")

    assert run(DEMO_RULES["fact_victim_inside"], wordy).points_awarded == 10.0


# ---------------------------------------------------------------------------------------------
# 2. CARD_FIELD_CORRECT
# ---------------------------------------------------------------------------------------------


def test_card_field_correct_matches_world_truth() -> None:
    result = run(DEMO_RULES["card_house_correct"], good_log())

    assert result.points_awarded == 8.0
    assert result.passed
    assert result.evidence[0].card_revision_id is not None


def test_card_field_correct_penalises_a_wrong_value() -> None:
    result = run(DEMO_RULES["card_house_correct"], mutate("wrong_house_number"))

    assert result.points_awarded == -4.0
    assert not result.passed


def test_card_field_correct_scores_zero_for_an_empty_field() -> None:
    """An empty field is `CARD_FIELD_PRESENT`'s business, not a wrong answer (§10.14 #2)."""
    card = {key: value for key, value in GOOD_CARD_VALUES.items() if key != "address.house"}

    result = run(DEMO_RULES["card_house_correct"], good_log(card_values=card))

    assert result.points_awarded == 0.0
    assert not result.passed


def test_card_field_correct_accepts_an_expected_literal() -> None:
    rule = rule_with(
        "card_house_correct",
        expected_from_fact_id=None,
        expected_literal="27",
        comparison="EXACT",
    )

    assert run(rule, good_log()).passed


def test_card_field_correct_ignores_an_instructor_prefab_revision() -> None:
    """Ruling R5: the DDS-only prefab card is not the trainee's work (D3)."""
    result = run(DEMO_RULES["card_house_correct"], dds_only_log())

    assert result.points_awarded == 0.0
    assert not result.passed


# ---------------------------------------------------------------------------------------------
# 3. CARD_FIELD_PRESENT
# ---------------------------------------------------------------------------------------------


def test_card_field_present_awards_a_filled_field() -> None:
    result = run(DEMO_RULES["card_phone_present"], good_log())

    assert result.points_awarded == 3.0
    assert result.passed


def test_card_field_present_falls_back_to_the_handoff_for_a_field_never_filled() -> None:
    """D11's own example of "absence" evidence."""
    events = mutate("field_never_filled")

    result = run(DEMO_RULES["card_phone_present"], events)

    assert not result.passed
    assert result.evidence[0].snapshot_id is not None


def test_card_field_present_penalty_applies() -> None:
    result = run(
        rule_with("card_phone_present", penalty_if_missing=-1.5),
        mutate("field_never_filled"),
    )

    assert result.points_awarded == -1.5


def test_card_field_present_treat_false_as_present() -> None:
    card = {**GOOD_CARD_VALUES, "flags.threat_to_life": False}
    strict = rule_with(
        "card_phone_present", field_path="flags.threat_to_life", treat_false_as_present=False
    )
    lenient = rule_with(
        "card_phone_present", field_path="flags.threat_to_life", treat_false_as_present=True
    )
    events = good_log(card_values=card)

    assert not run(strict, events).passed
    assert run(lenient, events).passed


# ---------------------------------------------------------------------------------------------
# 4. CARD_CONTRADICTION
# ---------------------------------------------------------------------------------------------


def test_card_contradiction_is_silent_when_the_card_agrees_with_the_caller() -> None:
    """SPEC §3: writing down the caller's wrong floor is not a contradiction."""
    result = run(DEMO_RULES["card_no_false_floor"], good_log())

    assert result.points_awarded == 0.0
    assert result.passed


def test_card_contradiction_penalises_a_value_the_caller_never_gave() -> None:
    events = mutate("contradiction_after_delivery")

    result = run(DEMO_RULES["card_no_false_floor"], events)

    assert result.points_awarded == -4.0
    assert not result.passed
    assert evidence_events(result, events).count(EventType.FACTS_DELIVERED) == 1


def test_card_contradiction_requires_the_fact_to_have_been_delivered() -> None:
    deliveries = tuple(
        (offset, tuple(f for f in fact_ids if f != "address.floor"))
        for offset, fact_ids in GOOD_DELIVERIES
    )
    events = good_log(card_values={**GOOD_CARD_VALUES, "address.floor": 9}, deliveries=deliveries)

    result = run(DEMO_RULES["card_no_false_floor"], events)

    assert result.points_awarded == 0.0
    assert result.passed


def test_card_contradiction_without_require_fact_delivered_still_penalises() -> None:
    deliveries = tuple(
        (offset, tuple(f for f in fact_ids if f != "address.floor"))
        for offset, fact_ids in GOOD_DELIVERIES
    )
    events = good_log(card_values={**GOOD_CARD_VALUES, "address.floor": 9}, deliveries=deliveries)

    result = run(rule_with("card_no_false_floor", require_fact_delivered=False), events)

    assert result.points_awarded == -4.0


def test_card_contradiction_is_silent_for_an_empty_field() -> None:
    card = {key: value for key, value in GOOD_CARD_VALUES.items() if key != "address.floor"}

    result = run(DEMO_RULES["card_no_false_floor"], good_log(card_values=card))

    assert result.passed


# ---------------------------------------------------------------------------------------------
# 5. SERVICE_SELECTION
# ---------------------------------------------------------------------------------------------


def test_service_selection_awards_per_required_service() -> None:
    result = run(DEMO_RULES["services_fire_and_ambulance"], good_log())

    assert result.points_awarded == 12.0
    assert result.passed


def test_service_selection_penalises_a_forbidden_service() -> None:
    result = run(DEMO_RULES["services_fire_and_ambulance"], mutate("forbidden_service"))

    assert result.points_awarded == 9.0
    assert not result.passed


def test_service_selection_partial_credit_without_all_or_nothing() -> None:
    result = run(
        DEMO_RULES["services_fire_and_ambulance"], good_log(recipient_services=("FIRE_RESCUE",))
    )

    assert result.points_awarded == 6.0
    assert not result.passed


def test_service_selection_all_or_nothing_awards_max_points_or_zero() -> None:
    rule = rule_with("services_fire_and_ambulance", all_or_nothing=True)

    assert run(rule, good_log()).points_awarded == 12.0
    assert run(rule, good_log(recipient_services=("FIRE_RESCUE",))).points_awarded == 0.0


def test_service_selection_missing_service_points_at_the_handoff() -> None:
    events = good_log(recipient_services=("FIRE_RESCUE",))

    result = run(DEMO_RULES["services_fire_and_ambulance"], events)

    assert EventType.HANDOFF_CREATED in evidence_events(result, events)
    assert any("AMBULANCE" in item.note_ru for item in result.evidence)


# ---------------------------------------------------------------------------------------------
# 6. DEADLINE
# ---------------------------------------------------------------------------------------------


def test_deadline_step_inside_the_window() -> None:
    rule = rule_with("deadline_handoff", scale="STEP", linear_zero_ms=None)

    result = run(rule, good_log())

    assert result.points_awarded == 10.0
    assert result.passed


def test_deadline_at_exactly_the_limit_still_passes() -> None:
    events = good_log(handoff_ms=CALL_ANSWERED_MS + DEADLINE_LIMIT_MS)

    result = run(DEMO_RULES["deadline_handoff"], events)

    assert result.points_awarded == 10.0
    assert result.passed


def test_deadline_step_one_millisecond_late_takes_the_penalty() -> None:
    rule = rule_with("deadline_handoff", scale="STEP", linear_zero_ms=None)
    events = good_log(handoff_ms=CALL_ANSWERED_MS + DEADLINE_LIMIT_MS + 1)

    assert run(rule, events).points_awarded == -5.0


@pytest.mark.parametrize(
    ("delta_ms", "expected"),
    [
        (DEADLINE_LIMIT_MS, 10.0),
        ((DEADLINE_LIMIT_MS + DEADLINE_ZERO_MS) // 2, 5.0),
        (DEADLINE_ZERO_MS - 1, pytest.approx(10.0 / 120_000)),
        (DEADLINE_ZERO_MS, -5.0),
        (DEADLINE_ZERO_MS + 60_000, -5.0),
    ],
)
def test_deadline_linear_scale_endpoints(delta_ms: int, expected: float) -> None:
    """`LINEAR`: full points at the limit, straight down to 0 at `linear_zero_ms`, then penalty."""
    events = good_log(handoff_ms=CALL_ANSWERED_MS + delta_ms)

    assert run(DEMO_RULES["deadline_handoff"], events).points_awarded == expected


def test_deadline_evidence_names_both_bounds() -> None:
    events = good_log()

    result = run(DEMO_RULES["deadline_handoff"], events)

    assert evidence_events(result, events) == [EventType.CALL_ANSWERED, EventType.HANDOFF_CREATED]


def test_deadline_to_event_never_occurred_takes_the_penalty() -> None:
    rule = rule_with("deadline_handoff", to_event_type="DDS_INCIDENT_CLOSED")
    events = dds_only_log()

    result = run(rule, events)

    assert result.points_awarded == -5.0
    assert not result.passed


def test_deadline_from_session_start_measures_from_zero() -> None:
    rule = rule_with(
        "deadline_handoff", from_event_type="SESSION_START", scale="STEP", linear_zero_ms=None
    )

    assert run(rule, good_log(handoff_ms=DEADLINE_LIMIT_MS)).passed
    assert not run(rule, good_log(handoff_ms=DEADLINE_LIMIT_MS + 1)).passed


# ---------------------------------------------------------------------------------------------
# 7. WORKFLOW_ACTION
# ---------------------------------------------------------------------------------------------


def test_workflow_action_within_the_count_range() -> None:
    result = run(DEMO_RULES["workflow_answered_call"], good_log())

    assert result.points_awarded == 2.0
    assert result.passed


def test_workflow_action_below_min_count_takes_the_missing_penalty() -> None:
    result = run(DEMO_RULES["workflow_answered_call"], dds_only_log())

    assert result.points_awarded == -2.0
    assert not result.passed


def test_workflow_action_above_max_count_takes_the_excess_penalty() -> None:
    rule = rule_with("workflow_answered_call", penalty_per_excess=-1.5)

    result = run(rule, mutate("double_answered_call"))

    assert result.points_awarded == -1.5
    assert not result.passed


def test_workflow_action_evidence_is_capped_at_five() -> None:
    rule = rule_with(
        "workflow_answered_call",
        event_type="CARD_FIELD_CHANGED",
        min_count=1,
        max_count=None,
    )

    result = run(rule, good_log())

    assert len(result.evidence) == 5


def test_workflow_action_payload_match_is_a_subset_match() -> None:
    matching = rule_with(
        "workflow_answered_call",
        event_type="SERVICE_SELECTED",
        payload_match={"service_type": "AMBULANCE"},
        max_count=1,
    )
    missing = rule_with(
        "workflow_answered_call",
        event_type="SERVICE_SELECTED",
        payload_match={"service_type": "GAS_SERVICE"},
        max_count=1,
    )

    assert run(matching, good_log()).passed
    assert not run(missing, good_log()).passed


def test_workflow_action_must_occur_after_is_enforced() -> None:
    rule = rule_with(
        "workflow_answered_call",
        event_type="CALL_ANSWERED",
        must_occur_after="HANDOFF_CREATED",
        max_count=1,
    )

    assert not run(rule, good_log()).passed


def test_workflow_action_required_stage_state_is_enforced() -> None:
    right = rule_with(
        "workflow_answered_call",
        event_type="SERVICE_SELECTED",
        required_stage_state="INTERVIEW",
        max_count=None,
    )
    wrong = rule_with(
        "workflow_answered_call",
        event_type="SERVICE_SELECTED",
        required_stage_state="HANDOFF_PREPARATION",
        max_count=None,
    )

    assert run(right, good_log()).passed
    assert not run(wrong, good_log()).passed


def test_workflow_action_absence_points_at_a_bounding_event() -> None:
    events = dds_only_log()

    result = run(DEMO_RULES["workflow_answered_call"], events)

    assert evidence_events(result, events) == [EventType.ROLE_STAGE_COMPLETED]


# ---------------------------------------------------------------------------------------------
# 8. RESOURCE_SELECTION
# ---------------------------------------------------------------------------------------------


def test_resource_selection_awards_full_points_when_every_requirement_is_met() -> None:
    result = run(DEMO_RULES["resources_fire_high_rise"], good_log())

    assert result.points_awarded == 12.0
    assert result.passed


def test_resource_selection_does_not_count_an_off_service_unit_for_another_service() -> None:
    """Ruling R6: the police patrol is allowed, but it is not a second fire unit."""
    result = run(DEMO_RULES["resources_fire_high_rise"], mutate("off_service_unit"))

    assert result.points_awarded == -8.0
    assert not result.passed


def test_resource_selection_penalises_a_forbidden_unit() -> None:
    from tests.unit.domain.scoring._event_log_builders import det_uuid

    rule = rule_with(
        "resources_fire_high_rise",
        forbidden_resource_ids=[str(det_uuid("resource:al1"))],
        penalty_per_forbidden=-6.0,
    )

    result = run(rule, good_log())

    assert result.points_awarded == 6.0
    assert not result.passed


def test_resource_selection_must_be_dispatched_false_counts_selections() -> None:
    rule = rule_with("resources_fire_high_rise", must_be_dispatched=False)

    assert run(rule, good_log()).passed


def test_resource_selection_absence_points_at_the_closure_or_stage_bound() -> None:
    events = good_log(units=[GOOD_UNITS[2]])

    result = run(DEMO_RULES["resources_fire_high_rise"], events)

    assert not result.passed
    assert EventType.DDS_INCIDENT_CLOSED in evidence_events(result, events)


def test_resource_selection_min_units_by_service_shortfall_is_counted_per_unit() -> None:
    rule = rule_with(
        "resources_fire_high_rise",
        min_units_by_service={"FIRE_RESCUE": 4, "AMBULANCE": 1},
        penalty_per_missing=-1.0,
    )

    assert run(rule, good_log()).points_awarded == -2.0


# ---------------------------------------------------------------------------------------------
# 9. REQUIRED_STATUS_UPDATE
# ---------------------------------------------------------------------------------------------


def test_required_status_update_in_time() -> None:
    result = run(DEMO_RULES["status_on_scene_report"], good_log())

    assert result.points_awarded == 5.0
    assert result.passed


def _with_second_unanswered_status_change(
    *, second_status_update_ms: int | None
) -> tuple[SessionEvent, ...]:
    """`good_log()` plus a *second* `RESOURCE_STATUS_CHANGED` (H4, E20-H): each qualifying change
    opens its own window, so this is what makes the difference between "first reference in the
    whole log" (the pre-H4 reading) and "every reference" observable in a test — the first
    window (`ON_SCENE_MS`, answered by `STATUS_UPDATE_MS`) is always satisfied here; only the
    second one varies.
    """
    base = good_log()
    reference_template = next(
        event for event in base if event.event_type is EventType.RESOURCE_STATUS_CHANGED
    )
    update_template = next(
        event for event in base if event.event_type is EventType.DDS_STATUS_UPDATE_SENT
    )
    next_seq = max(event.seq_no for event in base) + 1
    second_reference_ms = ON_SCENE_MS + 100_000
    extra = [
        reference_template.model_copy(
            update={
                "id": EventId(det_uuid("event:second-status-change")),
                "seq_no": next_seq,
                "monotonic_offset_ms": second_reference_ms,
                "payload": {**reference_template.payload, "new_status": "WORKING"},
            }
        )
    ]
    if second_status_update_ms is not None:
        extra.append(
            update_template.model_copy(
                update={
                    "id": EventId(det_uuid("event:second-status-update")),
                    "seq_no": next_seq + 1,
                    "monotonic_offset_ms": second_status_update_ms,
                }
            )
        )
    return (*base, *extra)


def test_required_status_update_every_qualifying_change_needs_its_own_answer() -> None:
    """H4 (E20-H) bite proof: a second `RESOURCE_STATUS_CHANGED` with NO timely report of its own
    must fail the rule, even though the *first* one (which the pre-H4 code alone checked) was
    answered in time. Reverting `evaluate()` to `ctx.first_of_type(...)` / `updates[0]` (the
    pre-H4 shape) turns this green again — that is exactly the unsatisfiable-in-a-real-session bug
    E20-C's walk reproduced (`"Задержка … 279160 мс при норме 60000 мс"`), just inverted: here the
    *first* window is fine and the *second* is silently ignored instead of wrongly blocking
    everything.
    """
    events = _with_second_unanswered_status_change(second_status_update_ms=None)

    result = run(DEMO_RULES["status_on_scene_report"], events)

    assert not result.passed
    assert result.points_awarded == -2.0
    assert EventType.RESOURCE_STATUS_CHANGED in evidence_events(result, events)


def test_required_status_update_every_qualifying_change_answered_in_time_passes() -> None:
    """Both windows answered in time: the rule passes and evidence lists both pairs."""
    events = _with_second_unanswered_status_change(
        second_status_update_ms=ON_SCENE_MS + 100_000 + 30_000
    )

    result = run(DEMO_RULES["status_on_scene_report"], events)

    assert result.passed
    assert result.points_awarded == 5.0
    assert evidence_events(result, events).count(EventType.DDS_STATUS_UPDATE_SENT) == 2


def test_required_status_update_at_exactly_the_limit_still_passes() -> None:
    events = good_log(status_update_ms=ON_SCENE_MS + 60_000)

    assert run(DEMO_RULES["status_on_scene_report"], events).passed


def test_required_status_update_one_millisecond_late_fails() -> None:
    events = good_log(status_update_ms=ON_SCENE_MS + 60_001)

    result = run(DEMO_RULES["status_on_scene_report"], events)

    assert not result.passed
    assert result.points_awarded == -2.0


def test_required_status_update_before_the_reference_event_does_not_count() -> None:
    events = good_log(status_update_ms=ON_SCENE_MS - 1_000)

    assert not run(DEMO_RULES["status_on_scene_report"], events).passed


def test_required_status_update_missing_points_at_the_missed_window() -> None:
    """H4 (E20-H): the reference event (`RESOURCE_STATUS_CHANGED`, the qualifying change whose
    window went unanswered) is now the evidence, not a generic stage-bound fallback — the rule
    still has a reference event, it just never got a matching report (§10.14 #9)."""
    events = mutate("missing_status_update")

    result = run(DEMO_RULES["status_on_scene_report"], events)

    assert not result.passed
    assert evidence_events(result, events) == [EventType.RESOURCE_STATUS_CHANGED]


def test_required_status_update_with_no_reference_event_at_all_points_at_the_stage_bound() -> None:
    """The pre-existing "event never happened" reading (§10.14) stays: no `RESOURCE_STATUS_CHANGED`
    at all means no window was ever opened, so the rule falls back to the stage-bound evidence."""
    events = tuple(
        event
        for event in mutate("missing_status_update")
        if event.event_type is not EventType.RESOURCE_STATUS_CHANGED
    )

    result = run(DEMO_RULES["status_on_scene_report"], events)

    assert not result.passed
    assert evidence_events(result, events) == [EventType.ROLE_STAGE_COMPLETED]


def test_required_status_update_without_timing_config_only_counts() -> None:
    rule = rule_with("status_on_scene_report", within_ms=None, within_ms_of_event=None)
    events = good_log(status_update_ms=ON_SCENE_MS - 1_000)

    assert run(rule, events).passed


# ---------------------------------------------------------------------------------------------
# 10. HANDOFF_COMPLETENESS
# ---------------------------------------------------------------------------------------------


def test_handoff_completeness_awards_per_present_field() -> None:
    result = run(DEMO_RULES["handoff_minimum_fields"], good_log())

    assert result.points_awarded == 12.0
    assert result.passed
    assert result.evidence[0].snapshot_id is not None


def test_handoff_completeness_counts_a_missing_field_and_names_it() -> None:
    card = {key: value for key, value in GOOD_CARD_VALUES.items() if key != "address.apartment"}

    result = run(DEMO_RULES["handoff_minimum_fields"], good_log(card_values=card))

    assert result.points_awarded == 10.0
    assert not result.passed
    assert any("address.apartment" in item.note_ru for item in result.evidence)


def test_handoff_completeness_all_or_nothing() -> None:
    card = {key: value for key, value in GOOD_CARD_VALUES.items() if key != "address.apartment"}
    rule = rule_with("handoff_minimum_fields", all_or_nothing=True)

    assert run(rule, good_log()).points_awarded == 12.0
    assert run(rule, good_log(card_values=card)).points_awarded == 0.0


def test_handoff_completeness_reads_the_snapshot_not_the_live_card() -> None:
    """D3: the handoff is a frozen copy; a later card edit cannot repair it."""
    handed_over = {
        key: value for key, value in GOOD_CARD_VALUES.items() if key != "description.text"
    }
    events = good_log(card_values=handed_over)

    result = run(DEMO_RULES["handoff_minimum_fields"], events)

    assert result.points_awarded == 10.0


def test_handoff_completeness_without_a_handoff_scores_every_field_missing() -> None:
    events = dds_only_log()

    result = run(DEMO_RULES["handoff_minimum_fields"], events)

    assert result.points_awarded == 0.0
    assert not result.passed
    assert evidence_events(result, events)[0] is EventType.ROLE_STAGE_COMPLETED


# ---------------------------------------------------------------------------------------------
# The registry is total
# ---------------------------------------------------------------------------------------------


def test_registry_maps_every_evaluator_type_to_an_evaluate() -> None:
    assert frozenset(EVALUATORS) == frozenset(EvaluatorType)


def test_every_demo_rule_produces_at_least_its_min_evidence() -> None:
    for rule in SCENARIO.scoring_rules:
        result = run(rule, good_log())
        assert len(result.evidence) >= max(1, rule.min_evidence), rule.rule_id


def test_bounding_event_is_required_for_an_absence() -> None:
    """A log that was scored before `SESSION_COMPLETED` cannot evidence an absence (ruling R2)."""
    truncated = [
        event
        for event in mutate("fact_never_delivered")
        if event.event_type not in {EventType.ROLE_STAGE_COMPLETED, EventType.SESSION_COMPLETED}
    ]

    with pytest.raises(ScoringEvidenceError):
        run(DEMO_RULES["fact_victim_inside"], truncated)


def test_service_ids_are_what_the_payloads_carry() -> None:
    """Guards the builder: the units' services are legacy catalog ids, verbatim (D18)."""
    assert {service for _, service, _ in GOOD_UNITS} <= set(LEGACY_SERVICE_IDS)

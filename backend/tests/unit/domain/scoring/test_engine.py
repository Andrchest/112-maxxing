"""`score`, `report_checksum`, `scoring_events` (HLD §10.14, D11, SPEC §28).

The engine owns four things no evaluator may decide for itself: applicability (ruling R7), the
single rounding step (R10), the evidence requirement (R3) and the shape of the totals. Each gets
its own test here; the per-evaluator arithmetic lives in `test_evaluators.py`.
"""

from __future__ import annotations

import pytest
from app.domain.enums import ActorType, EvaluatorType, RoleType, ScoringCategory
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.context import UnorderedEventLogError
from app.domain.scoring.engine import (
    NOT_APPLICABLE_NOTE_RU,
    NOT_APPLICABLE_VARIANT_NOTE_RU,
    ScoringEvidenceError,
    report_checksum,
    score,
    scoring_events,
)
from app.domain.scoring.evaluators import registry
from app.domain.scoring.results import ScoreEvidence, ScoreResult
from app.domain.scoring.rules import ScoringRule

from tests.unit.domain.scoring._event_log_builders import (
    dds_only_log,
    demo_scenario,
    good_log,
    mutate,
)

SCENARIO = demo_scenario()


def test_good_run_scores_every_rule_with_evidence() -> None:
    report = score(SCENARIO, good_log())

    assert len(report.results) == len(SCENARIO.scoring_rules)
    assert report.total_points == 74.0
    assert report.total_max_points == 78.0
    assert report.critical_errors == ()
    assert all(result.evidence for result in report.results)


def test_totals_are_the_sum_of_the_results() -> None:
    report = score(SCENARIO, mutate("wrong_house_number"))

    assert report.total_points == pytest.approx(
        sum(result.points_awarded for result in report.results)
    )
    assert report.total_max_points == pytest.approx(
        sum(result.max_points for result in report.results)
    )


def test_by_category_is_in_enum_order_and_only_for_categories_that_have_a_rule() -> None:
    report = score(SCENARIO, good_log())

    categories = [total.category for total in report.by_category]
    used = {rule.category for rule in SCENARIO.scoring_rules}

    assert categories == [member for member in ScoringCategory if member in used]
    assert set(categories) == used


def test_by_category_subtotals_match_their_results() -> None:
    report = score(SCENARIO, mutate("forbidden_service"))

    for total in report.by_category:
        matching = [r for r in report.results if r.category is total.category]
        assert total.points_awarded == pytest.approx(sum(r.points_awarded for r in matching))
        assert total.max_points == pytest.approx(sum(r.max_points for r in matching))


def test_critical_errors_are_the_results_with_a_critical_failure() -> None:
    report = score(SCENARIO, mutate("wrong_house_number"))

    assert [result.rule_id for result in report.critical_errors] == ["card_house_correct"]
    assert all(result.critical_failure for result in report.critical_errors)


def test_a_passed_critical_rule_is_not_a_critical_error() -> None:
    report = score(SCENARIO, good_log())

    assert any(rule.critical for rule in SCENARIO.scoring_rules)
    assert report.critical_errors == ()


def test_points_are_rounded_to_two_decimals() -> None:
    """`score_results.points_awarded` is `numeric(8,2)`: the domain rounds to match (R10)."""
    report = score(SCENARIO, good_log(handoff_ms=5_000 + 359_999))

    for result in report.results:
        assert round(result.points_awarded, 2) == result.points_awarded
    assert round(report.total_points, 2) == report.total_points


def test_computed_from_event_count_counts_what_was_read() -> None:
    events = good_log()

    report = score(SCENARIO, events)

    assert report.computed_from_event_count == len(events)


def test_unordered_input_raises() -> None:
    events = list(good_log())

    with pytest.raises(UnorderedEventLogError):
        score(SCENARIO, [*events[:3], events[4], events[3], *events[5:]])


def test_empty_log_raises_rather_than_scoring_nothing() -> None:
    with pytest.raises(ScoringEvidenceError):
        score(SCENARIO, [])


# ---------------------------------------------------------------------------------------------
# Applicability (ruling R7)
# ---------------------------------------------------------------------------------------------


def test_a_rule_whose_roles_are_absent_from_the_chain_is_not_applicable() -> None:
    report = score(SCENARIO, dds_only_log())
    by_rule = {result.rule_id: result for result in report.results}

    skipped = by_rule["card_house_correct"]

    assert skipped.points_awarded == 0.0
    assert skipped.max_points == 0.0
    assert skipped.passed
    assert not skipped.critical_failure
    assert [item.note_ru for item in skipped.evidence] == [NOT_APPLICABLE_NOTE_RU]


def test_a_non_applicable_rule_changes_neither_totals_nor_critical_errors() -> None:
    report = score(SCENARIO, dds_only_log())
    dds_rules = [
        rule
        for rule in SCENARIO.scoring_rules
        if not rule.applies_to_roles or RoleType.DDS in rule.applies_to_roles
    ]

    assert report.total_max_points == pytest.approx(sum(rule.max_points for rule in dds_rules))
    assert report.critical_errors == ()


def test_the_not_applicable_evidence_points_at_the_chain_recording_event() -> None:
    events = dds_only_log()
    report = score(SCENARIO, events)
    by_id = {event.id: event for event in events}

    skipped = next(result for result in report.results if result.max_points == 0.0)
    referenced = by_id[skipped.evidence[0].event_id]

    assert referenced.event_type is EventType.SESSION_CREATED
    assert referenced.payload["role_chain"] == ["DDS"]


def test_an_empty_applies_to_roles_always_applies() -> None:
    always = SCENARIO.scoring_rules[0].model_copy(update={"applies_to_roles": ()})
    version = SCENARIO.model_copy(update={"scoring_rules": (always,)})

    report = score(version, dds_only_log())

    assert report.results[0].max_points == always.max_points


# ---------------------------------------------------------------------------------------------
# Applicability by variant (HLD 70 §70.2.5, D14)
# ---------------------------------------------------------------------------------------------


def _one_rule_version(
    applies_to_variants: dict[str, tuple[str, ...]],
) -> tuple[ScoringRule, ScenarioVersion]:
    rule = SCENARIO.scoring_rules[0].model_copy(
        update={"applies_to_roles": (), "applies_to_variants": applies_to_variants}
    )
    return rule, SCENARIO.model_copy(update={"scoring_rules": (rule,)})


def _recording(variants: dict[str, str]) -> tuple[SessionEvent, ...]:
    events = good_log()
    created = events[0].model_copy(update={"payload": {**events[0].payload, "variants": variants}})
    return (created, *events[1:])


GENERATED = {
    "card_source": "GENERATED_CARD",
    "dds_mode": "RESOURCE_PICKER",
    "dds_card_check": "OFF",
    "dds_brigade_call": "OFF",
}


def test_a_rule_for_another_variant_yields_zero_zero() -> None:
    """A memo-only rule on a picker session: zero/zero, passed, no critical failure (§70.2.5)."""
    rule, version = _one_rule_version({"dds_mode": ("MEMO_STATUSES",)})
    critical = rule.model_copy(update={"critical": True})
    version = SCENARIO.model_copy(update={"scoring_rules": (critical,)})

    report = score(version, good_log())
    result = report.results[0]

    assert (result.points_awarded, result.max_points) == (0.0, 0.0)
    assert result.passed
    assert not result.critical_failure
    assert report.total_max_points == 0.0
    assert report.critical_errors == ()
    assert [item.note_ru for item in result.evidence] == [NOT_APPLICABLE_VARIANT_NOTE_RU]


def test_a_rule_for_the_sessions_variant_applies() -> None:
    rule, version = _one_rule_version({"dds_mode": ("RESOURCE_PICKER", "MEMO_STATUSES")})

    report = score(version, good_log())

    assert report.results[0].max_points == rule.max_points


def test_the_recorded_variants_decide_not_the_scenario_default() -> None:
    """`SESSION_CREATED.variants` is the source; a pre-E1 log falls back to the derivation."""
    _rule, version = _one_rule_version({"card_source": ("CALLER_VOICE",)})

    derived = score(version, good_log())
    recorded = score(version, _recording(GENERATED))

    assert derived.results[0].max_points > 0.0
    assert recorded.results[0].max_points == 0.0


def test_every_named_switch_must_match() -> None:
    _rule, version = _one_rule_version(
        {"card_source": ("GENERATED_CARD",), "dds_card_check": ("ON",)}
    )

    report = score(version, _recording(GENERATED))

    assert report.results[0].max_points == 0.0


def test_applies_to_variants_defaults_to_empty() -> None:
    assert SCENARIO.scoring_rules[0].applies_to_variants == {}


# ---------------------------------------------------------------------------------------------
# Evidence enforcement (ruling R3)
# ---------------------------------------------------------------------------------------------


def test_a_rule_that_wants_more_evidence_than_it_gets_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    greedy = SCENARIO.scoring_rules[0].model_copy(update={"min_evidence": 4})
    version = SCENARIO.model_copy(update={"scoring_rules": (greedy,)})

    with pytest.raises(ScoringEvidenceError, match="min_evidence"):
        score(version, good_log())


def test_an_evaluator_that_returns_no_evidence_cannot_even_build_a_result() -> None:
    """The `ScoreResult` model itself refuses (SPEC §28, §42 test 11)."""
    with pytest.raises(ValueError, match="evidence"):
        ScoreResult(
            rule_id="x",
            evaluator_type=EvaluatorType.FACT_OBTAINED,
            category=ScoringCategory.WORKFLOW,
            points_awarded=10.0,
            max_points=10.0,
            passed=True,
            critical_failure=False,
            evidence=(),
        )


def test_score_evidence_requires_exactly_one_reference() -> None:
    from uuid import uuid5

    some_id = uuid5(SCENARIO.id, "x")

    with pytest.raises(ValueError, match="exactly one"):
        ScoreEvidence(note_ru="нет ссылки")
    with pytest.raises(ValueError, match="exactly one"):
        ScoreEvidence(event_id=some_id, snapshot_id=some_id, note_ru="две ссылки")


# ---------------------------------------------------------------------------------------------
# Checksum (ruling R8)
# ---------------------------------------------------------------------------------------------


def test_checksum_is_stable_and_distinguishes_different_numbers() -> None:
    good = score(SCENARIO, good_log())
    wrong = score(SCENARIO, mutate("wrong_house_number"))

    assert report_checksum(good) == report_checksum(score(SCENARIO, good_log()))
    assert report_checksum(good) != report_checksum(wrong)
    assert len(report_checksum(good)) == 64


def test_checksum_ignores_evidence_wording() -> None:
    """It answers "are the numbers the same", which is what `rescoreSession` compares."""
    report = score(SCENARIO, good_log())
    reworded = report.model_copy(
        update={
            "results": tuple(
                result.model_copy(
                    update={
                        "evidence": tuple(
                            item.model_copy(update={"note_ru": "совершенно другой текст"})
                            for item in result.evidence
                        )
                    }
                )
                for result in report.results
            )
        }
    )

    assert report_checksum(report) == report_checksum(reworded)


# ---------------------------------------------------------------------------------------------
# `scoring_events` (§10.13 catalog row)
# ---------------------------------------------------------------------------------------------


def test_scoring_events_are_one_per_result_in_rule_order() -> None:
    report = score(SCENARIO, good_log())

    events = scoring_events(report, SCENARIO, monotonic_offset_ms=600_000)

    assert len(events) == len(report.results)
    assert [event.payload["rule_id"] for event in events] == [
        rule.rule_id for rule in SCENARIO.scoring_rules
    ]
    assert all(event.event_type is EventType.SCORING_RULE_EVALUATED for event in events)
    assert all(event.actor.actor_type is ActorType.SYSTEM for event in events)


def test_scoring_event_payload_matches_the_catalog_keys() -> None:
    from app.domain.events.catalog import EVENT_PAYLOAD_CATALOG

    report = score(SCENARIO, good_log())
    event = scoring_events(report, SCENARIO, monotonic_offset_ms=0)[0]
    spec = EVENT_PAYLOAD_CATALOG[EventType.SCORING_RULE_EVALUATED]

    assert set(event.payload) == set(spec.payload_keys)
    assert event.payload["critical"] is SCENARIO.scoring_rules[0].critical
    assert event.payload["evidence"]


def test_scoring_events_are_pure_and_repeatable() -> None:
    report = score(SCENARIO, good_log())

    first = scoring_events(report, SCENARIO, monotonic_offset_ms=600_000)
    second = scoring_events(report, SCENARIO, monotonic_offset_ms=600_000)

    assert first == second


# ---------------------------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------------------------


def test_every_rule_of_the_demo_scenario_dispatches_to_its_evaluator() -> None:
    report = score(SCENARIO, good_log())

    assert {result.evaluator_type for result in report.results} == frozenset(EvaluatorType)
    assert frozenset(registry.EVALUATORS) == frozenset(EvaluatorType)


def test_applies_to_roles_defaults_to_empty() -> None:
    rule = ScoringRule(
        rule_id="x",
        name_ru="x",
        description_ru="x",
        category=ScoringCategory.WORKFLOW,
        max_points=1.0,
        critical=False,
        evaluator_type=EvaluatorType.FACT_OBTAINED,
        config={"fact_id": "a", "within_ms": None, "points": 1.0},
    )

    assert rule.applies_to_roles == ()

"""`report_rule_text` (I7 E49, Q-E31-1): a `DEADLINE` rule whose norm is a named timer
(`max_offset_timer`) shows its ACTUAL recorded value in the report, never the scenario's literal
wording — and every other rule (or `DEADLINE` with a literal `max_offset_ms`) is untouched."""

from __future__ import annotations

from app.application.reports.rule_text import report_rule_text
from app.domain.dds.card_status import CardTimers
from app.domain.enums import EvaluatorType, ScoringCategory
from app.domain.scoring.rules import ScoringRule

DEFAULT_TIMERS = CardTimers()


def _deadline_rule(
    *, max_offset_ms: int | None = None, max_offset_timer: str | None = None
) -> ScoringRule:
    return ScoringRule(
        rule_id="dds_acknowledged_in_time",
        name_ru="Карточка принята в течение 30 секунд",
        description_ru="От поступления карточки в ДДС до её принятия — не более 30 секунд.",
        category=ScoringCategory.TIMELINESS,
        max_points=4.0,
        critical=False,
        evaluator_type=EvaluatorType.DEADLINE,
        config={
            "from_event_type": "HANDOFF_RECEIVED",
            "to_event_type": "DDS_ACKNOWLEDGED",
            "to_payload_match": None,
            "max_offset_ms": max_offset_ms,
            "max_offset_timer": max_offset_timer,
            "points": 4.0,
            "penalty_if_late": -2.0,
            "scale": "STEP",
            "linear_zero_ms": None,
        },
    )


def test_a_named_timer_rule_shows_the_default_unchanged_at_the_default() -> None:
    rule = _deadline_rule(max_offset_timer="accept_within_ms")
    name_ru, description_ru = report_rule_text(rule, DEFAULT_TIMERS)
    assert name_ru == rule.name_ru
    assert description_ru == rule.description_ru


def test_a_named_timer_rule_shows_the_overridden_value() -> None:
    rule = _deadline_rule(max_offset_timer="accept_within_ms")
    overridden = CardTimers(accept_within_ms=45_000)

    name_ru, description_ru = report_rule_text(rule, overridden)

    assert name_ru == "Карточка принята в течение 45 секунд"
    assert description_ru == "От поступления карточки в ДДС до её принятия — не более 45 секунд."


def test_a_literal_norm_rule_is_never_rewritten() -> None:
    """`max_offset_ms` (no named timer): the text is the scenario's own, regardless of `timers`."""
    rule = _deadline_rule(max_offset_ms=30_000)
    overridden = CardTimers(accept_within_ms=45_000)

    name_ru, description_ru = report_rule_text(rule, overridden)

    assert name_ru == rule.name_ru
    assert description_ru == rule.description_ru


def test_a_non_deadline_rule_is_never_rewritten() -> None:
    rule = ScoringRule(
        rule_id="x",
        name_ru="30 секунд is not a norm here",
        description_ru="x",
        category=ScoringCategory.WORKFLOW,
        max_points=1.0,
        critical=False,
        evaluator_type=EvaluatorType.FACT_OBTAINED,
        config={"fact_id": "a", "within_ms": None, "points": 1.0},
    )
    overridden = CardTimers(accept_within_ms=45_000)

    name_ru, description_ru = report_rule_text(rule, overridden)

    assert name_ru == rule.name_ru
    assert description_ru == rule.description_ru


def test_declension_of_the_substituted_seconds() -> None:
    rule = _deadline_rule(max_offset_timer="accept_within_ms")
    cases = {
        1: "1 секунда",
        2: "2 секунды",
        5: "5 секунд",
        11: "11 секунд",
        21: "21 секунда",
        25: "25 секунд",
    }
    for seconds, word in cases.items():
        name_ru, _ = report_rule_text(rule, CardTimers(accept_within_ms=seconds * 1000))
        assert word in name_ru, (seconds, name_ru)

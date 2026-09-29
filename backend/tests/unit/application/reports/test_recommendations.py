"""«Рекомендации по улучшению навыков» — G10 (I7 E54): advice selection, dedup, ordering.

Pure over `ScoreResult`/`ScoringRule` — no database, no event log.
"""

from __future__ import annotations

from uuid import UUID

from app.application.reports.recommendations import (
    MAX_RECOMMENDATIONS,
    Recommendation,
    session_recommendations,
)
from app.domain.common.ids import EventId
from app.domain.enums import EvaluatorType, ScoringCategory
from app.domain.scoring.results import ScoreEvidence, ScoreResult
from app.domain.scoring.rules import ScoringRule

DEFAULTS = {
    ScoringCategory.INFORMATION_GATHERING: "Соберите все факты.",
    ScoringCategory.CARD_QUALITY: "Заполняйте карточку точно.",
    ScoringCategory.SERVICE_ROUTING: "Выбирайте нужную службу.",
    ScoringCategory.TIMELINESS: "Соблюдайте нормативы времени.",
    ScoringCategory.WORKFLOW: "Проходите все шаги по порядку.",
    ScoringCategory.RESOURCE_MANAGEMENT: "Направляйте достаточно ресурсов.",
    ScoringCategory.COMMUNICATION: "Говорите по существу.",
}

_EVIDENCE = (ScoreEvidence(event_id=EventId(UUID(int=1)), seq_no=1, note_ru="x"),)


def _rule(rule_id: str, category: ScoringCategory, *, advice: str | None = None) -> ScoringRule:
    return ScoringRule(
        rule_id=rule_id,
        name_ru=rule_id,
        description_ru=rule_id,
        category=category,
        max_points=10,
        critical=False,
        evaluator_type=EvaluatorType.FACT_OBTAINED,
        config={},
        advice=advice,
    )


def _result(
    rule_id: str,
    category: ScoringCategory,
    *,
    points_awarded: float,
    max_points: float = 10,
    passed: bool,
) -> ScoreResult:
    return ScoreResult(
        rule_id=rule_id,
        evaluator_type=EvaluatorType.FACT_OBTAINED,
        category=category,
        points_awarded=points_awarded,
        max_points=max_points,
        passed=passed,
        critical_failure=False,
        evidence=_EVIDENCE,
    )


def test_nothing_failed_yields_no_recommendations() -> None:
    rules = {"r1": _rule("r1", ScoringCategory.CARD_QUALITY)}
    results = [_result("r1", ScoringCategory.CARD_QUALITY, points_awarded=10, passed=True)]
    assert session_recommendations(results, rules, DEFAULTS) == ()


def test_a_failed_rule_gets_its_category_default() -> None:
    rules = {"r1": _rule("r1", ScoringCategory.CARD_QUALITY)}
    results = [_result("r1", ScoringCategory.CARD_QUALITY, points_awarded=0, passed=False)]
    out = session_recommendations(results, rules, DEFAULTS)
    assert out == (
        Recommendation(ScoringCategory.CARD_QUALITY, DEFAULTS[ScoringCategory.CARD_QUALITY]),
    )


def test_a_rule_s_own_advice_overrides_the_category_default() -> None:
    rules = {"r1": _rule("r1", ScoringCategory.CARD_QUALITY, advice="Проверьте адрес дважды.")}
    results = [_result("r1", ScoringCategory.CARD_QUALITY, points_awarded=0, passed=False)]
    out = session_recommendations(results, rules, DEFAULTS)
    assert out == (Recommendation(ScoringCategory.CARD_QUALITY, "Проверьте адрес дважды."),)


def test_two_failed_rules_of_the_same_category_dedup_to_one_line() -> None:
    rules = {
        "r1": _rule("r1", ScoringCategory.CARD_QUALITY),
        "r2": _rule("r2", ScoringCategory.CARD_QUALITY),
    }
    results = [
        _result("r1", ScoringCategory.CARD_QUALITY, points_awarded=0, passed=False),
        _result("r2", ScoringCategory.CARD_QUALITY, points_awarded=5, passed=False),
    ]
    out = session_recommendations(results, rules, DEFAULTS)
    assert len(out) == 1
    assert out[0].category is ScoringCategory.CARD_QUALITY


def test_the_worst_rule_of_a_category_decides_the_override() -> None:
    """Two failed rules, same category, different `advice`: the one that lost the most points
    wins, not authoring order."""
    rules = {
        "cheap": _rule("cheap", ScoringCategory.CARD_QUALITY, advice="Дешёвый совет."),
        "costly": _rule("costly", ScoringCategory.CARD_QUALITY, advice="Дорогой совет."),
    }
    results = [
        _result(
            "cheap", ScoringCategory.CARD_QUALITY, points_awarded=9, max_points=10, passed=False
        ),
        _result(
            "costly", ScoringCategory.CARD_QUALITY, points_awarded=0, max_points=10, passed=False
        ),
    ]
    out = session_recommendations(results, rules, DEFAULTS)
    assert out == (Recommendation(ScoringCategory.CARD_QUALITY, "Дорогой совет."),)


def test_ordering_is_most_penalised_category_first() -> None:
    rules = {
        "light": _rule("light", ScoringCategory.COMMUNICATION),
        "heavy": _rule("heavy", ScoringCategory.CARD_QUALITY),
    }
    results = [
        _result(
            "light", ScoringCategory.COMMUNICATION, points_awarded=8, max_points=10, passed=False
        ),
        _result(
            "heavy", ScoringCategory.CARD_QUALITY, points_awarded=0, max_points=10, passed=False
        ),
    ]
    out = session_recommendations(results, rules, DEFAULTS)
    assert [r.category for r in out] == [
        ScoringCategory.CARD_QUALITY,
        ScoringCategory.COMMUNICATION,
    ]


def test_capped_at_five_even_with_seven_failed_categories() -> None:
    rules = {category.value: _rule(category.value, category) for category in ScoringCategory}
    results = [
        _result(category.value, category, points_awarded=0, passed=False)
        for category in ScoringCategory
    ]
    out = session_recommendations(results, rules, DEFAULTS)
    assert len(out) == MAX_RECOMMENDATIONS


def test_missing_default_and_no_override_is_silently_skipped() -> None:
    """A category with neither an override nor a pinned default (a fixture with a partial
    `defaults` map) never crashes and contributes no line."""
    rules = {"r1": _rule("r1", ScoringCategory.CARD_QUALITY)}
    results = [_result("r1", ScoringCategory.CARD_QUALITY, points_awarded=0, passed=False)]
    assert session_recommendations(results, rules, {}) == ()

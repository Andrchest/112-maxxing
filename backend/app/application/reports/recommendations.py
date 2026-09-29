"""`session_recommendations` — «Рекомендации по улучшению навыков», G10 (ТЗ ¶267, ¶237, final
criteria ¶460/¶469, I7 E54, manager decision `reports/i7/E42-gaps.md` §2 item 8).

Deterministic, no ML: one Russian line per `ScoringCategory` the session lost points in, worst
category first, capped at `MAX_RECOMMENDATIONS` — the report section shows no more than that. Two
failed rules of the same category collapse into the category's one line (dedup); the line is the
scenario-authored `advice` of whichever failed rule in that category lost the most points (a rule's
own override, R45, ≤300 chars), or the pinned default of `reference/advice/v1.yaml`
(`app.infrastructure.reference.advice_catalog`) when none of them set one.

Pure and read-only over already-scored, already-loaded data — the same reading
`assemble_report._stored_report` and `pass_verdict` give: this module never touches
`ScoreResult`/`ScoreReport`, never runs an evaluator and is never part of `report_checksum` (D11).
A session with nothing failed gets no lines at all (`SessionReportSchema`'s empty-array reads as
«Замечаний нет» in the UI, never a fabricated "well done").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.enums import ScoringCategory
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule

__all__ = ["MAX_RECOMMENDATIONS", "Recommendation", "session_recommendations"]

MAX_RECOMMENDATIONS = 5


@dataclass(frozen=True, slots=True)
class Recommendation:
    """One report line: `category`'s advice, chosen per the module doc."""

    category: ScoringCategory
    text_ru: str


def session_recommendations(
    results: Sequence[ScoreResult],
    rules_by_id: Mapping[str, ScoringRule],
    defaults: Mapping[ScoringCategory, str],
) -> tuple[Recommendation, ...]:
    """One `Recommendation` per category with a failed result in `results`, most points lost
    first (ties broken by the category's own wire value, for a total order), capped at
    `MAX_RECOMMENDATIONS`. `results` is whichever list the caller already narrowed to what this
    viewer may see (`assemble_report._visible_report`) — this function itself applies no
    visibility rule of its own."""
    lost_by_category: dict[ScoringCategory, float] = {}
    best_override: dict[ScoringCategory, tuple[float, str, str | None]] = {}
    for result in results:
        if result.passed:
            continue
        penalty = result.max_points - result.points_awarded
        lost_by_category[result.category] = lost_by_category.get(result.category, 0.0) + penalty
        rule = rules_by_id.get(result.rule_id)
        advice = rule.advice if rule is not None else None
        current = best_override.get(result.category)
        # The failed rule that lost the most points in this category decides the override; ties
        # broken by `rule_id` so the choice does not depend on dict/list iteration order.
        if current is None or (penalty, result.rule_id) > (current[0], current[1]):
            best_override[result.category] = (penalty, result.rule_id, advice)

    ordered = sorted(lost_by_category.items(), key=lambda item: (-item[1], item[0].value))[
        :MAX_RECOMMENDATIONS
    ]

    out: list[Recommendation] = []
    for category, _penalty in ordered:
        override = best_override[category][2]
        text = override if override else defaults.get(category)
        if text:
            out.append(Recommendation(category=category, text_ru=text))
    return tuple(out)

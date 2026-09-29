"""Report-only rule text with the session's actual timer value substituted (I7 E49, Q-E31-1).

A `DEADLINE` rule whose norm is a named timer (`max_offset_timer`, rule R44, I4 E31) writes its
`name_ru`/`description_ru` against a fixed number of seconds — e.g. "в течение 30 секунд" —
because the scenario document is the rule's only home and it cannot know what a session or lesson
entry will later override that timer to (`app.domain.scenario.timers.resolve_card_timers`). The
report is the one place that does know: `SESSION_CREATED.timers`
(`app.application.reports.norms.recorded_timers`), the same value the `DEADLINE` evaluator itself
already scores against (`app.domain.scoring.evaluators.deadline._norm_ms`). `report_rule_text`
rewrites every "<N> секунд..." mention in the literal text to that real value, in whole seconds,
correctly declined (секунда/секунды/секунд).

Scores are untouched by this module — it runs only when the report is rendered, strictly after
the stored `ScoreResult` rows are read (`assemble_report._stored_report`); it changes what the
report **says** about a norm that was already scored against the right number, never the number
itself, the checksum, or any stored row.
"""

from __future__ import annotations

import re

from pydantic import ValidationError

from app.domain.dds.card_status import CardTimers
from app.domain.scoring.evaluators.deadline import DeadlineConfig
from app.domain.scoring.evaluators.registry import parse_rule_config
from app.domain.scoring.rules import ScoringRule

__all__ = ["report_rule_text"]

_SECONDS_MENTION = re.compile(r"\d+\s+секунд[а-яё]*", re.IGNORECASE)


def report_rule_text(rule: ScoringRule, timers: CardTimers) -> tuple[str, str]:
    """`(name_ru, description_ru)`, with any timer mention rewritten to `timers`' real value.

    A rule that is not `DEADLINE` with a `max_offset_timer`, or whose text mentions no timer at
    all, comes back unchanged.
    """
    seconds = _timer_seconds(rule, timers)
    if seconds is None:
        return rule.name_ru, rule.description_ru
    replacement = _seconds_ru(seconds)
    return (
        _SECONDS_MENTION.sub(replacement, rule.name_ru),
        _SECONDS_MENTION.sub(replacement, rule.description_ru),
    )


def _timer_seconds(rule: ScoringRule, timers: CardTimers) -> int | None:
    """The rule's norm, in whole seconds, or `None` when it names no per-card timer."""
    try:
        config = parse_rule_config(rule)
    except ValidationError:  # pragma: no cover - a stored rule already passed §30.8 item 20
        return None
    if not isinstance(config, DeadlineConfig) or config.max_offset_timer is None:
        return None
    value = getattr(timers, config.max_offset_timer, None)
    if not isinstance(value, int):  # pragma: no cover - rule R44 refuses any other key
        return None
    return round(value / 1000)


def _seconds_ru(seconds: int) -> str:
    """A whole count of seconds, correctly declined: секунда/секунды/секунд."""
    hundred = seconds % 100
    ten = seconds % 10
    if 11 <= hundred <= 14:
        word = "секунд"
    elif ten == 1:
        word = "секунда"
    elif 2 <= ten <= 4:
        word = "секунды"
    else:
        word = "секунд"
    return f"{seconds} {word}"

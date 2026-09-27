"""«Сдал / не сдал» — the configurable pass criteria and the verdict (I5 E38, Q-E9b-3 variant г).

`PassCriteria` is what the instructor sets on a lesson (every card) or on a single session: three
independent criteria, each of which may be switched off —

* `min_score_percent` — the session's score percent must be at least this (`0…100`, `None` = off);
* `max_failed_rules` — at most this many rules may have failed (`>= 0`, `None` = off);
* `fail_on_critical` — any critical error means «не сдал» (`False` = off).

Defaults are `70`, `None`, `True`; at least one criterion must be on (`422 VALIDATION_ERROR`
otherwise — a verdict with nothing to check would pass everyone). `createSession` records the
criteria in `SESSION_CREATED.pass_criteria`, exactly as it records the resolved timers (I4 E31); a
log that records none (a session created before this epic) ran with the defaults.

**The verdict is derived, never stored, and never feeds the score.** `pass_verdict` reads the
stored totals and counters a report already shows — the percent is `score_percent`, the same
`100 · total_points / total_max_points` clamped to `0…100` the statistics show; a failed rule is a
stored result that did not pass; a critical error is a stored result with `critical_failure` —
and answers PASS iff every enabled criterion holds. Nothing in `app.domain.scoring` imports this
module: the score, its checksum and a rescore are what they were before the criteria existed.

A session whose `total_max_points` is not positive has no percent: the percent criterion, when on,
is then not met (there is no score to be at least the threshold).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.common.errors import DomainError

__all__ = [
    "DEFAULT_MIN_SCORE_PERCENT",
    "DEFAULT_PASS_CRITERIA",
    "PassCriteria",
    "PassCriteriaError",
    "PassCriterion",
    "PassVerdict",
    "pass_verdict",
    "score_percent",
]

DEFAULT_MIN_SCORE_PERCENT = 70
"""The default threshold of `min_score_percent` (the manager's decision, I5 E38)."""


class PassCriteriaError(DomainError):
    """Every criterion is switched off (`422 VALIDATION_ERROR`)."""

    code = "VALIDATION_ERROR"


class PassCriteria(BaseModel):
    """`openapi.yaml`'s `PassCriteriaRequest` / `PassCriteriaView`: the three criteria."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_score_percent: int | None = Field(default=DEFAULT_MIN_SCORE_PERCENT, ge=0, le=100)
    max_failed_rules: int | None = Field(default=None, ge=0)
    fail_on_critical: bool = True

    @model_validator(mode="after")
    def _at_least_one_criterion(self) -> Self:
        if (
            self.min_score_percent is None
            and self.max_failed_rules is None
            and not self.fail_on_critical
        ):
            raise PassCriteriaError(
                "pass_criteria: at least one criterion must be on (min_score_percent, "
                "max_failed_rules or fail_on_critical)"
            )
        return self


DEFAULT_PASS_CRITERIA = PassCriteria()
"""`70 %`, no failed-rule limit, a critical error fails — what an omitted request and an old log
mean."""


class PassCriterion(str, Enum):
    """`PassVerdictView.failed_criteria` items: which enabled criterion did not hold."""

    MIN_SCORE_PERCENT = "MIN_SCORE_PERCENT"
    MAX_FAILED_RULES = "MAX_FAILED_RULES"
    CRITICAL_ERRORS = "CRITICAL_ERRORS"


@dataclass(frozen=True, slots=True)
class PassVerdict:
    """The verdict of one scored session under its recorded criteria, with the numbers it read."""

    criteria: PassCriteria
    passed: bool
    failed_criteria: tuple[PassCriterion, ...]
    score_percent: float | None
    failed_rule_count: int
    critical_error_count: int


def score_percent(total_points: float, total_max_points: float) -> float | None:
    """`100 · total_points / total_max_points`, clamped to `0…100`; `None` for a zero maximum."""
    if total_max_points <= 0:
        return None
    percent = 100.0 * total_points / total_max_points
    return min(100.0, max(0.0, percent))


def pass_verdict(
    criteria: PassCriteria,
    *,
    total_points: float,
    total_max_points: float,
    failed_rule_count: int,
    critical_error_count: int,
) -> PassVerdict:
    """PASS iff every enabled criterion of `criteria` holds for these stored numbers."""
    percent = score_percent(total_points, total_max_points)
    failed: list[PassCriterion] = []
    if criteria.min_score_percent is not None and (
        percent is None or percent < criteria.min_score_percent
    ):
        failed.append(PassCriterion.MIN_SCORE_PERCENT)
    if criteria.max_failed_rules is not None and failed_rule_count > criteria.max_failed_rules:
        failed.append(PassCriterion.MAX_FAILED_RULES)
    if criteria.fail_on_critical and critical_error_count > 0:
        failed.append(PassCriterion.CRITICAL_ERRORS)
    return PassVerdict(
        criteria=criteria,
        passed=not failed,
        failed_criteria=tuple(failed),
        score_percent=percent,
        failed_rule_count=failed_rule_count,
        critical_error_count=critical_error_count,
    )

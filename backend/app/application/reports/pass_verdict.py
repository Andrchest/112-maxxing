"""«Сдал / не сдал» at report time (I5 E38, Q-E9b-3 variant г).

Pure: a read of `SESSION_CREATED.pass_criteria` plus the stored score numbers — no I/O, no
evaluator, no write. The criteria are the ones the session was created with (the lesson's, or the
single session's); a log without the key (a session created before I5 E38) ran with the defaults
(`DEFAULT_PASS_CRITERIA`: 70 %, no failed-rule limit, a critical error fails), exactly as
`norms.recorded_timers` reads a log without `timers`.

The verdict is `app.domain.session.pass_criteria.pass_verdict` over the **whole** stored report's
totals and counters — the same `failed_rule_count` / `critical_error_count` the lesson report shows
(`norms`) and the same percent the statistics show (`score_percent`). It is derived every time a
report is read and stored nowhere: the score rows, their checksum and a rescore never see it.
Only a scored session has one — an unscored (ABORTED) card has no verdict («—»).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from app.domain.events.types import EventType
from app.domain.session.pass_criteria import (
    DEFAULT_PASS_CRITERIA,
    PassCriteria,
    PassVerdict,
    pass_verdict,
)

__all__ = ["recorded_pass_criteria", "session_pass_verdict"]


class _Event(Protocol):
    @property
    def event_type(self) -> EventType: ...

    @property
    def payload(self) -> Mapping[str, Any]: ...


def recorded_pass_criteria(events: Iterable[_Event]) -> PassCriteria:
    """`SESSION_CREATED.pass_criteria`, or the defaults for a log that records none."""
    for event in events:
        if event.event_type is EventType.SESSION_CREATED:
            raw = event.payload.get("pass_criteria")
            if isinstance(raw, Mapping):
                return PassCriteria.model_validate(dict(raw))
            break
    return DEFAULT_PASS_CRITERIA


def session_pass_verdict(
    events: Iterable[_Event],
    *,
    total_points: float,
    total_max_points: float,
    failed_rule_count: int,
    critical_error_count: int,
) -> PassVerdict:
    """The verdict of one scored session: its recorded criteria over its stored numbers."""
    return pass_verdict(
        recorded_pass_criteria(events),
        total_points=total_points,
        total_max_points=total_max_points,
        failed_rule_count=failed_rule_count,
        critical_error_count=critical_error_count,
    )

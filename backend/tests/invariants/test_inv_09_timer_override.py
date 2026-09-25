"""INV 9 — "Scoring is reproducible without an LLM" — on a session with an overridden timer
(I4 E31, HLD 71 §71.8, D34).

The instructor's timer override is resolved at `createSession` and recorded in
`SESSION_CREATED.timers`; a `DEADLINE` rule with `max_offset_timer` reads it from there. So the
score is still a function of `(ScenarioVersion, events)` and nothing else:

* the same log scores identically twice, after a JSON round trip, and after the previous run's
  `SCORING_RULE_EVALUATED` events were appended (ruling R2) — same report, same checksum;
* the verdict follows the **recorded** value: the same actions under the same scenario version
  pass with a recorded 45 s and fail with a recorded 30 s. The number comes from the log, not from
  a setting, a clock or a lesson row.

The integration half (a real session created with `timers`, closed, and rescored over HTTP) is
`backend/tests/api/dds/test_timer_override.py`.
"""

from __future__ import annotations

from app.domain.events.session_event import SessionEvent
from app.domain.scoring.engine import report_checksum, score

from tests.unit.domain.scoring._event_log_builders import with_previous_scoring_events
from tests.unit.domain.scoring.test_deadline_timer import (
    DEFAULT_TIMERS,
    MEMO_RULE,
    SAMPLE,
    memo_log,
)

OVERRIDDEN = {**DEFAULT_TIMERS, "accept_within_ms": 45_000}


def _overridden_log() -> tuple[SessionEvent, ...]:
    """A decision 40 s after the card arrived, in a session run with a 45 s accept timer."""
    return memo_log(SAMPLE, decision_after_ms=40_000, timers=OVERRIDDEN)


def _memo_result(events: tuple[SessionEvent, ...]) -> tuple[float, bool]:
    report = score(SAMPLE, events)
    result = next(item for item in report.results if item.rule_id == MEMO_RULE)
    return result.points_awarded, result.passed


def test_an_overridden_session_scores_identically_twice() -> None:
    first = score(SAMPLE, _overridden_log())
    second = score(SAMPLE, _overridden_log())

    assert first == second
    assert report_checksum(first) == report_checksum(second)


def test_an_overridden_session_round_tripped_through_json_scores_identically() -> None:
    events = _overridden_log()
    restored = [SessionEvent.model_validate_json(event.model_dump_json()) for event in events]

    assert score(SAMPLE, restored) == score(SAMPLE, events)
    assert report_checksum(score(SAMPLE, restored)) == report_checksum(score(SAMPLE, events))


def test_rescoring_an_overridden_session_with_its_scoring_events_reproduces_the_report() -> None:
    events = _overridden_log()
    stored = with_previous_scoring_events(events, SAMPLE)

    assert len(stored) > len(events)
    assert score(SAMPLE, stored) == score(SAMPLE, events)
    assert report_checksum(score(SAMPLE, stored)) == report_checksum(score(SAMPLE, events))


def test_the_verdict_follows_the_recorded_timer() -> None:
    """Same scenario version, same actions: only `SESSION_CREATED.timers` differs."""
    assert _memo_result(_overridden_log()) == (4.0, True)
    assert _memo_result(memo_log(SAMPLE, decision_after_ms=40_000, timers=DEFAULT_TIMERS)) == (
        -2.0,
        False,
    )

"""INV 9/10 — the «сдал / не сдал» criteria never move a score (I5 E38, Q-E9b-3).

`SESSION_CREATED.pass_criteria` is read by the report paths only
(`app.application.reports.pass_verdict`): the same actions scored under any recorded criteria —
or under none, the shape of a session created before I5 E38 — give the same report and the same
checksum, including a rescore over a log that already carries the previous run's scoring events.
Structurally, nothing under `app.domain.scoring` imports `app.domain.session.pass_criteria`.

The integration half (two real lessons with different criteria, the same stored rows and
checksum, both rescoring `identical_to_stored`) is `backend/tests/api/lessons/test_pass_verdict.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring.engine import report_checksum, score

from tests.unit.domain.scoring._event_log_builders import with_previous_scoring_events
from tests.unit.domain.scoring.test_deadline_timer import SAMPLE, memo_log

SCORING_PACKAGE = Path(__file__).resolve().parents[2] / "app" / "domain" / "scoring"

CRITERIA: list[dict[str, Any] | None] = [
    None,
    {"min_score_percent": 70, "max_failed_rules": None, "fail_on_critical": True},
    {"min_score_percent": 100, "max_failed_rules": 0, "fail_on_critical": True},
    {"min_score_percent": None, "max_failed_rules": 5, "fail_on_critical": False},
]


def _log(criteria: dict[str, Any] | None) -> tuple[SessionEvent, ...]:
    """The timer tests' memo card (decision 40 s after arrival), with `criteria` recorded."""
    events = memo_log(SAMPLE, decision_after_ms=40_000)
    if criteria is None:
        return events
    return tuple(
        event.model_copy(update={"payload": {**event.payload, "pass_criteria": criteria}})
        if event.event_type is EventType.SESSION_CREATED
        else event
        for event in events
    )


@pytest.mark.parametrize("criteria", CRITERIA[1:])
def test_the_recorded_criteria_never_change_the_score_or_its_checksum(
    criteria: dict[str, Any],
) -> None:
    baseline = score(SAMPLE, _log(None))
    varied = score(SAMPLE, _log(criteria))
    assert varied == baseline
    assert report_checksum(varied) == report_checksum(baseline)


@pytest.mark.parametrize("criteria", CRITERIA)
def test_a_rescore_with_criteria_recorded_reproduces_the_report(
    criteria: dict[str, Any] | None,
) -> None:
    events = _log(criteria)
    stored = with_previous_scoring_events(events, SAMPLE)
    assert len(stored) > len(events)
    assert score(SAMPLE, stored) == score(SAMPLE, events)
    assert report_checksum(score(SAMPLE, stored)) == report_checksum(score(SAMPLE, events))


def test_no_scoring_module_imports_the_pass_criteria() -> None:
    offenders = [
        str(path.relative_to(SCORING_PACKAGE))
        for path in SCORING_PACKAGE.rglob("*.py")
        if "pass_criteria" in path.read_text("utf-8")
    ]
    assert offenders == []

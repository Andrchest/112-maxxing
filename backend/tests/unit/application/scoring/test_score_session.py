"""`compute_report` / `persist_score` / `score_session` (CHANGE item 3, R1-R3, epic E15-B).

Fakes only (`FakeUnitOfWork`): `compute_report` proves it touches only `uow.events` and
`uow.scenarios`, `score_session` proves the persisted rows and the appended events, both against
`good_log()` — a real, deterministic full 112 -> DDS cycle over the real demo scenario, scored by
the real `score()` (E15-A is done; no stub is needed here).
"""

from __future__ import annotations

import pytest
from app.application.scoring.score_session import (
    ScoreSessionPreconditionError,
    compute_report,
    persist_score,
    score_session,
    session_completed_offset,
)
from app.domain.enums import ActorType
from app.domain.events.types import EventType
from app.domain.scoring.engine import score
from app.domain.scoring.results import ScoreReport

from tests.unit.application.scoring._support import FakeUnitOfWork
from tests.unit.domain.scoring._event_log_builders import SESSION_ID, demo_scenario, good_log


async def test_compute_report_touches_only_events_and_scenarios() -> None:
    """CHANGE item 3: no materialized table, no `uow.sessions` (D5, R1)."""
    uow = FakeUnitOfWork(events=good_log())

    report, scenario_version, events = await compute_report(uow, SESSION_ID)

    assert not hasattr(uow, "sessions")
    assert report.session_id == SESSION_ID
    assert scenario_version.id == demo_scenario().id
    assert events == tuple(uow.events.events)
    assert report.results  # the real evaluators ran


async def test_compute_report_matches_calling_score_directly() -> None:
    """`compute_report` is a thin loader around the same pure `score()` a direct call uses."""
    uow = FakeUnitOfWork(events=good_log())
    report, _scenario_version, events = await compute_report(uow, SESSION_ID)
    assert report == score(demo_scenario(), events)


async def test_session_completed_offset_reads_the_bounding_event() -> None:
    events = good_log()
    completed = next(event for event in events if event.event_type is EventType.SESSION_COMPLETED)
    assert session_completed_offset(SESSION_ID, events) == completed.monotonic_offset_ms


async def test_session_completed_offset_raises_without_one() -> None:
    events = tuple(
        event for event in good_log() if event.event_type is not EventType.SESSION_COMPLETED
    )
    with pytest.raises(ScoreSessionPreconditionError):
        session_completed_offset(SESSION_ID, events)


async def test_score_session_persists_one_row_per_rule_and_appends_the_events() -> None:
    uow = FakeUnitOfWork(events=good_log())

    report = await score_session(uow, SESSION_ID)

    stored = await uow.scores.load_report(SESSION_ID)
    assert stored is not None
    assert len(stored) == len(demo_scenario().scoring_rules)
    assert [result.rule_id for result in stored] == [result.rule_id for result in report.results]

    scoring_type = EventType.SCORING_RULE_EVALUATED
    appended = [event for event in uow.events.events if event.event_type is scoring_type]
    assert len(appended) == len(demo_scenario().scoring_rules)
    assert all(event.actor_type is ActorType.SYSTEM for event in appended)
    # R2: every SCORING_RULE_EVALUATED comes after SESSION_COMPLETED, in the same unit of work.
    completed_type = EventType.SESSION_COMPLETED
    completed_seq = next(
        event.seq_no for event in uow.events.events if event.event_type is completed_type
    )
    assert all(event.seq_no > completed_seq for event in appended)
    # score_session itself never commits (the caller does) — matches every other use case here.
    assert uow.committed is False


async def test_score_session_does_not_commit_itself() -> None:
    """`score_session` never commits — a caller who forgets to commit loses nothing silently."""
    uow = FakeUnitOfWork(events=good_log())
    await score_session(uow, SESSION_ID)
    assert uow.committed is False


async def test_persist_score_is_a_no_op_write_when_the_report_has_no_results() -> None:
    """A scenario with zero scoring rules (not the demo one) must not blow up `scoring_events`."""
    uow = FakeUnitOfWork(events=good_log())
    scenario_version = demo_scenario()
    empty_report = ScoreReport(
        scenario_version_id=scenario_version.id,
        session_id=SESSION_ID,
        total_points=0.0,
        total_max_points=0.0,
        by_category=(),
        critical_errors=(),
        results=(),
        computed_from_event_count=0,
    )
    await persist_score(uow, SESSION_ID, scenario_version, empty_report, monotonic_offset_ms=0)
    assert await uow.scores.load_report(SESSION_ID) is None
    assert not [
        event for event in uow.events.events if event.event_type is EventType.SCORING_RULE_EVALUATED
    ]

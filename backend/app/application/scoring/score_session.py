"""`score_session` — compute and persist one session's `ScoreReport` (CHANGE item 3, R1-R3, R8).

`compute_report` is the read-only half D5/R1 demand: `(ScenarioVersion, ordered SessionEvents)`
and nothing else. It never reads `uow.sessions` or any other materialized table —
`scenario_version_id` comes from the log's own `SESSION_CREATED.scenario_version_id` (§10.13), the
one field every event payload carries redundantly with the aggregate precisely so a pure read of
the log alone can name it (D5: "every event payload must be self-sufficient for scoring"). A test
asserts `score_session` touches only `uow.events`, `uow.scenarios` and `uow.scores` (CHANGE item 3).

`persist_score` is the write half: `uow.scores.replace_for_session` first, then the
`SCORING_RULE_EVALUATED` events (R2's order — SESSION_COMPLETED has already been appended by the
caller before either half of this module runs), in the caller's own Unit of Work.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.application.ports.unit_of_work import UnitOfWork
from app.domain.common.ids import ScenarioVersionId, SessionId
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.engine import score, scoring_events
from app.domain.scoring.results import ScoreReport

__all__ = [
    "ScoreSessionPreconditionError",
    "compute_report",
    "persist_score",
    "score_session",
    "session_completed_offset",
]


class ScoreSessionPreconditionError(RuntimeError):
    """`score_session`'s own precondition was violated: the log is not a completed session's log.

    Not a `ProblemCode` — every caller that reaches `score_session` already guarantees this (the
    session-completion hook appends `SESSION_COMPLETED` in the same transaction just before
    calling it; `rescoreSession` checks `SessionState.COMPLETED` first), so this signals a bug in
    a caller, not a rejected request.
    """


async def compute_report(
    uow: UnitOfWork, session_id: SessionId
) -> tuple[ScoreReport, ScenarioVersion, tuple[SessionEvent, ...]]:
    """`score(scenario_version, events)` over the stored log; no write.

    Returns the `ScenarioVersion` and the events too: a caller that renders the report (the rule
    catalog's `name_ru` / `description_ru` are not on `ScoreResult` — only on `ScoringRule`) or
    that also needs `SESSION_COMPLETED`'s offset (this module's own `score_session`) does not read
    either a second time.
    """
    events = tuple(await uow.events.read(session_id))
    scenario_version_id = _scenario_version_id_of(session_id, events)
    document = await uow.scenarios.get_version_document(scenario_version_id)
    if document is None:
        raise ScoreSessionPreconditionError(
            f"session {session_id} names scenario version {scenario_version_id}, whose document "
            "no longer exists"
        )
    scenario_version = ScenarioVersion.model_validate(dict(document))
    report = score(scenario_version, events)
    return report, scenario_version, events


async def persist_score(
    uow: UnitOfWork,
    session_id: SessionId,
    scenario_version: ScenarioVersion,
    report: ScoreReport,
    *,
    monotonic_offset_ms: int,
) -> None:
    """Replace the stored rows, then append `SCORING_RULE_EVALUATED` (R2, R3): same transaction."""
    await uow.scores.replace_for_session(session_id, scenario_version.id, report)
    events = scoring_events(report, scenario_version, monotonic_offset_ms=monotonic_offset_ms)
    if events:
        await uow.events.append(session_id, list(events))


async def score_session(uow: UnitOfWork, session_id: SessionId) -> ScoreReport:
    """Score the stored log and persist it, inside the caller's Unit of Work.

    `SCORING_RULE_EVALUATED`'s `monotonic_offset_ms` is `SESSION_COMPLETED`'s own offset: scoring
    is the closing use case's act, so its events share the offset the session actually ended at
    instead of a fresh clock read reintroducing one at the call site (`score()` itself already
    takes no clock, R1).
    """
    report, scenario_version, events = await compute_report(uow, session_id)
    completed_at = session_completed_offset(session_id, events)
    await persist_score(uow, session_id, scenario_version, report, monotonic_offset_ms=completed_at)
    return report


def _scenario_version_id_of(
    session_id: SessionId, events: Sequence[SessionEvent]
) -> ScenarioVersionId:
    for event in events:
        if event.event_type is EventType.SESSION_CREATED:
            return ScenarioVersionId(UUID(str(event.payload["scenario_version_id"])))
    raise ScoreSessionPreconditionError(f"session {session_id}'s log has no SESSION_CREATED event")


def session_completed_offset(session_id: SessionId, events: Sequence[SessionEvent]) -> int:
    """`SESSION_COMPLETED.monotonic_offset_ms` — the only event `score()` treats as the log's end
    (R2). Scanned from the end: `SCORING_*` events, if any are already present (a re-score of an
    already-scored session), are the only events that may follow it (R2)."""
    for event in reversed(events):
        if event.event_type is EventType.SESSION_COMPLETED:
            return event.monotonic_offset_ms
    raise ScoreSessionPreconditionError(
        f"session {session_id}'s log has no SESSION_COMPLETED event"
    )

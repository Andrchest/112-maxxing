"""Evidence constructors shared by the ten evaluators (SPEC §28, D11, §42 test 11).

"Each `ScoreResult` must contain `ScoreEvidence` pointing to concrete events/card snapshots"
(SPEC §28). Concrete means: an id that is actually in the log this report was computed from.
Every constructor here takes the real object it points at, so an evaluator cannot invent a
reference — the only way to produce evidence is to hold the event, the card revision or the
handoff snapshot it refers to.

`result(...)` is the single `ScoreResult` factory. It derives `critical_failure` from
`rule.critical and not passed` (D11) so that no evaluator can decide on its own whether its
failure is a critical one — the scenario author decided that when they wrote the rule.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domain.common.ids import EventId, SnapshotId
from app.domain.enums import RoleType
from app.domain.events.session_event import SessionEvent
from app.domain.scoring.context import CardFieldChange, ScoringContext
from app.domain.scoring.errors import ScoringEvidenceError
from app.domain.scoring.results import ScoreEvidence, ScoreResult
from app.domain.scoring.rules import ScoringRule

__all__ = ["bounding_event", "from_card_revision", "from_event", "from_snapshot", "result"]


def from_event(event: SessionEvent, note_ru: str) -> ScoreEvidence:
    """Evidence pointing at one `session_events` row."""
    return ScoreEvidence(event_id=EventId(event.id), seq_no=event.seq_no, note_ru=note_ru)


def from_card_revision(change: CardFieldChange, note_ru: str) -> ScoreEvidence:
    """Evidence pointing at the card revision a value came from, else at its event.

    `CARD_FIELD_CHANGED` carries `revision_id` (D5: "every event payload must be self-sufficient
    for scoring"), which is the `incident_card_revisions` row the report renders as a card
    snapshot. A payload without one still yields evidence — the event itself.
    """
    if change.revision_id is None:
        return from_event(change.event, note_ru)
    return ScoreEvidence(
        card_revision_id=change.revision_id,
        seq_no=change.event.seq_no,
        note_ru=note_ru,
    )


def from_snapshot(handoff_event: SessionEvent, note_ru: str) -> ScoreEvidence:
    """Evidence pointing at the `HANDOFF_CREATED` snapshot, else at the event itself."""
    raw = handoff_event.payload.get("snapshot_id")
    snapshot_id = _snapshot_id(raw)
    if snapshot_id is None:
        return from_event(handoff_event, note_ru)
    return ScoreEvidence(
        snapshot_id=snapshot_id,
        seq_no=handoff_event.seq_no,
        note_ru=note_ru,
    )


def result(
    rule: ScoringRule,
    *,
    points: float,
    passed: bool,
    evidence: Sequence[ScoreEvidence],
) -> ScoreResult:
    """The one `ScoreResult` factory (§10.14). Rounding happens later, in `engine.score`."""
    return ScoreResult(
        rule_id=rule.rule_id,
        evaluator_type=rule.evaluator_type,
        category=rule.category,
        points_awarded=points,
        max_points=rule.max_points,
        passed=passed,
        critical_failure=rule.critical and not passed,
        evidence=tuple(evidence),
    )


def _snapshot_id(raw: object) -> SnapshotId | None:
    if isinstance(raw, UUID):
        return SnapshotId(raw)
    if isinstance(raw, str):
        try:
            return SnapshotId(UUID(raw))
        except ValueError:
            return None
    return None


def bounding_event(ctx: ScoringContext, *roles: RoleType) -> SessionEvent:
    """The event an "absence" points at, or `ScoringEvidenceError` (D11).

    D11's words: "'Absence' evidence points at the bounding events (e.g. `HANDOFF_CREATED` for a
    field never filled)". `ROLE_STAGE_COMPLETED` for the named roles is preferred, then the last
    stage of the log, then `SESSION_COMPLETED`. A log with none of those cannot be scored at all:
    ruling R2 puts `SESSION_COMPLETED` in the log *before* scoring runs, so its absence means the
    caller handed `score()` something that is not a finished session.
    """
    bound = ctx.stage_bound(*roles)
    if bound is None:
        raise ScoringEvidenceError(
            "no bounding event to point at: the log has neither ROLE_STAGE_COMPLETED nor "
            "SESSION_COMPLETED, so scoring was run before the session was closed (ruling R2)"
        )
    return bound

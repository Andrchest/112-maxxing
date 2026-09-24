"""`getSessionReport` — SPEC §29 items 1-14 assembled into `openapi.yaml`'s `SessionReport`.

**Scores are read, never recomputed** (E16 R1, D11). The report displays what was stored when the
session closed: `uow.scores.load_report` plus the checksum of exactly those rows. Re-running
`score()` here would make the report a second, silently-authoritative scorer — and the endpoint
that *does* re-run it, `rescoreSession`, exists precisely so that the comparison is explicit,
audited and instructor-only. A session with no stored results, or one that never reached
`COMPLETED` (including an `ABORTED` one, which is never scored), is `409 REPORT_NOT_READY`: "a
report for an unfinished session is refused" is this epic's own invariant.

**The report writes nothing.** Every read is a read; the Unit of Work commits only to release the
connection. An integration test asserts it: score row count, checksum and `session_events` count
are unchanged after a report is rendered, and a `rescoreSession` afterwards still reports
`identical_to_stored`.

**Who sees what** is one pure function, `visibility.report_visibility`, applied to every section.
A section this viewer may not see is **empty or null per the openapi nullability**, never omitted:
the shape of the document does not depend on who reads it, only its content does (D3).

**Reads, once each.** `compute_report`'s sibling read path is reused for `(scenario_version,
events)` — one `EventStore.read` serves the timeline, the DDS decisions, the resource timeline,
the barge-in metric and the handoff's `snapshot_id`, because §20.8 orders the log and every one of
those projections is a fold over it (D5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.views import OperatorCardView, card_view
from app.application.ports.clock import Clock
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.realtime.redaction import source_of_row
from app.application.reference.queries import reference_catalog
from app.application.reports.dds_decisions import DdsDecision, dds_decisions
from app.application.reports.resource_timeline import ResourceTimelineEntry, resource_timeline
from app.application.reports.timeline import TimelineEntry, timeline_entry
from app.application.reports.timing_metrics import TimingMetrics, timing_metrics
from app.application.reports.transcript import (
    AudioSegmentRef,
    TranscriptEntry,
    audio_segment_refs,
    transcript_entries,
)
from app.application.reports.truth_vs_card import TruthVsCardEntry, truth_vs_card_diff
from app.application.reports.visibility import ReportVisibility, report_visibility
from app.application.scoring.rescore_session import ReportNotReadyError
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.queries import SessionDetailView, assemble_session_detail
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import ScenarioVersionId, SessionId, SnapshotId
from app.domain.dds.assignment import DDSAssignment
from app.domain.enums import RoleType, SessionState
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.card_schema import CardSchema
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import CARD_SCHEMA_V1, OperatorCard
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.context import build_context
from app.domain.scoring.engine import report_checksum
from app.domain.scoring.results import ScoreCategoryTotal, ScoreReport, ScoreResult
from app.domain.scoring.rules import ScoringRule
from app.domain.session.session import SimulationSession

__all__ = ["GetSessionReport", "ScenarioVersionMissingError", "SessionReportView"]


class ScenarioVersionMissingError(RuntimeError):
    """The session names a scenario version whose document is gone — a storage bug, not a request
    error (`simulation_sessions.scenario_version_id` has `ON DELETE RESTRICT`)."""


@dataclass(frozen=True, slots=True)
class SessionReportView:
    """`openapi.yaml`'s `SessionReport` as application data — the schema mapper renders it as-is.

    The keys are the contract's fourteen, in the contract's order, which is SPEC §29's order.
    """

    session_id: SessionId
    session: SessionDetailView
    score_report: ScoreReport
    scoring_rules: tuple[ScoringRule, ...]
    """The scenario's rule catalog, for the schema mapper: `ScoreResultView.name_ru` /
    `.description_ru` live on `ScoringRule`, not on `ScoreResult` (the same reason
    `RescoreOutcome` carries it)."""
    checksum: str
    timeline: tuple[TimelineEntry, ...]
    transcript: tuple[TranscriptEntry, ...]
    audio_segments: tuple[AudioSegmentRef, ...]
    final_card: OperatorCardView | None
    """`null` only when the session has no `incident_cards` row at all, which a completed session
    always has. A viewer who may not see the card gets the *view* with an empty `values` map and
    the public field catalog: `SessionReport.final_card` is a required, non-nullable
    `OperatorCardView` in the contract, and R3 forbids answering a schema change instead."""
    truth_vs_card_diff: tuple[TruthVsCardEntry, ...]
    handoff: HandoffSnapshot | None
    dds_decisions: tuple[DdsDecision, ...]
    resource_timeline: tuple[ResourceTimelineEntry, ...]
    timing_metrics: TimingMetrics
    explanation_available: bool
    released: bool


class GetSessionReport:
    """`getSessionReport` — one read of everything SPEC §29 asks for, filtered per viewer."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._reference = reference

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> SessionReportView:
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not user.is_instructor_or_admin:
                # A trainee reads only a session they participated in; a stranger gets the same
                # `403 PARTICIPANT_NOT_ASSIGNED` every other session-scoped read gives them.
                resolve_participant(session, user)

            if session.state is not SessionState.COMPLETED:
                # R1: an unfinished session — and an ABORTED one, which is never scored — has no
                # report. This is the epic's invariant and has its own test.
                raise ReportNotReadyError(session_id, session.state)

            stored_results = await uow.scores.load_report(session_id)
            if stored_results is None:
                raise ReportNotReadyError(session_id, session.state)

            released = await uow.sessions.get_report_release(session_id) is not None
            visibility = report_visibility(session, user, released=released)

            events = tuple(await uow.events.read(session_id))
            scenario_version = await _scenario_version(uow, session.scenario_version_id)
            score_report = _stored_report(session_id, scenario_version, stored_results, events)
            # The card is rendered and diffed by the session's card schema (I3 E3a, §70.5.4).
            card_schema = (
                reference_catalog(self._reference).card_schema(scenario_version.reference_pack_id)
                or CARD_SCHEMA_V1
            )

            detail = await assemble_session_detail(uow, session, viewer=user, clock=self._clock)
            card = await uow.operator_cards.get(session.incident.incident_id)
            world_truth = (
                await uow.world_truth.get(session.incident.incident_id)
                if visibility.shows_operator_sections
                else None
            )
            transcript = (
                await uow.transcript_segments.list_for_session(session_id)
                if visibility.shows_operator_sections
                else []
            )
            audio = (
                await uow.audio_segments.list_for_session(session_id)
                if visibility.shows_operator_sections
                else []
            )
            handoff = await _handoff(uow, events) if visibility.shows_handoff else None
            legs = await _dds_legs(uow, session) if visibility.shows_dds_sections else []
            turns = await uow.dialogue_turns.list_for_session(session_id)
            metrics = await uow.inference_metrics.list_for_session(session_id)
            explanations = await uow.report_explanations.list_for_session(session_id)
            await uow.commit()

        actor_ids = {event.seq_no: _actor_id(event) for event in events}
        timeline = tuple(
            timeline_entry(
                envelope,
                actor_id=actor_ids.get(envelope.seq_no),
                scenario_title=scenario_version.title,
            )
            for envelope in (visibility.timeline_entry(source_of_row(event)) for event in events)
            if envelope is not None
        )

        return SessionReportView(
            session_id=session_id,
            session=detail,
            score_report=_visible_report(score_report, scenario_version, visibility),
            scoring_rules=scenario_version.scoring_rules,
            # The checksum is of the WHOLE stored report, never of the filtered view: there is one
            # report and one checksum (R3, D11), and a client comparing it with an explanation's
            # `score_report_checksum` must get the same string whoever is reading.
            checksum=report_checksum(score_report),
            timeline=timeline,
            transcript=transcript_entries(transcript),
            audio_segments=audio_segment_refs(audio),
            final_card=_final_card(card, visibility, card_schema),
            truth_vs_card_diff=(
                truth_vs_card_diff(scenario_version, card, world_truth, card_schema)
                if visibility.shows_operator_sections
                else ()
            ),
            handoff=handoff,
            dds_decisions=dds_decisions(legs, events),
            resource_timeline=(resource_timeline(events) if visibility.shows_dds_sections else ()),
            timing_metrics=timing_metrics(turns, metrics, events),
            explanation_available=bool(explanations),
            released=released,
        )


# -------------------------------------------------------------------------------------------
# Reads and folds
# -------------------------------------------------------------------------------------------


async def _scenario_version(
    uow: UnitOfWork, scenario_version_id: ScenarioVersionId
) -> ScenarioVersion:
    """The scenario document behind the session — the rule catalog and the declared world truth."""
    document = await uow.scenarios.get_version_document(scenario_version_id)
    if document is None:  # pragma: no cover - `simulation_sessions` has a FK to it
        raise ScenarioVersionMissingError(
            f"scenario version {scenario_version_id} no longer exists"
        )
    return ScenarioVersion.model_validate(dict(document))


async def _handoff(uow: UnitOfWork, events: Sequence[SessionEvent]) -> HandoffSnapshot | None:
    """The snapshot the log names, or `None` for a session that never handed off (§10.14 #9).

    `HandoffRepository.get` takes a `snapshot_id`, and the log carries it: `HANDOFF_CREATED`'s
    payload. Reading it from the events the report has already loaded costs nothing and keeps the
    log the source (D5).
    """
    for event in events:
        if event.event_type is EventType.HANDOFF_CREATED:
            snapshot_id = event.payload.get("snapshot_id")
            if snapshot_id is not None:
                return await uow.handoffs.get(SnapshotId(UUID(str(snapshot_id))))
    return None


async def _dds_legs(uow: UnitOfWork, session: SimulationSession) -> list[DDSAssignment]:
    """Every leg of every DDS stage of the chain (there is at most one today, SPEC §13)."""
    legs: list[DDSAssignment] = []
    for stage in session.stages:
        if stage.role_type is RoleType.DDS:
            legs.extend(await uow.dds_assignments.list_for_stage(stage.role_stage_id))
    return legs


def _final_card(
    card: OperatorCard | None, visibility: ReportVisibility, schema: CardSchema
) -> OperatorCardView | None:
    """The final card as this viewer may see it (§29 item 8, R3).

    The contract types `final_card` as a required, non-nullable `OperatorCardView`, so a viewer
    who may not see the card is answered with the card *view* emptied of its values rather than
    with a missing key — "sections a viewer may not see are returned EMPTY/null per the openapi
    nullability, never omitted by a schema change" (R3).
    """
    if card is None:  # pragma: no cover - a completed session always has its `incident_cards` row
        return None
    if visibility.shows_operator_sections:
        return card_view(card, schema)
    return card_view(card.model_copy(update={"values": {}}), schema)


def _actor_id(event: SessionEvent) -> UUID | None:
    """`session_events.actor_id`, which §40.2's realtime envelope deliberately does not carry."""
    return None if event.actor_id is None else UUID(str(event.actor_id))


def _stored_report(
    session_id: SessionId,
    scenario_version: ScenarioVersion,
    results: Sequence[ScoreResult],
    events: Sequence[SessionEvent],
) -> ScoreReport:
    """The stored rows as a `ScoreReport` — totals re-derived from the rows, nothing re-scored.

    "Re-derived" is arithmetic over what is stored (a sum per category), not a re-evaluation: no
    evaluator runs and `report_checksum` over the result is by construction the checksum of the
    stored numbers, which is what `rescoreSession` compares against (§10.14 reading #10).

    `computed_from_event_count` is the one field that is not a `score_results` column (it is a
    report-level fact, not a per-rule one, same reading `rescore_session._stored_report`'s own
    docstring gives) — derived here the same way `score()` itself derives it
    (`ScoringContext.computed_from_event_count`, `SCORING_*` events dropped first) over the
    already-fetched `events` this call site's sibling read path gives every other section (I3 E0
    D8: the count a loaded report shows must be the true count, not a placeholder zero).
    """
    computed_from_event_count = build_context(scenario_version, events).computed_from_event_count
    totals: dict[str, list[float]] = {}
    for result in results:
        bucket = totals.setdefault(str(result.category.value), [0.0, 0.0])
        bucket[0] += result.points_awarded
        bucket[1] += result.max_points
    by_category = tuple(
        ScoreCategoryTotal(
            category=result.category,
            points_awarded=totals[str(result.category.value)][0],
            max_points=totals[str(result.category.value)][1],
        )
        for result in _first_per_category(results)
    )
    return ScoreReport(
        scenario_version_id=scenario_version.id,
        session_id=session_id,
        total_points=sum(result.points_awarded for result in results),
        total_max_points=sum(result.max_points for result in results),
        by_category=by_category,
        critical_errors=tuple(result for result in results if result.critical_failure),
        results=tuple(results),
        computed_from_event_count=computed_from_event_count,
    )


def _first_per_category(results: Sequence[ScoreResult]) -> tuple[ScoreResult, ...]:
    seen: set[str] = set()
    ordered: list[ScoreResult] = []
    for result in results:
        key = str(result.category.value)
        if key not in seen:
            seen.add(key)
            ordered.append(result)
    return tuple(ordered)


def _visible_report(
    report: ScoreReport, scenario_version: ScenarioVersion, visibility: ReportVisibility
) -> ScoreReport:
    """The report with the per-rule rows this viewer may see — **totals untouched** (R3).

    The numbers a trainee is shown are the whole session's, because there is one report and one
    checksum (D11). Only the rule *list* narrows, and only by the rule's own `applies_to_roles`.
    """
    if visibility.is_instructor:
        return report
    rules: Mapping[str, ScoringRule] = {
        rule.rule_id: rule for rule in scenario_version.scoring_rules
    }
    visible = tuple(
        result
        for result in report.results
        if visibility.shows_rule(
            rules[result.rule_id].applies_to_roles if result.rule_id in rules else ()
        )
    )
    return report.model_copy(
        update={
            "results": visible,
            "critical_errors": tuple(result for result in visible if result.critical_failure),
        }
    )

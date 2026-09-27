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

**An ABORTED card of a lesson (I4 E31, HLD 71 §71.8, D34).** `unscored` is the one read of an
aborted session: its state, its timeline and its times, for `getLessonReport` (ТЗ ¶342–343 — a
lesson ended early still reports the actions of its unfinished cards). No score is read or
computed (an ABORTED session is never scored, SPEC §28, Q-E9b-6). The timeline is the same
`timeline_entry` projection through the same `report_visibility` as the report's own, so a viewer
sees exactly the events they would see in a finished card's timeline.

**The card's norms and counters (I4 E33, HLD 71 §71.10).** `norms`, `failed_rule_count` and
`critical_error_count` ride on the view for `getLessonReport` (and its CSV); `getSessionReport`'s
own schema does not carry them. The norms are `norms.card_norms` over the events already read,
against the session's recorded timers, gated like the sections they describe: an `ACCEPT` or
`DDS_FILL` leg with the ДДС sections, the 112 `FILL` with the operator's. The counters are over
the **whole** stored report, never the viewer's filtered rule list — numbers are one per session
(R3, D11).

**Reaction times and the workstation (I5 E36, Q-E12-1, Q-E12-3).** `reaction_times` is
`norms.card_reaction_times` over the same events, gated with the ДДС sections exactly like
`ACCEPT`/`DDS_FILL` — nothing new for the 112 operator's own card. `workstations` is the session's
participants' logins (`SessionDetailView.participants[].username`, Q-E12-3's «логин считается
рабочим местом»), sorted for a stable order; a lesson report row joins them into one column.

**«Грамотность и адреса» (I4 E35, HLD 71 §71.12, D35).** `text_quality` is built from `card` and
`events` alone, strictly after `score_report`/`checksum` are already computed from the stored
results — a `TextCheckerPort | None` cannot move either (report-only, no score effect until the
owner answers Q-E11-1). Gated per source the same way `norms` is gated per kind: the 112-card
fields with the operator sections, the ДДС comments with the ДДС ones.

**«Сдал / не сдал» (I5 E38, Q-E9b-3).** `pass_verdict` is `pass_verdict.session_pass_verdict`:
the session's recorded criteria (`SESSION_CREATED.pass_criteria`, defaults for an old log) over the
**whole** stored report's totals and counters — like `failed_rule_count`, never the viewer's
filtered list. Derived after `score_report`/`checksum` are fixed and stored nowhere, so it cannot
move the score, the checksum or a rescore.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.views import OperatorCardView, card_view
from app.application.ports.clock import Clock
from app.application.ports.reference import ReferencePort
from app.application.ports.text_checker import TextCheckerPort
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.realtime.redaction import source_of_row
from app.application.reference.queries import reference_catalog
from app.application.reports.dds_decisions import (
    DdsDecision,
    DdsParticipant,
    DdsParticipantTotals,
    dds_decisions,
    dds_participant_totals,
)
from app.application.reports.norms import (
    CardNorm,
    LegReactionTime,
    NormKind,
    card_norms,
    card_reaction_times,
    critical_error_count,
    failed_rule_count,
)
from app.application.reports.pass_verdict import session_pass_verdict
from app.application.reports.resource_timeline import ResourceTimelineEntry, resource_timeline
from app.application.reports.text_quality import (
    TextQualityReport,
    is_operator_source,
    text_quality_report,
)
from app.application.reports.timeline import TimelineEntry, call_parties, timeline_entry
from app.application.reports.timing_metrics import TimingMetrics, timing_metrics
from app.application.reports.transcript import (
    AudioSegmentRef,
    TranscriptEntry,
    audio_segment_refs,
    transcript_entries,
    turn_calls,
)
from app.application.reports.truth_vs_card import TruthVsCardEntry, truth_vs_card_diff
from app.application.reports.visibility import ReportVisibility, report_visibility
from app.application.scoring.rescore_session import ReportNotReadyError
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.queries import SessionDetailView, assemble_session_detail
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import ScenarioVersionId, SessionId, SnapshotId
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.call import dds_call_ids
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
from app.domain.session.pass_criteria import PassVerdict
from app.domain.session.session import SimulationSession

__all__ = [
    "GetSessionReport",
    "ScenarioVersionMissingError",
    "SessionReportView",
    "UnscoredSessionView",
]


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
    dds_participant_totals: tuple[DdsParticipantTotals, ...] = ()
    """ADDITIVE (I3 E5b): per ДДС participant — legs played, statuses set, decisions, flags.
    Empty when the viewer may not see the DDS sections."""
    norms: tuple[CardNorm, ...] = ()
    """(I4 E33) The card's times against its recorded timers, gated per section (module doc)."""
    reaction_times: tuple[LegReactionTime, ...] = ()
    """(I5 E36, Q-E12-1) Per-leg reaction times, gated with the ДДС sections (module doc)."""
    workstations: tuple[str, ...] = ()
    """(I5 E36, Q-E12-3) The session's participants' logins, sorted."""
    service_names_ru: Mapping[str, str] | None = None
    """(I4 E33) The reference pack's service names, for the lesson report's CSV."""
    failed_rule_count: int = 0
    """(I4 E33) Stored results that did not pass — the whole session's."""
    critical_error_count: int = 0
    """(I4 E33) Stored critical failures — the whole session's."""
    text_quality: TextQualityReport = field(
        default_factory=lambda: TextQualityReport(available=False)
    )
    """(I4 E35, HLD 71 §71.12) «Грамотность и адреса» — report-only, no score effect (D35). Never
    part of `checksum`: it is built after `score_report`/`checksum` from a wholly separate read
    (the card's texts and the ДДС comments), so a checker's presence or absence cannot move
    either."""
    pass_verdict: PassVerdict | None = None
    """(I5 E38, Q-E9b-3) «Сдал / не сдал» under the session's recorded criteria — derived, never
    stored, never part of `checksum` (module doc). `None` only for a view built without it."""


@dataclass(frozen=True, slots=True)
class UnscoredSessionView:
    """(I4 E31) `UnscoredCardView` as application data: an ABORTED session's actions and times.

    `started_at` / `aborted_at` are the `SESSION_STARTED` / `SESSION_ABORTED` wall stamps and
    `elapsed_ms` the session offset of the abort — `None` for a card aborted before it started."""

    session_id: SessionId
    state: SessionState
    timeline: tuple[TimelineEntry, ...]
    started_at: datetime | None
    aborted_at: datetime | None
    elapsed_ms: int | None


class GetSessionReport:
    """`getSessionReport` — one read of everything SPEC §29 asks for, filtered per viewer."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        reference: ReferencePort | None = None,
        text_checker: TextCheckerPort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._reference = reference
        # (I4 E35) `None` when the lexicon/street data is absent — `text_quality_report` reads
        # that as `available: false`, never raises.
        self._text_checker = text_checker

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
                if visibility.shows_operator_sections or visibility.shows_dds_sections
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

        display_names = {
            UUID(str(participant.user_id)): participant.display_name_ru
            for participant in detail.participants
        }
        catalog = reference_catalog(self._reference).services(scenario_version.reference_pack_id)
        service_names = (
            {} if catalog is None else {str(entry.id): entry.name_ru for entry in catalog.services}
        )
        # I3 E6c (HLD 80 §80.6.1, §80.6.2): every call of the session with its party label, the
        # ДДС call ids the timeline is call-scoped by, and each transcript row's call.
        dds_ids = dds_call_ids(events)
        parties = self._parties(events, scenario_version)
        timeline = _timeline(events, visibility, scenario_version, parties, dds_ids)
        calls_by_turn = turn_calls(events)
        visible_transcript = [
            segment
            for segment in transcript
            if _transcript_visible(visibility, segment.turn_index, calls_by_turn, dds_ids)
        ]

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
            transcript=transcript_entries(visible_transcript, calls=calls_by_turn, parties=parties),
            audio_segments=audio_segment_refs(audio),
            final_card=_final_card(card, visibility, card_schema),
            truth_vs_card_diff=(
                truth_vs_card_diff(scenario_version, card, world_truth, card_schema)
                if visibility.shows_operator_sections
                else ()
            ),
            handoff=handoff,
            dds_decisions=dds_decisions(
                legs, events, display_names=display_names, service_names=service_names
            ),
            resource_timeline=(resource_timeline(events) if visibility.shows_dds_sections else ()),
            timing_metrics=timing_metrics(turns, metrics, events),
            explanation_available=bool(explanations),
            released=released,
            dds_participant_totals=(
                dds_participant_totals(_dds_participants(session, detail), legs, events)
                if visibility.shows_dds_sections
                else ()
            ),
            norms=_visible_norms(card_norms(events, scenario_version.card_timers), visibility),
            reaction_times=(card_reaction_times(events) if visibility.shows_dds_sections else ()),
            workstations=tuple(sorted({p.username for p in detail.participants})),
            service_names_ru=service_names,
            failed_rule_count=failed_rule_count(score_report.results),
            critical_error_count=critical_error_count(score_report.results),
            # (I5 E38) Over the whole stored report, after `score_report`/`checksum` are fixed.
            pass_verdict=session_pass_verdict(
                events,
                total_points=score_report.total_points,
                total_max_points=score_report.total_max_points,
                failed_rule_count=failed_rule_count(score_report.results),
                critical_error_count=critical_error_count(score_report.results),
            ),
            # (I4 E35) Built from `card`/`events` alone, after `score_report`/`checksum` are
            # already fixed above — the checker's presence can only add or remove `text_quality`
            # itself, never move the score or the checksum (§71.12's own acceptance item).
            text_quality=_visible_text_quality(
                card=card, events=events, visibility=visibility, checker=self._text_checker
            ),
        )

    async def unscored(
        self, session_id: SessionId, user: AuthenticatedUser, *, released: bool
    ) -> UnscoredSessionView:
        """(I4 E31) An ABORTED session's state, timeline and times — no score (HLD 71 §71.8).

        The same gates as `__call__`: a trainee reads only a session they took part in (`403
        PARTICIPANT_NOT_ASSIGNED`) and only once `released` or their mode shows reports before a
        release (`403 REPORT_NOT_RELEASED`). `released` is the caller's: a lesson's release covers
        its aborted cards, which have no per-session release (`releaseLessonReport`). A session
        that is not `ABORTED` is `409 REPORT_NOT_READY` here — a finished card has its report.
        """
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not user.is_instructor_or_admin:
                resolve_participant(session, user)
            if session.state is not SessionState.ABORTED:
                raise ReportNotReadyError(session_id, session.state)
            session_released = await uow.sessions.get_report_release(session_id) is not None
            visibility = report_visibility(session, user, released=released or session_released)
            events = tuple(await uow.events.read(session_id))
            scenario_version = await _scenario_version(uow, session.scenario_version_id)
            await uow.commit()

        dds_ids = dds_call_ids(events)
        parties = self._parties(events, scenario_version)
        started = next((e for e in events if e.event_type is EventType.SESSION_STARTED), None)
        aborted = next((e for e in events if e.event_type is EventType.SESSION_ABORTED), None)
        return UnscoredSessionView(
            session_id=session_id,
            state=session.state,
            timeline=_timeline(events, visibility, scenario_version, parties, dds_ids),
            started_at=None if started is None else started.timestamp_utc,
            aborted_at=None if aborted is None else aborted.timestamp_utc,
            elapsed_ms=(
                None if started is None or aborted is None else aborted.monotonic_offset_ms
            ),
        )

    def _parties(
        self, events: Sequence[SessionEvent], scenario_version: ScenarioVersion
    ) -> Mapping[str, str]:
        """Every call's party label (I3 E6c, HLD 80 §80.6.1), persona titles from the pack."""
        personas = reference_catalog(self._reference).personas(scenario_version.reference_pack_id)
        return call_parties(
            events,
            {} if personas is None else {p.id: p.title_ru for p in personas.personas},
        )


def _timeline(
    events: Sequence[SessionEvent],
    visibility: ReportVisibility,
    scenario_version: ScenarioVersion,
    parties: Mapping[str, str],
    dds_ids: frozenset[str],
) -> tuple[TimelineEntry, ...]:
    """The report timeline: every event as this viewer may see it (R3), call-scoped by the
    session's ДДС call ids (I3 E6c, HLD 80 §80.6.2), with the row's own `actor_id`."""
    actor_ids = {event.seq_no: _actor_id(event) for event in events}
    return tuple(
        timeline_entry(
            envelope,
            actor_id=actor_ids.get(envelope.seq_no),
            scenario_title=scenario_version.title,
            parties=parties,
            dds_call_ids=dds_ids,
        )
        for envelope in (
            visibility.timeline_entry(source_of_row(event), dds_call_ids=dds_ids)
            for event in events
        )
        if envelope is not None
    )


def _visible_norms(norms: Sequence[CardNorm], visibility: ReportVisibility) -> tuple[CardNorm, ...]:
    """(I4 E33; I5 E36) A leg's `ACCEPT`/`DDS_FILL` with the ДДС sections, the 112 `FILL` with the
    operator's."""
    return tuple(
        norm
        for norm in norms
        if (
            visibility.shows_dds_sections
            if norm.kind in (NormKind.ACCEPT, NormKind.DDS_FILL)
            else visibility.shows_operator_sections
        )
    )


def _visible_text_quality(
    *,
    card: OperatorCard | None,
    events: Sequence[SessionEvent],
    visibility: ReportVisibility,
    checker: TextCheckerPort | None,
) -> TextQualityReport:
    """(I4 E35) The 112-card fields with the operator sections, the ДДС comments with the ДДС
    ones (mirrors `_visible_norms`'s per-kind gate). `available` stays `False` only when the
    checker itself is absent — a viewer who may see neither side simply gets an empty `fields`."""
    report = text_quality_report(
        card_values=None if card is None else card.values, events=events, checker=checker
    )
    if not report.available:
        return report
    return replace(
        report,
        fields=tuple(
            field
            for field in report.fields
            if (
                visibility.shows_operator_sections
                if is_operator_source(field.source)
                else visibility.shows_dds_sections
            )
        ),
    )


def _transcript_visible(
    visibility: ReportVisibility,
    turn_index: int | None,
    calls_by_turn: Mapping[int, str],
    dds_ids: frozenset[str],
) -> bool:
    """A transcript row by its call (I3 E6c, HLD 80 §80.6.2): a ДДС call's rows are the ДДС
    viewer's, every other row the operator's; the instructor reads all of them."""
    if visibility.is_instructor:
        return True
    call = None if turn_index is None else calls_by_turn.get(turn_index)
    if call is not None and call in dds_ids:
        return visibility.shows_dds_sections
    return visibility.shows_operator_sections


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


def _dds_participants(
    session: SimulationSession, detail: SessionDetailView
) -> tuple[DdsParticipant, ...]:
    """The session's ДДС participants (I3 E5b), in participant order, with their display names."""
    names = {UUID(str(view.user_id)): view.display_name_ru for view in detail.participants}
    return tuple(
        DdsParticipant(
            user_id=UUID(str(participant.user_id)),
            display_name_ru=names.get(UUID(str(participant.user_id)), str(participant.user_id)),
            assigned_service_id=(
                None
                if participant.assigned_service_id is None
                else str(participant.assigned_service_id)
            ),
        )
        for participant in session.participants
        if session.plays_dds(participant.user_id)
    )


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

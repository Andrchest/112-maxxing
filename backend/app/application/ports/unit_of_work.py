"""`UnitOfWork` port (D5: "Every use case runs in one Unit of Work").

One transaction covers the materialized state changes *and* the event append of a use case; the
event envelopes are published to Redis only after that transaction commits (§20.8), so a subscriber
never sees an event a later PostgreSQL read would not return (§40.6).

Usage::

    async with uow_factory() as uow:
        ...                                   # materialized writes through uow's repositories
        await uow.events.append(session_id, domain_events)
        await uow.commit()                    # publish happens here, after the commit

Leaving the block without `commit()` rolls back and publishes nothing.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, runtime_checkable

from app.application.ports.audio_segment_repository import AudioSegmentRepository
from app.application.ports.caller_belief_repository import CallerBeliefRepository
from app.application.ports.dds_assignment_repository import DDSAssignmentRepository
from app.application.ports.dds_call_repository import DdsCallRepository
from app.application.ports.dialogue_turn_repository import DialogueTurnRepository
from app.application.ports.event_store import EventStore
from app.application.ports.handoff_repository import HandoffRepository
from app.application.ports.inference_metric_repository import InferenceMetricRepository
from app.application.ports.lesson_repository import LessonRepository
from app.application.ports.notification_repository import NotificationRepository
from app.application.ports.operator_card_repository import OperatorCardRepository
from app.application.ports.recording_purge_repository import RecordingPurgeRepository
from app.application.ports.report_explanation_repository import ReportExplanationRepository
from app.application.ports.resource_repository import ResourceRepository
from app.application.ports.scenario_repository import ScenarioRepository
from app.application.ports.score_repository import ScoreRepository
from app.application.ports.session_repository import SessionRepository
from app.application.ports.trainee_group_repository import TraineeGroupRepository
from app.application.ports.transcript_segment_repository import TranscriptSegmentRepository
from app.application.ports.user_repository import UserRepository
from app.application.ports.world_engine_state_repository import WorldEngineStateRepository
from app.application.ports.world_truth_repository import WorldTruthRepository

__all__ = ["UnitOfWork", "UnitOfWorkFactory"]


@runtime_checkable
class UnitOfWork(Protocol):
    """One transaction plus the after-commit fan-out (D5)."""

    @property
    def events(self) -> EventStore:
        """The event store bound to this transaction."""
        ...

    @property
    def audio_segments(self) -> AudioSegmentRepository:
        """The `audio_segments` repository bound to this transaction (§20.6, §9.1, D9).

        The recording index commits with the event append that names it, so
        `transcript_segments.audio_segment_id` is never dangling (`50-voice-pipeline.md` §9.1).
        """
        ...

    @property
    def transcript_segments(self) -> TranscriptSegmentRepository:
        """The `transcript_segments` repository bound to this transaction (§20.6, §9.1, E12).

        The row commits with the `ASR_FINAL` that names it (§9.1), which is what makes
        `ASR_FINAL.transcript_segment_id` a reference that always resolves.
        """
        ...

    @property
    def dialogue_turns(self) -> DialogueTurnRepository:
        """The `dialogue_turns` materialized turn record bound to this transaction (§20.6, E12).

        A read model for the report, never read by scoring (D5, D11).
        """
        ...

    @property
    def inference_metrics(self) -> InferenceMetricRepository:
        """The `inference_metrics` telemetry table bound to this transaction (§20.6, SPEC §27).

        Written through `MetricsRecorder`, which opens a Unit of Work of its **own** so that a
        telemetry failure can never fail the turn it was measuring.
        """
        ...

    @property
    def lessons(self) -> LessonRepository:
        """The `lessons` repository bound to this transaction (HLD 70 §70.3, I3 E4a)."""
        ...

    @property
    def scenarios(self) -> ScenarioRepository:
        """The scenario reference-data repository bound to this transaction."""
        ...

    @property
    def trainee_groups(self) -> TraineeGroupRepository:
        """The `trainee_groups` repository bound to this transaction (HLD 70 §70.3.7, I3 E9a)."""
        ...

    @property
    def sessions(self) -> SessionRepository:
        """The session aggregate repository bound to this transaction (§20.3)."""
        ...

    @property
    def users(self) -> UserRepository:
        """The `users` repository bound to this transaction (§20.2, D8).

        Authentication reads through the same Unit of Work as everything else so that a login and
        a command see one consistent database, and so that `app.api` never needs a second,
        auth-only session factory.
        """
        ...

    @property
    def world_truth(self) -> WorldTruthRepository:
        """The `incident_world_states` repository bound to this transaction (D3)."""
        ...

    @property
    def caller_beliefs(self) -> CallerBeliefRepository:
        """The `incident_caller_beliefs` repository bound to this transaction (D3)."""
        ...

    @property
    def operator_cards(self) -> OperatorCardRepository:
        """The `incident_cards` repository bound to this transaction (D3)."""
        ...

    @property
    def handoffs(self) -> HandoffRepository:
        """The `handoff_snapshots` repository bound to this transaction (D3)."""
        ...

    @property
    def dds_assignments(self) -> DDSAssignmentRepository:
        """The `dds_assignments` repository bound to this transaction (§20.5, E9).

        It reaches no information layer: the DDS side sees the trainee's facts only through the
        `HandoffSnapshot` the assignment points at (D3, SPEC §42 test 3).
        """
        ...

    @property
    def dds_calls(self) -> DdsCallRepository:
        """The `dds_calls` read model bound to this transaction (I3 E6b, HLD 80 §80.7).

        Written in the same transaction as the `DDS_CALL_*` event it mirrors; like
        `dds_assignments` it reaches no information layer (SPEC §42 test 3).
        """
        ...

    @property
    def notifications(self) -> NotificationRepository:
        """The `notifications` repository bound to this transaction (§20.5 additive, E9).

        The rows are materialized from `NOTIFICATION_CREATED` in the very tick that emits it, so
        the table and the log commit together (D5). It reaches no information layer either.
        """
        ...

    @property
    def resources(self) -> ResourceRepository:
        """The `emergency_resources` repository bound to this transaction (§20.5)."""
        ...

    @property
    def world_engine_states(self) -> WorldEngineStateRepository:
        """The `world_engine_states` repository bound to this transaction (E6, D7)."""
        ...

    @property
    def report_explanations(self) -> ReportExplanationRepository:
        """The `report_explanations` repository bound to this transaction (§20.10, E16, D11).

        The optional LLM prose about an already-persisted `ScoreReport`, stored separately from
        the numbers it explains and holding no path back to them (SPEC §2, §29).
        """
        ...

    @property
    def scores(self) -> ScoreRepository:
        """The `score_results` / `score_evidence` repository bound to this transaction (§20.7, D11).

        Never read by `score()` itself (D5, R1): only the persistence and re-score use cases
        (`app.application.scoring`) touch this property.
        """
        ...

    @property
    def recording_purge(self) -> RecordingPurgeRepository:
        """The `recording_purge_audit` repository bound to this transaction (§9.2, D9, E18).

        Only `app.application.recording.purge_recordings.PurgeRecordings` touches this property:
        the retention purge never appends a `session_events` row (D9's own text: "the log is
        closed for a completed session").
        """
        ...

    async def __aenter__(self) -> UnitOfWork:
        """Begin the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Roll back unless `commit()` already succeeded."""
        ...

    async def commit(self) -> None:
        """Commit, then publish the envelopes of every event appended in this transaction.

        A publisher failure is logged and swallowed: the events are committed and authoritative
        (§40.6), so losing the fan-out costs liveness only, never correctness.
        """
        ...

    async def rollback(self) -> None:
        """Roll back and discard the pending envelopes; nothing is published."""
        ...


@runtime_checkable
class UnitOfWorkFactory(Protocol):
    """Creates a fresh, not-yet-entered `UnitOfWork` per use-case invocation."""

    def __call__(self) -> UnitOfWork:
        """Return a new Unit of Work."""
        ...

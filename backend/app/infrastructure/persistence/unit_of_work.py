"""`SqlAlchemyUnitOfWork` — one transaction, then the fan-out (D5, HLD §20.8, §40.6).

Materialised state changes and the event append share the single transaction of one `AsyncSession`.
Only after `commit()` returns does the Unit of Work hand the appended events' envelopes to the
`EventPublisher`, so a Redis subscriber can never see an event that a later PostgreSQL read would
not return (§40.6 "Publish-after-commit").

A publisher failure neither rolls back nor loses the committed events: Redis is a fan-out bus, not
a source of truth (§40.6, SPEC §31), so the exception is logged and swallowed. The cost of a lost
publish is live fan-out until the client's next resume — never simulation state.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.audio_segment_repository import AudioSegmentRepository
from app.application.ports.caller_belief_repository import CallerBeliefRepository
from app.application.ports.clock import Clock
from app.application.ports.dds_assignment_repository import DDSAssignmentRepository
from app.application.ports.dialogue_turn_repository import DialogueTurnRepository
from app.application.ports.event_publisher import EventPublisher, envelope_of
from app.application.ports.event_store import EventStore
from app.application.ports.handoff_repository import HandoffRepository
from app.application.ports.inference_metric_repository import InferenceMetricRepository
from app.application.ports.notification_repository import NotificationRepository
from app.application.ports.operator_card_repository import OperatorCardRepository
from app.application.ports.report_explanation_repository import ReportExplanationRepository
from app.application.ports.resource_repository import ResourceRepository
from app.application.ports.scenario_repository import ScenarioRepository
from app.application.ports.score_repository import ScoreRepository
from app.application.ports.session_repository import SessionRepository
from app.application.ports.transcript_segment_repository import TranscriptSegmentRepository
from app.application.ports.user_repository import UserRepository
from app.application.ports.world_engine_state_repository import WorldEngineStateRepository
from app.application.ports.world_truth_repository import WorldTruthRepository
from app.domain.common.ids import SessionId
from app.domain.events.session_event import SessionEvent
from app.infrastructure.persistence.audio_segment_repository import (
    SqlAlchemyAudioSegmentRepository,
)
from app.infrastructure.persistence.caller_belief_repository import (
    SqlAlchemyCallerBeliefRepository,
)
from app.infrastructure.persistence.dds_assignment_repository import (
    SqlAlchemyDDSAssignmentRepository,
)
from app.infrastructure.persistence.dialogue_turn_repository import (
    SqlAlchemyDialogueTurnRepository,
)
from app.infrastructure.persistence.event_store import SqlAlchemyEventStore
from app.infrastructure.persistence.handoff_repository import SqlAlchemyHandoffRepository
from app.infrastructure.persistence.inference_metric_repository import (
    SqlAlchemyInferenceMetricRepository,
)
from app.infrastructure.persistence.notification_repository import (
    SqlAlchemyNotificationRepository,
)
from app.infrastructure.persistence.operator_card_repository import (
    SqlAlchemyOperatorCardRepository,
)
from app.infrastructure.persistence.report_explanation_repository import (
    SqlAlchemyReportExplanationRepository,
)
from app.infrastructure.persistence.resource_repository import SqlAlchemyResourceRepository
from app.infrastructure.persistence.scenario_repository import SqlAlchemyScenarioRepository
from app.infrastructure.persistence.score_repository import SqlAlchemyScoreRepository
from app.infrastructure.persistence.session_repository import SqlAlchemySessionRepository
from app.infrastructure.persistence.transcript_segment_repository import (
    SqlAlchemyTranscriptSegmentRepository,
)
from app.infrastructure.persistence.user_repository import SqlAlchemyUserRepository
from app.infrastructure.persistence.world_engine_state_repository import (
    SqlAlchemyWorldEngineStateRepository,
)
from app.infrastructure.persistence.world_truth_repository import SqlAlchemyWorldTruthRepository

__all__ = ["SqlAlchemyUnitOfWork", "unit_of_work_factory"]

logger = logging.getLogger(__name__)


class SqlAlchemyUnitOfWork:
    """`UnitOfWork` over one `AsyncSession`, publishing after a successful commit."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        clock: Clock,
        publisher: EventPublisher,
        close_session: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._publisher = publisher
        #: False when the session is owned by the caller (a test's `db_session`, for example).
        self._close_session = close_session
        self._session: AsyncSession | None = None
        self._event_store: SqlAlchemyEventStore | None = None
        self._audio_segments: SqlAlchemyAudioSegmentRepository | None = None
        self._transcript_segments: SqlAlchemyTranscriptSegmentRepository | None = None
        self._dialogue_turns: SqlAlchemyDialogueTurnRepository | None = None
        self._inference_metrics: SqlAlchemyInferenceMetricRepository | None = None
        self._scenarios: SqlAlchemyScenarioRepository | None = None
        self._sessions: SqlAlchemySessionRepository | None = None
        self._users: SqlAlchemyUserRepository | None = None
        self._world_truth: SqlAlchemyWorldTruthRepository | None = None
        self._caller_beliefs: SqlAlchemyCallerBeliefRepository | None = None
        self._operator_cards: SqlAlchemyOperatorCardRepository | None = None
        self._handoffs: SqlAlchemyHandoffRepository | None = None
        self._resources: SqlAlchemyResourceRepository | None = None
        self._dds_assignments: SqlAlchemyDDSAssignmentRepository | None = None
        self._notifications: SqlAlchemyNotificationRepository | None = None
        self._world_engine_states: SqlAlchemyWorldEngineStateRepository | None = None
        self._scores: SqlAlchemyScoreRepository | None = None
        self._report_explanations: SqlAlchemyReportExplanationRepository | None = None
        self._pending: list[tuple[SessionId, list[SessionEvent]]] = []
        self._committed = False

    # -- lifecycle ----------------------------------------------------------------------------

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        session = self._session_factory()
        self._session = session
        self._event_store = SqlAlchemyEventStore(session, self._clock, on_append=self._record)
        self._audio_segments = SqlAlchemyAudioSegmentRepository(session)
        self._transcript_segments = SqlAlchemyTranscriptSegmentRepository(session)
        self._dialogue_turns = SqlAlchemyDialogueTurnRepository(session)
        self._inference_metrics = SqlAlchemyInferenceMetricRepository(session)
        self._scenarios = SqlAlchemyScenarioRepository(session)
        self._sessions = SqlAlchemySessionRepository(session)
        self._users = SqlAlchemyUserRepository(session)
        self._world_truth = SqlAlchemyWorldTruthRepository(session)
        self._caller_beliefs = SqlAlchemyCallerBeliefRepository(session)
        self._operator_cards = SqlAlchemyOperatorCardRepository(session)
        self._handoffs = SqlAlchemyHandoffRepository(session)
        self._resources = SqlAlchemyResourceRepository(session)
        self._dds_assignments = SqlAlchemyDDSAssignmentRepository(session)
        self._notifications = SqlAlchemyNotificationRepository(session)
        self._world_engine_states = SqlAlchemyWorldEngineStateRepository(session)
        self._scores = SqlAlchemyScoreRepository(session)
        self._report_explanations = SqlAlchemyReportExplanationRepository(session)
        self._pending = []
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if not self._committed:
                await self.rollback()
        finally:
            session = self._session
            self._session = None
            self._event_store = None
            self._audio_segments = None
            self._transcript_segments = None
            self._dialogue_turns = None
            self._inference_metrics = None
            self._scenarios = None
            self._sessions = None
            self._users = None
            self._world_truth = None
            self._caller_beliefs = None
            self._operator_cards = None
            self._handoffs = None
            self._resources = None
            self._dds_assignments = None
            self._notifications = None
            self._world_engine_states = None
            self._scores = None
            self._report_explanations = None
            if session is not None and self._close_session:
                await session.close()

    # -- repositories -------------------------------------------------------------------------

    @property
    def session(self) -> AsyncSession:
        """The bound session; use cases that need raw SQL share this one transaction."""
        if self._session is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._session

    @property
    def events(self) -> EventStore:
        if self._event_store is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._event_store

    @property
    def audio_segments(self) -> AudioSegmentRepository:
        if self._audio_segments is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._audio_segments

    @property
    def transcript_segments(self) -> TranscriptSegmentRepository:
        if self._transcript_segments is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._transcript_segments

    @property
    def dialogue_turns(self) -> DialogueTurnRepository:
        if self._dialogue_turns is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._dialogue_turns

    @property
    def inference_metrics(self) -> InferenceMetricRepository:
        if self._inference_metrics is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._inference_metrics

    @property
    def scenarios(self) -> ScenarioRepository:
        if self._scenarios is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._scenarios

    @property
    def sessions(self) -> SessionRepository:
        if self._sessions is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._sessions

    @property
    def users(self) -> UserRepository:
        if self._users is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._users

    @property
    def world_truth(self) -> WorldTruthRepository:
        if self._world_truth is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._world_truth

    @property
    def caller_beliefs(self) -> CallerBeliefRepository:
        if self._caller_beliefs is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._caller_beliefs

    @property
    def operator_cards(self) -> OperatorCardRepository:
        if self._operator_cards is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._operator_cards

    @property
    def handoffs(self) -> HandoffRepository:
        if self._handoffs is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._handoffs

    @property
    def resources(self) -> ResourceRepository:
        if self._resources is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._resources

    @property
    def dds_assignments(self) -> DDSAssignmentRepository:
        if self._dds_assignments is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._dds_assignments

    @property
    def notifications(self) -> NotificationRepository:
        if self._notifications is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._notifications

    @property
    def world_engine_states(self) -> WorldEngineStateRepository:
        if self._world_engine_states is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._world_engine_states

    @property
    def scores(self) -> ScoreRepository:
        if self._scores is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._scores

    @property
    def report_explanations(self) -> ReportExplanationRepository:
        if self._report_explanations is None:
            raise RuntimeError("the Unit of Work is not active; use `async with`")
        return self._report_explanations

    # -- transaction --------------------------------------------------------------------------

    async def commit(self) -> None:
        """Commit, then publish every envelope appended in this transaction, in `seq_no` order."""
        await self.session.commit()
        self._committed = True
        pending, self._pending = self._pending, []
        for session_id, events in pending:
            await self._publish(session_id, events)

    async def rollback(self) -> None:
        """Roll back and drop the pending envelopes; nothing is published."""
        self._pending = []
        if self._session is not None:
            await self._session.rollback()

    # -- internals ----------------------------------------------------------------------------

    def _record(self, session_id: SessionId, events: list[SessionEvent]) -> None:
        self._pending.append((session_id, events))

    async def _publish(self, session_id: SessionId, events: list[SessionEvent]) -> None:
        envelopes = [envelope_of(event) for event in sorted(events, key=lambda e: e.seq_no)]
        try:
            await self._publisher.publish(session_id, envelopes)
        except Exception:  # Redis is non-authoritative (§40.6); never propagate
            logger.exception(
                "publishing %d event(s) of session %s failed; the events are committed and "
                "remain readable from PostgreSQL",
                len(envelopes),
                session_id,
            )


def unit_of_work_factory(
    session_factory: Callable[[], AsyncSession], clock: Clock, publisher: EventPublisher
) -> Callable[[], SqlAlchemyUnitOfWork]:
    """A zero-argument factory a use case can call once per invocation (`UnitOfWorkFactory`)."""

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, clock, publisher)

    return factory

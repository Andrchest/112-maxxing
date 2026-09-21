"""The composition root (D2, D8) — the ONE module that wires ports to adapters.

D2's table says `api -> application -> domain` and `infrastructure -> application, domain`. Nobody
imports *both* sides… except the place where the two are joined, which every layered design needs
exactly one of. This is that place: `Container` is the only module in `app.api` that imports
`app.infrastructure`, and `backend/tools/check_imports.py` allows it by name and by name only.

What follows from that:

* no router, dependency, schema or error handler instantiates an adapter. They ask the container
  for a use case, and a use case is already holding its ports;
* a test builds a `Container` with whatever it wants overridden — `FakeClock`, an
  `InMemoryEventPublisher`, a `FakeInferenceReadiness` that is not ready — and calls
  `create_app(container)`. Nothing else has to be patched, because nothing else constructs
  anything;
* the container owns the resources it creates (`AsyncEngine`, `Redis`) and `aclose()` disposes
  them. The FastAPI lifespan calls it; a test that built its own engine passes `owns_engine=False`
  and keeps ownership.

`Settings` is read **here and only here** for the application layer's benefit: D2 forbids
`app.application` from importing `app.config`, so flags like `require_inference_ready` arrive at a
use case as constructor arguments that this module reads and passes in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from types import TracebackType

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.application.auth.list_users import ListUsers
from app.application.auth.login import Login
from app.application.dds.acknowledge import AcknowledgeDdsAssignment
from app.application.dds.acknowledge_notification import AcknowledgeNotification
from app.application.dds.back_to_acknowledged import BackToDdsAcknowledged
from app.application.dds.close_incident import CloseDdsIncident
from app.application.dds.command_context import DdsCommandGate
from app.application.dds.deselect_resource import DeselectDdsResource
from app.application.dds.dispatch import DispatchDdsResources
from app.application.dds.get_work_item import GetDdsWorkItem
from app.application.dds.list_notifications import ListNotifications
from app.application.dds.list_radio_messages import ListRadioMessages
from app.application.dds.list_resources import ListDdsResources
from app.application.dds.open_resource_selection import OpenDdsResourceSelection
from app.application.dds.select_resource import SelectDdsResource
from app.application.dds.send_status_update import SendDdsStatusUpdate
from app.application.dds.stage_automation import DdsStageAutomation
from app.application.handoff.complete_operator_stage import CompleteOperatorStage
from app.application.handoff.continue_to_next_stage import ContinueToNextStage
from app.application.handoff.create_handoff import CreateHandoff
from app.application.operator.answer_call import AnswerCall
from app.application.operator.back_to_interview import BackToInterview
from app.application.operator.begin_handoff_preparation import BeginHandoffPreparation
from app.application.operator.call_flow import AdvanceCallFlow
from app.application.operator.command_context import OperatorCommandGate
from app.application.operator.deselect_service import DeselectRecipientService
from app.application.operator.end_call import EndCall
from app.application.operator.get_card import GetOperatorCard
from app.application.operator.list_card_revisions import ListCardRevisions
from app.application.operator.select_service import SelectRecipientService
from app.application.operator.set_card_field import SetCardField
from app.application.ports.call_state_cache import CallStateCache
from app.application.ports.call_transport_status import CallTransportStatus
from app.application.ports.clock import Clock
from app.application.ports.event_publisher import EventPublisher
from app.application.ports.event_subscriber import EventSubscriber
from app.application.ports.health_probe import HealthProbe
from app.application.ports.id_generator import IdGenerator
from app.application.ports.idempotency_store import IdempotencyStore
from app.application.ports.inference_readiness import InferenceReadiness
from app.application.ports.last_seq_no_cache import LastSeqNoCache
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.runner_lock import RunnerLock
from app.application.ports.token_service import TokenService
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.voice_signal_publisher import VoiceSignalPublisher
from app.application.ports.voice_token_service import VoiceTokenService
from app.application.realtime.event_stream import SessionEventStream
from app.application.realtime.list_events import ListSessionEvents
from app.application.scenarios.import_scenario_version import ImportScenarioVersion
from app.application.scenarios.queries import (
    GetScenarioValidationReport,
    GetScenarioVersionSummary,
    ListScenarios,
    ListScenarioVersions,
    ValidateScenarioDocument,
)
from app.application.scoring.rescore_session import RescoreSession
from app.application.sessions.abort_session import AbortSession
from app.application.sessions.create_session import CreateSession
from app.application.sessions.get_snapshot import GetSnapshot
from app.application.sessions.queries import GetSession, ListSessions
from app.application.sessions.start_session import StartSession
from app.application.simulation.runner import SimulationRunner
from app.application.simulation.tick_session import TickSession
from app.application.voice_token.create_voice_token import CreateVoiceToken
from app.config.settings import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.domain.common.ids import SessionId
from app.infrastructure.auth.argon2_hasher import Argon2PasswordHasher
from app.infrastructure.auth.jwt_token_service import JwtTokenService
from app.infrastructure.clock import SystemClock
from app.infrastructure.health import (
    LiveKitHealthProbe,
    PlaceholderHealthProbe,
    PostgresHealthProbe,
    RedisHealthProbe,
)
from app.infrastructure.ids import Uuid4Generator
from app.infrastructure.persistence.unit_of_work import unit_of_work_factory
from app.infrastructure.realtime.redis_idempotency_store import RedisIdempotencyStore
from app.infrastructure.realtime.redis_last_seq_no_cache import RedisLastSeqNoCache
from app.infrastructure.realtime.redis_publisher import RedisEventPublisher
from app.infrastructure.realtime.redis_runner_lock import RedisRunnerLock
from app.infrastructure.realtime.redis_subscriber import RedisEventSubscriber
from app.infrastructure.transport.livekit_token_service import LiveKitTokenService
from app.infrastructure.transport.livekit_transport_status import LiveKitTransportStatus
from app.infrastructure.transport.local_call_transport_status import LocalCallTransportStatus
from app.infrastructure.transport.redis_call_state_cache import RedisCallStateCache
from app.infrastructure.transport.redis_voice_signals import RedisVoiceSignals

__all__ = ["Container", "build_container"]

#: `openapi.yaml`'s `ComponentHealth.component` enum, in the order `/health/ready` reports them.
HEALTH_COMPONENTS: tuple[str, ...] = ("postgres", "redis", "livekit", "llm", "asr", "tts", "vad")

#: The components `startSession` insists on while `require_inference_ready` is true
#: (`HealthReadyResponse.required_components`). `livekit` is required because the call cannot be
#: placed without it; the four inference services are D8's `INFERENCE_NOT_READY` set.
REQUIRED_HEALTH_COMPONENTS: tuple[str, ...] = (
    "postgres",
    "redis",
    "livekit",
    "llm",
    "asr",
    "tts",
    "vad",
)


class Container:
    """Everything the API is built from, wired once.

    Construct it with `build_container(settings)` for production, or directly with the pieces a
    test wants to override. Every argument that is `None` is built from `settings`, so a test
    overrides one port without restating the other twelve.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        redis: Redis | None = None,
        clock: Clock | None = None,
        ids: IdGenerator | None = None,
        publisher: EventPublisher | None = None,
        unit_of_work: UnitOfWorkFactory | None = None,
        inference: InferenceReadiness | None = None,
        runner_lock: RunnerLock | None = None,
        runner: SimulationRunner | None = None,
        hasher: PasswordHasher | None = None,
        tokens: TokenService | None = None,
        call_transport_status: CallTransportStatus | None = None,
        voice_tokens: VoiceTokenService | None = None,
        voice_signals: VoiceSignalPublisher | None = None,
        call_state_cache: CallStateCache | None = None,
        health_probes: Sequence[HealthProbe] | None = None,
        idempotency: IdempotencyStore | None = None,
        owns_engine: bool = True,
        owns_redis: bool = True,
    ) -> None:
        self.settings = settings
        #: False when a test handed in its own engine/Redis and will close them itself.
        self._owns_engine = owns_engine and engine is None
        self._owns_redis = owns_redis and redis is None

        self.engine: AsyncEngine = engine if engine is not None else create_engine(settings)
        self.session_factory: async_sessionmaker[AsyncSession] = (
            session_factory if session_factory is not None else create_session_factory(self.engine)
        )
        self.redis: Redis = (
            redis
            if redis is not None
            else Redis.from_url(settings.redis_url, decode_responses=True)
        )

        self.clock: Clock = clock if clock is not None else SystemClock()
        self.ids: IdGenerator = ids if ids is not None else Uuid4Generator()
        self.publisher: EventPublisher = (
            publisher
            if publisher is not None
            else RedisEventPublisher(self.redis, settings.session_cache_ttl_s)
        )
        self.unit_of_work: UnitOfWorkFactory = (
            unit_of_work
            if unit_of_work is not None
            else unit_of_work_factory(self.session_factory, self.clock, self.publisher)
        )
        self.inference: InferenceReadiness = (
            inference if inference is not None else _PlaceholderInferenceReadiness()
        )
        self.runner_lock: RunnerLock = (
            runner_lock if runner_lock is not None else RedisRunnerLock(self.redis)
        )
        self.tick_session = TickSession(self.unit_of_work, self.clock)
        self.runner: SimulationRunner = (
            runner
            if runner is not None
            else SimulationRunner(
                self.unit_of_work,
                self.tick_session,
                self.runner_lock,
                instance_id=settings.instance_id,
                tick_ms=settings.sim_tick_ms,
                lock_ttl_s=settings.sim_runner_lock_ttl_s,
                lock_refresh_s=settings.sim_runner_lock_refresh_s,
                after_tick=(self._advance_call_flow, self._dds_stage_automation),
            )
        )
        self.hasher: PasswordHasher = hasher if hasher is not None else Argon2PasswordHasher()
        self.tokens: TokenService = (
            tokens
            if tokens is not None
            else JwtTokenService(settings.jwt_secret, ttl_minutes=settings.jwt_ttl_minutes)
        )
        self.call_transport_status: CallTransportStatus = (
            call_transport_status
            if call_transport_status is not None
            else _call_transport_status(settings, self.redis)
        )
        self.health_probes: tuple[HealthProbe, ...] = tuple(
            health_probes if health_probes is not None else self._default_probes()
        )
        # E7-B: `idempotency:{user_id}:{client_command_id}` (§40.6). Appended here, at the end of
        # `__init__`, so nothing above it moves.
        self.idempotency: IdempotencyStore = (
            idempotency
            if idempotency is not None
            else RedisIdempotencyStore(self.redis, ttl_s=settings.idempotency_ttl_s)
        )
        # -- E11-B: the backend half of the call (D9, §40.6, SPEC §15, §34) --------------------
        #
        # Three ports, all appended at the end of `__init__` so nothing above them moves. The
        # token service mints plain HS256 JWTs with `pyjwt` — no `livekit` import ever enters
        # `backend/` (D2) — and it is handed `livekit_browser_url`, the URL a BROWSER dials, which
        # under compose is not the one this process dials (`SIM_LIVEKIT_PUBLIC_URL`).
        self.voice_tokens: VoiceTokenService = (
            voice_tokens
            if voice_tokens is not None
            else LiveKitTokenService(
                settings.livekit_api_key,
                settings.livekit_api_secret,
                livekit_url=settings.livekit_browser_url,
                ttl_minutes=settings.livekit_token_ttl_minutes,
            )
        )
        self.voice_signals: VoiceSignalPublisher = (
            voice_signals if voice_signals is not None else RedisVoiceSignals(self.redis)
        )
        self.call_state_cache: CallStateCache = (
            call_state_cache
            if call_state_cache is not None
            else RedisCallStateCache(self.redis, settings.session_cache_ttl_s)
        )
        # -- end E11-B -------------------------------------------------------------------------

    # -- use-case factories --------------------------------------------------------------------
    #
    # One method per use case. Routers call these; they never call a use-case constructor, so a
    # constructor signature can change without touching a single endpoint.

    def login(self) -> Login:
        """`loginUser`."""
        return Login(self.unit_of_work, self.hasher, self.tokens)

    def list_users(self) -> ListUsers:
        """`listUsers` (additive, E7)."""
        return ListUsers(self.unit_of_work)

    def list_scenarios(self) -> ListScenarios:
        """`listScenarios`."""
        return ListScenarios(self.unit_of_work)

    def list_scenario_versions(self) -> ListScenarioVersions:
        """`listScenarioVersions`."""
        return ListScenarioVersions(self.unit_of_work)

    def get_scenario_version_summary(self) -> GetScenarioVersionSummary:
        """`getScenarioVersionSummary`."""
        return GetScenarioVersionSummary(self.unit_of_work)

    def get_scenario_validation_report(self) -> GetScenarioValidationReport:
        """`getScenarioValidationReport`."""
        return GetScenarioValidationReport(self.unit_of_work)

    def import_scenario_version(self) -> ImportScenarioVersion:
        """`importScenarioVersion`."""
        return ImportScenarioVersion(self.unit_of_work)

    def validate_scenario_document(self) -> ValidateScenarioDocument:
        """`validateScenarioFile`."""
        return ValidateScenarioDocument()

    def create_session(self) -> CreateSession:
        """`createSession`."""
        return CreateSession(self.unit_of_work, self.ids)

    def start_session(self) -> StartSession:
        """`startSession`. `require_inference_ready` is read from `Settings` here (D2)."""
        return StartSession(
            self.unit_of_work,
            self.clock,
            self.inference,
            self.ids,
            require_inference_ready=self.settings.require_inference_ready,
        )

    def abort_session(self) -> AbortSession:
        """`abortSession`; publishes `voice:cancel:{session_id}` after the commit (§40.6)."""
        return AbortSession(self.unit_of_work, self.clock, self.voice_signals)

    def list_sessions(self) -> ListSessions:
        """`listSessions`."""
        return ListSessions(self.unit_of_work)

    def get_session(self) -> GetSession:
        """`getSession`."""
        return GetSession(self.unit_of_work, self.clock)

    def rescore_session(self) -> RescoreSession:
        """`rescoreSession` (epic E15-B)."""
        return RescoreSession(self.unit_of_work)

    # -- E7-C: the realtime read path (§40.1-§40.6) ---------------------------------------------
    #
    # Everything below this line belongs to task E7-C and nothing above it does. The two adapters
    # are built lazily and cached on first use rather than in `__init__`, so a process that never
    # opens a WebSocket never opens a pub/sub connection either — and so that this block is a
    # pure addition to the class.

    def event_subscriber(self) -> EventSubscriber:
        """The `session:{id}:events` subscriber (§40.3 step 2), one per container."""
        cached: EventSubscriber | None = getattr(self, "_event_subscriber", None)
        if cached is None:
            cached = RedisEventSubscriber(self.redis)
            self._event_subscriber: EventSubscriber = cached
        return cached

    def last_seq_no_cache(self) -> LastSeqNoCache:
        """The `session:{id}:last_seq_no` read cache (§40.6), one per container."""
        cached: LastSeqNoCache | None = getattr(self, "_last_seq_no_cache", None)
        if cached is None:
            cached = RedisLastSeqNoCache(self.redis, self.settings.session_cache_ttl_s)
            self._last_seq_no_cache: LastSeqNoCache = cached
        return cached

    def session_event_stream(self) -> SessionEventStream:
        """The §40.3 mechanism behind `WS /api/v1/ws/sessions/{id}`.

        The three `WS_*` settings are read here, not in the application layer, because D2 forbids
        `app.application` from importing `app.config`.
        """
        return SessionEventStream(
            self.unit_of_work,
            self.event_subscriber(),
            self.last_seq_no_cache(),
            self.clock,
            replay_page_size=self.settings.ws_replay_max_events,
            heartbeat_s=self.settings.ws_heartbeat_s,
        )

    def list_session_events(self) -> ListSessionEvents:
        """`listSessionEvents`."""
        return ListSessionEvents(self.unit_of_work)

    # -- E7-B: the Operator 112 commands, the snapshot and the call flow (SPEC §7, §9, §10) -----
    #
    # Everything below this line belongs to task E7-B and nothing above it does. The nine command
    # and read use cases share one `OperatorCommandGate` factory, so the pipeline of D8's two
    # gates is constructed in exactly one place.

    def operator_command_gate(self) -> OperatorCommandGate:
        """The single Operator 112 command pipeline (`application/operator/command_context`)."""
        return OperatorCommandGate(self.unit_of_work, self.clock, self.call_transport_status)

    def answer_call(self) -> AnswerCall:
        """`answerCall`."""
        return AnswerCall(self.operator_command_gate(), self.ids, self.clock, self.call_state_cache)

    def end_call(self) -> EndCall:
        """`endCall`; publishes `voice:cancel:{session_id}` after the commit (§40.6, E11-B)."""
        return EndCall(
            self.operator_command_gate(),
            self.ids,
            self.clock,
            self.voice_signals,
            self.call_state_cache,
        )

    def create_voice_token(self) -> CreateVoiceToken:
        """`createVoiceToken` (E11-B)."""
        return CreateVoiceToken(self.unit_of_work, self.voice_tokens)

    def get_operator_card(self) -> GetOperatorCard:
        """`getOperatorCard`."""
        return GetOperatorCard(self.unit_of_work)

    def set_card_field(self) -> SetCardField:
        """`setCardField`. The idempotency store is §40.6's, never authoritative."""
        return SetCardField(self.operator_command_gate(), self.ids, self.idempotency)

    def list_card_revisions(self) -> ListCardRevisions:
        """`listCardRevisions`."""
        return ListCardRevisions(self.unit_of_work)

    def select_recipient_service(self) -> SelectRecipientService:
        """`selectRecipientService`."""
        return SelectRecipientService(self.operator_command_gate(), self.ids)

    def deselect_recipient_service(self) -> DeselectRecipientService:
        """`deselectRecipientService`."""
        return DeselectRecipientService(self.operator_command_gate(), self.ids)

    def begin_handoff_preparation(self) -> BeginHandoffPreparation:
        """`beginHandoffPreparation`."""
        return BeginHandoffPreparation(self.operator_command_gate())

    def back_to_interview(self) -> BackToInterview:
        """`backToInterview`."""
        return BackToInterview(self.operator_command_gate())

    def get_snapshot(self) -> GetSnapshot:
        """`getSessionSnapshot`."""
        return GetSnapshot(self.unit_of_work, self.clock)

    def advance_call_flow(self) -> AdvanceCallFlow:
        """The `SIMULATION`-fired `ring` / `begin_interview` triggers (§10.8, D7).

        Built once and cached, unlike the command use cases above: §40.6's `voice:join` retry is
        rate-limited per session by `VOICE_JOIN_RETRY_MS`, and a use case rebuilt on every tick
        would carry a fresh, empty timer and re-publish on every tick instead (E11-B).
        """
        cached: AdvanceCallFlow | None = getattr(self, "_advance_call_flow_use_case", None)
        if cached is not None:
            return cached
        built = AdvanceCallFlow(
            self.unit_of_work,
            self.clock,
            self.call_transport_status,
            self.ids,
            self.voice_signals,
            self.call_state_cache,
            join_retry_ms=self.settings.voice_join_retry_ms,
        )
        self._advance_call_flow_use_case: AdvanceCallFlow = built
        return built

    async def _advance_call_flow(self, session_id: SessionId) -> bool:
        """The `SimulationRunner`'s one `after_tick` hook.

        A bound method rather than the use case itself, because the runner is constructed before
        `call_transport_status` is assigned: resolving the use case at *call* time keeps this an
        addition to `__init__` instead of a reordering of it, and costs one object per tick.
        """
        return await self.advance_call_flow()(session_id)

    # -- E9-A: the handoff and the role transition (SPEC §10, §13; §10.7-§10.9) ----------------
    #
    # Everything below this line belongs to task E9-A and nothing above it does. The two operator
    # commands share the same `OperatorCommandGate` as E7-B's nine; `continueToNextStage` has its
    # own Unit of Work, because by the time it runs the session is in `ROLE_TRANSITION` and the
    # 112 pipeline's preconditions no longer hold.

    def create_handoff(self) -> CreateHandoff:
        """`createHandoff`."""
        return CreateHandoff(self.operator_command_gate(), self.ids)

    def complete_operator_stage(self) -> CompleteOperatorStage:
        """`completeOperatorStage`."""
        return CompleteOperatorStage(self.operator_command_gate(), self.clock)

    def continue_to_next_stage(self) -> ContinueToNextStage:
        """`continueToNextStage`."""
        return ContinueToNextStage(self.unit_of_work, self.clock)

    # -- E9-B: the DDS commands, the DDS reads and the DDS stage automation (SPEC §11, §12) -----
    #
    # Everything below this line belongs to task E9-B and nothing above it does. The eight
    # commands share one `DdsCommandGate`, so D8's two gates are constructed in exactly one place
    # for this side too; the four reads take the Unit of Work directly, because a read fires no
    # action and has no transition to check.
    #
    # Not one of these is given a world-truth, caller-belief or operator-card repository — that is
    # what SPEC §42 test 3 asserts on the constructor signatures (D3).

    def dds_command_gate(self) -> DdsCommandGate:
        """The single DDS command pipeline (`application/dds/command_context`)."""
        return DdsCommandGate(self.unit_of_work, self.clock)

    def get_dds_work_item(self) -> GetDdsWorkItem:
        """`getDdsWorkItem`."""
        return GetDdsWorkItem(self.unit_of_work)

    def list_dds_resources(self) -> ListDdsResources:
        """`listDdsResources`."""
        return ListDdsResources(self.unit_of_work, self.clock)

    def acknowledge_dds_assignment(self) -> AcknowledgeDdsAssignment:
        """`acknowledgeDdsAssignment`."""
        return AcknowledgeDdsAssignment(self.dds_command_gate())

    def open_dds_resource_selection(self) -> OpenDdsResourceSelection:
        """`openDdsResourceSelection` (additive, E9)."""
        return OpenDdsResourceSelection(self.dds_command_gate())

    def back_to_dds_acknowledged(self) -> BackToDdsAcknowledged:
        """`backToDdsAcknowledged` (additive, E9)."""
        return BackToDdsAcknowledged(self.dds_command_gate())

    def select_dds_resource(self) -> SelectDdsResource:
        """`selectDdsResource`."""
        return SelectDdsResource(self.dds_command_gate())

    def deselect_dds_resource(self) -> DeselectDdsResource:
        """`deselectDdsResource`."""
        return DeselectDdsResource(self.dds_command_gate())

    def dispatch_dds_resources(self) -> DispatchDdsResources:
        """`dispatchDdsResources`."""
        return DispatchDdsResources(self.dds_command_gate())

    def send_dds_status_update(self) -> SendDdsStatusUpdate:
        """`sendDdsStatusUpdate`."""
        return SendDdsStatusUpdate(self.dds_command_gate())

    def list_notifications(self) -> ListNotifications:
        """`listNotifications`."""
        return ListNotifications(self.unit_of_work)

    def acknowledge_notification(self) -> AcknowledgeNotification:
        """`acknowledgeNotification`. Its own gate: both trainee roles hold the permission."""
        return AcknowledgeNotification(self.unit_of_work, self.clock)

    def list_radio_messages(self) -> ListRadioMessages:
        """`listRadioMessages`."""
        return ListRadioMessages(self.unit_of_work)

    def close_dds_incident(self) -> CloseDdsIncident:
        """`closeDdsIncident`."""
        return CloseDdsIncident(self.dds_command_gate(), self.clock)

    def dds_stage_automation(self) -> DdsStageAutomation:
        """The `SIMULATION`-fired DDS stage triggers (§10.8, D6, D7).

        The resolution verdict is `TickSession.resolution_condition_met`, bound here: evaluating
        `expected_response.resolution_condition` needs the live `WorldState`, which only the
        simulation slice may hold (D3), so the DDS slice is handed a boolean and nothing else.
        """
        return DdsStageAutomation(
            self.unit_of_work, self.clock, self.tick_session.resolution_condition_met
        )

    async def _dds_stage_automation(self, session_id: SessionId) -> bool:
        """The `SimulationRunner`'s second `after_tick` hook, beside `_advance_call_flow`."""
        return await self.dds_stage_automation()(session_id)

    # -- lifecycle -----------------------------------------------------------------------------

    async def aclose(self) -> None:
        """Dispose the engine and close the Redis client, if this container created them.

        The FastAPI lifespan calls it after stopping the runner; a test that passed in its own
        engine keeps it, so a shared `migrated_engine` fixture is not disposed under the next test.
        """
        if self._owns_engine:
            await self.engine.dispose()
        if self._owns_redis:
            await self.redis.aclose()

    async def __aenter__(self) -> Container:
        """`async with build_container(settings) as container: …`."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    # -- internals -----------------------------------------------------------------------------

    def _default_probes(self) -> list[HealthProbe]:
        """One probe per `ComponentHealth.component`, in report order.

        `postgres` and `redis` are real; the other five report `NOT_READY` with the owing epic —
        see `app.infrastructure.health` for why that is the honest reading and not a stub.
        """
        return [
            PostgresHealthProbe(self.engine),
            RedisHealthProbe(self.redis),
            LiveKitHealthProbe(self.settings.livekit_url),
            PlaceholderHealthProbe("llm", "E18"),
            PlaceholderHealthProbe("asr", "E18"),
            PlaceholderHealthProbe("tts", "E18"),
            PlaceholderHealthProbe("vad", "E18"),
        ]


class _PlaceholderInferenceReadiness:
    """`InferenceReadiness` while no inference stack exists (D8).

    It answers `False`, which is what makes `REQUIRE_INFERENCE_READY=true` refuse `startSession`
    with `503 INFERENCE_NOT_READY` on a box that has no voice-agent — the documented behaviour.
    `REQUIRE_INFERENCE_READY=false` never consults it at all (`StartSession._inference_ready`).

    TODO(E18): the real adapter over the `voice:health:{service}` keys of §40.6.
    """

    async def is_ready(self) -> bool:
        """`False`: nothing can report `READY` until the voice-agent exists."""
        return False


def _call_transport_status(settings: Settings, redis: Redis) -> CallTransportStatus:
    """The `CallTransportStatus` adapter `SIM_CALL_TRANSPORT` names (D9)."""
    transport = settings.call_transport.lower()
    if transport == "fake":
        return LocalCallTransportStatus()
    if transport == "livekit":
        return LiveKitTransportStatus(settings.livekit_url, redis)
    raise ValueError(
        f"SIM_CALL_TRANSPORT={settings.call_transport!r} is not a known transport; "
        f"expected 'fake' or 'livekit'"
    )


def build_container(settings: Settings | None = None) -> Container:
    """The production container: every port on its real adapter."""
    return Container(settings if settings is not None else get_settings())


#: Kept so `Callable[[], Container]` reads as a named thing where a factory is passed around.
ContainerFactory = Callable[[], Container]

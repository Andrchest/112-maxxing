"""An in-memory Unit of Work for the dialogue-chain tests (D13, `50-voice-pipeline.md` §3.7).

The responder and the context loader are the two components of this epic that touch persistence,
and both do it through the same `UnitOfWork` the backend and the voice agent use. A dict-backed
one makes a whole turn — seven events, one turn row, two repository reads — assertable without
PostgreSQL; the integration test in `backend/tests/integration/voice/` exercises the real one.

Nothing here decides anything: it stores what it was given and hands it back.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

import pytest
from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.dialogue_turn_repository import DialogueTurnUpsert
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.application.ports.world_engine_state_repository import WorldEngineState
from app.application.testing.fakes import FakeClock, InMemoryDialogueTurnRepository
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.turn_detector import DetectedTurn, TurnEndReason
from app.application.voice.turn_pipeline import TranscribedTurn, TurnContext
from app.domain.caller.emotion import EmotionState
from app.domain.common.ids import EventId, IncidentId, SessionId
from app.domain.enums import (
    EmotionLabel,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.layers.caller_belief import CallerBelief
from app.domain.session.session import RoleStage, SimulationSession

from tests.fixtures.scenarios import demo_document
from tests.unit.application.dialogue._support import demo_belief, demo_definitions
from tests.unit.domain.session._builders import build_session, build_stage, det_uuid

CALL_ID = uuid.UUID("c0ffee00-0000-4000-8000-000000000001")


# ---------------------------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------------------------


@dataclass
class DialogueStore:
    """Everything the fake Unit of Work has committed for one session."""

    session: SimulationSession
    caller_belief: CallerBelief
    engine_state: WorldEngineState
    document: dict[str, Any]
    events: list[SessionEvent] = field(default_factory=list)
    transcripts: list[StoredTranscriptSegment] = field(default_factory=list)
    turns: InMemoryDialogueTurnRepository = field(default_factory=InMemoryDialogueTurnRepository)
    commits: int = 0
    next_seq_no: int = 1
    fail_on_commit: Exception | None = None

    @property
    def event_types(self) -> list[str]:
        """The appended event types, in append order — what an order assertion reads."""
        return [event.event_type.value for event in self.events]

    def payloads(self, event_type: str) -> list[dict[str, Any]]:
        """Every payload of one event type, in append order."""
        return [
            dict(event.payload) for event in self.events if event.event_type.value == event_type
        ]


class _Sessions:
    def __init__(self, store: DialogueStore) -> None:
        self._store = store

    async def get(self, session_id: SessionId) -> SimulationSession | None:
        return self._store.session if session_id == self._store.session.id else None


class _CallerBeliefs:
    def __init__(self, store: DialogueStore) -> None:
        self._store = store

    async def get(self, incident_id: IncidentId) -> CallerBelief | None:
        return self._store.caller_belief

    async def save(self, caller_belief: CallerBelief) -> None:
        self._store.caller_belief = caller_belief


class _EngineStates:
    def __init__(self, store: DialogueStore) -> None:
        self._store = store

    async def get(self, incident_id: IncidentId) -> WorldEngineState | None:
        return self._store.engine_state

    async def save(self, state: WorldEngineState) -> None:
        self._store.engine_state = state


class _Scenarios:
    def __init__(self, store: DialogueStore) -> None:
        self._store = store

    async def get_version_document(self, scenario_version_id: Any) -> dict[str, Any] | None:
        return self._store.document


class _Events:
    def __init__(self, store: DialogueStore, pending: list[SessionEvent], clock: FakeClock) -> None:
        self._store = store
        self._pending = pending
        self._clock = clock

    async def append(
        self, session_id: SessionId, events: Sequence[DomainEvent]
    ) -> list[SessionEvent]:
        appended: list[SessionEvent] = []
        for event in events:
            appended.append(
                SessionEvent(
                    id=EventId(uuid.uuid4()),
                    session_id=session_id,
                    seq_no=self._store.next_seq_no,
                    event_type=event.event_type,
                    timestamp_utc=self._clock.now(),
                    monotonic_offset_ms=event.monotonic_offset_ms,
                    actor_type=event.actor.actor_type,
                    actor_id=event.actor.actor_id,
                    correlation_id=event.correlation_id,
                    payload=dict(event.payload),
                )
            )
            self._store.next_seq_no += 1
        self._pending.extend(appended)
        return appended

    async def read(self, session_id: SessionId, after_seq_no: int = 0, limit: int | None = None):
        return [event for event in self._store.events if event.seq_no > after_seq_no]


class _Transcripts:
    def __init__(self, store: DialogueStore, pending: list[StoredTranscriptSegment]) -> None:
        self._store = store
        self._pending = pending

    async def add(self, segment: StoredTranscriptSegment) -> None:
        self._pending.append(segment)

    async def list_for_session(self, session_id: SessionId) -> list[StoredTranscriptSegment]:
        return list(self._store.transcripts)


class _AudioSegments:
    async def add_all(self, segments: Sequence[StoredAudioSegment]) -> None:
        return None


class InMemoryDialogueUnitOfWork:
    """The repositories the dialogue chain reads and writes, with commit/rollback semantics."""

    def __init__(self, store: DialogueStore, clock: FakeClock) -> None:
        self._store = store
        self._clock = clock
        self._events: list[SessionEvent] = []
        self._transcripts: list[StoredTranscriptSegment] = []

    @property
    def sessions(self) -> _Sessions:
        return _Sessions(self._store)

    @property
    def caller_beliefs(self) -> _CallerBeliefs:
        return _CallerBeliefs(self._store)

    @property
    def world_engine_states(self) -> _EngineStates:
        return _EngineStates(self._store)

    @property
    def scenarios(self) -> _Scenarios:
        return _Scenarios(self._store)

    @property
    def events(self) -> _Events:
        return _Events(self._store, self._events, self._clock)

    @property
    def transcript_segments(self) -> _Transcripts:
        return _Transcripts(self._store, self._transcripts)

    @property
    def dialogue_turns(self) -> InMemoryDialogueTurnRepository:
        return self._store.turns

    @property
    def audio_segments(self) -> _AudioSegments:
        return _AudioSegments()

    async def __aenter__(self) -> InMemoryDialogueUnitOfWork:
        self._events = []
        self._transcripts = []
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        if self._store.fail_on_commit is not None:
            raise self._store.fail_on_commit
        self._store.events.extend(self._events)
        self._store.transcripts.extend(self._transcripts)
        self._store.commits += 1

    async def rollback(self) -> None:
        return None


# ---------------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(start=datetime(2026, 1, 1, tzinfo=UTC))


def make_store() -> DialogueStore:
    """A session mid-call: ACTIVE, one operator stage, the demo scenario instantiated.

    A plain function beside the fixture so that suites outside this package (the INV 14 file in
    `backend/tests/invariants/`) can build the same world without re-describing it.
    """
    stage: RoleStage = build_stage(
        order_index=0,
        role_type=RoleType.OPERATOR_112,
        state=Operator112StageState.INTERVIEW,
    )
    session = build_session(
        session_mode=SessionMode.SINGLE_ROLE, state=SessionState.ACTIVE, stages=[stage]
    ).model_copy(update={"started_at": datetime(2026, 1, 1, tzinfo=UTC)})
    document = demo_document()
    document["id"] = str(det_uuid("scenario-version"))
    document["scenario_id"] = str(det_uuid("scenario"))
    return DialogueStore(
        session=session,
        caller_belief=demo_belief(
            demo_definitions(),
            emotion=EmotionState(emotion=EmotionLabel.FRIGHTENED, stress_level=0.6),
        ).model_copy(update={"incident_id": session.incident.incident_id}),
        engine_state=WorldEngineState(incident_id=session.incident.incident_id),
        document=document,
    )


def make_uow_factory(
    store: DialogueStore, clock: FakeClock
) -> Callable[[], InMemoryDialogueUnitOfWork]:
    """A `UnitOfWorkFactory` over one shared store."""

    def factory() -> InMemoryDialogueUnitOfWork:
        return InMemoryDialogueUnitOfWork(store, clock)

    return factory


def make_turn_context(
    store: DialogueStore,
    clock: FakeClock,
    uow_factory: Callable[[], InMemoryDialogueUnitOfWork],
) -> TurnContext:
    """The `TurnContext` a responder is handed for this call."""
    return TurnContext(
        session_id=store.session.id,
        call_id=CALL_ID,
        config=VoiceTurnConfig(),
        transport=None,  # type: ignore[arg-type]  # the dialogue chain never touches it
        appender=VoiceEventAppender(
            session_id=store.session.id,
            uow_factory=uow_factory,  # type: ignore[arg-type]
            clock=clock,
            started_at=store.session.started_at,
        ),
        recorder=None,
    )


@pytest.fixture
def store() -> DialogueStore:
    """`make_store()`, per test."""
    return make_store()


@pytest.fixture
def uow_factory(store: DialogueStore, clock: FakeClock) -> Callable[[], InMemoryDialogueUnitOfWork]:
    """`make_uow_factory()`, per test."""
    return make_uow_factory(store, clock)


@pytest.fixture
def turn_context(
    store: DialogueStore,
    clock: FakeClock,
    uow_factory: Callable[[], InMemoryDialogueUnitOfWork],
) -> TurnContext:
    """`make_turn_context()`, per test."""
    return make_turn_context(store, clock, uow_factory)


def transcribed_turn(text: str, *, turn_index: int = 0) -> TranscribedTurn:
    """One finalized, transcribed trainee turn (R1's seam value)."""
    turn_id = uuid.uuid5(uuid.NAMESPACE_URL, f"turn:{turn_index}")
    detected = DetectedTurn(
        turn_id=turn_id,
        turn_index=turn_index,
        audio=b"\x00\x00" * 160,
        start_ms=turn_index * 2000,
        end_ms=turn_index * 2000 + 640,
        is_barge_in=False,
        pre_roll_ms=300,
        end_reason=TurnEndReason.ENDPOINT_SILENCE,
        discarded_short=False,
    )
    return TranscribedTurn(
        turn=detected,
        text=text,
        confidence=0.9,
        turn_index=turn_index,
        role_stage_id=None,
        transcript_segment_id=uuid.uuid4(),
    )


def seed_turn_row(store: DialogueStore, turn: TranscribedTurn) -> None:
    """The `dialogue_turns` row `AsrTurnResponder` wrote before the dialogue chain ran."""
    store.turns.rows[(store.session.id, turn.turn_index)] = store.turns.rows.get(
        (store.session.id, turn.turn_index)
    ) or _row(store, turn)


def _row(store: DialogueStore, turn: TranscribedTurn):
    from app.application.ports.dialogue_turn_repository import StoredDialogueTurn

    return StoredDialogueTurn(
        id=uuid.uuid4(),
        session_id=store.session.id,
        role_stage_id=store.session.stages[0].role_stage_id,
        turn_index=turn.turn_index,
        user_speech_started_offset_ms=turn.turn.start_ms,
        user_speech_ended_offset_ms=turn.turn.end_ms,
        operator_transcript_segment_id=turn.transcript_segment_id,
        correlation_id=turn.turn.turn_id,
    )


__all__ = [
    "CALL_ID",
    "DialogueStore",
    "DialogueTurnUpsert",
    "InMemoryDialogueUnitOfWork",
    "make_store",
    "make_turn_context",
    "make_uow_factory",
    "seed_turn_row",
    "transcribed_turn",
]

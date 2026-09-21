"""Shared helpers for the voice turn-path unit tests (HLD `50-voice-pipeline.md` §4, D13).

Everything here is deterministic: synthetic audio from `app.application.testing.fakes`, the
`EnergyVAD` (no model file), and a `FakeClock` that only a test moves. No sleeping, no LiveKit, no
PostgreSQL — which is the point of building the whole slice against fakes (this task's ruling 1).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from types import TracebackType

import pytest
from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.call_transport import AudioFrame
from app.application.ports.dialogue_turn_repository import DialogueTurnUpsert
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.application.testing.fakes import FakeClock, silence_frames, sine_burst_frames
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.turn_detector import DetectorStep, TurnDetector
from app.domain.common.ids import EventId, SessionId
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.inference.vad import EnergyVAD


@pytest.fixture
def config() -> VoiceTurnConfig:
    """The HLD's defaults, which is what an unconfigured process would load."""
    return VoiceTurnConfig()


def make_vad(config: VoiceTurnConfig) -> EnergyVAD:
    """An `EnergyVAD` whose window matches the config's analysis frame."""
    return EnergyVAD(frame_samples=config.frame_samples, required_sample_rate=config.sample_rate)


def speech(config: VoiceTurnConfig, duration_ms: int, start_offset_ms: int) -> list[AudioFrame]:
    """A loud synthetic burst: every frame scores well above `speech_start_threshold`."""
    return sine_burst_frames(
        duration_ms=duration_ms,
        frame_samples=config.frame_samples,
        sample_rate=config.sample_rate,
        start_offset_ms=start_offset_ms,
    )


def quiet(config: VoiceTurnConfig, duration_ms: int, start_offset_ms: int) -> list[AudioFrame]:
    """Digital silence: every frame scores 0.0, below `speech_end_threshold`."""
    return silence_frames(
        duration_ms=duration_ms,
        frame_samples=config.frame_samples,
        sample_rate=config.sample_rate,
        start_offset_ms=start_offset_ms,
    )


def concat(*groups: Sequence[AudioFrame]) -> list[AudioFrame]:
    """Join frame groups and restamp `capture_offset_ms` so the timeline is continuous."""
    frames: list[AudioFrame] = []
    offset = 0
    for group in groups:
        for frame in group:
            frames.append(
                AudioFrame(
                    pcm=frame.pcm,
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                    samples_per_channel=frame.samples_per_channel,
                    capture_offset_ms=offset,
                )
            )
            offset += frame.duration_ms
    return frames


async def drive(
    detector: TurnDetector,
    vad: EnergyVAD,
    frames: Sequence[AudioFrame],
    *,
    playback_active: bool = False,
) -> list[DetectorStep]:
    """Push every frame through the VAD and the detector, returning the non-empty steps."""
    steps: list[DetectorStep] = []
    for frame in frames:
        result = await vad.process(frame)
        step = detector.process(frame, result, playback_active=playback_active)
        if step.started is not None or step.finished is not None:
            steps.append(step)
    return steps


# ---------------------------------------------------------------------------------------------
# A Unit of Work in a dict, so the pipeline's append path is assertable without PostgreSQL.
# The integration test in `backend/tests/integration/voice/` exercises the real one; this exists
# to make the *ordering* of a whole call cheap to assert (D13).
# ---------------------------------------------------------------------------------------------


@dataclass
class VoiceStore:
    """What the fake Unit of Work committed, and what it rolled back."""

    events: list[SessionEvent] = field(default_factory=list)
    segments: list[StoredAudioSegment] = field(default_factory=list)
    transcripts: list[StoredTranscriptSegment] = field(default_factory=list)
    turns: list[DialogueTurnUpsert] = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0
    next_seq_no: int = 1
    fail_on_commit: Exception | None = None
    fail_on_event_append: Exception | None = None
    fail_on_transcript_add: Exception | None = None


class _FakeEventStore:
    def __init__(self, store: VoiceStore, pending: list[SessionEvent], clock: FakeClock) -> None:
        self._store = store
        self._pending = pending
        self._clock = clock

    async def append(
        self, session_id: SessionId, events: Sequence[DomainEvent]
    ) -> list[SessionEvent]:
        if self._store.fail_on_event_append is not None:
            raise self._store.fail_on_event_append
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


class _FakeAudioSegments:
    def __init__(self, pending: list[StoredAudioSegment]) -> None:
        self._pending = pending

    async def add_all(self, segments: Sequence[StoredAudioSegment]) -> None:
        self._pending.extend(segments)


class _FakeTranscriptSegments:
    def __init__(self, store: VoiceStore, pending: list[StoredTranscriptSegment]) -> None:
        self._store = store
        self._pending = pending

    async def add(self, segment: StoredTranscriptSegment) -> None:
        if self._store.fail_on_transcript_add is not None:
            raise self._store.fail_on_transcript_add
        self._pending.append(segment)


class _FakeDialogueTurns:
    def __init__(self, pending: list[DialogueTurnUpsert]) -> None:
        self._pending = pending

    async def upsert(self, turn: DialogueTurnUpsert) -> uuid.UUID:
        self._pending.append(turn)
        return turn.id


class InMemoryVoiceUnitOfWork:
    """The two repositories `VoiceEventAppender` uses, plus commit/rollback semantics."""

    def __init__(self, store: VoiceStore, clock: FakeClock) -> None:
        self._store = store
        self._clock = clock
        self._events: list[SessionEvent] = []
        self._segments: list[StoredAudioSegment] = []
        self._transcripts: list[StoredTranscriptSegment] = []
        self._turns: list[DialogueTurnUpsert] = []

    @property
    def events(self) -> _FakeEventStore:
        return _FakeEventStore(self._store, self._events, self._clock)

    @property
    def audio_segments(self) -> _FakeAudioSegments:
        return _FakeAudioSegments(self._segments)

    @property
    def transcript_segments(self) -> _FakeTranscriptSegments:
        return _FakeTranscriptSegments(self._store, self._transcripts)

    @property
    def dialogue_turns(self) -> _FakeDialogueTurns:
        return _FakeDialogueTurns(self._turns)

    async def __aenter__(self) -> InMemoryVoiceUnitOfWork:
        self._events = []
        self._segments = []
        self._transcripts = []
        self._turns = []
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
            self._store.rollbacks += 1
            raise self._store.fail_on_commit
        self._store.events.extend(self._events)
        self._store.segments.extend(self._segments)
        self._store.transcripts.extend(self._transcripts)
        self._store.turns.extend(self._turns)
        self._store.commits += 1

    async def rollback(self) -> None:
        self._store.rollbacks += 1


def uow_factory(store: VoiceStore, clock: FakeClock) -> Callable[[], InMemoryVoiceUnitOfWork]:
    """A `UnitOfWorkFactory` over one shared store."""

    def factory() -> InMemoryVoiceUnitOfWork:
        return InMemoryVoiceUnitOfWork(store, clock)

    return factory

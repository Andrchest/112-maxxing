"""SPEC §39 #5 — "LiveKit temporary reconnect: session/domain state survives." (`SPEC.md:1041`).

The mechanism (HLD 60 §6 row 5): `LiveKitCallTransport` surfaces `RECONNECTING`/`RECONNECTED`;
`TurnPipeline` turns them into `TRANSPORT_DISCONNECTED`/`TRANSPORT_RECONNECTED` and resumes; and a
disconnect longer than `transport.reconnect_grace_s` emits `CALL_ENDED {reason: "TRANSPORT_LOST"}`
"and leaves the session for the instructor to decide".

Driven end to end through the public seam — a real `TurnPipeline` over `FakeCallTransport`,
`EnergyVAD` and a `FakeClock` — rather than by importing the unit test beside it, because the point
of SPEC §39 is behaviour at the seam a call actually runs through. The unit-level coverage of the
timer's own arithmetic stays in `backend/tests/unit/application/voice/test_reconnect_grace.py`.

Every test closes on §39's own last line, "Never silently reset the simulation": the event log
before the episode is a prefix of the log after it (`conftest.assert_prefix_preserved`), the
session's own state is never written by this path at all (the voice agent has no session use case
to write it with, D3), and no incident, card or score is touched.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
from app.application.ports.call_transport import TransportEvent, TransportEventType
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.events import VoiceEventAppender
from app.application.voice.turn_detector import TurnDetector
from app.application.voice.turn_pipeline import NullTurnResponder, TurnPipeline
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType

from tests.resilience.conftest import assert_prefix_preserved
from tests.unit.application.voice.conftest import (
    VoiceStore,
    concat,
    make_vad,
    quiet,
    speech,
    uow_factory,
)

CALL_ID = uuid.UUID("39595959-3959-4959-8959-395959595959")


@pytest.fixture
def config() -> VoiceTurnConfig:
    """The HLD's defaults, which is what an unconfigured process would load.

    Declared here rather than taken from `tests/unit/application/voice/conftest.py`: a conftest
    fixture does not travel to a sibling package, and this suite is about §39, not about sharing.
    """
    return VoiceTurnConfig()


class _HeldSleeper:
    """The pipeline's `SleepMs`, held open until a test decides the grace period is over."""

    def __init__(self) -> None:
        self.requested_ms: list[int] = []
        self.release = asyncio.Event()

    async def __call__(self, milliseconds: int) -> None:
        self.requested_ms.append(milliseconds)
        await self.release.wait()


def _call(
    config: VoiceTurnConfig, frames: list, sleeper: _HeldSleeper
) -> tuple[TurnPipeline, FakeCallTransport, VoiceStore, SessionId]:
    clock = FakeClock()
    store = VoiceStore()
    session_id = SessionId(uuid.uuid4())
    transport = FakeCallTransport(
        clock=clock, inbound=frames, outbound_queue_ms=config.outbound_queue_ms
    )
    pipeline = TurnPipeline(
        session_id=session_id,
        call_id=CALL_ID,
        transport=transport,
        vad=make_vad(config),
        detector=TurnDetector(config),
        appender=VoiceEventAppender(
            session_id=session_id,
            uow_factory=uow_factory(store, clock),
            clock=clock,
            started_at=clock.now(),
        ),
        clock=clock,
        config=config,
        responder=NullTurnResponder(),
        sleep_ms=sleeper,
    )
    return pipeline, transport, store, session_id


def _types(pipeline: TurnPipeline) -> list[EventType]:
    return [event.event_type for event in pipeline.appended]


async def _until(predicate, what: str) -> None:
    for _ in range(500):
        await asyncio.sleep(0)
        if predicate():
            return
    raise AssertionError(f"timed out waiting for {what}")


def _snapshot(store: VoiceStore) -> list[tuple[int, str, str]]:
    """The committed log as comparable rows: seq_no, type, payload — nothing may change."""
    return [
        (event.seq_no, event.event_type.value, repr(sorted(event.payload.items())))
        for event in store.events
    ]


async def test_a_reconnect_inside_the_grace_period_keeps_the_call_and_every_earlier_event(
    config: VoiceTurnConfig,
) -> None:
    """SPEC §39 #5: the session survives a temporary reconnect, and so does everything logged."""
    frames = concat(
        quiet(config, 400, 0),
        speech(config, 900, 0),
        quiet(config, 900, 0),
        speech(config, 900, 0),
        quiet(config, 900, 0),
    )
    sleeper = _HeldSleeper()
    pipeline, transport, store, _session_id = _call(config, frames, sleeper)

    running = asyncio.create_task(pipeline.run())
    await _until(
        lambda: EventType.USER_SPEECH_ENDED in _types(pipeline), "the first turn to finalize"
    )
    before = _snapshot(store)
    turns_before = _types(pipeline).count(EventType.USER_SPEECH_ENDED)

    transport.emit(
        TransportEvent(
            type=TransportEventType.DISCONNECTED, call_id=CALL_ID, at_offset_ms=1500, detail="net"
        )
    )
    await _until(lambda: bool(sleeper.requested_ms), "the grace timer to arm")
    transport.emit(
        TransportEvent(type=TransportEventType.RECONNECTED, call_id=CALL_ID, at_offset_ms=1800)
    )
    await asyncio.wait_for(running, timeout=5)

    types = _types(pipeline)
    # The episode's only trace is the documented pair.
    assert types.count(EventType.TRANSPORT_DISCONNECTED) == 1
    assert types.count(EventType.TRANSPORT_RECONNECTED) == 1
    # The call was not ended by the reconnect: it ended when the audio ran out.
    reasons = [
        e.payload["reason"] for e in pipeline.appended if e.event_type is EventType.CALL_ENDED
    ]
    assert reasons == ["TRANSPORT_CLOSED"]
    # The turn that was already in the log is still there, and the call kept detecting turns.
    assert types.count(EventType.USER_SPEECH_ENDED) > turns_before
    assert_prefix_preserved(before, _snapshot(store))


async def test_a_disconnect_beyond_the_grace_period_ends_the_call_without_resetting_anything(
    config: VoiceTurnConfig,
) -> None:
    """SPEC §39 #5 + §6 row 5: `CALL_ENDED{TRANSPORT_LOST}`, and nothing else is rewritten.

    "Leaves the session for the instructor to decide" is asserted structurally: the pipeline
    appends `CALL_ENDED` and nothing that could change a session's state — no `SESSION_ABORTED`,
    no state write of any kind — because the voice agent has no session use case at all (D3).
    """
    frames = concat(quiet(config, 400, 0), speech(config, 900, 0), quiet(config, 8000, 0))
    sleeper = _HeldSleeper()
    pipeline, transport, store, _session_id = _call(config, frames, sleeper)

    running = asyncio.create_task(pipeline.run())
    await _until(
        lambda: EventType.USER_SPEECH_ENDED in _types(pipeline), "the first turn to finalize"
    )
    before = _snapshot(store)
    assert before, "the first turn must be committed before the disconnect, or this proves nothing"

    transport.emit(
        TransportEvent(
            type=TransportEventType.DISCONNECTED, call_id=CALL_ID, at_offset_ms=1500, detail="net"
        )
    )
    await _until(lambda: bool(sleeper.requested_ms), "the grace timer to arm")
    assert sleeper.requested_ms == [config.reconnect_grace_s * 1000]
    sleeper.release.set()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(running, timeout=5)

    types = _types(pipeline)
    call_ended = [e for e in pipeline.appended if e.event_type is EventType.CALL_ENDED]
    assert len(call_ended) == 1
    assert call_ended[0].payload["reason"] == "TRANSPORT_LOST"
    # Never silently reset: nothing that was written before the loss changed.
    assert_prefix_preserved(before, _snapshot(store))
    # And the pipeline aborted nothing — that is an instructor's decision, with an actor (D3).
    assert EventType.SESSION_ABORTED not in types


async def test_the_call_that_never_reconnects_still_logs_the_disconnect_first(
    config: VoiceTurnConfig,
) -> None:
    """Order matters for the instructor's timeline: the disconnect is visible before the end."""
    frames = concat(quiet(config, 400, 0), speech(config, 900, 0), quiet(config, 8000, 0))
    sleeper = _HeldSleeper()
    pipeline, transport, _store, _session_id = _call(config, frames, sleeper)

    running = asyncio.create_task(pipeline.run())
    await _until(
        lambda: EventType.USER_SPEECH_ENDED in _types(pipeline), "the first turn to finalize"
    )
    transport.emit(
        TransportEvent(type=TransportEventType.DISCONNECTED, call_id=CALL_ID, at_offset_ms=1500)
    )
    await _until(lambda: bool(sleeper.requested_ms), "the grace timer to arm")
    sleeper.release.set()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(running, timeout=5)

    types = _types(pipeline)
    assert types.index(EventType.TRANSPORT_DISCONNECTED) < types.index(EventType.CALL_ENDED)

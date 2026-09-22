"""`transport.reconnect_grace_s` — HLD 60 §6 row 5 / SPEC §39 item 5 (E18-C, R6).

"A disconnect longer than `transport.reconnect_grace_s` (default 30) emits
`CALL_ENDED {reason: "TRANSPORT_LOST"}` and leaves the session for the instructor to decide."

The timer lives in `TurnPipeline`, not in the LiveKit wrapper, and that is what makes this file
possible: `FakeCallTransport` + `FakeClock` + an injected `SleepMs` drive the whole grace period in
microseconds, with no SDK, no network and no thirty-second wait.
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

from tests.unit.application.voice.conftest import (
    VoiceStore,
    concat,
    make_vad,
    quiet,
    speech,
    uow_factory,
)

CALL_ID = uuid.UUID("77777777-7777-4777-8777-777777777777")


class _Sleeper:
    """A `SleepMs` a test releases by hand, recording what it was asked to wait for."""

    def __init__(self) -> None:
        self.requested_ms: list[int] = []
        self.release = asyncio.Event()

    async def __call__(self, milliseconds: int) -> None:
        self.requested_ms.append(milliseconds)
        await self.release.wait()


def _build(
    config: VoiceTurnConfig, frames: list, sleeper: _Sleeper
) -> tuple[TurnPipeline, FakeCallTransport, VoiceStore]:
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
    return pipeline, transport, store


def _types(pipeline: TurnPipeline) -> list[EventType]:
    return [event.event_type for event in pipeline.appended]


async def _until(predicate: object, what: str) -> None:
    """Yield to the loop until `predicate()` is true — the deterministic `await` of these tests."""
    assert callable(predicate)
    for _ in range(500):
        await asyncio.sleep(0)
        if predicate():
            return
    raise AssertionError(f"timed out waiting for {what}")


async def _armed(sleeper: _Sleeper) -> None:
    """Let the event loop run until the grace task has actually entered `sleep_ms`.

    Creating the task is not the same as running it: `_start_reconnect_grace` schedules a
    coroutine, and a RECONNECTED that arrives in the same loop iteration cancels it before its
    first line. These tests are about what happens *after* the timer is really waiting.
    """
    await _until(lambda: bool(sleeper.requested_ms), "the reconnect-grace timer to be armed")


def _call_ended_reasons(pipeline: TurnPipeline) -> list[str]:
    return [
        str(event.payload["reason"])
        for event in pipeline.appended
        if event.event_type is EventType.CALL_ENDED
    ]


def test_the_default_grace_is_the_documented_thirty_seconds() -> None:
    """§6 row 5's "(default 30)", carried through profile → `Settings` → `VoiceTurnConfig`."""
    assert VoiceTurnConfig().reconnect_grace_s == 30


async def test_a_reconnect_inside_the_grace_period_changes_nothing_but_the_two_events(
    config: VoiceTurnConfig,
) -> None:
    """§6 row 5: "session/domain state survives". One turn before, one turn after, one call."""
    frames = concat(
        quiet(config, 400, 0),
        speech(config, 900, 0),
        quiet(config, 900, 0),
        speech(config, 900, 0),
        quiet(config, 900, 0),
    )
    sleeper = _Sleeper()
    pipeline, transport, store = _build(config, frames, sleeper)

    transport.emit(
        TransportEvent(
            type=TransportEventType.DISCONNECTED, call_id=CALL_ID, at_offset_ms=500, detail="net"
        )
    )
    running = asyncio.create_task(pipeline.run())
    await _armed(sleeper)
    transport.emit(
        TransportEvent(type=TransportEventType.RECONNECTED, call_id=CALL_ID, at_offset_ms=900)
    )
    await asyncio.wait_for(running, timeout=5)

    types = _types(pipeline)
    assert EventType.TRANSPORT_DISCONNECTED in types
    assert EventType.TRANSPORT_RECONNECTED in types
    # The grace timer was armed and then disarmed: nothing it could have done happened.
    assert sleeper.requested_ms == [config.reconnect_grace_s * 1000]
    assert _call_ended_reasons(pipeline) == ["TRANSPORT_CLOSED"]
    # Both turns survived the episode — the detector was not reset and no event was dropped.
    assert types.count(EventType.USER_SPEECH_STARTED) == 2
    assert types.count(EventType.USER_SPEECH_ENDED) == 2
    assert [event.event_type for event in store.events] == types


async def test_a_disconnect_longer_than_the_grace_period_ends_the_call_as_transport_lost(
    config: VoiceTurnConfig,
) -> None:
    """§6 row 5: `CALL_ENDED {reason: "TRANSPORT_LOST"}`, through the ordinary call-end path."""
    frames = concat(quiet(config, 400, 0), speech(config, 900, 0), quiet(config, 8000, 0))
    sleeper = _Sleeper()
    pipeline, transport, _store = _build(config, frames, sleeper)

    running = asyncio.create_task(pipeline.run())
    # One complete turn first: the point of §39 item 5 is that what already happened survives.
    await _until(
        lambda: EventType.USER_SPEECH_ENDED in _types(pipeline), "the first turn to finalize"
    )
    before = len(pipeline.appended)
    transport.emit(
        TransportEvent(
            type=TransportEventType.DISCONNECTED, call_id=CALL_ID, at_offset_ms=500, detail="net"
        )
    )
    await _armed(sleeper)
    assert sleeper.requested_ms == [config.reconnect_grace_s * 1000]
    sleeper.release.set()
    # `stop()` cancels the ingest task, so `run()` ends in `CancelledError` — the same ending a
    # `voice:cancel` hang-up produces, and `voice_agent.main._run_call` treats it the same way.
    # `_close_call()` has already appended `CALL_ENDED` from `_ingest`'s `finally` by then.
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(running, timeout=5)

    assert _call_ended_reasons(pipeline) == ["TRANSPORT_LOST"]
    # Exactly one CALL_ENDED, and the turn that had already happened is still in the log,
    # unchanged and in place (SPEC §39's closing rule).
    types = _types(pipeline)
    assert types.count(EventType.CALL_ENDED) == 1
    assert EventType.USER_SPEECH_ENDED in types[:before]
    assert EventType.TRANSPORT_DISCONNECTED in types
    assert len(pipeline.appended) >= before


async def test_the_timer_is_armed_once_per_disconnect(config: VoiceTurnConfig) -> None:
    """A transport that repeats DISCONNECTED must not stack timers (each would end the call)."""
    frames = concat(quiet(config, 400, 0), speech(config, 900, 0), quiet(config, 900, 0))
    sleeper = _Sleeper()
    pipeline, transport, _store = _build(config, frames, sleeper)

    transport.emit(
        TransportEvent(type=TransportEventType.DISCONNECTED, call_id=CALL_ID, at_offset_ms=500)
    )
    running = asyncio.create_task(pipeline.run())
    await _armed(sleeper)
    for offset in (600, 700):
        transport.emit(
            TransportEvent(
                type=TransportEventType.DISCONNECTED, call_id=CALL_ID, at_offset_ms=offset
            )
        )
    transport.emit(
        TransportEvent(type=TransportEventType.RECONNECTED, call_id=CALL_ID, at_offset_ms=800)
    )
    await asyncio.wait_for(running, timeout=5)
    assert sleeper.requested_ms == [config.reconnect_grace_s * 1000]


@pytest.mark.parametrize("grace_s", [0, 1, 600])
def test_the_grace_period_is_configuration_not_a_literal(grace_s: int) -> None:
    """SPEC §17: "Make this configuration, not a hard-coded magic value."."""
    assert VoiceTurnConfig(reconnect_grace_s=grace_s).reconnect_grace_s == grace_s


def test_an_out_of_range_grace_period_is_refused_at_load() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VoiceTurnConfig(reconnect_grace_s=-1)

"""One clock origin for SPEC §27's `speech_end_to_first_audio_ms` (R13, E19-E3 bug #5).

The metric is a subtraction across two events: `CALLER_TTS_STARTED.first_audio_offset_ms` minus
`USER_SPEECH_ENDED.at_offset_ms`. The first comes from `VoiceEventAppender.offset_ms()`, i.e.
`session_offset_ms(clock.now(), session.started_at)`. The second comes from
`DetectedTurn.end_ms`, i.e. from `AudioFrame.capture_offset_ms`, i.e. from the transport's
`_now_ms()`. Over LiveKit that second one used to be "ms since this transport's first frame",
and because a session starts well before the agent's transport does — create → ring → join →
answer — the two were measured from different zeros. E19-E3's real run produced 34 samples, every
one of them negative (−29 711, −34 127, −35 759 … ms) and drifting further apart every turn, and
`benchmark_e2e.py` discarded the lot rather than publish a percentile over impossible numbers.

These tests drive the two stamping expressions themselves, with a **30 s gap** between the
session's start and the transport's first frame — the gap that made the old code negative — and
assert the metric is positive and identical to the in-process one. No LiveKit server and no SDK:
`LiveKitCallTransport` imports the SDK inside `connect()`, so its clock arithmetic is testable on
a machine that has never seen it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.timebase import session_offset_ms
from app.application.voice.config import voice_turn_config_from_settings
from app.config.settings import Settings
from voice_agent.transport.livekit_transport import LiveKitCallTransport
from voice_agent.wiring import build_transport

#: The session started at this instant; the agent's transport joins `_JOIN_GAP_MS` later.
SESSION_STARTED_AT = datetime(2026, 9, 22, 10, 16, 49, tzinfo=UTC)

#: E19-E3's first sample was −29 711 ms, i.e. a gap of about half a minute between the session's
#: start and the agent's first frame. 30 s is that gap, rounded.
_JOIN_GAP_MS = 30_000

#: How long the turn takes from the trainee's last frame to the caller's first audio — the number
#: the metric is supposed to report.
_TURN_MS = 900


def settings(**overrides: Any) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        "redis_url": "redis://localhost:56379/0",
        "jwt_secret": "test-only-secret-padded-32-bytes!",
        "livekit_url": "ws://localhost:7880",
        "livekit_api_key": "devkey",
        "livekit_api_secret": "devsecret1234567890",
        "llm_base_url": "http://localhost:8080/v1",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _livekit_transport(clock: FakeClock) -> LiveKitCallTransport:
    return LiveKitCallTransport(
        url="ws://localhost:7880",
        token="not-used-without-connect",
        outbound_queue_ms=200,
        outbound_sample_rate=16_000,
        clock=clock,
        started_at=SESSION_STARTED_AT,
    )


def _clock_at_join(gap_ms: int) -> FakeClock:
    """A clock reading `gap_ms` after the session started — the agent joining late."""
    return FakeClock(start=SESSION_STARTED_AT + timedelta(milliseconds=gap_ms))


def test_the_livekit_transport_stamps_session_offsets_not_its_own_first_frame() -> None:
    """The old `_now_ms` answered 0 here, whatever the gap; the fixed one answers the gap."""
    clock = _clock_at_join(_JOIN_GAP_MS)
    transport = _livekit_transport(clock)

    assert transport._now_ms() == _JOIN_GAP_MS

    clock.advance_ms(500)
    assert transport._now_ms() == _JOIN_GAP_MS + 500
    assert transport._now_ms() == session_offset_ms(clock.now(), SESSION_STARTED_AT)


def _speech_end_to_first_audio_ms(gap_ms: int) -> int:
    """The metric, computed from the two expressions the product actually stamps with.

    `speech_end` is a frame's `capture_offset_ms` (the transport's `_now_ms`); `first_audio` is
    `VoiceEventAppender.offset_ms()`, which is `session_offset_ms(clock.now(), started_at)`
    literally — the same expression, so this is the subtraction the benchmark reads back out of
    the event log.
    """
    clock = _clock_at_join(gap_ms)
    transport = _livekit_transport(clock)

    speech_end = transport._now_ms()
    clock.advance_ms(_TURN_MS)
    first_audio = session_offset_ms(clock.now(), SESSION_STARTED_AT)
    return first_audio - speech_end


def test_speech_end_to_first_audio_is_positive_over_a_late_joining_transport() -> None:
    """A 30 s join gap used to make this −30 000; it is now the turn's own duration."""
    assert _speech_end_to_first_audio_ms(_JOIN_GAP_MS) == _TURN_MS
    assert _speech_end_to_first_audio_ms(_JOIN_GAP_MS) > 0


def test_the_metric_is_the_same_whatever_the_join_gap_was() -> None:
    """In process the gap is ~0 and the numbers were always sound; they now agree exactly."""
    assert _speech_end_to_first_audio_ms(_JOIN_GAP_MS) == _speech_end_to_first_audio_ms(0)


def test_the_fake_transport_stamps_the_same_offset_as_the_livekit_one() -> None:
    """D13's fake is the gate's stand-in, so it must share the definition, not approximate it."""
    clock = _clock_at_join(_JOIN_GAP_MS)
    livekit = _livekit_transport(clock)
    fake = FakeCallTransport(clock=clock, started_at=SESSION_STARTED_AT)

    assert fake.now_ms() == livekit._now_ms() == _JOIN_GAP_MS

    clock.advance_ms(320)
    assert fake.now_ms() == livekit._now_ms()


def test_the_fake_transport_without_a_started_at_keeps_its_old_timeline() -> None:
    """Every pre-R13 caller passes no origin and must see exactly what it saw before."""
    clock = FakeClock()
    fake = FakeCallTransport(clock=clock)

    clock.advance_ms(64)
    assert fake.now_ms() == clock.monotonic_ms() == 64


async def test_a_livekit_transport_cannot_be_built_without_the_sessions_clock() -> None:
    """The origin is not defaultable: a transport with no clock would re-introduce the bug."""
    config = voice_turn_config_from_settings(settings())

    with pytest.raises(ValueError, match="session offsets"):
        build_transport(
            settings(call_transport="livekit"), config, token="t", clock=None, started_at=None
        )


async def test_build_transport_hands_the_clock_and_origin_to_the_livekit_transport() -> None:
    """The wiring seam itself, so the plumbing cannot rot without a test noticing."""
    clock = _clock_at_join(_JOIN_GAP_MS)
    transport = build_transport(
        settings(call_transport="livekit"),
        voice_turn_config_from_settings(settings()),
        token="t",
        clock=clock,
        started_at=SESSION_STARTED_AT,
    )

    assert isinstance(transport, LiveKitCallTransport)
    assert transport._now_ms() == _JOIN_GAP_MS

"""Chunked playback and its cancellation (§2.1, §6.1–§6.3; SPEC §18, §42 test 12).

SPEC §18 requires that queued caller audio really is cancelled and that the delivered portion is
preserved. Both are *measurements* here, taken from the fake transport's simulated playout clock
rather than from what the producer thinks it generated.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from app.application.ports.call_transport import AudioFrame
from app.application.testing.fakes import FakeCallTransport, FakeClock
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.turn_detector import TurnDetector

from tests.unit.application.voice.conftest import make_vad, quiet, speech


def caller_chunks(config: VoiceTurnConfig, *, count: int) -> list[AudioFrame]:
    """`count` TTS-sized chunks of caller audio (`tts_chunk_ms` each)."""
    samples = (config.sample_rate * config.tts_chunk_ms) // 1000
    return [
        AudioFrame(
            pcm=b"\x11\x11" * samples,
            sample_rate=config.sample_rate,
            num_channels=1,
            samples_per_channel=samples,
            capture_offset_ms=index * config.tts_chunk_ms,
        )
        for index in range(count)
    ]


async def as_stream(frames: list[AudioFrame]) -> AsyncIterator[AudioFrame]:
    """The `AsyncIterator[AudioFrame]` shape `CallTransport.play` takes (E14 gives a real one)."""
    for frame in frames:
        yield frame
        await asyncio.sleep(0)


@pytest.fixture
def clock() -> FakeClock:
    """A clock only this test moves."""
    return FakeClock()


async def test_natural_end_delivers_everything_and_nothing_is_discarded(
    config: VoiceTurnConfig, clock: FakeClock
) -> None:
    """A playback nobody interrupts reports `cancelled=False` and the whole utterance."""
    transport = FakeCallTransport(clock=clock, outbound_queue_ms=config.outbound_queue_ms)
    chunks = caller_chunks(config, count=10)
    handle = await transport.play(as_stream(chunks))

    delivered = await asyncio.wait_for(handle.wait_done(), timeout=5)

    assert delivered.cancelled is False
    assert delivered.total_audio_ms_generated == len(chunks) * config.tts_chunk_ms
    assert delivered.delivered_audio_ms == delivered.total_audio_ms_generated
    assert delivered.frames_discarded == 0
    assert transport.queue.queued_duration_ms() == 0


async def test_cancel_mid_utterance_reports_what_the_playout_clock_says(
    config: VoiceTurnConfig, clock: FakeClock
) -> None:
    """§6.3: `delivered = captured - queued_at_cancel`, measured, then clamped.

    The simulated playout clock is the arbiter: whatever it says had drained by the moment of the
    cancel is what the trainee heard, and everything still in the queue is thrown away.
    """
    transport = FakeCallTransport(clock=clock, outbound_queue_ms=config.outbound_queue_ms)
    chunks = caller_chunks(config, count=40)
    started_ms = clock.monotonic_ms()
    handle = await transport.play(as_stream(chunks))

    # Let the pump fill the queue and some of it drain.
    for _ in range(8):
        await asyncio.sleep(0)
    clock.advance_ms(120)
    await asyncio.sleep(0)

    played_out_ms = clock.monotonic_ms() - started_ms
    queued_before_cancel = transport.queue.queued_duration_ms()
    assert queued_before_cancel > 0, "the queue should still hold audio at the cancel"

    delivered = await handle.cancel()

    assert delivered.cancelled is True
    assert delivered.delivered_audio_ms == played_out_ms
    assert delivered.delivered_audio_ms < delivered.total_audio_ms_generated
    assert delivered.frames_discarded > 0
    assert transport.queue.queued_duration_ms() == 0
    assert transport.discarded_frames, "clear_queue must really drop the queued frames"
    # Idempotent: a second cancel returns the same accounting, it does not re-measure.
    assert await handle.cancel() == delivered


async def test_cancel_is_idempotent_and_leaves_the_handle_inactive(
    config: VoiceTurnConfig, clock: FakeClock
) -> None:
    """§2.1: "Stop playback now, drop queued frames, return what was delivered. Idempotent"."""
    transport = FakeCallTransport(clock=clock, outbound_queue_ms=config.outbound_queue_ms)
    handle = await transport.play(as_stream(caller_chunks(config, count=20)))
    for _ in range(4):
        await asyncio.sleep(0)

    first = await handle.cancel()
    assert handle.is_active() is False
    assert await handle.cancel() == first


async def test_onset_to_cutoff_is_inside_the_spec_18_budget(clock: FakeClock) -> None:
    """SPEC §18 / §6.2: onset → audio cutoff under 250 ms of simulated time, at defaults.

    "Onset" is the first trainee speech frame the detector sees; "cutoff" is the completion of
    `clear_outbound()`, which is the call that actually stops sound (§6.1 step 3). The whole path
    runs here — fake transport, `EnergyVAD`, `TurnDetector` — so the number is the pipeline's and
    not an arithmetic restatement of the config.
    """
    config = VoiceTurnConfig()
    frames = [
        *quiet(config, 300, 0),
        *speech(config, 500, 300),
    ]
    transport = FakeCallTransport(
        clock=clock, inbound=frames, outbound_queue_ms=config.outbound_queue_ms
    )
    handle = await transport.play(as_stream(caller_chunks(config, count=200)))
    detector = TurnDetector(config)
    vad = make_vad(config)

    onset_ms: int | None = None
    cutoff_ms: int | None = None
    async for frame in transport.inbound_audio():
        result = await vad.process(frame)
        if onset_ms is None and result.speech_probability >= config.speech_start_threshold:
            onset_ms = clock.monotonic_ms()
        step = detector.process(frame, result, playback_active=handle.is_active())
        if step.started is not None and step.started.was_during_playback:
            await transport.clear_outbound()
            cutoff_ms = clock.monotonic_ms()
            await handle.cancel()
            break

    assert onset_ms is not None, "the synthetic burst must cross the start threshold"
    assert cutoff_ms is not None, "a barge-in must have been detected during playback"
    assert cutoff_ms - onset_ms < 250, f"onset→cutoff was {cutoff_ms - onset_ms} ms (SPEC §18)"
    assert transport.queue.queued_duration_ms() == 0

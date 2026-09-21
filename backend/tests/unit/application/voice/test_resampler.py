"""`Resampler` — 48 kHz stereo in, 16 kHz mono frames out (§3.1, SPEC §16)."""

from __future__ import annotations

import math
from itertools import pairwise

from app.application.ports.call_transport import AudioFrame
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.resampler import Resampler


def transport_frame(
    *,
    duration_ms: int,
    sample_rate: int = 48_000,
    num_channels: int = 1,
    capture_offset_ms: int = 0,
    amplitude: float = 0.5,
    frequency_hz: float = 440.0,
) -> AudioFrame:
    """One inbound frame at the transport's rate, as LiveKit would deliver it."""
    count = (duration_ms * sample_rate) // 1000
    step = 2.0 * math.pi * frequency_hz / sample_rate
    pcm = bytearray()
    for index in range(count):
        value = round(amplitude * math.sin(step * index) * 32767)
        for _ in range(num_channels):
            pcm += value.to_bytes(2, "little", signed=True)
    return AudioFrame(
        pcm=bytes(pcm),
        sample_rate=sample_rate,
        num_channels=num_channels,
        samples_per_channel=count,
        capture_offset_ms=capture_offset_ms,
    )


def make() -> Resampler:
    config = VoiceTurnConfig()
    return Resampler(target_sample_rate=config.sample_rate, frame_samples=config.frame_samples)


def test_output_is_16k_mono_frames_of_exactly_frame_samples() -> None:
    """§3.1: the VAD window is fixed by the model; a short frame is a different question."""
    config = VoiceTurnConfig()
    resampler = make()
    out = resampler.process(transport_frame(duration_ms=200, num_channels=2))

    assert out, "200 ms at 48 kHz must complete several 32 ms output frames"
    for frame in out:
        assert frame.sample_rate == config.sample_rate
        assert frame.num_channels == 1
        assert frame.samples_per_channel == config.frame_samples
        assert len(frame.pcm) == config.frame_samples * 2


def test_remainder_is_carried_so_no_sample_is_lost_or_duplicated() -> None:
    """A partial output frame waits for the next input instead of being padded or dropped."""
    config = VoiceTurnConfig()
    resampler = make()
    total = 0
    for index in range(10):
        total += len(
            resampler.process(transport_frame(duration_ms=20, capture_offset_ms=index * 20))
        )
    # 200 ms at 16 kHz is 3200 samples = 6 whole 512-sample frames, with 128 carried.
    assert total == (200 * config.sample_rate // 1000) // config.frame_samples
    assert len(resampler.flush()) == 1


def test_capture_offsets_are_continuous_across_input_frames() -> None:
    """Offsets come from the emitted-sample count, so re-blocking cannot drift (D5, D7)."""
    config = VoiceTurnConfig()
    resampler = make()
    emitted: list[AudioFrame] = []
    for index in range(8):
        emitted.extend(
            resampler.process(transport_frame(duration_ms=40, capture_offset_ms=1000 + index * 40))
        )

    assert emitted[0].capture_offset_ms == 1000
    for previous, current in pairwise(emitted):
        assert current.capture_offset_ms - previous.capture_offset_ms == config.vad_frame_ms


def test_a_loud_input_is_limited_rather_than_clipped() -> None:
    """§3.1: a loud trainee must not clip the VAD/ASR input."""
    resampler = make()
    out = resampler.process(transport_frame(duration_ms=100, amplitude=1.0))
    peak = max(
        abs(int.from_bytes(frame.pcm[i : i + 2], "little", signed=True))
        for frame in out
        for i in range(0, len(frame.pcm), 2)
    )
    assert peak <= 32767
    assert peak > 0


def test_reset_drops_every_carried_sample_and_offset() -> None:
    """`reset()` is called at the start of every call; nothing may survive it."""
    resampler = make()
    resampler.process(transport_frame(duration_ms=20, capture_offset_ms=5000))
    resampler.reset()
    out = resampler.process(transport_frame(duration_ms=100, capture_offset_ms=7000))
    assert out[0].capture_offset_ms == 7000

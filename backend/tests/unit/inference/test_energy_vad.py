"""`EnergyVAD` — the gate's VAD (§2.2, `60-inference-ops.md` §1, D13)."""

from __future__ import annotations

import pytest
from app.application.ports.call_transport import AudioFrame
from app.application.testing.fakes import noise_frames, silence_frames, sine_burst_frames
from app.application.voice.config import VoiceTurnConfig
from app.inference.vad import EnergyVAD
from app.inference.vad.energy_vad import DEFAULT_FRAME_SAMPLES, DEFAULT_SAMPLE_RATE


@pytest.fixture
def vad() -> EnergyVAD:
    return EnergyVAD()


def test_window_matches_silero_so_the_two_are_frame_interchangeable(vad: EnergyVAD) -> None:
    """§2.2: "the same `frame_samples` so that config and tests are frame-identical"."""
    assert vad.frame_samples == DEFAULT_FRAME_SAMPLES == 512
    assert vad.required_sample_rate == DEFAULT_SAMPLE_RATE == 16_000
    assert vad.provider_name == "energy"


async def test_loud_speech_is_above_the_start_threshold_and_silence_is_below_the_end(
    vad: EnergyVAD,
) -> None:
    """The default hysteresis band must sit between synthetic speech and digital silence."""
    config = VoiceTurnConfig()
    loud = sine_burst_frames(duration_ms=64)[0]
    empty = silence_frames(duration_ms=64)[0]

    assert (await vad.process(loud)).speech_probability >= config.speech_start_threshold
    assert (await vad.process(empty)).speech_probability < config.speech_end_threshold


async def test_a_quiet_noise_floor_does_not_read_as_speech(vad: EnergyVAD) -> None:
    """Breath noise must not open a turn (§4.4's closing paragraph)."""
    config = VoiceTurnConfig()
    for frame in noise_frames(duration_ms=320):
        probability = (await vad.process(frame)).speech_probability
        assert probability < config.speech_start_threshold


async def test_the_result_carries_the_frame_s_own_offset_and_duration(vad: EnergyVAD) -> None:
    """`VadFrameResult` is session-relative, from the frame, never from a wall clock (D5)."""
    frame = sine_burst_frames(duration_ms=32, start_offset_ms=4096)[0]
    result = await vad.process(frame)
    assert result.frame_start_ms == 4096
    assert result.frame_duration_ms == 32


@pytest.mark.parametrize(
    "bad",
    [
        {"sample_rate": 8_000},
        {"num_channels": 2},
        {"samples_per_channel": 256},
    ],
)
async def test_a_frame_of_the_wrong_shape_is_refused(vad: EnergyVAD, bad: dict[str, int]) -> None:
    """§2.2: "`frame` must carry exactly `frame_samples` mono samples at the required rate"."""
    frame = sine_burst_frames(duration_ms=32)[0]
    wrong = AudioFrame(
        pcm=frame.pcm,
        sample_rate=bad.get("sample_rate", frame.sample_rate),
        num_channels=bad.get("num_channels", frame.num_channels),
        samples_per_channel=bad.get("samples_per_channel", frame.samples_per_channel),
        capture_offset_ms=frame.capture_offset_ms,
    )
    with pytest.raises(ValueError, match="EnergyVAD"):
        await vad.process(wrong)


async def test_warm_up_and_reset_are_no_ops_and_close_is_final(vad: EnergyVAD) -> None:
    """The port is uniform even for a provider with no model (SPEC §37)."""
    await vad.warm_up()
    vad.reset()
    await vad.close()
    await vad.close()
    with pytest.raises(RuntimeError, match="closed"):
        await vad.process(sine_burst_frames(duration_ms=32)[0])

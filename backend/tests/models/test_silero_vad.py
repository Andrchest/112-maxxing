"""`SileroVAD` contract test against the real onnx model and a real Russian recording.

Marker `requires_models` (E12 ruling 1): `make test-models` only. Skips (never fails) when
`SIM_RUN_MODEL_TESTS!=1`, onnxruntime is not importable, or `models/silero-vad/silero_vad.onnx`
(`make models-silero`) is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from app.application.ports.call_transport import AudioFrame
from app.inference.vad.silero_vad import FRAME_SAMPLES, REQUIRED_SAMPLE_RATE, SileroVAD

from tests.models._skip import require_model_env

pytestmark = pytest.mark.requires_models

_MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / "silero-vad" / "silero_vad.onnx"
_SAMPLE_PATH = Path(__file__).resolve().parent / "assets" / "ru_sample.wav"


def _frames(pcm: bytes, *, start_offset_ms: int = 0) -> list[AudioFrame]:
    """Chop raw PCM s16le mono into exact `FRAME_SAMPLES`-sample frames; a short tail is dropped
    (the model needs an exact frame — the pipeline's `Resampler` carries the remainder itself,
    §3.1, so a test fixture dropping it is faithful to production, not a shortcut)."""
    bytes_per_frame = FRAME_SAMPLES * 2
    out = []
    offset_ms = start_offset_ms
    ms_per_frame = (FRAME_SAMPLES * 1000) // REQUIRED_SAMPLE_RATE
    for i in range(0, len(pcm) - bytes_per_frame + 1, bytes_per_frame):
        out.append(
            AudioFrame(
                pcm=pcm[i : i + bytes_per_frame],
                sample_rate=REQUIRED_SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=FRAME_SAMPLES,
                capture_offset_ms=offset_ms,
            )
        )
        offset_ms += ms_per_frame
    return out


def _read_sample_pcm() -> bytes:
    with wave.open(str(_SAMPLE_PATH), "rb") as wf:
        assert wf.getframerate() == REQUIRED_SAMPLE_RATE
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        return wf.readframes(wf.getnframes())


@pytest.fixture
async def vad() -> SileroVAD:
    require_model_env(packages=("onnxruntime",), paths=(_MODEL_PATH, _SAMPLE_PATH))
    provider = SileroVAD(model_path=str(_MODEL_PATH))
    await provider.warm_up()
    yield provider
    await provider.close()


async def test_the_sample_recording_produces_at_least_one_confident_speech_frame(
    vad: SileroVAD,
) -> None:
    pcm = _read_sample_pcm()
    probabilities = [(await vad.process(frame)).speech_probability for frame in _frames(pcm)]
    assert max(probabilities) >= 0.55


async def test_a_silence_buffer_stays_below_the_end_threshold(vad: SileroVAD) -> None:
    silence = b"\x00\x00" * FRAME_SAMPLES * 20  # ~640 ms of digital silence
    probabilities = [(await vad.process(frame)).speech_probability for frame in _frames(silence)]
    assert all(p < 0.35 for p in probabilities)


async def test_reset_makes_two_identical_passes_produce_identical_probabilities(
    vad: SileroVAD,
) -> None:
    pcm = _read_sample_pcm()
    frames = _frames(pcm)[:40]  # a prefix is enough to prove state carries and resets cleanly

    vad.reset()
    first_pass = [(await vad.process(frame)).speech_probability for frame in frames]
    vad.reset()
    second_pass = [(await vad.process(frame)).speech_probability for frame in frames]

    assert first_pass == second_pass

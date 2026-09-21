"""`FasterWhisperProvider` contract test — optional, never downloads a model (E12 ruling 4).

Marker `requires_models` (E12 ruling 1): `make test-models` only. Skips (never fails) unless
`SIM_RUN_MODEL_TESTS=1`, `faster_whisper` is importable, **and** `SIM_WHISPER_MODEL_PATH` points at
a CTranslate2 Whisper model directory a developer already has locally — this task does not ship
one and must not download one (SPEC §41).
"""

from __future__ import annotations

import os
import wave
from pathlib import Path

import pytest
from app.inference.asr.faster_whisper_provider import FasterWhisperProvider

from tests.models._skip import require_model_env

pytestmark = pytest.mark.requires_models

_SAMPLE_PATH = Path(__file__).resolve().parent / "assets" / "ru_sample.wav"
_SAMPLE_RATE = 16_000


def _read_sample_pcm() -> bytes:
    with wave.open(str(_SAMPLE_PATH), "rb") as wf:
        assert wf.getframerate() == _SAMPLE_RATE
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        return wf.readframes(wf.getnframes())


@pytest.fixture
async def provider() -> FasterWhisperProvider:
    model_path = os.environ.get("SIM_WHISPER_MODEL_PATH")
    if not model_path:
        pytest.skip("SIM_WHISPER_MODEL_PATH is unset (ruling 4: this test never downloads a model)")
    require_model_env(packages=("faster_whisper",), paths=(model_path, _SAMPLE_PATH))
    instance = FasterWhisperProvider(model_path=model_path)
    await instance.warm_up()
    yield instance
    await instance.close()


async def test_transcribe_returns_nonempty_text(provider: FasterWhisperProvider) -> None:
    pcm = _read_sample_pcm()
    result = await provider.transcribe(pcm, _SAMPLE_RATE, request_id="fw-smoke")
    assert result.text.strip()
    assert result.is_final is True
    assert result.provider == "faster_whisper"


async def test_the_wrong_sample_rate_is_refused(provider: FasterWhisperProvider) -> None:
    with pytest.raises(ValueError, match="16000"):
        await provider.transcribe(b"\x00\x00", 8_000, request_id="fw-bad-rate")

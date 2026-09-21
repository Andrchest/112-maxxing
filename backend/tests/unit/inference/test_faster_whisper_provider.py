"""`FasterWhisperProvider` — gate-side guarantees only (E12 ruling 1/2/4).

No `faster_whisper` package, no model: this file runs everywhere `make gate` runs. There is no
`backend/tests/models/` counterpart with a bundled model — ruling 4 forbids downloading a Whisper
model, so the contract test (also in this file's sibling under `backend/tests/models/`) skips
unless a developer points `SIM_WHISPER_MODEL_PATH` at one they already have locally.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.application.ports.asr import UnsupportedOperationError
from app.inference.asr.faster_whisper_provider import FasterWhisperProvider
from app.inference.errors import ModelNotAvailableError


def test_the_module_imports_cleanly_with_no_faster_whisper_installed() -> None:
    """E12 ruling 2: `import app.inference.asr.faster_whisper_provider` needs no extra."""
    assert True


def test_port_properties_need_no_model_loaded() -> None:
    provider = FasterWhisperProvider(model_path="/nonexistent/whisper-model")
    assert provider.provider_name == "faster_whisper"
    assert provider.model_version == "whisper-model"
    assert provider.supports_streaming is False
    assert provider.required_sample_rate == 16_000


def test_stream_raises_not_implemented_naming_the_pseudo_stream() -> None:
    provider = FasterWhisperProvider(model_path="/nonexistent/whisper-model")
    with pytest.raises(UnsupportedOperationError, match="pseudo-stream"):
        provider.stream(iter(()), request_id="r1")


async def test_transcribe_before_warm_up_is_refused() -> None:
    provider = FasterWhisperProvider(model_path="/nonexistent/whisper-model")
    with pytest.raises(RuntimeError, match="warm_up"):
        await provider.transcribe(b"\x00\x00", 16_000, request_id="r1")


async def test_the_wrong_sample_rate_is_refused_even_before_warm_up() -> None:
    provider = FasterWhisperProvider(model_path="/nonexistent/whisper-model")
    with pytest.raises(ValueError, match="16000"):
        await provider.transcribe(b"\x00\x00", 8_000, request_id="r1")


async def test_a_missing_model_path_raises_model_not_available_without_importing_faster_whisper(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "whisper-model"
    provider = FasterWhisperProvider(model_path=str(missing))
    with pytest.raises(ModelNotAvailableError, match=str(missing)) as excinfo:
        await provider.warm_up()
    assert "SIM_WHISPER_MODEL_PATH" in str(excinfo.value)


async def test_close_before_warm_up_is_a_no_op() -> None:
    provider = FasterWhisperProvider(model_path="/nonexistent/whisper-model")
    await provider.close()
    await provider.close()

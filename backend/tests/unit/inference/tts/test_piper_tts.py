"""`PiperTTS` — warm_up/model-missing, streaming/chunking and cancel, over a FAKE `piper` module
(this task's brief, item 3). `piper-tts` need not be installed for these tests: `warm_up()`
imports it lazily (`from piper import PiperVoice`), so a fake module injected into `sys.modules`
before the call is all any test here needs — the real package is only exercised by
`backend/tests/models/test_tts_contract.py` (marker `requires_models`).
"""

from __future__ import annotations

import logging
import struct
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from app.application.ports.tts import TtsUnavailableError, TtsVoiceSpec
from app.inference.errors import ModelNotAvailableError
from app.inference.tts.piper_tts import PiperTTS

_VOICE = TtsVoiceSpec(voice_id="ru_RU-irina-medium", speaking_rate=1.0)
_SAMPLE_RATE = 22050


class _FakeConfig:
    sample_rate = _SAMPLE_RATE


class _FakeAudioChunk:
    """Stands in for `piper.voice.AudioChunk` — only the attribute this adapter reads."""

    def __init__(self, pcm: bytes) -> None:
        self.audio_int16_bytes = pcm


class _FakeVoice:
    """Stands in for `piper.voice.PiperVoice` (the real `piper-tts>=1.2,<2`, measured 1.8.0,
    package: `synthesize(text) -> Iterable[AudioChunk]`, not the older `synthesize_stream_raw`
    this adapter was originally written against — see `piper_tts.py`'s "E14 close-out fix")."""

    def __init__(self, pieces: list[bytes] | None = None, *, fail: bool = False) -> None:
        self.config = _FakeConfig()
        self._pieces = pieces if pieces is not None else [_tone_pcm(200), _tone_pcm(200)]
        self._fail = fail
        self.calls: list[str] = []

    def synthesize(self, text: str):
        self.calls.append(text)
        if self._fail:
            raise RuntimeError("piper internal failure detail")
        yield from (_FakeAudioChunk(piece) for piece in self._pieces)


def _tone_pcm(n_samples: int) -> bytes:
    return struct.pack(f"<{n_samples}h", *([500] * n_samples))


def _install_fake_piper(monkeypatch: pytest.MonkeyPatch, voice: _FakeVoice) -> None:
    fake_module = types.ModuleType("piper")

    class _PiperVoice:
        @staticmethod
        def load(onnx_path: str, json_path: str) -> _FakeVoice:
            return voice

    fake_module.PiperVoice = _PiperVoice  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper", fake_module)


async def test_warm_up_raises_model_not_available_when_files_are_missing(tmp_path: Path) -> None:
    provider = PiperTTS(voice_path=str(tmp_path / "does-not-exist.onnx"))
    with pytest.raises(ModelNotAvailableError):
        await provider.warm_up()


async def test_warm_up_loads_the_voice_and_sets_sample_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    onnx_path = tmp_path / "ru_RU-irina-medium.onnx"
    onnx_path.write_bytes(b"fake")
    (tmp_path / "ru_RU-irina-medium.onnx.json").write_text("{}")
    voice = _FakeVoice()
    _install_fake_piper(monkeypatch, voice)

    provider = PiperTTS(voice_path=str(onnx_path))
    await provider.warm_up()

    assert provider.output_sample_rate == _SAMPLE_RATE
    assert provider.model_version == "ru_RU-irina-medium"


def _ready_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, voice: _FakeVoice) -> Any:
    onnx_path = tmp_path / "ru_RU-irina-medium.onnx"
    onnx_path.write_bytes(b"fake")
    (tmp_path / "ru_RU-irina-medium.onnx.json").write_text("{}")
    _install_fake_piper(monkeypatch, voice)
    return PiperTTS(voice_path=str(onnx_path))


async def test_stream_before_warm_up_raises() -> None:
    provider = PiperTTS(voice_path="unused.onnx")
    stream = provider.stream("тест", _VOICE, request_id="r0")
    with pytest.raises(RuntimeError):
        _ = [chunk async for chunk in stream]


async def test_stream_yields_chunks_within_max_chunk_ms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice = _FakeVoice(pieces=[_tone_pcm(_SAMPLE_RATE)])  # 1 s of audio
    provider = _ready_provider(tmp_path, monkeypatch, voice)
    await provider.warm_up()

    stream = provider.stream(
        "Здравствуйте, это проверка.", _VOICE, request_id="r1", max_chunk_ms=40
    )
    chunks = [chunk async for chunk in stream]

    assert chunks
    for chunk in chunks:
        assert chunk.audio_ms <= 40
        assert chunk.alignment_is_exact is False
    assert chunks[-1].text_offset_end == len("Здравствуйте, это проверка.")
    assert voice.calls == ["Здравствуйте, это проверка."]


async def test_synthesis_failure_raises_tts_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice = _FakeVoice(fail=True)
    provider = _ready_provider(tmp_path, monkeypatch, voice)
    await provider.warm_up()

    stream = provider.stream("тест", _VOICE, request_id="r2")
    with pytest.raises(TtsUnavailableError):
        _ = [chunk async for chunk in stream]


async def test_cancel_before_iteration_yields_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice = _FakeVoice()
    provider = _ready_provider(tmp_path, monkeypatch, voice)
    await provider.warm_up()

    stream = provider.stream("тест", _VOICE, request_id="r3")
    await stream.cancel()
    chunks = [chunk async for chunk in stream]

    assert chunks == []


async def test_cancel_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    voice = _FakeVoice()
    provider = _ready_provider(tmp_path, monkeypatch, voice)
    await provider.warm_up()
    stream = provider.stream("тест", _VOICE, request_id="r4")
    await stream.cancel()
    await stream.cancel()


async def test_warm_up_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    voice = _FakeVoice()
    provider = _ready_provider(tmp_path, monkeypatch, voice)
    await provider.warm_up()
    await provider.warm_up()  # must not reload / must not raise
    assert provider.output_sample_rate == _SAMPLE_RATE


# --- E20-G/G6: the logical -> native voice map ---------------------------------------------------


def test_native_voice_id_maps_a_logical_id_and_defaults_to_the_loaded_voice(
    tmp_path: Path,
) -> None:
    provider = PiperTTS(
        voice_path=str(tmp_path / "ru_RU-irina-medium.onnx"),
        voice_map={"ru_female_adult_01": "ru_RU-irina-medium"},
    )
    assert provider.native_voice_id("ru_female_adult_01") == "ru_RU-irina-medium"
    # A miss falls back to the loaded voice file's stem — never an error.
    assert provider.native_voice_id("ru_male_adult_01") == "ru_RU-irina-medium"
    assert provider.native_voice_id("") == "ru_RU-irina-medium"


def test_an_explicit_default_voice_wins_over_the_voice_file_stem(tmp_path: Path) -> None:
    provider = PiperTTS(
        voice_path=str(tmp_path / "whatever.onnx"), default_voice="ru_RU-irina-medium"
    )
    assert provider.native_voice_id("ru_female_adult_01") == "ru_RU-irina-medium"


def test_an_unmapped_logical_voice_id_warns_exactly_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    provider = PiperTTS(voice_path=str(tmp_path / "ru_RU-irina-medium.onnx"))
    with caplog.at_level(logging.WARNING, logger="app.inference.tts.piper_tts"):
        for _ in range(3):
            provider.native_voice_id("ru_female_adult_01")
        provider.native_voice_id("ru_male_adult_01")
    warnings = [r for r in caplog.records if "voice_map" in r.getMessage()]
    assert len(warnings) == 2


async def test_stream_never_raises_for_an_unknown_logical_voice_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug E20-C's walk hit on Qwen3-TTS, asserted for the fallback provider too."""
    onnx_path = tmp_path / "ru_RU-irina-medium.onnx"
    onnx_path.write_bytes(b"fake")
    (tmp_path / "ru_RU-irina-medium.onnx.json").write_text("{}")
    _install_fake_piper(monkeypatch, _FakeVoice())

    provider = PiperTTS(voice_path=str(onnx_path))
    await provider.warm_up()
    stream = provider.stream(
        "тест", TtsVoiceSpec(voice_id="ru_female_adult_01", speaking_rate=1.0), request_id="r1"
    )
    chunks = [chunk async for chunk in stream]
    assert chunks

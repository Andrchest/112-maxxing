"""`FasterWhisperProvider` — the optional fallback `ASRProvider` over faster-whisper
(`50-voice-pipeline.md` §2.3, E12 ruling 4).

Not downloaded or exercised by `make gate` or `make test-models` by default: its own contract test
(`backend/tests/models/test_faster_whisper_provider.py`) skips unless `SIM_WHISPER_MODEL_PATH`
points at an already-present CTranslate2 Whisper model directory (SPEC §41 — nothing here ever
downloads a model). `faster_whisper` (the `asr-whisper` extra) is imported lazily inside
`warm_up()`, never at module import time (E12 ruling 2).
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any

import numpy as np

from app.application.ports.asr import AsrResult, UnsupportedOperationError
from app.inference.errors import ModelNotAvailableError

__all__ = ["FasterWhisperProvider"]

_PROVIDER_NAME = "faster_whisper"
_LANGUAGE = "ru"
_BYTES_PER_SAMPLE = 2
_MS_PER_S = 1000
_INT16_SCALE = 32768.0


class FasterWhisperProvider:
    """`ASRProvider` over a local CTranslate2 Whisper model directory."""

    provider_name = _PROVIDER_NAME

    def __init__(self, *, model_path: str, device: str = "cpu", compute_type: str = "int8") -> None:
        self._model_path = model_path
        self._device = device
        self._compute_type = compute_type
        self._model_version = Path(model_path).name
        self._model: Any = None
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def supports_streaming(self) -> bool:
        return False

    @property
    def required_sample_rate(self) -> int:
        return 16_000

    async def warm_up(self) -> None:
        if self._model is not None:
            return
        path = Path(self._model_path)
        if not await asyncio.to_thread(path.exists):
            raise ModelNotAvailableError(
                f"faster-whisper model not found at {path}; set SIM_WHISPER_MODEL_PATH to a local "
                "CTranslate2 Whisper model directory (this provider never downloads one, SPEC §41)"
            )
        from faster_whisper import WhisperModel

        self._model = WhisperModel(str(path), device=self._device, compute_type=self._compute_type)
        silence = b"\x00\x00" * (self.required_sample_rate // 10)  # 100 ms
        await self.transcribe(silence, self.required_sample_rate, request_id="warmup")

    async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> AsrResult:
        if sample_rate != self.required_sample_rate:
            raise ValueError(
                f"FasterWhisperProvider needs {self.required_sample_rate} Hz, got {sample_rate}"
            )
        if self._model is None:
            raise RuntimeError("FasterWhisperProvider.warm_up() must be called before transcribe()")
        async with self._lock:
            text, confidence = await asyncio.to_thread(self._transcribe_sync, audio)
        duration_ms = (
            (len(audio) * _MS_PER_S) // (sample_rate * _BYTES_PER_SAMPLE) if sample_rate else 0
        )
        return AsrResult(
            text=text,
            is_final=True,
            start_ms=0,
            end_ms=duration_ms,
            confidence=confidence,
            words=[],
            provider=self.provider_name,
            model_version=self._model_version,
            audio_duration_ms=duration_ms,
            language=_LANGUAGE,
        )

    def _transcribe_sync(self, audio: bytes) -> tuple[str, float]:
        samples = np.frombuffer(audio, dtype="<i2").astype(np.float32) / _INT16_SCALE
        segments, _info = self._model.transcribe(samples, language=_LANGUAGE)
        texts: list[str] = []
        weighted_confidence = 0.0
        total_duration_s = 0.0
        for segment in segments:
            texts.append(segment.text.strip())
            duration_s = max(0.0, segment.end - segment.start)
            # faster-whisper gives no direct probability; `avg_logprob` -> exp() is the standard
            # proxy (whisper.cpp/openai-whisper use the same conversion for a confidence display).
            weighted_confidence += math.exp(segment.avg_logprob) * duration_s
            total_duration_s += duration_s
        text = " ".join(part for part in texts if part)
        confidence = weighted_confidence / total_duration_s if total_duration_s > 0 else 0.0
        return text, min(1.0, max(0.0, confidence))

    def stream(self, frames: Any, *, request_id: str) -> Any:
        raise UnsupportedOperationError(
            "FasterWhisperProvider.supports_streaming is False; the TurnPipeline pseudo-streams "
            "over transcribe() instead (docs/hld/50-voice-pipeline.md §4.5)"
        )

    async def close(self) -> None:
        """Drop the model. Idempotent."""
        self._closed = True
        self._model = None

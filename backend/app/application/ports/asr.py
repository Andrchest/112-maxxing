"""`ASRProvider` port (HLD `50-voice-pipeline.md` §2.3, D9, SPEC §19).

SPEC §19 is the reason this file exists at all: "Domain code must not depend on a specific model."
The turn path knows `transcribe()` and `stream()`; it never knows GigaAM, faster-whisper or the
fake. The one place a provider's identity is allowed to surface is telemetry — `provider_name` and
`model_version` are written to `ASR_FINAL.asr_provider` / `asr_model` and to `inference_metrics`
(SPEC §27) — and §2.3 says so in as many words: "Downstream code never branches on `provider_name`
except when writing telemetry."

The dataclasses are §2.3's, field for field:

* `AsrWord` — optional word timings, empty for a provider that gives none;
* `AsrResult` — one finalized recognition; `transcribe()` always returns `is_final=True`;
* `AsrPartial` — one incremental hypothesis, `stability=None` when the provider has no such
  signal (which is every pseudo-streamed partial of §4.5).

`start_ms` / `end_ms` are **session-relative**, like every other offset in the voice path (D9):
the provider is handed the turn's own offsets, it does not invent a timeline of its own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.application.ports.call_transport import AudioFrame

__all__ = [
    "ASRProvider",
    "AsrPartial",
    "AsrResult",
    "AsrWord",
    "UnsupportedOperationError",
]


class UnsupportedOperationError(RuntimeError):
    """Raised by `ASRProvider.stream` when `supports_streaming` is False (§2.3).

    §4.5 branches on `supports_streaming` before it ever calls `stream()`, so this error is a
    programming-time guard rather than a runtime path: a provider that answers False and is then
    streamed anyway is a wiring bug, not a degraded mode.
    """


@dataclass(frozen=True, slots=True)
class AsrWord:
    """One recognised word with its timing (§2.3)."""

    text: str
    start_ms: int
    end_ms: int
    confidence: float | None


@dataclass(frozen=True, slots=True)
class AsrResult:
    """One finalized recognition (§2.3). `transcribe` always returns `is_final=True`."""

    text: str
    is_final: bool
    start_ms: int
    """Session-relative."""

    end_ms: int
    confidence: float | None
    words: list[AsrWord] = field(default_factory=list)
    provider: str = ""
    """e.g. `"gigaam"` — telemetry only (SPEC §19)."""

    model_version: str = ""
    """e.g. `"v3_e2e_ctc"` — telemetry only."""

    audio_duration_ms: int = 0
    language: str = "ru"


@dataclass(frozen=True, slots=True)
class AsrPartial:
    """One incremental hypothesis (§2.3, §4.5). Never persisted, never fed downstream."""

    text: str
    start_ms: int
    end_ms: int
    stability: float | None
    """`None` when the provider gives no stability signal."""


@runtime_checkable
class ASRProvider(Protocol):
    """Speech recognition over one finalized turn, or incrementally (§2.3)."""

    @property
    def provider_name(self) -> str:
        """Short identifier written to `ASR_FINAL.asr_provider` and `inference_metrics.provider`."""
        ...

    @property
    def model_version(self) -> str:
        """The loaded weights' version, written to `ASR_FINAL.asr_model`."""
        ...

    @property
    def supports_streaming(self) -> bool:
        """True when `stream()` is usable; §4.5 pseudo-streams when it is False."""
        ...

    @property
    def required_sample_rate(self) -> int:
        """The only sample rate this provider accepts (16000 for every provider so far)."""
        ...

    async def warm_up(self) -> None:
        """Run one dummy recognition so the first real turn is not the first inference (§4.2)."""
        ...

    async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> AsrResult:
        """Transcribe one finalized turn.

        `audio` is PCM s16le mono at `sample_rate`. Always returns `is_final=True`.
        """
        ...

    def stream(
        self, frames: AsyncIterator[AudioFrame], *, request_id: str
    ) -> AsyncIterator[AsrResult | AsrPartial]:
        """Incremental recognition.

        Raises `UnsupportedOperationError` when `supports_streaming` is False. Yields zero or more
        `AsrPartial` then exactly one `AsrResult` with `is_final=True`.
        """
        ...

    async def close(self) -> None:
        """Release the model. Idempotent."""
        ...

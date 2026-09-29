"""`TTSProvider` port (HLD `50-voice-pipeline.md` §2.4, D9, SPEC §18, §19, §25, §41).

Every outbound caller utterance is synthesised through this one Protocol. `FakeTTS`
(`app.inference.tts.fake_tts`) is what the gate and every non-`requires_models` test run against
(D13); `PiperTTS` is the CPU fallback and `Qwen3TTS` the GPU default, both under
`app.inference.tts/` (E14-B).

`TtsTimeoutError` and `TtsUnavailableError` live here, not in `app.inference`, for exactly the
reason given in `ports/llm.py`: a caller in `app.application` (`TtsSpeechSink`, which classifies a
failure into `InferenceMetric.status` and `MODEL_ERROR.error_kind`) and an adapter in
`app.inference` (which raises them) need the same type, and `app.application` may not import
`app.inference` (D2).

Copied verbatim from §2.4 apart from:

* `from __future__ import annotations`, `__all__` and `@runtime_checkable` on the two Protocols —
  the same house-keeping `ports/llm.py` (E13-B1) added to its §2.5 snippet.
* the two error types above, which §2.4 does not declare at all (§2.5 declares its pair, and
  INV 14 needs the TTS equivalent).
* `TtsVoiceSpec.emotion: EmotionState | None = None` — additive (this task's MANAGER RULING on
  E14-B's gap 1: emotion must reach the voice without mutable provider state; see
  `app.application.voice.tts_speech_sink.TtsSpeechSink._voice_for`/`speak` and
  `app.inference.tts.qwen3_tts.Qwen3TTS.stream`).

Every name, order, type and default in the snippet is otherwise unchanged apart from the additive
`emotion` field above and `max_chunk_ms`'s default (40 -> 20, this task, SPEC §18); unlike §2.5,
§2.4 had no mypy-strict violation to fix.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.application.ports.call_transport import AudioFrame
from app.domain.caller.emotion import EmotionState
from app.domain.enums import CallerVoiceStyle

__all__ = [
    "TTSProvider",
    "TtsChunk",
    "TtsStream",
    "TtsTimeoutError",
    "TtsUnavailableError",
    "TtsVoiceSpec",
]


@dataclass(frozen=True, slots=True)
class TtsVoiceSpec:
    voice_id: str  # CallerProfile.voice_id
    speaking_rate: float  # 1.0 = provider default; CallerProfile.speaking_rate
    pitch: float = 0.0  # semitones; 0.0 = provider default
    language: str = "ru"
    emotion: EmotionState | None = None
    # additive (MANAGER RULING on E14-B gap 1, E14): PlannedCallerUtterance.emotion, carried so a
    # provider's instruct/style lever can read it without any mutable provider-side state. `None`
    # means "no live emotion available" (e.g. a warm-up call) — a provider treats that as neutral.
    # `app.application` -> `app.domain` is an allowed import (D2).
    voice_style: CallerVoiceStyle | None = None
    # additive (I8 V0): the scenario's closed `caller_profile.voice_style` hint (`PAIN`), read
    # once per session with the voice. A provider without a style lever ignores it.
    seed: int | None = None
    # additive (I8 V1): the synthesis seed of ONE unit, set per unit by `ChunkedTtsStream` when
    # the profile's `tts.seed_mode` is `derived` (`derive_tts_seed`). `None` = unseeded. A
    # provider without a seed lever ignores it.


@dataclass(frozen=True, slots=True)
class TtsChunk:
    """One cancellable unit of synthesised audio with the text it covers."""

    frame: AudioFrame
    text_offset_start: int  # character offset into the request text this chunk begins at
    text_offset_end: int  # exclusive; the text-alignment metadata D9 requires
    alignment_is_exact: bool  # False when the adapter derived offsets word-proportionally
    chunk_index: int
    audio_ms: int


class TtsTimeoutError(RuntimeError):
    """Synthesis exceeded `tts_timeout_ms` / `tts_first_chunk_timeout_ms`
    (SPEC §27 `status = "TIMEOUT"`)."""


class TtsUnavailableError(RuntimeError):
    """The provider could not be reached, or failed with a transport/HTTP/runtime failure that is
    not an out-of-memory condition (`app.inference.errors.InferenceOutOfMemoryError` is that one;
    SPEC §27 `status = "ERROR"`)."""


@runtime_checkable
class TtsStream(Protocol):
    @property
    def request_id(self) -> str: ...

    def __aiter__(self) -> AsyncIterator[TtsChunk]: ...

    async def cancel(self) -> None:
        """Stop generation as soon as the current chunk completes. Idempotent."""
        ...

    @property
    def text(self) -> str:
        """The exact text handed to the provider — persisted per SPEC §25."""
        ...


@runtime_checkable
class TTSProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    @property
    def output_sample_rate(self) -> int: ...

    async def warm_up(self) -> None: ...

    def stream(
        self,
        text: str,
        voice: TtsVoiceSpec,
        *,
        request_id: str,
        max_chunk_ms: int = 20,
    ) -> TtsStream:
        """Begin streaming synthesis. Must yield the first chunk without waiting for full synthesis.
        Chunks are at most `max_chunk_ms` of audio so that cancellation is bounded (SPEC §18)."""
        ...

    async def close(self) -> None: ...

"""`PiperTTS` — the CPU `TTSProvider`, and the configured fallback for every profile (HLD
`50-voice-pipeline.md` §2.4, §10, D9: "`PiperTTS` — CPU, onnxruntime, Russian voice models; ... the
configured fallback").

Unlike `Qwen3TTS`, Piper runs **in-process**: the `piper-tts` PyPI package wraps an onnxruntime
session directly, so there is no separate worker/venv split here (its own `onnxruntime` floor does
not conflict with the backend's `vad-silero` extra's `onnxruntime>=1.19,<2` pin — see this task's
report). `piper.PiperVoice.load()`/`.synthesize()` are imported lazily inside `warm_up()`, matching
every other real adapter in this repository (D1).

**E14 close-out fix (item 7, "Piper, for real").** The real `piper-tts>=1.2,<2` this extra resolves
to today (measured: 1.8.0) exposes
`PiperVoice.synthesize(text) -> Iterable[piper.voice.AudioChunk]`, not the
`synthesize_stream_raw(text) -> Iterable[bytes]` this adapter was written against (never
actually run against the real package before this task — `piper-tts` was not installed anywhere in
the environment, see E14-B's report). `AudioChunk.audio_int16_bytes` is the s16le PCM this adapter
needs; everything else about the shape (one `AudioChunk` per sentence-ish piece, still a
**synchronous generator**) is unchanged. This adapter drains it via repeated
`asyncio.to_thread(next, ...)` calls rather than one `asyncio.to_thread(list, generator)` call: the
event loop never blocks on Piper's CPU inference (`asyncio.to_thread`, this task's brief item 3)
*and* `cancel()` can stop the drain between pieces rather than only before or after the whole
sentence — genuinely bounded cancellation, unlike Qwen3-TTS's whole-utterance call (recon §1.1, §6
item 2).

**HLD gap** (listed in this task's report): pieces are buffered and re-chunked to `<= max_chunk_ms`
*after* the generator is fully drained, not re-chunked incrementally as each piece arrives — so the
first `TtsChunk` is only yielded once this adapter has consumed all of Piper's raw pieces for the
given text unit, not literally "before full synthesis" the way §2.4's docstring asks. The
alternative (emitting Piper's raw, irregularly-sized pieces directly as `TtsChunk`s without
re-chunking) would violate the `<= max_chunk_ms` bound the port promises callers cancellation
around; re-chunking incrementally with honest proportional text offsets would need either
per-piece timing data Piper's raw-stream API does not expose, or an invented total-duration
estimate (SPEC §27 forbids fabricating a number). Since the input unit here is one sentence/clause
(the chunker in `app.application.voice` splits before this adapter ever sees text) and Piper's CPU
RTF for one short Russian sentence is well under the `tts_first_chunk_timeout_ms` budget in
practice, buffer-then-rechunk was judged the smaller compromise; a future epic revisiting real
first-audio-latency measurements (`benchmarks/benchmark_tts.py`, `60-inference-ops.md` §7.3) is
where this should be revisited if it turns out to matter.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.application.ports.call_transport import AudioFrame
from app.application.ports.tts import TtsChunk, TtsUnavailableError, TtsVoiceSpec
from app.inference.errors import ModelNotAvailableError

__all__ = ["PiperTTS"]

logger = logging.getLogger(__name__)

_BYTES_PER_SAMPLE = 2
_MS_PER_S = 1000
_STOP = object()  # sentinel: "the generator is exhausted"


class _VoiceResolver:
    """`TtsVoiceSpec.voice_id` (a SCENARIO-LOGICAL id) -> Piper's NATIVE voice name (E20-G).

    Same contract and same reasoning as `app.inference.tts.qwen3_tts._VoiceResolver` (read its
    docstring): the logical -> native table lives in the active model profile (`tts.voice_map`),
    `tts.default_voice` answers every miss, a miss is one WARN per `(provider, logical id)` pair
    and never an error. Duplicated rather than shared for the same reason `_chunk_pcm` is.

    Piper's "native voice" is the voice MODEL this process loaded (`ru_RU-irina-medium`): a single
    `.onnx` file chosen by `SIM_TTS_PIPER_VOICE_PATH`, not a per-utterance parameter. So the
    resolved id here does not change what is synthesised — it is what
    `CALLER_TTS_STARTED.voice_id_native` records, and it keeps one resolution rule across
    providers rather than a special case per adapter.
    """

    __slots__ = ("_default", "_map", "_provider_name", "_warned")

    def __init__(
        self, *, provider_name: str, voice_map: Mapping[str, str] | None, default: str
    ) -> None:
        self._provider_name = provider_name
        self._map = dict(voice_map or {})
        self._default = default
        self._warned: set[str] = set()

    def resolve(self, voice_id: str) -> str:
        if not voice_id:
            return self._default
        native = self._map.get(voice_id)
        if native is not None:
            return native
        if voice_id not in self._warned:
            self._warned.add(voice_id)
            logger.warning(
                "TTS voice_id %r is not in %s's tts.voice_map; falling back to the profile's "
                "tts.default_voice %r (add the mapping to the active model profile to silence "
                "this)",
                voice_id,
                self._provider_name,
                self._default,
            )
        return self._default


def _config_path_for(onnx_path: Path) -> Path:
    """Piper's convention: `<voice>.onnx` ships beside `<voice>.onnx.json`."""
    return onnx_path.with_suffix(onnx_path.suffix + ".json")


def _chunk_pcm(pcm: bytes, sample_rate: int, text: str, max_chunk_ms: int) -> list[TtsChunk]:
    """Identical shape to `app.inference.tts.qwen3_tts._chunk_pcm` (proportional-by-byte
    offsets, `alignment_is_exact=False` — Piper gives no per-word timing either). Duplicated
    rather than shared: two ~20-line pure functions in sibling files, not worth a new shared
    module for (see this task's report)."""
    if not pcm or not text:
        return []
    bytes_per_ms = max(1, (sample_rate * _BYTES_PER_SAMPLE) // _MS_PER_S)
    chunk_bytes = max(_BYTES_PER_SAMPLE, max_chunk_ms * bytes_per_ms)
    chunk_bytes -= chunk_bytes % _BYTES_PER_SAMPLE
    total_bytes = len(pcm)
    text_len = len(text)
    chunks: list[TtsChunk] = []
    offset = 0
    index = 0
    while offset < total_bytes:
        piece = pcm[offset : offset + chunk_bytes]
        samples = len(piece) // _BYTES_PER_SAMPLE
        audio_ms = (samples * _MS_PER_S) // sample_rate
        start_frac = offset / total_bytes
        end_frac = min(1.0, (offset + len(piece)) / total_bytes)
        chunks.append(
            TtsChunk(
                frame=AudioFrame(
                    pcm=piece,
                    sample_rate=sample_rate,
                    num_channels=1,
                    samples_per_channel=samples,
                    capture_offset_ms=0,
                ),
                text_offset_start=int(start_frac * text_len),
                text_offset_end=int(end_frac * text_len),
                alignment_is_exact=False,
                chunk_index=index,
                audio_ms=audio_ms,
            )
        )
        offset += len(piece)
        index += 1
    if chunks:
        last = chunks[-1]
        chunks[-1] = TtsChunk(
            frame=last.frame,
            text_offset_start=last.text_offset_start,
            text_offset_end=text_len,
            alignment_is_exact=False,
            chunk_index=last.chunk_index,
            audio_ms=last.audio_ms,
        )
    return chunks


def _drain_step(generator: Any) -> object:
    """One `next()` on Piper's sync generator, run on a worker thread. Returns `_STOP` at the
    end instead of letting `StopIteration` cross the thread boundary (it does not pickle/carry
    cleanly through `asyncio.to_thread`)."""
    try:
        return next(generator)
    except StopIteration:
        return _STOP


@dataclass
class _PiperTtsStream:
    _provider: PiperTTS
    _text: str
    _voice: TtsVoiceSpec
    _request_id: str
    _max_chunk_ms: int
    _cancelled: bool = field(default=False, init=False)

    @property
    def request_id(self) -> str:
        return self._request_id

    @property
    def text(self) -> str:
        return self._text

    def __aiter__(self) -> AsyncIterator[TtsChunk]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[TtsChunk]:
        if self._cancelled:
            return
        pieces = await self._provider._drain_sentence(self._text, self)
        if self._cancelled or not pieces:
            return
        pcm = b"".join(pieces)
        for chunk in _chunk_pcm(
            pcm, self._provider.output_sample_rate, self._text, self._max_chunk_ms
        ):
            if self._cancelled:
                return
            yield chunk

    async def cancel(self) -> None:
        """Idempotent. Checked between `next()` calls on Piper's generator (see module
        docstring): stops the drain, discards whatever was already produced, yields nothing."""
        self._cancelled = True


class PiperTTS:
    """`TTSProvider` over the local `piper-tts` package — CPU, the configured fallback (D9)."""

    provider_name = "piper"

    def __init__(
        self,
        *,
        voice_path: str,
        voice_map: Mapping[str, str] | None = None,
        default_voice: str | None = None,
    ) -> None:
        self._voice_path = Path(voice_path)
        self._voice: Any = None
        self._sample_rate: int | None = None
        self._lock = asyncio.Lock()
        # E20-G: `voice_map`/`default_voice` come from the active model profile's `tts.voice_map` /
        # `tts.default_voice`. Piper's own natural default is the stem of the voice file it loads
        # (`ru_RU-irina-medium`), which is what `tts.default_voice` is expected to name anyway.
        self._voices = _VoiceResolver(
            provider_name=self.provider_name,
            voice_map=voice_map,
            default=default_voice or self._voice_path.stem,
        )

    @property
    def model_version(self) -> str:
        return self._voice_path.stem  # e.g. "ru_RU-irina-medium"

    @property
    def output_sample_rate(self) -> int:
        if self._sample_rate is None:
            raise RuntimeError("PiperTTS.warm_up() must be called before output_sample_rate")
        return self._sample_rate

    async def warm_up(self) -> None:
        if self._voice is not None:
            return
        async with self._lock:
            if self._voice is not None:
                return
            onnx_path = self._voice_path
            json_path = _config_path_for(onnx_path)
            onnx_exists = await asyncio.to_thread(onnx_path.is_file)
            json_exists = await asyncio.to_thread(json_path.is_file)
            if not onnx_exists or not json_exists:
                raise ModelNotAvailableError(
                    f"Piper voice not found: {onnx_path} (+ {json_path.name}) — "
                    "run `make models-piper`, see models/README.md"
                )
            from piper import PiperVoice

            voice = await asyncio.to_thread(PiperVoice.load, str(onnx_path), str(json_path))
            self._voice = voice
            self._sample_rate = int(voice.config.sample_rate)

    def stream(
        self,
        text: str,
        voice: TtsVoiceSpec,
        *,
        request_id: str,
        max_chunk_ms: int = 20,
    ) -> _PiperTtsStream:
        # E20-G: resolve for the WARN/record side-effect; the loaded `.onnx` is what actually
        # speaks (see `_VoiceResolver`'s docstring). An unknown logical id never raises.
        self.native_voice_id(voice.voice_id)
        return _PiperTtsStream(self, text, voice, request_id, max_chunk_ms)

    def native_voice_id(self, voice_id: str) -> str:
        """The native Piper voice this adapter reports for `voice_id` (E20-G).

        Public because `CALLER_TTS_STARTED` records both the logical `voice_id` and the
        `voice_id_native` that was really used (HLD 10 §10.13). Idempotent.
        """
        return self._voices.resolve(voice_id)

    async def close(self) -> None:
        self._voice = None
        self._sample_rate = None

    # -- internals (called by `_PiperTtsStream`) -----------------------------------------------

    async def _drain_sentence(self, text: str, stream_obj: _PiperTtsStream) -> list[bytes]:
        if self._voice is None:
            raise RuntimeError("PiperTTS.warm_up() must be called before stream()")
        try:
            generator = await asyncio.to_thread(self._voice.synthesize, text)
        except Exception as exc:  # piper's own synthesis-setup failure
            raise TtsUnavailableError(f"piper synthesize failed: {exc}") from exc

        pieces: list[bytes] = []
        while True:
            if stream_obj._cancelled:
                return []
            try:
                chunk = await asyncio.to_thread(_drain_step, generator)
            except Exception as exc:
                if stream_obj._cancelled:
                    return []
                raise TtsUnavailableError(f"piper synthesis failed: {exc}") from exc
            if chunk is _STOP:
                break
            if stream_obj._cancelled:
                return []
            # `AudioChunk.audio_int16_bytes` — s16le PCM (piper >= 1.x's real `synthesize()` shape,
            # see module docstring's "E14 close-out fix").
            pieces.append(chunk.audio_int16_bytes)
        return pieces

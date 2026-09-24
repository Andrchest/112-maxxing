"""The service heads' pre-synthesised lines (HLD `80-telephony.md` §80.4.3; I3 E6c).

Qwen3-TTS is whole-utterance: its first audio arrives only once a whole unit is synthesised
(measured p50 ≈ 4 s on the dev card, `DEV_3060TI.yaml`). The lines that matter most on a ДДС call
are fixed — a persona's greeting, «Повторите вопрос.», «Пока в пути, доложу позже.», the memo's
words for a status — so the agent synthesises them once per persona voice and keeps them:

* `TtsLineCache.warm` renders every line of `ResponderTemplates.static_lines` for one voice and
  stores it in memory and on disk as `tts_cache/{voice_id}/{sha256(text)[:16]}.wav` under
  `Settings.data_dir` — a restart reads the files back instead of synthesising again;
* `CachedTTSProvider` wraps the process's `TTSProvider`: a unit whose (voice, text) is cached is
  played from the cache at once; anything else — a dynamic line with an order number — goes to
  the wrapped provider's streaming synthesis exactly as before. `ChunkedTtsStream` asks for one
  sentence unit at a time, so a cached sentence inside a longer reply is still a hit.

Nothing here decides what is said, and a cache that cannot be written (a read-only data dir) or a
line that fails to synthesise is only a miss: the provider answers instead.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import wave
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

from app.application.ports.call_transport import AudioFrame
from app.application.ports.tts import TtsChunk, TTSProvider, TtsStream, TtsVoiceSpec

__all__ = ["CACHE_DIR_NAME", "CachedTTSProvider", "TtsLineCache", "line_key"]

logger = logging.getLogger(__name__)

CACHE_DIR_NAME = "tts_cache"
_BYTES_PER_SAMPLE = 2
_MS_PER_S = 1000


def line_key(text: str) -> str:
    """The file stem of one line: the first 16 hex digits of sha256 of the stripped text."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


class TtsLineCache:
    """`(voice_id, text) → PCM` for the fixed lines (see the module docstring)."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory
        self._pcm: dict[tuple[str, str], tuple[bytes, int]] = {}

    def __len__(self) -> int:
        return len(self._pcm)

    def get(self, voice_id: str, text: str) -> tuple[bytes, int] | None:
        """`(pcm, sample_rate)` of a cached line, or `None`."""
        return self._pcm.get((voice_id, text.strip()))

    def put(self, voice_id: str, text: str, pcm: bytes, sample_rate: int) -> None:
        self._pcm[(voice_id, text.strip())] = (pcm, sample_rate)

    def path_for(self, voice_id: str, text: str) -> Path | None:
        if self._directory is None:
            return None
        return self._directory / voice_id / f"{line_key(text)}.wav"

    async def warm(self, provider: TTSProvider, voice: TtsVoiceSpec, lines: Iterable[str]) -> int:
        """Cache every line for `voice`; returns how many lines are now cached for it."""
        cached = 0
        for line in dict.fromkeys(item.strip() for item in lines if item.strip()):
            if self.get(voice.voice_id, line) is not None:
                cached += 1
                continue
            if self._read(voice.voice_id, line):
                cached += 1
                continue
            try:
                pcm, rate = await _synthesise(provider, voice, line)
            except Exception:
                logger.warning("pre-synthesis of %r for %s failed; it stays a miss", line, voice)
                continue
            if not pcm:
                continue
            self.put(voice.voice_id, line, pcm, rate)
            self._write(voice.voice_id, line, pcm, rate)
            cached += 1
        return cached

    def _read(self, voice_id: str, text: str) -> bool:
        path = self.path_for(voice_id, text)
        if path is None or not path.is_file():
            return False
        try:
            with wave.open(str(path), "rb") as source:
                pcm = source.readframes(source.getnframes())
                rate = source.getframerate()
        except (OSError, wave.Error, EOFError):
            return False
        self.put(voice_id, text, pcm, rate)
        return True

    def _write(self, voice_id: str, text: str, pcm: bytes, rate: int) -> None:
        path = self.path_for(voice_id, text)
        if path is None:
            return
        with contextlib.suppress(OSError):
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as sink:
                sink.setnchannels(1)
                sink.setsampwidth(_BYTES_PER_SAMPLE)
                sink.setframerate(rate)
                sink.writeframes(pcm)


async def _synthesise(provider: TTSProvider, voice: TtsVoiceSpec, text: str) -> tuple[bytes, int]:
    pcm = bytearray()
    rate = provider.output_sample_rate
    async for chunk in provider.stream(text, voice, request_id=f"tts-cache:{line_key(text)}"):
        pcm.extend(chunk.frame.pcm)
        rate = chunk.frame.sample_rate
    return bytes(pcm), rate


class _CachedStream:
    """A `TtsStream` over cached PCM, sliced into `max_chunk_ms` frames."""

    def __init__(
        self, text: str, pcm: bytes, sample_rate: int, *, request_id: str, max_chunk_ms: int
    ) -> None:
        self._text = text
        self._pcm = pcm
        self._rate = sample_rate
        self._request_id = request_id
        self._max_chunk_ms = max(1, max_chunk_ms)
        self._cancelled = False

    @property
    def request_id(self) -> str:
        return self._request_id

    @property
    def text(self) -> str:
        return self._text

    async def cancel(self) -> None:
        self._cancelled = True

    def __aiter__(self) -> AsyncIterator[TtsChunk]:
        return self._chunks()

    async def _chunks(self) -> AsyncIterator[TtsChunk]:
        samples_per_chunk = max(1, self._rate * self._max_chunk_ms // _MS_PER_S)
        step = samples_per_chunk * _BYTES_PER_SAMPLE
        total = len(self._pcm)
        length = len(self._text)
        for index, start in enumerate(range(0, total, step)):
            if self._cancelled:
                return
            block = self._pcm[start : start + step]
            samples = len(block) // _BYTES_PER_SAMPLE
            yield TtsChunk(
                frame=AudioFrame(
                    pcm=block,
                    sample_rate=self._rate,
                    num_channels=1,
                    samples_per_channel=samples,
                    capture_offset_ms=0,
                ),
                text_offset_start=length * start // total,
                text_offset_end=length * min(total, start + step) // total,
                alignment_is_exact=False,
                chunk_index=index,
                audio_ms=samples * _MS_PER_S // self._rate,
            )


class CachedTTSProvider:
    """A `TTSProvider` that plays a cached line at once and streams everything else."""

    def __init__(self, inner: TTSProvider, cache: TtsLineCache) -> None:
        self._inner = inner
        self._cache = cache

    @property
    def inner(self) -> TTSProvider:
        return self._inner

    @property
    def cache(self) -> TtsLineCache:
        return self._cache

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    @property
    def model_version(self) -> str:
        return self._inner.model_version

    @property
    def output_sample_rate(self) -> int:
        return self._inner.output_sample_rate

    async def warm_up(self) -> None:
        await self._inner.warm_up()

    def native_voice_id(self, voice_id: str) -> str | None:
        resolve = getattr(self._inner, "native_voice_id", None)
        return resolve(voice_id) if callable(resolve) else None

    def stream(
        self,
        text: str,
        voice: TtsVoiceSpec,
        *,
        request_id: str,
        max_chunk_ms: int = 20,
    ) -> TtsStream:
        hit = self._cache.get(voice.voice_id, text)
        if hit is None:
            return self._inner.stream(text, voice, request_id=request_id, max_chunk_ms=max_chunk_ms)
        pcm, rate = hit
        return _CachedStream(text, pcm, rate, request_id=request_id, max_chunk_ms=max_chunk_ms)

    async def close(self) -> None:
        await self._inner.close()

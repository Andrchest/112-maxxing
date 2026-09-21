"""`FakeTTS` — the gate's `TTSProvider` (HLD `50-voice-pipeline.md` §2.4, D13, SPEC §18).

§2.4 names it literally: "deterministic silence of a length proportional to the text; exact
alignment". Everything here follows from that one sentence plus what a barge-in test needs:

* **Deterministic length.** `audio_ms = ms_per_char * len(text)`, rounded up to a whole
  `max_chunk_ms` frame. `ms_per_char` defaults to 60 ms — the brief's documented function — so a
  30-character reply is 1 800 ms of audio and a test can compute the expected cutoff by hand
  instead of discovering it.
* **Deterministic samples.** Silence by default (`tone_hz = 0.0`); a fixed sine when a test wants
  audio a `SessionRecorder` assertion can tell from padding. Both are a pure function of
  `(text, voice, max_chunk_ms)` — the same request always produces byte-identical frames.
* **Exact alignment.** `text_offset_start` / `text_offset_end` are the character interval this
  chunk's audio covers, derived from the same `ms_per_char` the duration came from, and
  `alignment_is_exact` is `True`. The last chunk always ends at `len(text)` so that
  `planned_text[: last.text_offset_end]` is the whole text and never a truncation artefact.
* **Scriptable slowness and failure.** `chunk_delay_ms` sleeps before each chunk (that is how a
  `tts_first_chunk_timeout_ms` test is written without a real model), `fail_on_warm_up` raises
  from `warm_up()`, and `fail_on_chunk` raises `TtsUnavailableError` instead of yielding the Nth
  chunk — the two halves of INV 14's TTS variant.
* **Prompt cancellation.** `cancel()` sets a flag the generator checks before every yield, so a
  cancelled stream stops within one chunk and never emits audio after the cancel (§6.1 step 2).

It is a *test double* and nothing outside a fake wiring may construct it; `SIM_TTS_PROVIDER=fake`
is what selects it (D13).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator

from app.application.ports.call_transport import AudioFrame
from app.application.ports.tts import (
    TtsChunk,
    TtsUnavailableError,
    TtsVoiceSpec,
)

__all__ = ["FakeTTS", "FakeTtsStream"]

_BYTES_PER_SAMPLE = 2
_MS_PER_S = 1000
_INT16_MAX = 32767

#: The documented deterministic length function: 60 ms of audio per character of the request text.
DEFAULT_MS_PER_CHAR = 60.0
#: What `TTSProvider.output_sample_rate` answers; the transport's rate, so no resample is needed.
DEFAULT_OUTPUT_SAMPLE_RATE = 16_000
#: Peak amplitude of the optional tone: audible in a WAV, never clipping.
TONE_AMPLITUDE = 0.3


class FakeTtsStream:
    """One `TtsStream` over deterministic PCM (§2.4)."""

    def __init__(
        self,
        provider: FakeTTS,
        text: str,
        voice: TtsVoiceSpec,
        *,
        request_id: str,
        max_chunk_ms: int,
    ) -> None:
        self._provider = provider
        self._text = text
        self._voice = voice
        self._request_id = request_id
        self._max_chunk_ms = max(1, max_chunk_ms)
        self._cancelled = False
        #: Every chunk actually yielded, in yield order — what a test asserts alignment on.
        self.yielded: list[TtsChunk] = []

    @property
    def request_id(self) -> str:
        """The id the caller gave this synthesis request."""
        return self._request_id

    @property
    def text(self) -> str:
        """The exact text handed to the provider — persisted per SPEC §25."""
        return self._text

    @property
    def cancelled(self) -> bool:
        """True once `cancel()` has been awaited."""
        return self._cancelled

    async def cancel(self) -> None:
        """Stop generation as soon as the current chunk completes. Idempotent."""
        self._cancelled = True

    def __aiter__(self) -> AsyncIterator[TtsChunk]:
        """Yield `max_chunk_ms` frames until the text is covered or `cancel()` is called."""
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[TtsChunk]:
        provider = self._provider
        total_ms = provider.audio_ms_for(self._text, max_chunk_ms=self._max_chunk_ms)
        if total_ms <= 0:
            return
        chunk_index = 0
        elapsed_ms = 0
        while elapsed_ms < total_ms:
            if self._cancelled:
                return
            if provider.chunk_delay_ms > 0:
                await asyncio.sleep(provider.chunk_delay_ms / _MS_PER_S)
            else:
                # Always yield to the loop, so a cancel issued from another task lands between
                # chunks rather than after the whole utterance.
                await asyncio.sleep(0)
            if self._cancelled:
                return
            if provider.fail_on_chunk is not None and chunk_index == provider.fail_on_chunk:
                raise TtsUnavailableError(
                    f"FakeTTS was scripted to fail at chunk {chunk_index} of request "
                    f"{self._request_id!r}"
                )
            chunk_ms = min(self._max_chunk_ms, total_ms - elapsed_ms)
            last = elapsed_ms + chunk_ms >= total_ms
            chunk = TtsChunk(
                frame=AudioFrame(
                    pcm=provider.pcm_for(elapsed_ms, chunk_ms),
                    sample_rate=provider.output_sample_rate,
                    num_channels=1,
                    samples_per_channel=(provider.output_sample_rate * chunk_ms) // _MS_PER_S,
                    capture_offset_ms=elapsed_ms,
                ),
                text_offset_start=provider.text_offset_for(self._text, elapsed_ms),
                text_offset_end=(
                    len(self._text)
                    if last
                    else provider.text_offset_for(self._text, elapsed_ms + chunk_ms)
                ),
                alignment_is_exact=True,
                chunk_index=chunk_index,
                audio_ms=chunk_ms,
            )
            self.yielded.append(chunk)
            yield chunk
            chunk_index += 1
            elapsed_ms += chunk_ms


class FakeTTS:
    """A `TTSProvider` with no model, no GPU and no network (D13, §2.4)."""

    def __init__(
        self,
        *,
        provider_name: str = "fake",
        model_version: str = "fake-tts-1",
        output_sample_rate: int = DEFAULT_OUTPUT_SAMPLE_RATE,
        ms_per_char: float = DEFAULT_MS_PER_CHAR,
        chunk_delay_ms: int = 0,
        tone_hz: float = 0.0,
        fail_on_warm_up: BaseException | None = None,
        fail_on_chunk: int | None = None,
    ) -> None:
        if output_sample_rate <= 0:
            raise ValueError("output_sample_rate must be positive")
        if ms_per_char <= 0:
            raise ValueError("ms_per_char must be positive")
        self._provider_name = provider_name
        self._model_version = model_version
        self._output_sample_rate = output_sample_rate
        self._ms_per_char = ms_per_char
        #: Sleep before each chunk — how a timeout test is written with no real model.
        self.chunk_delay_ms = chunk_delay_ms
        #: 0.0 = silence; a positive frequency synthesises a fixed sine instead.
        self.tone_hz = tone_hz
        #: Raised from `warm_up()` when set (§4.2's warm-up failure path).
        self.fail_on_warm_up = fail_on_warm_up
        #: Raise `TtsUnavailableError` instead of yielding this chunk index (INV 14).
        self.fail_on_chunk = fail_on_chunk
        #: Every `(text, voice, request_id)` handed to `stream()`, in call order.
        self.requests: list[tuple[str, TtsVoiceSpec, str]] = []
        #: Every stream handed out, in creation order.
        self.streams: list[FakeTtsStream] = []
        #: How many times `warm_up()` completed.
        self.warm_ups = 0
        self.closed = False

    # -- the TTSProvider port -----------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        """`inference_metrics.provider` for this adapter."""
        return self._provider_name

    @property
    def model_version(self) -> str:
        """`inference_metrics.model_version` for this adapter."""
        return self._model_version

    @property
    def output_sample_rate(self) -> int:
        """The rate every emitted frame carries (16 kHz: the transport's, so no resample)."""
        return self._output_sample_rate

    async def warm_up(self) -> None:
        """Nothing to load; raises `fail_on_warm_up` when a test scripted one."""
        if self.fail_on_warm_up is not None:
            raise self.fail_on_warm_up
        self.warm_ups += 1

    def stream(
        self,
        text: str,
        voice: TtsVoiceSpec,
        *,
        request_id: str,
        max_chunk_ms: int = 20,
    ) -> FakeTtsStream:
        """Begin streaming synthesis (§2.4). Returns immediately; nothing is generated yet."""
        self.requests.append((text, voice, request_id))
        stream = FakeTtsStream(self, text, voice, request_id=request_id, max_chunk_ms=max_chunk_ms)
        self.streams.append(stream)
        return stream

    async def close(self) -> None:
        """Release nothing. Idempotent."""
        self.closed = True

    # -- the deterministic functions ----------------------------------------------------------

    @property
    def ms_per_char(self) -> float:
        """Milliseconds of audio one character of the request text is worth."""
        return self._ms_per_char

    def audio_ms_for(self, text: str, *, max_chunk_ms: int) -> int:
        """`ms_per_char * len(text)`, rounded **up** to a whole `max_chunk_ms` frame.

        Rounding up rather than truncating is what keeps the last chunk a whole frame: a
        transport that expects `samples_per_channel * num_channels * 2 == len(pcm)` must not be
        handed a ragged final frame, and a barge-in test's arithmetic stays in whole frames.
        """
        raw_ms = self._ms_per_char * len(text)
        if raw_ms <= 0:
            return 0
        frames = math.ceil(raw_ms / max(1, max_chunk_ms))
        return frames * max(1, max_chunk_ms)

    def text_offset_for(self, text: str, at_ms: int) -> int:
        """The character offset `at_ms` of audio into `text` corresponds to (exact alignment)."""
        if not text:
            return 0
        return max(0, min(len(text), int(at_ms / self._ms_per_char)))

    def pcm_for(self, start_ms: int, duration_ms: int) -> bytes:
        """`duration_ms` of mono s16le audio starting `start_ms` into the utterance.

        A pure function of the two offsets and `tone_hz`, so the same request always produces the
        same bytes and a recording assertion is reproducible.
        """
        samples = (self._output_sample_rate * duration_ms) // _MS_PER_S
        if self.tone_hz <= 0.0:
            return b"\x00" * (samples * _BYTES_PER_SAMPLE)
        first = (self._output_sample_rate * start_ms) // _MS_PER_S
        pcm = bytearray(samples * _BYTES_PER_SAMPLE)
        for index in range(samples):
            phase = 2.0 * math.pi * self.tone_hz * (first + index) / self._output_sample_rate
            scaled = int(math.sin(phase) * TONE_AMPLITUDE * _INT16_MAX)
            pcm[index * _BYTES_PER_SAMPLE : (index + 1) * _BYTES_PER_SAMPLE] = scaled.to_bytes(
                _BYTES_PER_SAMPLE, "little", signed=True
            )
        return bytes(pcm)

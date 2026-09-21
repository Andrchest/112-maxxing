"""`FakeASR` — the scripted `ASRProvider` every gate test runs against (D1, D13, SPEC §19).

It is a *script reader*, not a model: the caller hands it the sequence of outcomes the test needs
and it returns them in order, one per `transcribe()` / `stream()` call. A `str` entry becomes the
final text; an `Exception` **instance** is raised from the call, which is how the INV 14 tests
(SPEC §42 item 14) produce an ASR failure without owning a model that can fail.

Three properties the tests depend on and that are therefore rules of this class:

* **No randomness and no clock.** The partials for a given text are always the same list, the
  confidence is always `_CONFIDENCE`, and nothing here reads the wall clock — timing is the
  caller's `Clock`, so a test can assert on a latency it set itself.
* **Every call is recorded.** `calls` holds one `FakeAsrCall` per invocation with the audio byte
  length and the `request_id`, so "the pseudo-streamed partials used request ids `…:p0`, `…:p1`"
  is assertable without instrumenting the pipeline.
* **An exhausted script is not an error.** Past the end of the script the provider returns the
  empty transcript, which is the "the trainee said nothing recognisable" case the responder must
  handle anyway (§4.5: an empty final still produces `ASR_FINAL`, never a dialogue turn).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from app.application.ports.asr import AsrPartial, AsrResult
from app.application.ports.call_transport import AudioFrame

__all__ = ["FakeASR", "FakeAsrCall"]

#: `FakeASR` speaks Russian like every other provider in this project (SPEC §1).
_LANGUAGE = "ru"
#: The confidence a scripted final carries. Fixed, because a fake that varied it would invite a
#: test to assert on a number nobody chose.
_CONFIDENCE = 0.9
_PROVIDER_NAME = "fake"
_MODEL_VERSION = "fake-1"
_SAMPLE_RATE = 16_000
_BYTES_PER_SAMPLE = 2
_MS_PER_S = 1000


@dataclass(frozen=True, slots=True)
class FakeAsrCall:
    """One recorded invocation — what a test asserts the pipeline actually asked for."""

    kind: str
    """`"transcribe"` or `"stream"`."""

    audio_bytes: int
    sample_rate: int
    request_id: str


@dataclass(frozen=True, slots=True)
class _Scripted:
    """One script entry resolved into what the provider must do."""

    text: str | None
    error: BaseException | None


class FakeASR:
    """A deterministic `ASRProvider` driven by a script (D13).

    `script` entries are consumed in order across `transcribe()` and `stream()` alike — the two
    share one cursor, because a test that mixes them is describing one call's worth of audio.
    """

    def __init__(self, script: Sequence[str | Exception] = (), *, partials: bool = True) -> None:
        self._script: tuple[_Scripted, ...] = tuple(
            _Scripted(text=None, error=entry)
            if isinstance(entry, BaseException)
            else _Scripted(text=entry, error=None)
            for entry in script
        )
        self._partials_enabled = partials
        self._cursor = 0
        #: Every call, in call order.
        self.calls: list[FakeAsrCall] = []
        #: Incremented by `warm_up()`; `close()` sets `closed`.
        self.warm_ups = 0
        self.closed = False

    # -- port properties ----------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        """`"fake"` — what `ASR_FINAL.asr_provider` and the metric row carry."""
        return _PROVIDER_NAME

    @property
    def model_version(self) -> str:
        """`"fake-1"`."""
        return _MODEL_VERSION

    @property
    def supports_streaming(self) -> bool:
        """True: the fake is the one provider §4.5's native-stream branch can be tested against."""
        return True

    @property
    def required_sample_rate(self) -> int:
        """16 kHz, like every real provider, so a test cannot accidentally skip the resampler."""
        return _SAMPLE_RATE

    @property
    def remaining(self) -> int:
        """Script entries not yet consumed."""
        return max(0, len(self._script) - self._cursor)

    # -- the port -----------------------------------------------------------------------------

    async def warm_up(self) -> None:
        """Count the warm-up; consume no script entry."""
        self.warm_ups += 1

    async def close(self) -> None:
        """Mark the provider closed. Idempotent."""
        self.closed = True

    async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> AsrResult:
        """Return the next scripted final, or raise the next scripted exception."""
        self.calls.append(
            FakeAsrCall(
                kind="transcribe",
                audio_bytes=len(audio),
                sample_rate=sample_rate,
                request_id=request_id,
            )
        )
        entry = self._next()
        if entry.error is not None:
            raise entry.error
        return self._final(entry.text or "", len(audio), sample_rate)

    def stream(
        self, frames: AsyncIterator[AudioFrame], *, request_id: str
    ) -> AsyncIterator[AsrResult | AsrPartial]:
        """Zero or more `AsrPartial`, then exactly one final `AsrResult` (§2.3)."""
        return self._stream(frames, request_id=request_id)

    async def _stream(
        self, frames: AsyncIterator[AudioFrame], *, request_id: str
    ) -> AsyncIterator[AsrResult | AsrPartial]:
        # The script entry is chosen when the stream opens, not when it closes: a real streaming
        # recogniser commits words as the audio arrives, so the partials must be yielded *during*
        # the iteration. A fake that produced them all after the last frame would let a caller
        # that cancels at `USER_SPEECH_ENDED` — which §4.5 requires — see none of them.
        entry = self._next()
        if entry.error is not None:
            raise entry.error
        text = entry.text or ""
        prefixes = partial_prefixes(text) if self._partials_enabled else []
        cursor = 0
        audio_bytes = 0
        sample_rate = _SAMPLE_RATE
        async for frame in frames:
            audio_bytes += len(frame.pcm)
            sample_rate = frame.sample_rate
            if cursor < len(prefixes):
                yield AsrPartial(
                    text=prefixes[cursor],
                    start_ms=0,
                    end_ms=self._duration_ms(audio_bytes, sample_rate),
                    stability=None,
                )
                cursor += 1
        self.calls.append(
            FakeAsrCall(
                kind="stream",
                audio_bytes=audio_bytes,
                sample_rate=sample_rate,
                request_id=request_id,
            )
        )
        yield self._final(text, audio_bytes, sample_rate)

    # -- internals ----------------------------------------------------------------------------

    def _next(self) -> _Scripted:
        if self._cursor >= len(self._script):
            return _Scripted(text="", error=None)
        entry = self._script[self._cursor]
        self._cursor += 1
        return entry

    def _final(self, text: str, audio_bytes: int, sample_rate: int) -> AsrResult:
        duration_ms = self._duration_ms(audio_bytes, sample_rate)
        return AsrResult(
            text=text,
            is_final=True,
            start_ms=0,
            end_ms=duration_ms,
            confidence=_CONFIDENCE,
            words=[],
            provider=_PROVIDER_NAME,
            model_version=_MODEL_VERSION,
            audio_duration_ms=duration_ms,
            language=_LANGUAGE,
        )

    @staticmethod
    def _duration_ms(audio_bytes: int, sample_rate: int) -> int:
        if sample_rate <= 0:  # pragma: no cover - guarded by the port's contract
            return 0
        return (audio_bytes * _MS_PER_S) // (sample_rate * _BYTES_PER_SAMPLE)


def partial_prefixes(text: str) -> list[str]:
    """The deterministic partial hypotheses for `text`: its word prefixes, final excluded.

    Word boundaries rather than characters, because a partial is what a streaming recogniser
    would have committed so far and no recogniser commits half a word. A single-word (or empty)
    text yields no partial at all — there is nothing to be partial about.
    """
    words = text.split()
    return [" ".join(words[: index + 1]) for index in range(len(words) - 1)]

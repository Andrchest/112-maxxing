"""Sentence-chunked synthesis (HLD `50-voice-pipeline.md` §2.4, §8 lever 1; SPEC §18; D9).

SPEC §18 forbids an utterance that cannot be interrupted, and §2.4 requires the first chunk of
audio without waiting for full synthesis. Not every provider can do that: the GPU default
(`Qwen3TTS`) generates a **whole utterance** per call and offers no way to abort one, and §2.4
answers that case literally — "adapters that can only synthesise sentence-at-a-time still satisfy
the port by slicing each synthesised sentence into `max_chunk_ms` frames as they are produced".

This module is the half of that answer which does **not** belong to any one adapter:

* `split_for_tts` — a pure, deterministic splitter from one text into the units a provider is
  asked to synthesise one at a time. It is a property of the *text*, not of the model, so it
  lives in `app.application.voice` and the same units are produced whichever provider is
  configured (that is also what makes the chunking testable with no model at all).
* `ChunkedTtsStream` — a `TtsStream` that pulls unit by unit from the wrapped provider, re-bases
  each chunk's text offsets onto the whole text, and gives `cancel()` the granularity §6.1 needs:
  generation stops after the unit in flight, that unit's remaining audio is **discarded and never
  played**, and no further request is issued.

Splitting rules (the brief's, which are §2.4's "sentence granularity" made concrete):

1. Split after a sentence ender — `.`, `!`, `?`, `…` — only when it is followed by whitespace or
   the end of the text. `3.14`, `д.5` and `т.е.` therefore never split.
2. Never split after a `.` whose preceding token is a known abbreviation (`д.`, `кв.`, `ул.`,
   `т.е.`, …), a bare number (`27.`), or a single letter (an initial).
3. A unit longer than `max_unit_chars` is subdivided at commas, semicolons, colons and spaced
   dashes — never inside a word, a number or an abbreviation. A unit with no such separator is
   left long: a correct long unit beats a mangled short one.
4. **The units concatenate back to the original text exactly.** Every character, including the
   whitespace between sentences, belongs to exactly one unit, and `TextUnit.start` / `.end` are
   offsets into the original text. `delivered_text` (§6.3) is a prefix of that original text, so
   an offset that drifted by one space would be a wrong transcript row.

I8 V1 (the owner's Qwen3-TTS recipe, provider-agnostic here):

* **Pauses between units.** `inter_unit_pause_ms` (`tts.inter_unit_pause_ms`, 200 on the voice
  profile) of silence is yielded *between* two units — never before the first, never after the
  last, never after a cancel. The silence chunks cover no text (`text_offset_start ==
  text_offset_end == the finished unit's end`, exact), so `delivered_text` is unchanged by them.
* **Per-unit seeds.** With a `seed_scope = (session_id, turn_index)` (the sink passes it when
  `tts.seed_mode` is `derived`), every unit's `TtsVoiceSpec.seed` is `derive_tts_seed(session_id,
  turn_index, unit_index)` — a stable hash, so a replay of the same turn asks for the same audio.
* **What the provider reported.** A provider stream that exposes `synthesis_attributes` (duck-typed,
  like the sink's `native_voice_id`; `Qwen3TTS` does) is read once per unit, at its first chunk,
  into `unit_attributes` — the sink records the first unit's on `CALLER_TTS_STARTED`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, replace

from app.application.ports.call_transport import AudioFrame
from app.application.ports.tts import TtsChunk, TTSProvider, TtsStream, TtsVoiceSpec

__all__ = [
    "ABBREVIATIONS_RU",
    "DEFAULT_MAX_UNIT_CHARS",
    "ChunkedTtsStream",
    "TextUnit",
    "derive_tts_seed",
    "split_for_tts",
]

#: A derived seed is 31 bits wide (`& 0x7fffffff`), so `seed + 1` (the worker's one retry) and
#: every consumer that stores it as a signed 32-bit integer stay in range.
_SEED_MASK = 0x7FFFFFFF
_BYTES_PER_SAMPLE = 2
_MS_PER_S = 1000


def derive_tts_seed(session_id: str, turn_index: int, unit_index: int) -> int:
    """`stable_hash(session_id, turn_index, unit_index) & 0x7fffffff` (I8 V1, `seed_mode: derived`).

    SHA-256 of the three values, not Python's `hash()` — that one is salted per process, and the
    whole point is that a replay of the same turn, in any process, asks for the same seed.
    """
    digest = hashlib.sha256(f"{session_id}:{turn_index}:{unit_index}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & _SEED_MASK


#: `tts_max_unit_chars`'s default — the brief's 120 characters. Long enough that an ordinary
#: Russian sentence is one unit (so alignment stays sentence-exact), short enough that a run-on
#: sentence cannot hold the first chunk of audio hostage for a whole `generate()` call.
DEFAULT_MAX_UNIT_CHARS = 120

_SENTENCE_ENDERS = ".!?…"

#: Russian abbreviations whose trailing dot is not a sentence end. The set is deliberately small
#: and literal — every member is a word that appears in an address or a clarification, which is
#: exactly what a 112 caller says. It is matched case-insensitively against the token in front of
#: the dot, dot included.
ABBREVIATIONS_RU: frozenset[str] = frozenset(
    {
        "д.",
        "дом.",
        "кв.",
        "ул.",
        "пр.",
        "пер.",
        "просп.",
        "стр.",
        "корп.",
        "к.",
        "п.",
        "г.",
        "обл.",
        "р-н.",
        "т.е.",
        "т.к.",
        "т.д.",
        "т.п.",
        "им.",
        "св.",
        "тел.",
        "мин.",
        "сек.",
        "ч.",
        "эт.",
        "подъезд.",
    }
)

#: A comma/semicolon/colon that a subdivision may cut after, or a spaced dash. Both forms require
#: the separator to be followed by whitespace, so a decimal comma («0,5») is never a cut point.
_CLAUSE_SEPARATOR = re.compile(r"[,;:](?=\s)|(?<=\s)[—–-](?=\s)")

#: The last run of non-space characters before a position — the token a rule 2 check looks at.
_LAST_TOKEN = re.compile(r"\S*$")


@dataclass(frozen=True, slots=True)
class TextUnit:
    """One synthesis unit, with its offsets into the **original** text."""

    text: str
    start: int
    end: int


def split_for_tts(
    text: str, *, max_unit_chars: int = DEFAULT_MAX_UNIT_CHARS
) -> tuple[TextUnit, ...]:
    """Split `text` into the units a `TTSProvider` is asked to synthesise one at a time.

    Pure and deterministic. The empty string yields no unit; anything else yields at least one,
    and `"".join(unit.text for unit in split_for_tts(t)) == t` always holds.
    """
    if not text:
        return ()
    limit = max(1, max_unit_chars)
    units: list[TextUnit] = []
    for start, end in _sentence_spans(text):
        units.extend(_subdivide(text, start, end, limit))
    return tuple(units)


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """`[start, end)` of every sentence, trailing whitespace included in the sentence before."""
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    length = len(text)
    while index < length:
        if text[index] not in _SENTENCE_ENDERS:
            index += 1
            continue
        end = index
        while end < length and text[end] in _SENTENCE_ENDERS:
            end += 1
        if end < length and not text[end].isspace():
            # Not a boundary: `3.14`, `д.5`, an ellipsis glued to the next word.
            index = end
            continue
        if text[index] == "." and _is_abbreviation_dot(text, index, next_index=end):
            index = end
            continue
        while end < length and text[end].isspace():
            end += 1
        spans.append((start, end))
        start = end
        index = end
    if start < length:
        spans.append((start, length))
    return spans


def _is_abbreviation_dot(text: str, dot_index: int, *, next_index: int) -> bool:
    """Rule 2: a `.` that closes an abbreviation or an initial is not a sentence boundary.

    A **digit** token is the one case that needs a look-ahead rather than a lexicon. «д. 5.» ends
    a sentence and «Дом 27. окончание» does not, and the only thing that tells them apart without
    a parser is what follows: a new sentence starts with a capital, a continuation does not. A
    digit followed immediately by a dot and another digit («36.6») never reaches here at all —
    rule 1 already refused it, because the character after the dot is not whitespace.
    """
    match = _LAST_TOKEN.search(text[:dot_index])
    token = match.group(0) if match is not None else ""
    candidate = f"{token}."
    if candidate.lower() in ABBREVIATIONS_RU:
        return True
    if len(token) == 1 and token.isalpha():
        return True
    if token.isdigit():
        following = text[next_index:].lstrip()
        return bool(following) and following[0].islower()
    return False


def _subdivide(text: str, start: int, end: int, limit: int) -> list[TextUnit]:
    """Rule 3: cut an over-long sentence at clause separators, greedily and never inside a word."""
    body = text[start:end]
    if len(body) <= limit:
        return [TextUnit(text=body, start=start, end=end)]
    cuts: list[int] = []
    for match in _CLAUSE_SEPARATOR.finditer(body):
        position = match.end()
        while position < len(body) and body[position].isspace():
            position += 1
        if 0 < position < len(body):
            cuts.append(position)
    if not cuts:
        # No honest cut point: one long unit beats a unit cut inside a word or a number.
        return [TextUnit(text=body, start=start, end=end)]
    units: list[TextUnit] = []
    unit_start = 0
    previous = 0
    for cut in [*cuts, len(body)]:
        if cut - unit_start > limit and previous > unit_start:
            units.append(
                TextUnit(
                    text=body[unit_start:previous],
                    start=start + unit_start,
                    end=start + previous,
                )
            )
            unit_start = previous
        previous = cut
    units.append(TextUnit(text=body[unit_start:], start=start + unit_start, end=end))
    return units


class ChunkedTtsStream:
    """A `TtsStream` over one text, synthesised unit by unit (§2.4, §6.1 step 2).

    The same wrapper sits in front of **every** provider, including the ones that could stream a
    whole utterance natively: a single cancellation semantics is worth more than a few saved
    milliseconds, and it is the only way the barge-in budget of §6.2 survives a provider whose
    unit of work is a whole `generate()` call.
    """

    def __init__(
        self,
        provider: TTSProvider,
        text: str,
        voice: TtsVoiceSpec,
        *,
        request_id: str,
        max_chunk_ms: int = 20,
        max_unit_chars: int = DEFAULT_MAX_UNIT_CHARS,
        units: Sequence[TextUnit] | None = None,
        inter_unit_pause_ms: int = 0,
        seed_scope: tuple[str, int] | None = None,
    ) -> None:
        self._provider = provider
        self._text = text
        self._voice = voice
        self._request_id = request_id
        self._max_chunk_ms = max_chunk_ms
        self._units = (
            tuple(units)
            if units is not None
            else split_for_tts(text, max_unit_chars=max_unit_chars)
        )
        self._inter_unit_pause_ms = max(0, inter_unit_pause_ms)
        self._seed_scope = seed_scope
        self._cancelled = False
        self._inner: TtsStream | None = None
        #: Every unit a request was actually issued for, in request order.
        self.requested_units: list[TextUnit] = []
        #: Every chunk yielded to the caller, re-based onto the whole text.
        self.yielded: list[TtsChunk] = []
        #: What each unit's provider stream reported it actually generated (I8 V1), in unit
        #: order — only for units whose stream exposes `synthesis_attributes`.
        self.unit_attributes: list[Mapping[str, object]] = []

    @property
    def request_id(self) -> str:
        """The id of the whole utterance; each unit's request id is `{request_id}:{n}`."""
        return self._request_id

    @property
    def text(self) -> str:
        """The exact text handed to the provider — persisted per SPEC §25."""
        return self._text

    @property
    def units(self) -> tuple[TextUnit, ...]:
        """The units this stream will synthesise, in order."""
        return self._units

    @property
    def cancelled(self) -> bool:
        """True once `cancel()` has been awaited."""
        return self._cancelled

    async def cancel(self) -> None:
        """Stop after the unit in flight; discard its audio and issue no further request."""
        self._cancelled = True
        inner = self._inner
        if inner is not None:
            await inner.cancel()

    def __aiter__(self) -> AsyncIterator[TtsChunk]:
        """Chunks of the whole text, with offsets re-based onto it."""
        return self._iterate()

    def _voice_for_unit(self, position: int) -> TtsVoiceSpec:
        """The voice of unit `position`: with a `seed_scope`, its own derived seed (I8 V1)."""
        if self._seed_scope is None:
            return self._voice
        session_id, turn_index = self._seed_scope
        return replace(self._voice, seed=derive_tts_seed(session_id, turn_index, position))

    def _silence(self, at_offset: int, chunk_index: int) -> list[TtsChunk]:
        """`inter_unit_pause_ms` of silence as `<= max_chunk_ms` chunks covering no text."""
        sample_rate = self._provider.output_sample_rate
        remaining_ms = self._inter_unit_pause_ms
        step_ms = max(1, self._max_chunk_ms)
        chunks: list[TtsChunk] = []
        elapsed_ms = 0
        while remaining_ms > 0:
            chunk_ms = min(step_ms, remaining_ms)
            samples = (sample_rate * chunk_ms) // _MS_PER_S
            chunks.append(
                TtsChunk(
                    frame=AudioFrame(
                        pcm=bytes(samples * _BYTES_PER_SAMPLE),
                        sample_rate=sample_rate,
                        num_channels=1,
                        samples_per_channel=samples,
                        capture_offset_ms=elapsed_ms,
                    ),
                    text_offset_start=at_offset,
                    text_offset_end=at_offset,
                    # Exact: the whole previous unit has been handed over before this silence.
                    alignment_is_exact=True,
                    chunk_index=chunk_index + len(chunks),
                    audio_ms=chunk_ms,
                )
            )
            elapsed_ms += chunk_ms
            remaining_ms -= chunk_ms
        return chunks

    async def _iterate(self) -> AsyncIterator[TtsChunk]:
        chunk_index = 0
        last_position = len(self._units) - 1
        for position, unit in enumerate(self._units):
            if self._cancelled:
                return
            inner = self._provider.stream(
                unit.text,
                self._voice_for_unit(position),
                request_id=f"{self._request_id}:{position}",
                max_chunk_ms=self._max_chunk_ms,
            )
            self._inner = inner
            self.requested_units.append(unit)
            first_of_unit = True
            try:
                async for chunk in inner:
                    if self._cancelled:
                        # §6.1 step 2 / ruling (3): the audio of the unit in flight is thrown
                        # away, never played. Yielding it would put sound on the wire *after*
                        # the trainee started speaking.
                        return
                    if first_of_unit:
                        first_of_unit = False
                        attributes = getattr(inner, "synthesis_attributes", None)
                        if isinstance(attributes, Mapping):
                            self.unit_attributes.append(attributes)
                    rebased = replace(
                        chunk,
                        text_offset_start=unit.start + chunk.text_offset_start,
                        text_offset_end=unit.start + chunk.text_offset_end,
                        chunk_index=chunk_index,
                    )
                    self.yielded.append(rebased)
                    yield rebased
                    chunk_index += 1
            finally:
                self._inner = None
            if self._cancelled:
                return
            if position < last_position and self._inter_unit_pause_ms > 0:
                for silence in self._silence(unit.end, chunk_index):
                    if self._cancelled:
                        return
                    self.yielded.append(silence)
                    yield silence
                    chunk_index += 1

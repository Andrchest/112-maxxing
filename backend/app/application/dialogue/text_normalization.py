"""Normalisation and tokenisation of Russian text (HLD `50-voice-pipeline.md` §7.2).

Pure and synchronous: no model, no clock, no I/O. Applied once per validated string, producing the
`normalized_text` and the token list that §7.3–§7.6 all reuse, so a model cannot evade one check by
spelling something the way another check would have missed.

The five steps of §7.2, in order:

1. NFKC normalise; `ё` → `е`; lower case for lexicon matching (the original casing survives on
   `Token.original`, which is what §7.5's capitalised-name rule reads).
2. Every Unicode dash variant becomes `-` and every quote variant becomes `"`.
3. Split on ``[^0-9A-Za-zА-Яа-я\\-/]+``, keeping hyphens and slashes **inside** tokens (`27/2`,
   `дом-27`).
4. Numeral folding against `ru_numerals.RU_NUMERAL_LEXICON`; adjacent numeral tokens fold
   left-to-right into one value, and the folded run keeps its source span.
5. Digit/word equivalence falls out of 4: `27` and `двадцать семь` produce the same canonical
   value, so a model cannot evade §7.5's number check by spelling a digit out.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.application.dialogue.ru_numerals import (
    FRACTION_VALUES_RU,
    RU_NUMERAL_LEXICON,
    THOUSAND,
)

__all__ = [
    "IDENTIFIER_PATTERN",
    "NormalizedText",
    "NumberRun",
    "Token",
    "canonical_numbers",
    "normalize_text",
    "token_texts",
]

#: §7.2 step 3. Hyphen and slash stay inside a token; everything else separates.
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-zА-Яа-я]+(?:[\-/][0-9A-Za-zА-Яа-я]+)*")
#: A pure digit run, possibly with internal separators (`27`, `27/2`, `1985`, `12-14`).
_DIGIT_RUN = re.compile(r"^[0-9]+(?:[\-/][0-9]+)*$")
#: Every Unicode dash variant §7.2 step 2 collapses onto `-`.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−－"), "-")
#: Every quote variant §7.2 step 2 collapses onto `"`.
_QUOTES = dict.fromkeys(map(ord, "‘’‚‛“”„‟«»‹›"), '"')
_SENTENCE_ENDERS = frozenset(".!?…\n")
#: An identifier-shaped substring: `people.victim_01.inside`, `world_value`, `fact_id`. §7.3 asks
#: for a match "on any substring containing `_` or `.` that appears in the set"; this is the
#: structural half of that rule and needs no scenario to be handed in (see `validator.py`).
IDENTIFIER_PATTERN = re.compile(r"[0-9a-zA-Zа-яА-Я]+[._][0-9a-zA-Zа-яА-Я._]*[0-9a-zA-Zа-яА-Я]")

_LATIN = re.compile(r"^[A-Za-z]+$")


@dataclass(frozen=True, slots=True)
class Token:
    """One token of a normalised string (§7.2 step 3)."""

    text: str
    """Normalised: NFKC, `ё`→`е`, lower case."""

    original: str
    """The same span in the original casing — what §7.5's capitalised-name rule reads."""

    index: int
    """Position in the token list."""

    start: int
    """Character offset of the token in the normalised string."""

    sentence_start: bool
    """True when no sentence-ending punctuation separates this token from the text's start."""

    number: str | None = None
    """The canonical numeric value when this token *is* a number (digit run or numeral word)."""

    @property
    def is_latin(self) -> bool:
        """True for a pure Latin-script token (§7.4's Latin-run rule)."""
        return bool(_LATIN.match(self.text))


@dataclass(frozen=True, slots=True)
class NumberRun:
    """One folded numeral run: its canonical value and the token span it came from (§7.2 step 4)."""

    value: str
    first_index: int
    last_index: int


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """The result of §7.2, shared by §7.3–§7.6."""

    normalized: str
    tokens: tuple[Token, ...]
    numbers: tuple[NumberRun, ...]

    @property
    def texts(self) -> tuple[str, ...]:
        """The normalised token strings, in order — the haystack §7.6 scans."""
        return tuple(token.text for token in self.tokens)

    @property
    def number_values(self) -> frozenset[str]:
        """Every canonical numeric value this text carries."""
        return frozenset(run.value for run in self.numbers)


def _fold_case(raw: str) -> str:
    folded = unicodedata.normalize("NFKC", raw)
    folded = folded.translate(_DASHES).translate(_QUOTES)
    return folded.replace("ё", "е").replace("Ё", "Е")


def _sentence_starts(text: str, spans: Sequence[tuple[int, int]]) -> list[bool]:
    """True for each token that opens a sentence (nothing but punctuation before it)."""
    starts: list[bool] = []
    previous_end = 0
    opening = True
    for start, end in spans:
        if opening:
            starts.append(True)
        else:
            between = text[previous_end:start]
            starts.append(any(char in _SENTENCE_ENDERS for char in between))
        opening = False
        previous_end = end
    return starts


def _numeral_value(token_text: str) -> int | None:
    return RU_NUMERAL_LEXICON.get(token_text)


def _fold_run(values: Sequence[int]) -> int:
    """`сто двадцать пять` → 125, `две тысячи пятьсот` → 2500 (§7.2 step 4, left to right)."""
    total = 0
    current = 0
    for value in values:
        if value == THOUSAND:
            current = (current or 1) * THOUSAND
            total += current
            current = 0
        else:
            current += value
    return total + current


def normalize_text(raw: str) -> NormalizedText:
    """Apply §7.2 to `raw`, returning the normalised string, its tokens and its folded numbers."""
    normalized = _fold_case(raw)
    lowered = normalized.lower()
    matches = list(_TOKEN_PATTERN.finditer(lowered))
    spans = [(match.start(), match.end()) for match in matches]
    starts = _sentence_starts(lowered, spans)

    raw_tokens: list[Token] = []
    for index, match in enumerate(matches):
        start, end = match.span()
        raw_tokens.append(
            Token(
                text=match.group(),
                original=normalized[start:end],
                index=index,
                start=start,
                sentence_start=starts[index],
            )
        )

    numbers: list[NumberRun] = []
    values: list[str | None] = [None] * len(raw_tokens)
    index = 0
    while index < len(raw_tokens):
        token = raw_tokens[index]
        if _DIGIT_RUN.match(token.text):
            numbers.append(NumberRun(value=token.text, first_index=index, last_index=index))
            values[index] = token.text
            index += 1
            continue
        fraction = FRACTION_VALUES_RU.get(token.text)
        if fraction is not None:
            numbers.append(NumberRun(value=fraction, first_index=index, last_index=index))
            values[index] = fraction
            index += 1
            continue
        numeral = _numeral_value(token.text)
        if numeral is None:
            index += 1
            continue
        run: list[int] = [numeral]
        last = index
        probe = index + 1
        while probe < len(raw_tokens):
            following = _numeral_value(raw_tokens[probe].text)
            if following is None:
                break
            run.append(following)
            last = probe
            probe += 1
        value = str(_fold_run(run))
        numbers.append(NumberRun(value=value, first_index=index, last_index=last))
        for position in range(index, last + 1):
            values[position] = value
        index = last + 1

    tokens = tuple(
        Token(
            text=token.text,
            original=token.original,
            index=token.index,
            start=token.start,
            sentence_start=token.sentence_start,
            number=values[token.index],
        )
        for token in raw_tokens
    )
    return NormalizedText(normalized=normalized, tokens=tokens, numbers=tuple(numbers))


def token_texts(raw: str) -> tuple[str, ...]:
    """The normalised token strings of `raw` — the shorthand §7.6's subsequence scan uses."""
    return normalize_text(raw).texts


def canonical_numbers(values: Iterable[str]) -> frozenset[str]:
    """Every canonical numeric value appearing anywhere in `values` (§7.5's permitted set)."""
    found: set[str] = set()
    for value in values:
        found.update(normalize_text(value).number_values)
    return frozenset(found)

"""`SpellingDictionary` — the ru_RU hunspell half of `TextCheckerPort` (I4 E35, HLD 71 §71.12,
D35).

Reads the LibreOffice `ru_RU` hunspell `.aff`/`.dic` pair packaged at `reference/lexicon/`
(BSD-style, Lebedev 1997-2008; licence and provenance in `reference/lexicon/SOURCES.txt`) through
`spylls` 0.1.7 (MIT, pure Python — no system hunspell/enchant, proven offline by E23). `spylls`
is imported lazily, inside `load`, so a backend that never asks for a text-quality report never
pays for it and a data-absent worktree does not need it installed either.

**Tokeniser.** `ru_RU.aff` declares no `BREAK`/`WORDCHARS`, so hunspell's own hyphen-splitting is
not in play here: `_WORD` matches a run of Cyrillic or Latin letters only, so a hyphenated compound
(«интернет-магазин») is checked as its two parts, punctuation and digits are never words, and a
lone letter (Russian has several one-letter words: «и», «я», «с», «к», «у», «в», «о») is still
checked — length is not a filter.

**Determinism (INV 9).** `misspellings` is a pure function of `text` and the loaded dictionary; the
dictionary is loaded once and reused (module-level cache, keyed by directory, mirroring
`file_catalog.py`'s pattern), so two reports of the same text always agree.
"""

from __future__ import annotations

import functools
import hashlib
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from app.application.ports.text_checker import MisspelledSpan

if TYPE_CHECKING:
    from spylls.hunspell import Dictionary

__all__ = ["SpellingDictionary", "SpellingDictionaryError"]

_WORD = re.compile(r"[A-Za-zА-Яа-яЁё]+")
_MAX_SUGGESTIONS = 3
_SUGGESTION_CACHE_WORDS = 4096
"""(I7 E57) Words whose suggestions are kept per dictionary: `suggest` is ~150 ms a word in
pure Python and a pure function of the word (INV 9), so a report read twice, or a lesson's
cards repeating a typo, pay for it once."""

_CACHE: dict[Path, SpellingDictionary] = {}
_LOCK = threading.Lock()


class SpellingDictionaryError(RuntimeError):
    """The lexicon directory exists but is malformed (present but unreadable, never "absent")."""


class SpellingDictionary:
    """`TextCheckerPort.misspellings`'s half, over one `spylls.hunspell.Dictionary`."""

    def __init__(self, dictionary: Dictionary, *, sha256: str) -> None:
        self._dictionary = dictionary
        self._sha256 = sha256
        self._suggestions = functools.lru_cache(maxsize=_SUGGESTION_CACHE_WORDS)(
            self._suggest_uncached
        )

    @property
    def sha256(self) -> str:
        """sha256 of `ru_RU.aff` and `ru_RU.dic`, concatenated in that order."""
        return self._sha256

    def misspellings(self, text: str, *, suggest: bool = True) -> tuple[MisspelledSpan, ...]:
        """Every word `_WORD` finds that the dictionary does not `lookup`, in reading order.
        (I7 E57) `suggest=False` never calls `Dictionary.suggest` (the expensive part)."""
        spans: list[MisspelledSpan] = []
        for match in _WORD.finditer(text):
            word = match.group(0)
            if self._dictionary.lookup(word):
                continue
            suggestions = self._suggestions(word) if suggest else ()
            spans.append(
                MisspelledSpan(
                    start=match.start(), end=match.end(), word=word, suggestions=suggestions
                )
            )
        return tuple(spans)

    def _suggest_uncached(self, word: str) -> tuple[str, ...]:
        return tuple(_first(self._dictionary.suggest(word), _MAX_SUGGESTIONS))

    @classmethod
    def load(cls, directory: Path) -> SpellingDictionary | None:
        """`reference/lexicon/ru_RU.{aff,dic}`, or `None` when the directory or either file is
        absent (the report's «Проверка недоступна» path) — cached per directory for the process.
        """
        aff = directory / "ru_RU.aff"
        dic = directory / "ru_RU.dic"
        if not aff.is_file() or not dic.is_file():
            return None
        with _LOCK:
            cached = _CACHE.get(directory)
            if cached is None:
                cached = cls._read(aff, dic)
                _CACHE[directory] = cached
            return cached

    @classmethod
    def _read(cls, aff: Path, dic: Path) -> SpellingDictionary:
        from spylls.hunspell import Dictionary  # lazy: only paid for when the data is present

        sha = hashlib.sha256(aff.read_bytes() + dic.read_bytes()).hexdigest()
        try:
            dictionary = Dictionary.from_files(str(aff.with_suffix("")))
        except Exception as error:  # spylls raises plain Exception/OSError on a malformed pair
            raise SpellingDictionaryError(f"{aff.parent}: {error}") from error
        return cls(dictionary, sha256=sha)


def _first(items: object, limit: int) -> list[str]:
    """The first `limit` items of `suggest`'s lazy generator, without exhausting it further."""
    out: list[str] = []
    for item in items:  # type: ignore[attr-defined]
        out.append(str(item))
        if len(out) >= limit:
            break
    return out

"""`TextCheckerPort` — the text-quality annotation's two reads (I4 E35 + I5 E41,
`docs/hld/71-i4-wave4.md` §71.12, D35, Q-E23-2).

**Report-time, read-only, no score effect** (D35, Q-E11-1 open). The port has exactly the two
methods the design names:

* `misspellings(text)` — every word the ru_RU dictionary does not recognise, as a `MisspelledSpan`
  (offsets into `text`, plus up to three suggestions);
* `street_status(street, locality)` — whether a street name is in the Moscow street directory:
  `KNOWN`, `UNKNOWN`, or `NEAR` with suggestions when the directory has a close match. Since I5 E41
  CHANGE A, `KNOWN` means the OSM extract *or* the КЛАДР extract has it (the two are unioned).
  `locality` is accepted for the signature's future scope (Q-E11-2, streets outside Moscow) but the
  one adapter today checks every street against the same Moscow list regardless of its value — no
  locality-based skip is built, because outside-Moscow coverage does not exist to skip *to*.

The adapter is `app.infrastructure.reference.text_checker.FileTextChecker`, over the packaged data
under `reference/lexicon/` and `reference/streets/` (BSD-style LibreOffice dictionary; ODbL OSM
names unioned with ФНС open-data КЛАДР names). Both properties below are the data's own sha256,
recorded so a report can say exactly which snapshot it checked against (INV 9).

`TextCheckerPort | None` is the composition root's shape for "the data is absent" (mirrors
`ReferencePort | None` in `assemble_report.py`): `application.reports.text_quality` reads `None`
as `available: false` and never raises.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

__all__ = [
    "MisspelledSpan",
    "StreetLookup",
    "StreetStatusKind",
    "TextCheckerPort",
]


@dataclass(frozen=True, slots=True)
class MisspelledSpan:
    """One word `misspellings` does not recognise, as an offset into the checked text."""

    start: int
    end: int
    word: str
    suggestions: tuple[str, ...] = ()
    """Up to three dictionary suggestions, closest first; empty when the dictionary has none."""


class StreetStatusKind(str, Enum):
    """`street_status`'s three outcomes (§71.12)."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    NEAR = "NEAR"


@dataclass(frozen=True, slots=True)
class StreetLookup:
    """`street_status`'s result: the kind, plus close-match suggestions for `NEAR`."""

    status: StreetStatusKind
    suggestions: tuple[str, ...] = ()
    """Non-empty only when `status` is `NEAR`."""


@runtime_checkable
class TextCheckerPort(Protocol):
    """Read access to the ru_RU dictionary and the Moscow street directory."""

    def misspellings(self, text: str, *, suggest: bool = True) -> Sequence[MisspelledSpan]:
        """Every word of `text` the dictionary does not recognise, in reading order.

        (I7 E57) `suggest=False` skips the suggestion search — every span's `suggestions` is
        empty. That search is the one expensive step (hunspell's, in pure Python: ~150 ms a
        misspelled word, against under 0.1 ms a lookup), so a caller that only counts the spans
        passes it."""
        ...

    def street_status(
        self, street: str, locality: str | None = None, *, suggest: bool = True
    ) -> StreetLookup:
        """Whether `street` is a known Moscow street name (§71.12; `locality` is unused today).

        (I7 E57) `suggest=False` skips the close-match search over the whole directory: a street
        it does not hold is then `UNKNOWN`, never `NEAR` — for a caller that only asks "is it
        `KNOWN`"."""
        ...

    @property
    def dictionary_sha256(self) -> str:
        """`reference/lexicon`'s pinned sha256 (the `.dic` + `.aff` pair, concatenated)."""
        ...

    @property
    def street_list_sha256(self) -> str:
        """`reference/streets/`'s street files, pinned: `osm_moscow_street_names.txt`'s sha256
        alone, or (since I5 E41) that sha256 concatenated with `kladr_moscow_street_names.txt`'s
        when the КЛАДР extract is present — the same "concatenate, then hash" shape
        `dictionary_sha256` already uses for its two-file lexicon."""
        ...

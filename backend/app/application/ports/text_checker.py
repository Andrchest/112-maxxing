"""`TextCheckerPort` — the text-quality annotation's two reads (I4 E35, `docs/hld/71-i4-wave4.md`
§71.12, D35).

**Report-time, read-only, no score effect** (D35, Q-E11-1 open). The port has exactly the two
methods the design names:

* `misspellings(text)` — every word the ru_RU dictionary does not recognise, as a `MisspelledSpan`
  (offsets into `text`, plus up to three suggestions);
* `street_status(street, locality)` — whether a street name is in the Moscow OSM directory:
  `KNOWN`, `UNKNOWN`, or `NEAR` with suggestions when the directory has a close match. `locality`
  is accepted for the signature's future scope (Q-E11-2, streets outside Moscow) but the one
  adapter today checks every street against the same Moscow list regardless of its value — no
  locality-based skip is built, because outside-Moscow coverage does not exist to skip *to*.

The adapter is `app.infrastructure.reference.text_checker.FileTextChecker`, over the packaged data
under `reference/lexicon/` and `reference/streets/` (BSD-style LibreOffice dictionary, ODbL OSM
names). Both properties below are the data's own sha256, recorded so a report can say exactly
which snapshot it checked against (INV 9).

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

    def misspellings(self, text: str) -> Sequence[MisspelledSpan]:
        """Every word of `text` the dictionary does not recognise, in reading order."""
        ...

    def street_status(self, street: str, locality: str | None = None) -> StreetLookup:
        """Whether `street` is a known Moscow street name (§71.12; `locality` is unused today)."""
        ...

    @property
    def dictionary_sha256(self) -> str:
        """`reference/lexicon`'s pinned sha256 (the `.dic` + `.aff` pair, concatenated)."""
        ...

    @property
    def street_list_sha256(self) -> str:
        """`reference/streets/osm_moscow_street_names.txt`'s pinned sha256."""
        ...

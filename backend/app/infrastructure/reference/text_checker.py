"""`FileTextChecker` — the file-backed `TextCheckerPort` (I4 E35, HLD 71 §71.12, D35).

Composes `SpellingDictionary` and `StreetDirectory` behind the one port `GetSessionReport` (and
`application.reports.text_quality`) hold an optional reference to — the same "`Port | None`,
absence is a real, reportable state" shape as `ReferencePort | None` elsewhere in this codebase.
`load` never raises for "the data is not there": it returns `None`, and the report renders
«Проверка недоступна» (D35's own honesty rule, SPEC §27 — never «0 ошибок»). A directory that
exists but is corrupt is a real bug and does raise, from the sub-loader.

Both halves must load for `load` to return a checker: a report that could check spelling but not
streets, or vice versa, is not a state this epic's «Грамотность и адреса» section distinguishes
(recorded as a technical simplification in the report; splitting it is a follow-up if the owner
ever wants partial availability surfaced).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from app.application.ports.text_checker import MisspelledSpan, StreetLookup
from app.infrastructure.reference.spelling_dictionary import SpellingDictionary
from app.infrastructure.reference.street_directory import StreetDirectory

__all__ = ["DEFAULT_LEXICON_DIR", "DEFAULT_STREETS_DIR", "FileTextChecker"]

_REPO_ROOT = Path(__file__).resolve().parents[4]
"""`<repo>` — `backend/app/infrastructure/reference/text_checker.py` is four levels in, the same
count `file_catalog.py` uses for `DEFAULT_REFERENCE_DIR`."""

DEFAULT_LEXICON_DIR = _REPO_ROOT / "reference" / "lexicon"
DEFAULT_STREETS_DIR = _REPO_ROOT / "reference" / "streets"


class FileTextChecker:
    """`TextCheckerPort` over `reference/lexicon/` and `reference/streets/`."""

    def __init__(self, spelling: SpellingDictionary, streets: StreetDirectory) -> None:
        self._spelling = spelling
        self._streets = streets

    def misspellings(self, text: str) -> Sequence[MisspelledSpan]:
        return self._spelling.misspellings(text)

    def street_status(self, street: str, locality: str | None = None) -> StreetLookup:
        return self._streets.status(street, locality)

    @property
    def dictionary_sha256(self) -> str:
        return self._spelling.sha256

    @property
    def street_list_sha256(self) -> str:
        return self._streets.sha256

    @classmethod
    def load(
        cls,
        lexicon_dir: Path | str = DEFAULT_LEXICON_DIR,
        streets_dir: Path | str = DEFAULT_STREETS_DIR,
    ) -> FileTextChecker | None:
        """Both halves, or `None` when either's data is absent."""
        spelling = SpellingDictionary.load(Path(lexicon_dir))
        streets = StreetDirectory.load(Path(streets_dir))
        if spelling is None or streets is None:
            return None
        return cls(spelling, streets)

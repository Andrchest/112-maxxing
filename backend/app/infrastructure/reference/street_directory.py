"""`StreetDirectory` — the OSM half of `TextCheckerPort` (I4 E35, HLD 71 §71.12, D35).

Reads `reference/streets/osm_moscow_street_names.txt` (ODbL 1.0, OpenStreetMap contributors;
provenance in `reference/streets/SOURCES.txt`) — the unique `name` values of Moscow's named
`highway` ways, one per line, in the Overpass CSV's own quoting (RFC 4180: a value with a comma is
`"quoted"`, and a literal `"` inside one is doubled). Moscow-only (Q-E11-2 leaves the rest); the
directory has no okrug or district, so `street_status`'s `locality` parameter is accepted for the
port's signature but not used to filter — there is nothing else to filter *to* yet.

**Matching, order- and abbreviation-insensitive.** A street's type word («улица», «проспект», …)
sits on either side of the name depending on the type (§71.12's own examples: «Кутузовский
проспект» but «Дубнинская улица»), and a trainee may type the abbreviation («ул.») or none at all.
`_normalise` strips every token in `_TYPE_WORDS`, lower-cases, folds «ё»→«е», and sorts what is
left — so «ул. Зверенецкая», «Зверенецкая» and «Зверенецкая улица» all normalise to the same key,
comparable against the directory's own «Зверинецкая улица» → `{зверинецкая}` vs `{зверенецкая}`.
That one-letter difference is exactly why it is `NEAR`, not `KNOWN`: **the misspelling is flagged,
never silently matched or corrected** (D-h) — ticket-15-call-3's organizer-verbatim spelling stays
in the scenario untouched; only the report says the directory disagrees.
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import re
import threading
from pathlib import Path

from app.application.ports.text_checker import StreetLookup, StreetStatusKind

__all__ = ["StreetDirectory"]

_TYPE_WORDS = frozenset(
    {
        "ул",
        "улица",
        "пер",
        "переулок",
        "пр",
        "пр-т",
        "просп",
        "проспект",
        "пл",
        "площадь",
        "наб",
        "набережная",
        "ш",
        "шоссе",
        "б-р",
        "бул",
        "бульвар",
        "туп",
        "тупик",
        "проезд",
        "линия",
        "аллея",
        "мкр",
        "микрорайон",
        "кв-л",
        "квартал",
        "пос",
        "поселок",
        "посёлок",
        "деревня",
        "село",
        "город",
        "г",
        "км",
        "километр",
    }
)
_TOKEN = re.compile(r"[а-я0-9]+")
_MAX_SUGGESTIONS = 3
_NEAR_CUTOFF = 0.72

_CACHE: dict[Path, StreetDirectory] = {}
_LOCK = threading.Lock()


def _normalise(raw: str) -> str:
    text = raw.strip().replace("ё", "е").replace("Ё", "Е").lower()
    tokens = _TOKEN.findall(text)
    words = [t for t in tokens if t not in _TYPE_WORDS]
    return " ".join(sorted(words or tokens))


class StreetDirectory:
    """`TextCheckerPort.street_status`'s half, over the OSM Moscow street-name list."""

    def __init__(self, by_key: dict[str, list[str]], *, sha256: str) -> None:
        self._by_key = by_key
        self._keys = tuple(by_key)
        self._sha256 = sha256

    @property
    def sha256(self) -> str:
        return self._sha256

    def status(self, street: str, locality: str | None = None) -> StreetLookup:
        """`locality` is accepted, not used (module doc) — the one directory covers Moscow."""
        if not street.strip():
            return StreetLookup(status=StreetStatusKind.UNKNOWN)
        key = _normalise(street)
        if key in self._by_key:
            return StreetLookup(status=StreetStatusKind.KNOWN)
        close = difflib.get_close_matches(key, self._keys, n=_MAX_SUGGESTIONS, cutoff=_NEAR_CUTOFF)
        if close:
            suggestions = tuple(self._by_key[match][0] for match in close)
            return StreetLookup(status=StreetStatusKind.NEAR, suggestions=suggestions)
        return StreetLookup(status=StreetStatusKind.UNKNOWN)

    @classmethod
    def load(cls, directory: Path) -> StreetDirectory | None:
        """`reference/streets/osm_moscow_street_names.txt`, or `None` when absent — cached per
        directory for the process."""
        path = directory / "osm_moscow_street_names.txt"
        if not path.is_file():
            return None
        with _LOCK:
            cached = _CACHE.get(directory)
            if cached is None:
                cached = cls._read(path)
                _CACHE[directory] = cached
            return cached

    @classmethod
    def _read(cls, path: Path) -> StreetDirectory:
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        by_key: dict[str, list[str]] = {}
        for row in csv.reader(raw.decode("utf-8").splitlines()):
            if not row or not row[0].strip():
                continue
            name = row[0].strip()
            by_key.setdefault(_normalise(name), []).append(name)
        return cls(by_key, sha256=sha)

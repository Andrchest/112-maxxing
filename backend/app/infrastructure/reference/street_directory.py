"""`StreetDirectory` — the street half of `TextCheckerPort` (I4 E35 + I5 E41, HLD 71 §71.12, D35,
Q-E23-2).

Reads two files under its directory and unions them:

* `reference/streets/osm_moscow_street_names.txt` (ODbL 1.0, OpenStreetMap contributors;
  provenance in `reference/streets/SOURCES.txt`) — the unique `name` values of Moscow's named
  `highway` ways, one per line, in the Overpass CSV's own quoting (RFC 4180: a value with a comma
  is `"quoted"`, and a literal `"` inside one is doubled). **Required**: `load` returns `None`
  without it, same as before I5 E41.
* `reference/streets/kladr_moscow_street_names.txt` (ФНС open data, КЛАДР region 77; provenance in
  the same `SOURCES.txt`) — one `"<name> <socr>"` per line, plain text (`backend/tools/
  import_kladr_streets.py`). **Optional**: when it is absent the directory still loads, OSM-only,
  exactly as before this epic — the raw `base.7z` archive it is built from is never committed
  (I5 E41 CHANGE A), so an environment that never ran the extractor keeps working.

A street is `KNOWN` if either source has it (I5 E41 CHANGE A, manager decision, final); `NEAR`
suggestions are drawn from the union of both directories' keys. Moscow-only (Q-E11-2 leaves the
rest); the directory has no okrug or district, so `street_status`'s `locality` parameter is
accepted for the port's signature but not used to filter — there is nothing else to filter *to*
yet.

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
import functools
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
        # (I7 E57) The close-match search scans the whole directory (difflib, pure Python):
        # kept per normalised key, the same answer every time (INV 9).
        self._close_matches = functools.lru_cache(maxsize=4096)(self._close_uncached)

    @property
    def sha256(self) -> str:
        return self._sha256

    def status(
        self, street: str, locality: str | None = None, *, suggest: bool = True
    ) -> StreetLookup:
        """`locality` is accepted, not used (module doc) — the one directory covers Moscow.
        (I7 E57) `suggest=False` stops before the close-match search: not `KNOWN` is `UNKNOWN`."""
        if not street.strip():
            return StreetLookup(status=StreetStatusKind.UNKNOWN)
        key = _normalise(street)
        if key in self._by_key:
            return StreetLookup(status=StreetStatusKind.KNOWN)
        if not suggest:
            return StreetLookup(status=StreetStatusKind.UNKNOWN)
        close = self._close_matches(key)
        if close:
            suggestions = tuple(self._by_key[match][0] for match in close)
            return StreetLookup(status=StreetStatusKind.NEAR, suggestions=suggestions)
        return StreetLookup(status=StreetStatusKind.UNKNOWN)

    def _close_uncached(self, key: str) -> tuple[str, ...]:
        return tuple(
            difflib.get_close_matches(key, self._keys, n=_MAX_SUGGESTIONS, cutoff=_NEAR_CUTOFF)
        )

    @classmethod
    def load(cls, directory: Path) -> StreetDirectory | None:
        """The OSM file (required) unioned with the КЛАДР file (optional) — `None` when the OSM
        file is absent — cached per directory for the process."""
        osm_path = directory / "osm_moscow_street_names.txt"
        if not osm_path.is_file():
            return None
        kladr_path = directory / "kladr_moscow_street_names.txt"
        with _LOCK:
            cached = _CACHE.get(directory)
            if cached is None:
                cached = cls._read(osm_path, kladr_path if kladr_path.is_file() else None)
                _CACHE[directory] = cached
            return cached

    @classmethod
    def _read(cls, osm_path: Path, kladr_path: Path | None) -> StreetDirectory:
        osm_raw = osm_path.read_bytes()
        by_key = cls._read_osm_csv(osm_raw)
        combined_raw = osm_raw
        if kladr_path is not None:
            kladr_raw = kladr_path.read_bytes()
            by_key = _merge_by_key(by_key, cls._read_plain_lines(kladr_raw))
            combined_raw = osm_raw + kladr_raw
        sha = hashlib.sha256(combined_raw).hexdigest()
        return cls(by_key, sha256=sha)

    @staticmethod
    def _read_osm_csv(raw: bytes) -> dict[str, list[str]]:
        """`osm_moscow_street_names.txt`'s own Overpass CSV quoting (module doc)."""
        by_key: dict[str, list[str]] = {}
        for row in csv.reader(raw.decode("utf-8").splitlines()):
            if not row or not row[0].strip():
                continue
            name = row[0].strip()
            by_key.setdefault(_normalise(name), []).append(name)
        return by_key

    @staticmethod
    def _read_plain_lines(raw: bytes) -> dict[str, list[str]]:
        """`kladr_moscow_street_names.txt`: one name per line, no quoting needed."""
        by_key: dict[str, list[str]] = {}
        for line in raw.decode("utf-8").splitlines():
            name = line.strip()
            if not name:
                continue
            by_key.setdefault(_normalise(name), []).append(name)
        return by_key


def _merge_by_key(*sources: dict[str, list[str]]) -> dict[str, list[str]]:
    """Union several `by_key` maps, keeping each key's display names in source order, deduplicated
    (so a name present in both files is not offered twice as a suggestion)."""
    merged: dict[str, list[str]] = {}
    for source in sources:
        for key, names in source.items():
            bucket = merged.setdefault(key, [])
            for name in names:
                if name not in bucket:
                    bucket.append(name)
    return merged

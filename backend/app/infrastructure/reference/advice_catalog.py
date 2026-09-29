"""`load_advice_catalog` — the G10 default advice text per `ScoringCategory` (ТЗ ¶267, ¶237, final
criteria ¶460/¶469, I7 E54), `reference/advice/v1.yaml`.

Flat like `materials/organizer.yaml` — one small file with no pack association (the seven
categories never change per reference pack) — so it is read directly here rather than folded into
`ReferenceCatalog`'s pack-scoped shape. It is still pinned in `reference/manifest.json`'s `files`
map, so `file_catalog.load_reference`'s generic sha256 loop (run once, at container start-up)
already refuses a drifted copy before this loader ever runs.

Cached per path for the process, mirroring `SpellingDictionary`'s pattern: `None` only when the
file is absent (a stripped-down fixture directory, the composition root's own "no advice" path,
`Container.advice_catalog` falling back to `{}`), never for a malformed one — a pack that ships
`advice/v1.yaml` but gets it wrong is a startup error, not a silently empty report section.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from app.domain.enums import ScoringCategory

__all__ = ["AdviceCatalogError", "load_advice_catalog"]

_CACHE: dict[Path, Mapping[ScoringCategory, str]] = {}
_LOCK = threading.Lock()

_MAX_LENGTH = 300
"""The same cap `ScoringRule.advice` and rule R45 enforce on a rule's own override."""


class AdviceCatalogError(RuntimeError):
    """`reference/advice/<id>.yaml` exists but is malformed: an unknown category, a missing one,
    a blank text, or a text over `_MAX_LENGTH` characters."""


def load_advice_catalog(
    directory: Path, *, name: str = "v1"
) -> Mapping[ScoringCategory, str] | None:
    """`<directory>/advice/<name>.yaml`'s `categories` map, every `ScoringCategory` covered.

    `directory` is the reference pack root (`settings.reference_dir`), the same argument
    `FileReferenceCatalog`/`SpellingDictionary.load` take. `None` when the file itself is absent;
    raises `AdviceCatalogError` for anything else wrong with a file that IS there.
    """
    path = directory / "advice" / f"{name}.yaml"
    if not path.is_file():
        return None
    with _LOCK:
        cached = _CACHE.get(path)
        if cached is not None:
            return cached
        catalog = _read(path)
        _CACHE[path] = catalog
        return catalog


def _read(path: Path) -> Mapping[ScoringCategory, str]:
    document: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    categories = document.get("categories") if isinstance(document, Mapping) else None
    if not isinstance(categories, Mapping):
        raise AdviceCatalogError(f"{path}: no top-level 'categories' mapping")
    result: dict[ScoringCategory, str] = {}
    for key, text in categories.items():
        try:
            category = ScoringCategory(str(key))
        except ValueError as error:
            raise AdviceCatalogError(f"{path}: unknown ScoringCategory {key!r}") from error
        if not isinstance(text, str) or not text.strip():
            raise AdviceCatalogError(f"{path}: category {key!r} has no advice text")
        if len(text) > _MAX_LENGTH:
            raise AdviceCatalogError(
                f"{path}: category {key!r} advice is {len(text)} characters, "
                f"over the {_MAX_LENGTH}-character cap"
            )
        result[category] = text
    missing = sorted(category.value for category in set(ScoringCategory) - result.keys())
    if missing:
        raise AdviceCatalogError(f"{path}: missing advice for {missing}")
    return result

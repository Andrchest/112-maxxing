"""`ReferencePort` — the reference pack (HLD `70-i3-alignment.md` §70.6.1, D18).

`reference/` (manifest, card schemas, classifier, service catalog) is read-only, versioned by git
and small, so it is not a table: the composition root loads it once into an immutable
`ReferenceCatalog` behind this port (file-backed adapter:
`app.infrastructure.reference.file_catalog`). A test injects any catalog it likes — a fixture
pack — through `Container(reference=…)`, and nothing else changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.routing.catalog import ReferenceCatalog

__all__ = ["ReferencePort"]


@runtime_checkable
class ReferencePort(Protocol):
    """Read access to the reference pack."""

    def catalog(self) -> ReferenceCatalog:
        """The parsed reference pack. Loaded on first use, then the same object every call."""
        ...

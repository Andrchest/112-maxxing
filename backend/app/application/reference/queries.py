"""The reference API's read use cases (HLD `70-i3-alignment.md` §70.6.1-§70.6.3, D18).

`getReferenceManifest`, `listReferenceServices`, `searchClassifier`, `getClassifierRow`: pure reads
of the `ReferenceCatalog` behind `ReferencePort` — no Unit of Work, no event, nothing written.
`pack` defaults to the newest pack of the manifest (`PackQueryParam`); an unknown pack, a pack
without a classifier and an unknown classifier code are `404 NOT_FOUND`.

`reference_catalog(port)` is the one place the application falls back to `LEGACY_REFERENCE` when
no port was wired (a use case built by a unit test with only the arguments it needs).
"""

from __future__ import annotations

from collections.abc import Mapping

from app.application.ports.reference import ReferencePort
from app.domain.common.errors import DomainError
from app.domain.dds.personas import Persona
from app.domain.routing.catalog import (
    LEGACY_REFERENCE,
    ReferenceCatalog,
    ServiceCatalog,
    ServiceCatalogEntry,
)
from app.domain.routing.classifier import Classifier, ClassifierRow

__all__ = [
    "GetClassifierRow",
    "GetReferenceManifest",
    "ListReferenceServices",
    "ReferenceNotFoundError",
    "SearchClassifier",
    "reference_catalog",
]


class ReferenceNotFoundError(DomainError):
    """Unknown pack, a pack without a classifier, or an unknown classifier code (`404`)."""

    code = "NOT_FOUND"


def reference_catalog(reference: ReferencePort | None) -> ReferenceCatalog:
    """The injected pack's catalog, else `LEGACY_REFERENCE` (the six legacy services)."""
    return reference.catalog() if reference is not None else LEGACY_REFERENCE


def _pack_id(catalog: ReferenceCatalog, pack: str | None) -> str:
    pack_id = pack if pack else catalog.newest_pack_id
    if catalog.pack(pack_id) is None:
        raise ReferenceNotFoundError(f"no reference pack {pack_id!r}")
    return pack_id


def _services(catalog: ReferenceCatalog, pack: str | None) -> ServiceCatalog:
    services = catalog.services(_pack_id(catalog, pack))
    assert services is not None  # `_pack_id` checked the pack
    return services


def _classifier(catalog: ReferenceCatalog, pack: str | None) -> Classifier:
    pack_id = _pack_id(catalog, pack)
    classifier = catalog.classifier(pack_id)
    if classifier is None:
        raise ReferenceNotFoundError(f"reference pack {pack_id!r} has no classifier")
    return classifier


class GetReferenceManifest:
    """`getReferenceManifest` — `reference/manifest.json`, verbatim."""

    def __init__(self, reference: ReferencePort) -> None:
        self._reference = reference

    def __call__(self) -> Mapping[str, object]:
        return self._reference.catalog().manifest


class ListReferenceServices:
    """`listReferenceServices` — a pack's service catalog, searchable."""

    def __init__(self, reference: ReferencePort) -> None:
        self._reference = reference

    def __call__(
        self, *, pack: str | None = None, include_hidden: bool = False, q: str | None = None
    ) -> list[ServiceCatalogEntry]:
        return _services(self._reference.catalog(), pack).search(q, include_hidden=include_hidden)


class SearchClassifier:
    """`searchClassifier` — the «Класс.:» picker: a page of rows plus the total match count."""

    def __init__(self, reference: ReferencePort) -> None:
        self._reference = reference

    def __call__(
        self, *, pack: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[ClassifierRow], int]:
        return _classifier(self._reference.catalog(), pack).search(q, limit=limit, offset=offset)


class GetClassifierRow:
    """`getClassifierRow` — one row with its routing cells."""

    def __init__(self, reference: ReferencePort) -> None:
        self._reference = reference

    def __call__(self, code: str, *, pack: str | None = None) -> ClassifierRow:
        row = _classifier(self._reference.catalog(), pack).row(code)
        if row is None:
            raise ReferenceNotFoundError(f"no classifier row {code!r}")
        return row


class ListReferencePersonas:
    """`listReferencePersonas` — the ДДС phone's personas of a pack, in file order (I3 E6c, HLD 80
    §80.4.1). A pack without personas (`legacy-r1`) answers an empty list; an unknown pack `404`."""

    def __init__(self, reference: ReferencePort) -> None:
        self._reference = reference

    def __call__(self, *, pack: str | None = None) -> list[Persona]:
        catalog = self._reference.catalog()
        personas = catalog.personas(_pack_id(catalog, pack))
        return [] if personas is None else list(personas.personas)

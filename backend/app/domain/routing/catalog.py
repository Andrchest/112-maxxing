"""The service catalog and the reference packs (HLD `70-i3-alignment.md` §70.6.1, §70.6.3, D18).

Pure data, no I/O: the file-backed adapter (`infrastructure/reference/file_catalog.py`) parses
`reference/` into these types once, and everything downstream — scenario rule R37/R38, the
`selectRecipientService` check, the reference API, `SESSION_CREATED.reference_pack` — reads them.

`LEGACY_REFERENCE` is the pack the product had before E2a expressed as data: the six legacy ids of
`LEGACY_SERVICE_IDS` and the `legacy-r1` pack id. It is what a pure caller gets when it passes no
reference (tests, the validator's default), so a schema-1 scenario validates exactly as before.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, PrivateAttr

from app.domain.enums import LEGACY_SERVICE_IDS, ServiceId
from app.domain.layers.card_schema import CardSchema
from app.domain.layers.operator_card import CARD_SCHEMA_V1

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.domain.routing.classifier import Classifier

__all__ = [
    "DEFAULT_PACK_ID",
    "LEGACY_REFERENCE",
    "ReferenceCatalog",
    "ReferencePack",
    "ReferencePackRecord",
    "ServiceCatalog",
    "ServiceCatalogEntry",
    "ServiceKind",
    "StatusPolicy",
]

DEFAULT_PACK_ID = "legacy-r1"
"""The pack a schema-1 scenario uses, and a schema-2 one that names none (HLD 70 §70.5.4)."""


class ServiceKind(str, Enum):
    """§70.6.3 `kind`."""

    CITY = "CITY"
    DISTRICT = "DISTRICT"
    PREFECTURE = "PREFECTURE"
    DEPARTMENT = "DEPARTMENT"


class StatusPolicy(str, Enum):
    """§70.6.3 `status_policy`: `NO_REFUSAL` services (103) may not answer «Отказ»."""

    DEFAULT = "DEFAULT"
    NO_REFUSAL = "NO_REFUSAL"


class ServiceCatalogEntry(BaseModel):
    """One service of the catalog (§70.6.3; `openapi.yaml`'s `ServiceCatalogEntry`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: ServiceId
    name_ru: str
    full_name_ru: str
    kind: ServiceKind
    code: str | None
    okrug: str | None
    district: str | None
    classifier_org_id: str | None
    classifier_org_ids: tuple[str, ...] = ()
    """Every classifier column group that answers for this service (HLD 70 §70.6.3, B1 G4):
    `FIRE_RESCUE` is both «Служба 101» and «ОДС ПСЦ». `classifier_org_id` is its first member."""
    status_policy: StatusPolicy
    display: bool
    deprecated: bool
    phone: str | None


class ServiceCatalog(BaseModel):
    """A versioned service catalog (`services/<catalog_id>.yaml`), entries in file order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_id: str
    services: tuple[ServiceCatalogEntry, ...]

    _by_id: Mapping[str, ServiceCatalogEntry] = PrivateAttr(default_factory=dict)

    def model_post_init(self, context: Any, /) -> None:
        self._by_id = MappingProxyType({entry.id: entry for entry in self.services})

    def get(self, service_id: str) -> ServiceCatalogEntry | None:
        """The entry for `service_id`, or `None` when the catalog has no such id."""
        return self._by_id.get(service_id)

    def __contains__(self, service_id: object) -> bool:
        return isinstance(service_id, str) and service_id in self._by_id

    @property
    def ids(self) -> tuple[ServiceId, ...]:
        return tuple(entry.id for entry in self.services)

    def search(
        self, query: str | None = None, *, include_hidden: bool = False
    ) -> list[ServiceCatalogEntry]:
        """Entries in catalog order, `display: false` and `deprecated` ones left out unless
        `include_hidden`, filtered by a case-insensitive substring of id, `name_ru` or
        `full_name_ru` when `query` is non-blank."""
        needle = (query or "").strip().casefold()
        return [
            entry
            for entry in self.services
            if (include_hidden or (entry.display and not entry.deprecated))
            and (
                not needle
                or needle in entry.id.casefold()
                or needle in entry.name_ru.casefold()
                or needle in entry.full_name_ru.casefold()
            )
        ]


class ReferencePack(BaseModel):
    """One `manifest.json` pack: the file ids it is made of (§70.6.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_id: str
    card_schema: str
    services: str
    classifier: str | None


class ReferencePackRecord(BaseModel):
    """What `SESSION_CREATED.reference_pack` records: the ids and sha256 of the files a session
    runs with (HLD 70 §70.7; `openapi.yaml`'s `ReferencePackRecord`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_id: str
    card_schema: str
    card_schema_sha256: str
    classifier: str | None
    classifier_sha256: str | None
    services: str
    services_sha256: str


class ReferenceCatalog:
    """Everything `reference/` holds, parsed: packs in manifest order, each service catalog,
    classifier and card schema by id, and every file's sha256. Immutable once built (§70.6.1).

    The code-backed card schema `v1` (`CARD_SCHEMA_V1`) is always present, so a catalog built
    without card schemas (a unit test's fixture pack) still resolves the `legacy-r1` card.
    """

    def __init__(
        self,
        *,
        packs: Iterable[ReferencePack],
        service_catalogs: Iterable[ServiceCatalog],
        classifiers: Iterable[Classifier] = (),
        card_schemas: Iterable[CardSchema] = (),
        file_sha256: Mapping[str, str] | None = None,
        manifest: Mapping[str, object] | None = None,
    ) -> None:
        self._packs: Mapping[str, ReferencePack] = MappingProxyType(
            {pack.pack_id: pack for pack in packs}
        )
        self._services: Mapping[str, ServiceCatalog] = MappingProxyType(
            {catalog.catalog_id: catalog for catalog in service_catalogs}
        )
        self._classifiers: Mapping[str, Classifier] = MappingProxyType(
            {classifier.classifier_id: classifier for classifier in classifiers}
        )
        self._card_schemas: Mapping[str, CardSchema] = MappingProxyType(
            {CARD_SCHEMA_V1.schema_id: CARD_SCHEMA_V1}
            | {schema.schema_id: schema for schema in card_schemas}
        )
        self._file_sha256: Mapping[str, str] = MappingProxyType(dict(file_sha256 or {}))
        self._manifest: Mapping[str, object] = MappingProxyType(dict(manifest or {}))
        if not self._packs:
            raise ValueError("a reference catalog needs at least one pack")
        for pack in self._packs.values():
            if pack.services not in self._services:
                raise ValueError(f"pack {pack.pack_id}: no service catalog {pack.services!r}")
            if pack.classifier is not None and pack.classifier not in self._classifiers:
                raise ValueError(f"pack {pack.pack_id}: no classifier {pack.classifier!r}")
            if pack.card_schema not in self._card_schemas:
                raise ValueError(f"pack {pack.pack_id}: no card schema {pack.card_schema!r}")

    @property
    def pack_ids(self) -> tuple[str, ...]:
        """Every pack id, in manifest order."""
        return tuple(self._packs)

    @property
    def newest_pack_id(self) -> str:
        """The last pack of the manifest — the reference API's default `pack` (`PackQueryParam`)."""
        return self.pack_ids[-1]

    @property
    def manifest(self) -> Mapping[str, object]:
        """`manifest.json`, verbatim (`getReferenceManifest`)."""
        return self._manifest

    def file_sha256(self, name: str) -> str:
        """The manifest's sha256 of `name` (`card-schema/v2.yaml`, …); `""` when not pinned."""
        return self._file_sha256.get(name, "")

    def pack(self, pack_id: str) -> ReferencePack | None:
        return self._packs.get(pack_id)

    def services(self, pack_id: str) -> ServiceCatalog | None:
        """The service catalog of `pack_id`, or `None` for an unknown pack."""
        pack = self._packs.get(pack_id)
        return self._services[pack.services] if pack is not None else None

    def classifier(self, pack_id: str) -> Classifier | None:
        """The classifier of `pack_id`; `None` for an unknown pack or a pack without one."""
        pack = self._packs.get(pack_id)
        if pack is None or pack.classifier is None:
            return None
        return self._classifiers[pack.classifier]

    def card_schema(self, pack_id: str) -> CardSchema | None:
        """The card schema of `pack_id` (HLD 70 §70.5.4), or `None` for an unknown pack."""
        pack = self._packs.get(pack_id)
        return self._card_schemas[pack.card_schema] if pack is not None else None

    def card_schema_by_id(self, schema_id: str) -> CardSchema | None:
        """A card schema by its own id (`v1`, `v2`), or `None` (`getCardSchema`)."""
        return self._card_schemas.get(schema_id)

    def record(self, pack_id: str) -> ReferencePackRecord | None:
        """`SESSION_CREATED.reference_pack` for `pack_id`, or `None` for an unknown pack."""
        pack = self._packs.get(pack_id)
        if pack is None:
            return None
        return ReferencePackRecord(
            pack_id=pack.pack_id,
            card_schema=pack.card_schema,
            card_schema_sha256=self._file_sha256.get(f"card-schema/{pack.card_schema}.yaml", ""),
            classifier=pack.classifier,
            classifier_sha256=(
                self._file_sha256.get(f"classifier/{pack.classifier}.json", "")
                if pack.classifier is not None
                else None
            ),
            services=pack.services,
            services_sha256=self._file_sha256.get(f"services/{pack.services}.yaml", ""),
        )


def _legacy_entry(service_id: ServiceId, name_ru: str, **extra: object) -> ServiceCatalogEntry:
    return ServiceCatalogEntry.model_validate(
        {
            "id": service_id,
            "name_ru": name_ru,
            "full_name_ru": name_ru,
            "kind": ServiceKind.CITY,
            "code": None,
            "okrug": None,
            "district": None,
            "classifier_org_id": None,
            "status_policy": StatusPolicy.DEFAULT,
            "display": True,
            "deprecated": False,
            "phone": None,
            **extra,
        }
    )


_LEGACY_NAMES_RU: Mapping[str, str] = {
    "FIRE_RESCUE": "Пожарно-спасательная служба",
    "POLICE": "Полиция",
    "AMBULANCE": "Скорая медицинская помощь",
    "GAS_SERVICE": "Газовая служба",
    "UTILITY_EMERGENCY": "Аварийная коммунальная служба",
    "EDDS": "РЕДДС",
}

LEGACY_REFERENCE = ReferenceCatalog(
    packs=(
        ReferencePack(pack_id=DEFAULT_PACK_ID, card_schema="v1", services="v1", classifier=None),
    ),
    service_catalogs=(
        ServiceCatalog(
            catalog_id="v1",
            services=tuple(
                _legacy_entry(
                    service_id,
                    _LEGACY_NAMES_RU[service_id],
                    **(
                        {"status_policy": StatusPolicy.NO_REFUSAL}
                        if service_id == "AMBULANCE"
                        else {"deprecated": True}
                        if service_id == "UTILITY_EMERGENCY"
                        else {}
                    ),
                )
                for service_id in LEGACY_SERVICE_IDS
            ),
        ),
    ),
)
"""The `legacy-r1` pack with only the six legacy services and no file shas — the default of pure
callers (`validate_scenario_version` without a `reference`). Production always passes the real
catalog the composition root loaded."""

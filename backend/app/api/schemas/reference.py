"""The reference API's models (`openapi.yaml` tag `reference`; HLD 70 §70.6, D18).

Property names are `openapi.yaml`'s `ReferenceManifest`, `ServiceCatalogEntry`,
`ClassifierRowSummary` and `ClassifierRow`, literally; each is built from the domain's
`app.domain.routing` types by an explicit mapping function (D2).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.operator import CardFieldSpecSchema, card_field_spec_schema
from app.application.reference.card_schemas import CardSchemaView
from app.domain.dds.personas import Persona
from app.domain.enums import ServiceId
from app.domain.routing.catalog import ServiceCatalogEntry
from app.domain.routing.classifier import ClassifierRow

__all__ = [
    "CardSchemaViewSchema",
    "ClassifierRowSchema",
    "ClassifierRowSummarySchema",
    "ClassifierSearchPageSchema",
    "ReferenceManifestSchema",
    "ServiceCatalogEntrySchema",
    "card_schema_view_schema",
    "classifier_row_schema",
    "classifier_row_summary_schema",
    "manifest_schema",
    "service_catalog_entry_schema",
]


class ReferencePackPartsSchema(ApiModel):
    """One `ReferenceManifest.packs` value."""

    card_schema: str
    services: str
    classifier: str | None
    personas: str | None = None
    """I3 E6c (HLD 80 §80.4.1): the ДДС phone's persona set; absent for a pack without one."""


class ReferenceSourceSchema(ApiModel):
    """One `ReferenceManifest.sources` value."""

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool: str


class ReferenceManifestSchema(ApiModel):
    """`openapi.yaml`'s `ReferenceManifest` — `reference/manifest.json`."""

    manifest_version: Literal[1]
    packs: dict[str, ReferencePackPartsSchema]
    files: dict[str, str]
    sources: dict[str, ReferenceSourceSchema]


class ServiceCatalogEntrySchema(ApiModel):
    """`openapi.yaml`'s `ServiceCatalogEntry`."""

    id: ServiceId
    name_ru: str
    full_name_ru: str
    kind: Literal["CITY", "DISTRICT", "PREFECTURE", "DEPARTMENT"]
    code: str | None
    okrug: str | None
    district: str | None
    classifier_org_id: str | None
    classifier_org_ids: list[str] = Field(default_factory=list)
    status_policy: Literal["DEFAULT", "NO_REFUSAL"]
    display: bool
    deprecated: bool
    phone: str | None


class CardSchemaViewSchema(ApiModel):
    """`openapi.yaml`'s `CardSchemaView` — a card schema as field specs (HLD 70 §70.5)."""

    schema_id: str
    sha256: str
    field_specs: list[CardFieldSpecSchema]


def card_schema_view_schema(view: CardSchemaView) -> CardSchemaViewSchema:
    return CardSchemaViewSchema(
        schema_id=view.schema_id,
        sha256=view.sha256,
        field_specs=[card_field_spec_schema(spec) for spec in view.field_specs],
    )


class ClassifierRowSummarySchema(ApiModel):
    """`openapi.yaml`'s `ClassifierRowSummary` — a search hit, routing omitted."""

    code: str
    group_no: int
    group_ru: str
    features: list[str] = Field(max_length=3)
    final_type_ru: str
    main_service: str | None


class RoutingCellSchema(ApiModel):
    """One `ClassifierRow.routing` cell."""

    when: dict[str, bool]
    value: str | None


class ClassifierRowSchema(ClassifierRowSummarySchema):
    """`openapi.yaml`'s `ClassifierRow` — the summary plus its routing cells."""

    extra_features: list[str]
    ekp35_ru: str | None
    routing: dict[str, list[RoutingCellSchema]]


class ClassifierSearchPageSchema(ApiModel):
    """`searchClassifier`'s inline `{items, total}`."""

    items: list[ClassifierRowSummarySchema]
    total: int = Field(ge=0)


def manifest_schema(manifest: Mapping[str, Any]) -> ReferenceManifestSchema:
    return ReferenceManifestSchema.model_validate(dict(manifest))


def service_catalog_entry_schema(entry: ServiceCatalogEntry) -> ServiceCatalogEntrySchema:
    return ServiceCatalogEntrySchema.model_validate(entry.model_dump(mode="json"))


def classifier_row_summary_schema(row: ClassifierRow) -> ClassifierRowSummarySchema:
    return ClassifierRowSummarySchema(
        code=row.code,
        group_no=row.group_no,
        group_ru=row.group_ru,
        features=list(row.features),
        final_type_ru=row.final_type_ru,
        main_service=row.main_service,
    )


def classifier_row_schema(row: ClassifierRow) -> ClassifierRowSchema:
    return ClassifierRowSchema(
        code=row.code,
        group_no=row.group_no,
        group_ru=row.group_ru,
        features=list(row.features),
        final_type_ru=row.final_type_ru,
        main_service=row.main_service,
        extra_features=list(row.extra_features),
        ekp35_ru=row.ekp35_ru,
        routing={
            org_id: [RoutingCellSchema(when=dict(cell.when), value=cell.value) for cell in cells]
            for org_id, cells in row.routing.items()
        },
    )


class PersonaAppliesSchema(ApiModel):
    """`PersonaView.applies` — most specific wins, `code` over `kind` (HLD 80 §80.4.1)."""

    code: str | None
    kind: str | None


class PersonaViewSchema(ApiModel):
    """`openapi.yaml`'s `PersonaView` (I3 E6c): a persona of the ДДС phone. Voices are logical ids;
    no TTS internals are exposed."""

    persona_id: str
    applies: PersonaAppliesSchema
    title_ru: str
    gender: Literal["MALE", "FEMALE"]
    voice_id: str


def persona_view_schema(persona: Persona) -> PersonaViewSchema:
    """`Persona` -> the wire model."""
    return PersonaViewSchema(
        persona_id=persona.id,
        applies=PersonaAppliesSchema(code=persona.applies.code, kind=persona.applies.kind),
        title_ru=persona.title_ru,
        gender=persona.gender.value,
        voice_id=persona.voice_id,
    )

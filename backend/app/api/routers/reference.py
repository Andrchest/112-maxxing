"""`reference` router — the reference pack reads of `openapi.yaml` (HLD 70 §70.6.1-§70.6.3, D18).

Four reads any authenticated caller may make: the manifest, a pack's service catalog, and the
classifier search and row. They read the `ReferenceCatalog` the composition root loaded; nothing
is written and no event is emitted (`x-emits: []`). `pack` defaults to the newest pack of the
manifest; an unknown pack, a pack without a classifier and an unknown code are `404 NOT_FOUND`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.api.schemas.reference import (
    CardSchemaViewSchema,
    ClassifierRowSchema,
    ClassifierSearchPageSchema,
    ReferenceManifestSchema,
    ServiceCatalogEntrySchema,
    card_schema_view_schema,
    classifier_row_schema,
    classifier_row_summary_schema,
    manifest_schema,
    service_catalog_entry_schema,
)
from app.api.security import CurrentUserDep

router = APIRouter(prefix="/api/v1/reference", tags=["reference"])

PackQuery = Annotated[str | None, Query(description="Reference pack id; default: the newest.")]


@router.get(
    "/manifest",
    operation_id="getReferenceManifest",
    summary="The reference packs and the sha256 of every reference file.",
    response_model=ReferenceManifestSchema,
    status_code=200,
)
async def get_reference_manifest(
    container: ContainerDep, _user: CurrentUserDep
) -> ReferenceManifestSchema:
    """`reference/manifest.json`, verbatim."""
    return manifest_schema(container.get_reference_manifest()())


@router.get(
    "/services",
    operation_id="listReferenceServices",
    summary="The service catalog («СЛУЖБЫ 112») of a pack.",
    response_model=list[ServiceCatalogEntrySchema],
    status_code=200,
)
async def list_reference_services(
    container: ContainerDep,
    _user: CurrentUserDep,
    pack: PackQuery = None,
    include_hidden: bool = False,
    q: str | None = None,
) -> list[ServiceCatalogEntrySchema]:
    """Catalog entries in catalog order; hidden and deprecated ones only with `include_hidden`."""
    entries = container.list_reference_services()(pack=pack, include_hidden=include_hidden, q=q)
    return [service_catalog_entry_schema(entry) for entry in entries]


@router.get(
    "/classifier",
    operation_id="searchClassifier",
    summary="Search the incident classifier (v_046_24) of a pack — the «Класс.:» picker.",
    response_model=ClassifierSearchPageSchema,
    status_code=200,
)
async def search_classifier(
    container: ContainerDep,
    _user: CurrentUserDep,
    pack: PackQuery = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ClassifierSearchPageSchema:
    """Matching rows, routing omitted (fetch one row for it)."""
    rows, total = container.search_classifier()(pack=pack, q=q, limit=limit, offset=offset)
    return ClassifierSearchPageSchema(
        items=[classifier_row_summary_schema(row) for row in rows], total=total
    )


@router.get(
    "/classifier/{code}",
    operation_id="getClassifierRow",
    summary="One classifier row with its routing cells (instructor tooling, resolver fixtures).",
    response_model=ClassifierRowSchema,
    status_code=200,
)
async def get_classifier_row(
    code: str, container: ContainerDep, _user: CurrentUserDep, pack: PackQuery = None
) -> ClassifierRowSchema:
    """The row with its routing cells, aligned with the pack's classifier column map."""
    return classifier_row_schema(container.get_classifier_row()(code, pack=pack))


@router.get(
    "/card-schema/{schema_id}",
    operation_id="getCardSchema",
    summary=(
        "A card schema (`v1` / `v2`) as field specs — the same `CardFieldSpec` the card views "
        "carry."
    ),
    response_model=CardSchemaViewSchema,
    status_code=200,
)
async def get_card_schema(
    schema_id: str, container: ContainerDep, _user: CurrentUserDep
) -> CardSchemaViewSchema:
    """The schema's field specs in schema order (HLD 70 §70.5); `404` for an unknown id."""
    return card_schema_view_schema(container.get_card_schema()(schema_id))

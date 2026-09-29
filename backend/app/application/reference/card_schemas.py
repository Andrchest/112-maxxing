"""Card schemas as the application serves them (HLD `70-i3-alignment.md` §70.5, D17; I3 E3a).

One home for three things every card reader needs, kept out of `app.application.operator` so the
DDS projection (`app.application.handoff.work_item`) can use them without importing the operator
package:

* `CardOptionView` / `CardFieldSpecView` / `field_spec_views` — `openapi.yaml`'s `CardOption` and
  `CardFieldSpec`, built once per schema: "the UI renders the form from this, never from a
  hard-coded list";
* `session_pack_id` / `pack_card_schema` — the pack `SESSION_CREATED.reference_pack` recorded
  (`legacy-r1` for a log that predates it) and its card schema, from the log and the reference
  catalog alone (the DDS side never holds a `ScenarioVersion`, INV 3);
* `GetCardSchema` — `getCardSchema`, a card schema by id.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.application.ports.reference import ReferencePort
from app.application.reference.queries import ReferenceNotFoundError
from app.domain.enums import ValueType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.card_schema import CardControl, CardSchema, condition_document
from app.domain.layers.operator_card import CARD_SCHEMA_V1
from app.domain.routing.catalog import DEFAULT_PACK_ID, ReferenceCatalog

__all__ = [
    "CardFieldSpecView",
    "CardOptionView",
    "CardSchemaView",
    "GetCardSchema",
    "field_spec_views",
    "pack_card_schema",
    "session_pack_id",
]


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CardOptionView(_View):
    """`openapi.yaml`'s `CardOption` — one option of a data-driven field (HLD 70 §70.5.2)."""

    code: str
    label_ru: str
    classifier_features: tuple[str, ...] | None
    routing: str | None


class CardFieldSpecView(_View):
    """`openapi.yaml`'s `CardFieldSpec` — one field of a card schema (§10.6, and the I3 additive
    properties of HLD 70 §70.5.2)."""

    field_path: str
    value_type: ValueType
    enum_name: str | None
    label_ru: str
    scoring_relevant: bool
    required_for_handoff: bool
    group: str | None = None
    order: int = 0
    control: CardControl = CardControl.TEXT
    options: tuple[CardOptionView, ...] | None = None
    visible_when: dict[str, Any] | None = None
    required_in_block: bool = False
    routing_relevant: bool = False
    max_length: int | None = None


class CardSchemaView(_View):
    """`openapi.yaml`'s `CardSchemaView`."""

    schema_id: str
    sha256: str
    field_specs: tuple[CardFieldSpecView, ...]


_FIELD_SPEC_VIEWS: dict[tuple[str, str | None], tuple[CardFieldSpecView, ...]] = {}
"""Each schema's views, built once, keyed by `(schema_id, sha256)` — a loaded schema never
changes."""


def field_spec_views(schema: CardSchema) -> tuple[CardFieldSpecView, ...]:
    """The `CardFieldSpec` views of `schema`, in schema order."""
    key = (schema.schema_id, schema.sha256)
    cached = _FIELD_SPEC_VIEWS.get(key)
    if cached is None:
        cached = tuple(
            CardFieldSpecView(
                field_path=spec.field_path,
                value_type=spec.value_type,
                enum_name=spec.enum_name,
                label_ru=spec.label_ru,
                scoring_relevant=spec.scoring_relevant,
                required_for_handoff=spec.required_for_handoff,
                group=spec.group,
                order=spec.order,
                control=spec.control,
                options=(
                    None
                    if spec.options is None
                    else tuple(
                        CardOptionView(
                            code=option.code,
                            label_ru=option.label_ru,
                            classifier_features=option.classifier_features,
                            routing=option.routing,
                        )
                        for option in spec.options
                    )
                ),
                visible_when=(
                    None if spec.visible_when is None else condition_document(spec.visible_when)
                ),
                required_in_block=spec.required_in_block,
                routing_relevant=spec.routing_relevant,
                max_length=spec.max_length,
            )
            for spec in schema.fields
        )
        _FIELD_SPEC_VIEWS[key] = cached
    return cached


def session_pack_id(log: Sequence[SessionEvent]) -> str:
    """`SESSION_CREATED.reference_pack.pack_id`, or `legacy-r1` for a log that predates it."""
    for event in log:
        if event.event_type is not EventType.SESSION_CREATED:
            continue
        record = event.payload.get("reference_pack")
        if isinstance(record, Mapping) and isinstance(record.get("pack_id"), str):
            return str(record["pack_id"])
        break
    return DEFAULT_PACK_ID


def pack_card_schema(reference: ReferenceCatalog, log: Sequence[SessionEvent]) -> CardSchema:
    """The card schema of the session's recorded pack; `v1` when the log predates the record or
    the catalog no longer has the pack."""
    return reference.card_schema(session_pack_id(log)) or CARD_SCHEMA_V1


class GetCardSchema:
    """`getCardSchema` — a card schema (`v1` / `v2`) as field specs (`404` when unknown)."""

    def __init__(self, reference: ReferencePort) -> None:
        self._reference = reference

    def __call__(self, schema_id: str) -> CardSchemaView:
        catalog = self._reference.catalog()
        schema = catalog.card_schema_by_id(schema_id)
        if schema is None:
            raise ReferenceNotFoundError(f"no card schema {schema_id!r}")
        return CardSchemaView(
            schema_id=schema.schema_id,
            sha256=schema.sha256 or catalog.file_sha256(f"card-schema/{schema.schema_id}.yaml"),
            field_specs=field_spec_views(schema),
        )

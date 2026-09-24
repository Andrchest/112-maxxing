"""`OperatorCard` — what the trainee actually entered (HLD `10-domain-model.md` §10.3, §10.6, D3,
SPEC §3, §9).

Written by trainee commands only. This module must not import any other layer module
(`world_truth`, `caller_belief`, `handoff`) — see the structural test in
`backend/tests/unit/domain/layers/`.

`ActorRef` has its one home in `common/actors.py` (consolidation ruling R1 of this task's brief;
this module previously defined its own copy, now removed — see the report).

`CardFieldSpec.required_for_handoff` is `True` for exactly the eight fields §10.6 names under the
field table (ruling R4): `incident.type`, `address.locality`, `address.street`, `address.house`,
`caller.phone`, `description.text`, `flags.threat_to_life`, `recipients.services`. It remains
advisory only — a missing field never blocks a handoff (§10.6) — and nothing in this task's slice
reads it yet; a later task wires it into the handoff-preparation UI/report.

`set_field` returns the HLD's literal 3-tuple `(card, revision | None, DomainEvent | None)`
(ruling R3): a successful mutation returns a `CARD_FIELD_CHANGED` `DomainEvent` alongside the
`CardRevision`; a no-op write (same value) returns `(card, None, None)`, per §10.6's "no revision,
no event".

**The card schema (I3 E3a, HLD 70 §70.5, D17).** `CardFieldSpec` and the schema parser live in
`card_schema.py`; this module keeps `CARD_FIELDS` as the v1 alias (`CARD_SCHEMA_V1.fields`) and
`set_field`, which validates against the session's schema (`schema=`, v1 when omitted).

Every `label_ru` below is trainee-facing Russian text (SPEC language rule); `# ruff: noqa: RUF001`
below suppresses ruff's ambiguous-unicode-character check for this file, which otherwise flags
ordinary Cyrillic letters that merely resemble Latin ones.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.common.actors import ActorRef
from app.domain.common.errors import CardFieldError
from app.domain.common.ids import CardId, CardRevisionId, IncidentId
from app.domain.common.values import FactValue
from app.domain.enums import ActorType, ValueType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.layers.card_schema import (
    CardFieldSpec,
    CardSchema,
    build_card_schema,
    check_value,
)

__all__ = [
    "CARD_FIELDS",
    "CARD_SCHEMA_V1",
    "CardFieldSpec",
    "CardRevision",
    "CardSchema",
    "OperatorCard",
    "set_field",
]


class OperatorCard(BaseModel):
    """The trainee-entered incident card (§10.3, §10.6). `revision_counter` is 0 before the first
    mutation.
    """

    model_config = ConfigDict(extra="forbid")

    card_id: CardId
    incident_id: IncidentId
    values: dict[str, FactValue]
    revision_counter: int = 0


class CardRevision(BaseModel):
    """One `set_field` mutation (§10.6, SPEC §9): previous value, new value, field path, actor,
    timestamp offset.
    """

    model_config = ConfigDict(extra="forbid")

    revision_id: CardRevisionId
    card_id: CardId
    revision_no: int
    field_path: str
    previous_value: FactValue
    new_value: FactValue
    actor: ActorRef
    at_offset_ms: int


_V1_FIELDS: tuple[CardFieldSpec, ...] = (
    CardFieldSpec(
        field_path="incident.type",
        value_type=ValueType.ENUM,
        enum_name="IncidentType",
        label_ru="Тип происшествия",
        scoring_relevant=True,
        required_for_handoff=True,
    ),
    CardFieldSpec(
        field_path="incident.subtype",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Уточнение типа",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="incident.reported_at_offset_ms",
        value_type=ValueType.INTEGER,
        enum_name=None,
        label_ru="Время приёма вызова",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="address.locality",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Населённый пункт",
        scoring_relevant=True,
        required_for_handoff=True,
    ),
    CardFieldSpec(
        field_path="address.street",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Улица",
        scoring_relevant=True,
        required_for_handoff=True,
    ),
    CardFieldSpec(
        field_path="address.house",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Дом",
        scoring_relevant=True,
        required_for_handoff=True,
    ),
    CardFieldSpec(
        field_path="address.building",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Корпус / строение",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="address.entrance",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Подъезд",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="address.floor",
        value_type=ValueType.INTEGER,
        enum_name=None,
        label_ru="Этаж",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="address.apartment",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Квартира",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="address.landmark",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Ориентир",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="address.comment",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Примечание к адресу",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="caller.full_name",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="ФИО заявителя",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="caller.phone",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Телефон заявителя",
        scoring_relevant=True,
        required_for_handoff=True,
    ),
    CardFieldSpec(
        field_path="caller.relationship",
        value_type=ValueType.ENUM,
        enum_name="CallerRelationship",
        label_ru="Отношение к происшествию",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="caller.callback_possible",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Возможен обратный вызов",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="description.text",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Описание происшествия",
        scoring_relevant=True,
        required_for_handoff=True,
    ),
    CardFieldSpec(
        field_path="people.total_affected",
        value_type=ValueType.INTEGER,
        enum_name=None,
        label_ru="Всего людей в опасности",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="people.victims_count",
        value_type=ValueType.INTEGER,
        enum_name=None,
        label_ru="Число пострадавших",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="people.trapped_count",
        value_type=ValueType.INTEGER,
        enum_name=None,
        label_ru="Число заблокированных",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="people.children_present",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Есть дети",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="people.evacuation_needed",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Требуется эвакуация",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="people.notes",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Примечания по людям",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="hazards.open_fire",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Открытое горение",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="hazards.smoke",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Задымление",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="hazards.gas_leak",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Утечка газа",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="hazards.electrical",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Электроопасность",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="hazards.chemical",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Химическая опасность",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="hazards.collapse_risk",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Угроза обрушения",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="hazards.other",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Иная опасность",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="flags.threat_to_life",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Угроза жизни",
        scoring_relevant=True,
        required_for_handoff=True,
    ),
    CardFieldSpec(
        field_path="flags.mass_event",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Массовое происшествие",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="flags.repeat_call",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Повторное обращение",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="flags.requires_escalation",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Требует эскалации",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="flags.false_call",
        value_type=ValueType.BOOLEAN,
        enum_name=None,
        label_ru="Ложный вызов",
        scoring_relevant=True,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="notes.free_text",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Дополнительная информация",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
    CardFieldSpec(
        field_path="recipients.services",
        value_type=ValueType.STRING_LIST,
        enum_name=None,
        label_ru="Службы-получатели",
        scoring_relevant=True,
        required_for_handoff=True,
    ),
    CardFieldSpec(
        field_path="recipients.comment",
        value_type=ValueType.STRING,
        enum_name=None,
        label_ru="Комментарий для служб",
        scoring_relevant=False,
        required_for_handoff=False,
    ),
)

CARD_SCHEMA_V1: CardSchema = build_card_schema("v1", _V1_FIELDS)
"""Card schema `v1` — the card every existing session uses (HLD 70 §70.5.1). It is code-backed:
`reference/card-schema/v1.yaml` is generated from it (`backend/tools/import_card_schema.py`) and a
test proves the file equals it field by field."""

CARD_FIELDS: tuple[CardFieldSpec, ...] = CARD_SCHEMA_V1.fields
"""The v1 alias (HLD 70 §70.5.1): `CARD_SCHEMA_V1.fields`, each with its neutral `order`."""

_ALLOWED_MUTATION_ACTORS = frozenset({ActorType.TRAINEE, ActorType.INSTRUCTOR})


def set_field(
    card: OperatorCard,
    field_path: str,
    new_value: FactValue,
    actor: ActorRef,
    at_offset_ms: int,
    revision_id: CardRevisionId,
    *,
    schema: CardSchema | None = None,
) -> tuple[OperatorCard, CardRevision | None, DomainEvent | None]:
    """Set one card field (§10.6, SPEC §9).

    Pure: returns a new `OperatorCard`, the `CardRevision` recording `{revision_id, field_path,
    previous_value, new_value, actor, at_offset_ms}`, and one `CARD_FIELD_CHANGED` `DomainEvent`
    carrying the same values plus `card_id` and `value_type` (ruling R3; self-sufficient for
    scoring per D5). `schema` is the session's card schema (HLD 70 §70.5.1; `CARD_SCHEMA_V1` when
    omitted). Raises `CardFieldError` when `field_path` is not in the schema, the value does not
    match the spec's `value_type`, or `actor.actor_type` is not `TRAINEE`/`INSTRUCTOR` (SPEC §9,
    §42 test 4 — ASR never calls this), and its subclass `CardOptionUnknownError` when the value
    is not one of the field's option codes. A field hidden by `visible_when` is still accepted —
    visibility is advisory (§70.5.2). Setting a field to its current value is a no-op:
    the card is returned unchanged and the revision/event slots are both `None` (§10.6).
    """
    card_schema = schema if schema is not None else CARD_SCHEMA_V1
    spec = card_schema.spec(field_path)
    if spec is None:
        raise CardFieldError(f"unknown card field path: {field_path!r}")
    if actor.actor_type not in _ALLOWED_MUTATION_ACTORS:
        raise CardFieldError(
            f"actor_type {actor.actor_type!r} may not mutate the operator card "
            f"(only TRAINEE/INSTRUCTOR may)"
        )
    check_value(spec, new_value)

    previous_value = card.values.get(field_path)
    if previous_value == new_value:
        return card, None, None

    new_values = dict(card.values)
    new_values[field_path] = new_value
    new_revision_no = card.revision_counter + 1
    new_card = card.model_copy(update={"values": new_values, "revision_counter": new_revision_no})
    revision = CardRevision(
        revision_id=revision_id,
        card_id=card.card_id,
        revision_no=new_revision_no,
        field_path=field_path,
        previous_value=previous_value,
        new_value=new_value,
        actor=actor,
        at_offset_ms=at_offset_ms,
    )
    event = DomainEvent(
        event_type=EventType.CARD_FIELD_CHANGED,
        actor=actor,
        monotonic_offset_ms=at_offset_ms,
        correlation_id=None,
        payload={
            "card_id": card.card_id,
            "revision_id": revision_id,
            "revision_no": new_revision_no,
            "field_path": field_path,
            "previous_value": previous_value,
            "new_value": new_value,
            "value_type": spec.value_type,
            "actor_user_id": actor.actor_id,
            "at_offset_ms": at_offset_ms,
        },
    )
    return new_card, revision, event

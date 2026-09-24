"""`operator` schemas (`openapi.yaml`, D8, D12).

One pydantic model per schema the `operator` tag's operations answer with, plus the mapping
functions from `app.application.operator.views`. Property names are copied **literally** from the
contract; `backend/tests/api/test_contract.py` compares each response model's field-name set with
the YAML's `properties` keys, so a rename on either side fails the suite.

Nothing here is a domain type (D2). The application views are already wire-shaped — that is what
`app.application.operator.views` is for — so these mappings are almost mechanical; they exist
anyway, because a response model that *was* an application view would make the two impossible to
change independently, and because `openapi.yaml` is the thing this layer must match.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.operator.set_card_field import SetCardFieldResult
from app.application.operator.views import (
    ActionView,
    CallStateView,
    CardFieldSpecView,
    CardRevisionView,
    OperatorCardView,
    OperatorStageView,
    ServiceSelectionView,
)
from app.domain.enums import Operator112StageState, ServiceId, SessionState, ValueType
from app.domain.layers.card_schema import CardControl

__all__ = [
    "ActionDescriptorSchema",
    "ActorRefSchema",
    "CallStateViewSchema",
    "CardFieldSpecSchema",
    "CardOptionSchema",
    "CardRevisionPageSchema",
    "CardRevisionViewSchema",
    "EndCallRequestSchema",
    "OperatorCardViewSchema",
    "OperatorStageViewSchema",
    "ServiceSelectionRequestSchema",
    "ServiceSelectionViewSchema",
    "SetCardFieldRequestSchema",
    "SetCardFieldResponseSchema",
    "call_state_schema",
    "card_field_spec_schema",
    "card_revision_schema",
    "operator_card_schema",
    "operator_stage_schema",
    "service_selection_schema",
    "set_card_field_response_schema",
]

FactValueSchema = str | int | float | bool | list[str] | None
"""`openapi.yaml`'s `FactValue` — the value domain shared by the three information layers."""


class ActorRefSchema(ApiModel):
    """`openapi.yaml`'s `ActorRef`."""

    actor_type: str
    actor_id: UUID | None = None


class CardOptionSchema(ApiModel):
    """`openapi.yaml`'s `CardOption` — one option of a data-driven field (HLD 70 §70.5.2)."""

    code: str
    label_ru: str
    classifier_features: list[str] | None = None
    routing: Literal["none"] | None = None


class CardFieldSpecSchema(ApiModel):
    """`openapi.yaml`'s `CardFieldSpec` — one field of the session's card schema (§10.6; the I3
    additive properties of HLD 70 §70.5.2)."""

    field_path: str
    value_type: ValueType
    enum_name: str | None = None
    label_ru: str
    scoring_relevant: bool
    required_for_handoff: bool
    group: str | None = None
    order: int = Field(default=0, ge=0)
    control: CardControl = CardControl.TEXT
    options: list[CardOptionSchema] | None = None
    visible_when: dict[str, Any] | None = None
    required_in_block: bool = False
    routing_relevant: bool = False


class OperatorCardViewSchema(ApiModel):
    """`openapi.yaml`'s `OperatorCardView` (SPEC §9)."""

    card_id: UUID
    incident_id: UUID
    values: dict[str, FactValueSchema]
    revision_counter: int = Field(ge=0)
    field_specs: list[CardFieldSpecSchema]
    card_schema: str = "v1"


class CardRevisionViewSchema(ApiModel):
    """`openapi.yaml`'s `CardRevisionView` — one `incident_card_revisions` row."""

    revision_id: UUID
    card_id: UUID
    revision_no: int = Field(ge=1)
    field_path: str
    previous_value: FactValueSchema = None
    new_value: FactValueSchema = None
    actor: ActorRefSchema
    at_offset_ms: int


class CardRevisionPageSchema(ApiModel):
    """`openapi.yaml`'s `CardRevisionPage`."""

    items: list[CardRevisionViewSchema]
    total: int = Field(ge=0)


class SetCardFieldRequestSchema(ApiModel):
    """`openapi.yaml`'s `SetCardFieldRequest`."""

    field_path: str
    new_value: FactValueSchema = None
    client_command_id: UUID | None = None


class SetCardFieldResponseSchema(ApiModel):
    """`openapi.yaml`'s `SetCardFieldResponse`; `revision` is `null` for a no-op write."""

    card: OperatorCardViewSchema
    revision: CardRevisionViewSchema | None = None


class ServiceSelectionRequestSchema(ApiModel):
    """`openapi.yaml`'s `ServiceSelectionRequest`."""

    service_type: ServiceId


class ServiceSelectionViewSchema(ApiModel):
    """`openapi.yaml`'s `ServiceSelectionView`."""

    card_id: UUID
    selected_services: list[ServiceId]
    available_services: list[ServiceId]
    card: OperatorCardViewSchema


class EndCallRequestSchema(ApiModel):
    """`openapi.yaml`'s `EndCallRequest`."""

    reason: Literal["OPERATOR_HANGUP", "CALLER_HANGUP", "TRANSPORT_LOST"]


class CallStateViewSchema(ApiModel):
    """`openapi.yaml`'s `CallStateView` — the phone widget's state (D12)."""

    call_id: UUID | None = None
    room_name: str | None = None
    phase: Literal["NO_CALL", "RINGING", "CONNECTED", "ENDED"]
    caller_display_ru: str | None = None
    started_at_offset_ms: int | None = None
    answered_at_offset_ms: int | None = None
    ended_at_offset_ms: int | None = None
    duration_ms: int | None = None
    caller_speaking: bool


class ActionDescriptorSchema(ApiModel):
    """`openapi.yaml`'s `ActionDescriptor` — the frontend enables buttons from this (D12)."""

    action_id: str
    label_ru: str
    permission: str
    trigger: str | None = None


class OperatorStageViewSchema(ApiModel):
    """`openapi.yaml`'s `OperatorStageView` — what every Operator 112 command returns (D8)."""

    role_stage_id: UUID
    stage_state: Operator112StageState
    available_actions: list[ActionDescriptorSchema]
    card: OperatorCardViewSchema
    call_state: CallStateViewSchema
    session_state: SessionState
    last_seq_no: int = Field(ge=0)


# ---------------------------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------------------------


def operator_card_schema(view: OperatorCardView) -> OperatorCardViewSchema:
    """`OperatorCardView` -> `OperatorCardView` (the wire one)."""
    return OperatorCardViewSchema(
        card_id=view.card_id,
        incident_id=view.incident_id,
        values=dict(view.values),
        revision_counter=view.revision_counter,
        field_specs=[card_field_spec_schema(spec) for spec in view.field_specs],
        card_schema=view.card_schema,
    )


def card_field_spec_schema(spec: CardFieldSpecView) -> CardFieldSpecSchema:
    """`CardFieldSpecView` -> `CardFieldSpec` (the wire one)."""
    return CardFieldSpecSchema.model_validate(spec.model_dump(mode="json"))


def card_revision_schema(view: CardRevisionView) -> CardRevisionViewSchema:
    """`CardRevisionView` -> `CardRevisionView` (the wire one)."""
    return CardRevisionViewSchema(
        revision_id=view.revision_id,
        card_id=view.card_id,
        revision_no=view.revision_no,
        field_path=view.field_path,
        previous_value=view.previous_value,
        new_value=view.new_value,
        actor=ActorRefSchema(actor_type=view.actor.actor_type, actor_id=view.actor.actor_id),
        at_offset_ms=view.at_offset_ms,
    )


def call_state_schema(view: CallStateView) -> CallStateViewSchema:
    """`CallStateView` -> `CallStateView` (the wire one)."""
    return CallStateViewSchema(
        call_id=view.call_id,
        room_name=view.room_name,
        phase=view.phase.value,
        caller_display_ru=view.caller_display_ru,
        started_at_offset_ms=view.started_at_offset_ms,
        answered_at_offset_ms=view.answered_at_offset_ms,
        ended_at_offset_ms=view.ended_at_offset_ms,
        duration_ms=view.duration_ms,
        caller_speaking=view.caller_speaking,
    )


def action_schemas(actions: tuple[ActionView, ...]) -> list[ActionDescriptorSchema]:
    """`available_actions` -> the wire descriptors."""
    return [
        ActionDescriptorSchema(
            action_id=action.action_id,
            label_ru=action.label_ru,
            permission=action.permission,
            trigger=action.trigger,
        )
        for action in actions
    ]


def operator_stage_schema(view: OperatorStageView) -> OperatorStageViewSchema:
    """`OperatorStageView` -> `OperatorStageView` (the wire one)."""
    return OperatorStageViewSchema(
        role_stage_id=view.role_stage_id,
        stage_state=view.stage_state,
        available_actions=action_schemas(view.available_actions),
        card=operator_card_schema(view.card),
        call_state=call_state_schema(view.call_state),
        session_state=view.session_state,
        last_seq_no=view.last_seq_no,
    )


def service_selection_schema(view: ServiceSelectionView) -> ServiceSelectionViewSchema:
    """`ServiceSelectionView` -> `ServiceSelectionView` (the wire one)."""
    return ServiceSelectionViewSchema(
        card_id=view.card_id,
        selected_services=list(view.selected_services),
        available_services=list(view.available_services),
        card=operator_card_schema(view.card),
    )


def set_card_field_response_schema(result: SetCardFieldResult) -> SetCardFieldResponseSchema:
    """`SetCardFieldResult` -> `SetCardFieldResponse`."""
    return SetCardFieldResponseSchema(
        card=operator_card_schema(result.card),
        revision=(None if result.revision is None else card_revision_schema(result.revision)),
    )

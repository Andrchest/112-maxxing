"""`dds-calls` schemas — the ДДС phone line (I3 E6b, `openapi.yaml` `StartDdsCallRequest`,
`StartDdsCallResponse`, `DdsCallView`; HLD `80-telephony.md` §80.3).

Property names literal, one explicit mapping per model (D2). `StartDdsCallResponse.voice` is a
credential when present: it is serialised into this one response body and never logged (SPEC §41).
"""

from __future__ import annotations

from uuid import UUID

from app.api.schemas.common import ApiModel
from app.api.schemas.operator import ActionDescriptorSchema, action_schemas
from app.api.schemas.voice import VoiceTokenResponseSchema, voice_token_response_schema
from app.application.dds.dds_call_views import DdsCallView
from app.application.dds.start_dds_call import StartedDdsCall
from app.domain.dds.call import (
    CallAnsweredBy,
    CallEndpoint,
    DdsCallDirection,
    DdsCallEndReason,
    DdsCallKind,
    DdsCallState,
)

__all__ = [
    "DdsCallViewSchema",
    "StartDdsCallRequestSchema",
    "StartDdsCallResponseSchema",
    "dds_call_schema",
    "started_dds_call_schema",
]


class StartDdsCallRequestSchema(ApiModel):
    """`openapi.yaml`'s `StartDdsCallRequest`."""

    kind: DdsCallKind
    assignment_id: UUID | None = None


class DdsCallViewSchema(ApiModel):
    """`openapi.yaml`'s `DdsCallView` — one `dds_calls` row plus the caller's legal actions."""

    call_id: UUID
    session_id: UUID
    kind: DdsCallKind
    direction: DdsCallDirection
    assignment_id: UUID | None
    service_type: str | None
    dialed: str
    endpoint: CallEndpoint
    room_name: str
    persona_id: str | None
    persona_title_ru: str | None
    actor_user_id: UUID | None
    state: DdsCallState
    answered_by: CallAnsweredBy | None
    started_at_offset_ms: int
    answered_at_offset_ms: int | None
    ended_at_offset_ms: int | None
    end_reason: DdsCallEndReason | None
    available_actions: list[ActionDescriptorSchema]


class StartDdsCallResponseSchema(ApiModel):
    """`openapi.yaml`'s `StartDdsCallResponse`: the call and, for the browser endpoint, its
    token."""

    call: DdsCallViewSchema
    voice: VoiceTokenResponseSchema | None


def dds_call_schema(view: DdsCallView) -> DdsCallViewSchema:
    """`DdsCallView` -> the wire model, field by field."""
    return DdsCallViewSchema(
        call_id=view.call_id,
        session_id=view.session_id,
        kind=view.kind,
        direction=view.direction,
        assignment_id=view.assignment_id,
        service_type=view.service_type,
        dialed=view.dialed,
        endpoint=view.endpoint,
        room_name=view.room_name,
        persona_id=view.persona_id,
        persona_title_ru=view.persona_title_ru,
        actor_user_id=view.actor_user_id,
        state=view.state,
        answered_by=view.answered_by,
        started_at_offset_ms=view.started_at_offset_ms,
        answered_at_offset_ms=view.answered_at_offset_ms,
        ended_at_offset_ms=view.ended_at_offset_ms,
        end_reason=view.end_reason,
        available_actions=action_schemas(view.available_actions),
    )


def started_dds_call_schema(started: StartedDdsCall) -> StartDdsCallResponseSchema:
    """`StartedDdsCall` -> the wire model."""
    return StartDdsCallResponseSchema(
        call=dds_call_schema(started.call),
        voice=None if started.voice is None else voice_token_response_schema(started.voice),
    )

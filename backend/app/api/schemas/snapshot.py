"""`snapshot` schema (`openapi.yaml`'s `SessionSnapshot`, SPEC §39, §42 test 13; D3, D8).

One model and one mapping function. `card` and `work_item` are both nullable here because the
contract makes them so, and because a stage can legitimately have neither: the card is one the
DDS role may never see (D3), and a DDS stage that has not been handed off to yet has no work item
to show. The decision is made by `app.application.sessions.get_snapshot`, never here — a schema
that chose which panel to fill would be a second place where D3 could be got wrong.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.handoff import DdsWorkItemSchema, dds_work_item_schema
from app.api.schemas.operator import (
    ActionDescriptorSchema,
    CallStateViewSchema,
    OperatorCardViewSchema,
    action_schemas,
    call_state_schema,
    operator_card_schema,
)
from app.api.schemas.sessions import SessionDetailSchema, StageStateSchema, session_detail_schema
from app.application.sessions.get_snapshot import SessionSnapshotView
from app.domain.enums import RoleType

__all__ = ["SessionSnapshotSchema", "session_snapshot_schema"]


class SessionSnapshotSchema(ApiModel):
    """`openapi.yaml`'s `SessionSnapshot`, property names literal."""

    session: SessionDetailSchema
    my_role_type: RoleType | None = None
    active_role_stage_id: UUID | None = None
    active_role_type: RoleType | None = None
    stage_state: StageStateSchema | None = None
    available_actions: list[ActionDescriptorSchema]
    card: OperatorCardViewSchema | None = None
    work_item: DdsWorkItemSchema | None = None
    call_state: CallStateViewSchema
    last_seq_no: int = Field(ge=0)
    visible_sources: list[str]
    server_time_utc: datetime


def session_snapshot_schema(view: SessionSnapshotView) -> SessionSnapshotSchema:
    """`SessionSnapshotView` -> `SessionSnapshot`."""
    return SessionSnapshotSchema(
        session=session_detail_schema(view.session),
        my_role_type=view.my_role_type,
        active_role_stage_id=view.active_role_stage_id,
        active_role_type=view.active_role_type,
        stage_state=view.stage_state,
        available_actions=action_schemas(view.available_actions),
        card=None if view.card is None else operator_card_schema(view.card),
        work_item=None if view.work_item is None else dds_work_item_schema(view.work_item),
        call_state=call_state_schema(view.call_state),
        last_seq_no=view.last_seq_no,
        visible_sources=list(view.visible_sources),
        server_time_utc=view.server_time_utc,
    )

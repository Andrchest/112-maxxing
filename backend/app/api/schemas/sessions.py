"""`sessions` schemas (`openapi.yaml`, D8).

`SessionDetailSchema` is "the materialized session header every command returns (D8)": E7-B's
command endpoints answer with this same model, built by the same `session_detail_schema` mapping
function, so a command response and a `getSession` response can never disagree about a field.

Nothing here is a domain type. `RoleStageViewSchema.state` is typed as the union of the two
implemented stage-state enums, which is exactly what `openapi.yaml`'s `StageState` `oneOf` is, and
the mapping functions below are the only bridge between the aggregate and the wire.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.ports.session_repository import StoredSessionListing
from app.application.sessions.queries import ParticipantView, SessionDetailView
from app.domain.enums import (
    DDSStageState,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.session.session import RoleStage
from app.domain.session.variants import (
    CardSource,
    DdsBrigadeCall,
    DdsCardCheck,
    DdsMode,
    PartialVariants,
    SessionVariants,
)

__all__ = [
    "AbortSessionRequestSchema",
    "ParticipantAssignmentSchema",
    "RoleStageViewSchema",
    "SessionCreateRequestSchema",
    "SessionDetailSchema",
    "SessionListItemSchema",
    "SessionParticipantViewSchema",
    "SessionVariantsSchema",
    "VariantsRequestSchema",
    "session_detail_schema",
    "session_list_item_schema",
]

StageStateSchema = Operator112StageState | DDSStageState
"""`openapi.yaml`'s `StageState`: an `Operator112StageState` **or** a `DDSStageState` member."""


class ParticipantAssignmentSchema(ApiModel):
    """`openapi.yaml`'s `ParticipantAssignment` — a user bound to a simulation role.

    `assigned_role_type: null` is "permitted only where `SessionPolicy.assignment_rule` is
    `ALL_STAGES_ONE_PARTICIPANT`", and that rule is checked by the `validate` guard in the domain,
    not here (§10.10).
    """

    user_id: UUID
    assigned_role_type: RoleType | None = None


class VariantsRequestSchema(ApiModel):
    """`openapi.yaml`'s `VariantsRequest` — every switch optional (HLD 70 §70.2.2)."""

    card_source: CardSource | None = None
    dds_mode: DdsMode | None = None
    dds_card_check: DdsCardCheck | None = None
    dds_brigade_call: DdsBrigadeCall | None = None

    def to_domain(self) -> PartialVariants:
        return PartialVariants(
            card_source=self.card_source,
            dds_mode=self.dds_mode,
            dds_card_check=self.dds_card_check,
            dds_brigade_call=self.dds_brigade_call,
        )


class SessionVariantsSchema(ApiModel):
    """`openapi.yaml`'s `SessionVariants` — the resolved, recorded switches."""

    card_source: CardSource
    dds_mode: DdsMode
    dds_card_check: DdsCardCheck
    dds_brigade_call: DdsBrigadeCall

    @classmethod
    def of(cls, variants: SessionVariants) -> SessionVariantsSchema:
        return cls(
            card_source=variants.card_source,
            dds_mode=variants.dds_mode,
            dds_card_check=variants.dds_card_check,
            dds_brigade_call=variants.dds_brigade_call,
        )


class SessionCreateRequestSchema(ApiModel):
    """`openapi.yaml`'s `SessionCreateRequest`."""

    scenario_version_id: UUID
    session_mode: SessionMode
    participants: list[ParticipantAssignmentSchema] = Field(min_length=1)
    session_seed: str | None = None
    time_scale: float = Field(default=1.0, ge=0.1, le=10)
    variants: VariantsRequestSchema | None = None


class AbortSessionRequestSchema(ApiModel):
    """`openapi.yaml`'s `AbortSessionRequest`."""

    reason: str = Field(min_length=1, max_length=500)


class SessionParticipantViewSchema(ApiModel):
    """`openapi.yaml`'s `SessionParticipantView`."""

    user_id: UUID
    username: str
    display_name_ru: str
    assigned_role_type: RoleType | None = None
    joined_at: datetime


class RoleStageViewSchema(ApiModel):
    """`openapi.yaml`'s `RoleStageView`."""

    role_stage_id: UUID
    role_type: RoleType
    order_index: int = Field(ge=0)
    state: StageStateSchema
    participant_user_id: UUID | None = None
    started_at_offset_ms: int | None = None
    completed_at_offset_ms: int | None = None


class SessionListItemSchema(ApiModel):
    """`openapi.yaml`'s `SessionListItem`."""

    id: UUID
    scenario_slug: str
    scenario_version: int = Field(ge=1)
    session_mode: SessionMode
    state: SessionState
    created_at: datetime
    created_by_user_id: UUID
    my_role_type: RoleType | None = None


class SessionDetailSchema(ApiModel):
    """`openapi.yaml`'s `SessionDetail` — what every session command returns (D8)."""

    id: UUID
    scenario_version_id: UUID
    scenario_slug: str
    scenario_version: int = Field(ge=1)
    session_mode: SessionMode
    state: SessionState
    session_seed: str
    time_scale: float
    incident_id: UUID
    role_chain: list[RoleType]
    stages: list[RoleStageViewSchema]
    active_role_stage_id: UUID | None = None
    participants: list[SessionParticipantViewSchema]
    created_by_user_id: UUID
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    abort_reason: str | None = None
    monotonic_offset_ms: int = Field(ge=0)
    last_seq_no: int = Field(ge=0)
    transition_pause_seconds: int = Field(ge=0)
    transition_continue_available_at_offset_ms: int | None = None
    variants: SessionVariantsSchema
    scenario_role_chain: list[RoleType]
    lesson_id: UUID | None
    lesson_position: int | None = Field(ge=1)


class SessionScopeQuery(ApiModel):
    """The `scope` query parameter of `listSessions`."""

    scope: Literal["MINE", "ALL"] = "MINE"


def _stage_schema(stage: RoleStage) -> RoleStageViewSchema:
    return RoleStageViewSchema(
        role_stage_id=UUID(str(stage.role_stage_id)),
        role_type=stage.role_type,
        order_index=stage.order_index,
        state=stage.state,
        participant_user_id=(
            None if stage.participant_user_id is None else UUID(str(stage.participant_user_id))
        ),
        started_at_offset_ms=stage.started_at_offset_ms,
        completed_at_offset_ms=stage.completed_at_offset_ms,
    )


def _participant_schema(view: ParticipantView) -> SessionParticipantViewSchema:
    return SessionParticipantViewSchema(
        user_id=UUID(str(view.user_id)),
        username=view.username,
        display_name_ru=view.display_name_ru,
        assigned_role_type=view.assigned_role_type,
        joined_at=view.joined_at,
    )


def session_list_item_schema(listing: StoredSessionListing) -> SessionListItemSchema:
    """`StoredSessionListing` → `SessionListItem`."""
    return SessionListItemSchema(
        id=UUID(str(listing.session_id)),
        scenario_slug=listing.scenario_slug,
        scenario_version=listing.scenario_version,
        session_mode=listing.session_mode,
        state=listing.state,
        created_at=listing.created_at,
        created_by_user_id=UUID(str(listing.created_by_user_id)),
        my_role_type=listing.my_role_type,
    )


def session_detail_schema(view: SessionDetailView) -> SessionDetailSchema:
    """`SessionDetailView` → `SessionDetail` — the one mapping every command's response uses."""
    session = view.session
    active = view.active_role_stage_id
    return SessionDetailSchema(
        id=UUID(str(session.id)),
        scenario_version_id=UUID(str(session.scenario_version_id)),
        scenario_slug=view.scenario_slug,
        scenario_version=view.scenario_version,
        session_mode=session.session_mode,
        state=session.state,
        session_seed=session.session_seed,
        time_scale=session.time_scale,
        incident_id=UUID(str(session.incident.incident_id)),
        role_chain=list(view.role_chain),
        stages=[_stage_schema(stage) for stage in session.stages],
        active_role_stage_id=None if active is None else UUID(str(active)),
        participants=[_participant_schema(participant) for participant in view.participants],
        created_by_user_id=UUID(str(session.created_by_user_id)),
        created_at=view.created_at,
        started_at=session.started_at,
        completed_at=session.completed_at,
        abort_reason=session.abort_reason,
        monotonic_offset_ms=view.monotonic_offset_ms,
        last_seq_no=view.last_seq_no,
        transition_pause_seconds=view.transition_pause_seconds,
        transition_continue_available_at_offset_ms=(
            view.transition_continue_available_at_offset_ms
        ),
        variants=SessionVariantsSchema.of(session.variants),
        scenario_role_chain=list(view.scenario_role_chain),
        lesson_id=None if session.lesson_id is None else UUID(str(session.lesson_id)),
        lesson_position=session.lesson_position,
    )

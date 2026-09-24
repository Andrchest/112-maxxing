"""`DdsCallView` and the two reads of the ДДС phone line (I3 E6b, HLD `80-telephony.md` §80.3,
`openapi.yaml` `listDdsCalls` / `getDdsCall`).

The phone widget never folds the per-turn events into a call: it reads `GET …/dds-calls` — the
`dds_calls` read model (migration `0014`) — and the three `DDS_CALL_*` events refresh it. That is
what restores a live call after a refresh (INV 13), together with `createVoiceToken {call_id}`.

Who may read: the work item's rule (`may_read_work_item`) — every ДДС participant and the
instructor; an OPERATOR_112-only participant is `403` (a ДДС call is not the 112 side's business,
HLD 80 §80.6.2).

`persona_title_ru` is «Заявитель» for a claimant call (the scenario's `CallerProfile` is the
persona, and its identity is a fact the trainee may still have to ask for, so the widget shows the
role, never the name); the service-head and 112 personas resolve in E6c / E6d.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.get_work_item import may_read_work_item
from app.application.operator.views import ActionView, action_views
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId
from app.domain.dds.call import (
    CallAnsweredBy,
    CallEndpoint,
    DdsCall,
    DdsCallDirection,
    DdsCallEndReason,
    DdsCallKind,
    DdsCallState,
)
from app.domain.roles.dds import dds_call_actions
from app.domain.session.session import SimulationSession

__all__ = [
    "CLAIMANT_TITLE_RU",
    "DdsCallNotFoundError",
    "DdsCallView",
    "GetDdsCall",
    "ListDdsCalls",
    "dds_call_view",
]

CLAIMANT_TITLE_RU = "Заявитель"
"""The widget's party label for a claimant call — the role, never the caller's identity (D3)."""


class DdsCallNotFoundError(DomainError):
    """No ДДС call with this id in this session (`404`)."""

    code = "NOT_FOUND"

    def __init__(self, call_id: UUID) -> None:
        self.call_id = call_id
        super().__init__(f"no ДДС call {call_id} in this session")


class DdsCallView(BaseModel):
    """`openapi.yaml`'s `DdsCallView` — one `dds_calls` row plus the caller's legal actions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

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
    available_actions: tuple[ActionView, ...]


def dds_call_view(call: DdsCall, user: AuthenticatedUser | None = None) -> DdsCallView:
    """One call's view. `available_actions` are the line owner's: `hang_up` while live — empty
    for anyone else (the instructor observes, SPEC §7)."""
    mine = (
        user is not None and call.actor_user_id is not None and call.actor_user_id == user.user_id
    )
    return DdsCallView(
        call_id=call.call_id,
        session_id=UUID(str(call.session_id)),
        kind=call.kind,
        direction=call.direction,
        assignment_id=None if call.assignment_id is None else UUID(str(call.assignment_id)),
        service_type=call.service_type,
        dialed=call.dialed,
        endpoint=call.endpoint,
        room_name=call.room,
        persona_id=call.persona_id,
        persona_title_ru=CLAIMANT_TITLE_RU if call.kind is DdsCallKind.CLAIMANT else None,
        actor_user_id=None if call.actor_user_id is None else UUID(str(call.actor_user_id)),
        state=call.state,
        answered_by=call.answered_by,
        started_at_offset_ms=call.started_at_offset_ms,
        answered_at_offset_ms=call.answered_at_offset_ms,
        ended_at_offset_ms=call.ended_at_offset_ms,
        end_reason=call.end_reason,
        available_actions=action_views(dds_call_actions(call)) if mine else (),
    )


def _check_may_read(session: SimulationSession, user: AuthenticatedUser) -> None:
    if not may_read_work_item(session, user):
        raise ForbiddenForRoleError(
            f"the caller may not read the ДДС calls of session {session.id}"
        )


class ListDdsCalls:
    """`listDdsCalls` — every ДДС call of the session, newest first (INV 13)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> list[DdsCallView]:
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            _check_may_read(session, user)
            calls = await uow.dds_calls.list_for_session(session_id)
            await uow.commit()
        return [dds_call_view(call, user) for call in calls]


class GetDdsCall:
    """`getDdsCall` — one ДДС call."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, session_id: SessionId, call_id: UUID, user: AuthenticatedUser
    ) -> DdsCallView:
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            _check_may_read(session, user)
            call = await uow.dds_calls.get(session_id, call_id)
            await uow.commit()
        if call is None:
            raise DdsCallNotFoundError(call_id)
        return dds_call_view(call, user)

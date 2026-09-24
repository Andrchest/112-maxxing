"""`listDdsLegs` — every leg of the card with its status history (I3 E5a, HLD 70 §70.4.3).

A *read*: no action to check, nothing to append. Every notified service sees every other
service's statuses (broadcast — owner decision, REQ-5294/5295), so the list is the same for every
ДДС participant and for the instructor; only `is_mine` and the dropdown (`available_actions`) are
the caller's own. Who may read it is `getDdsWorkItem`'s rule (`may_read_work_item`), because the
legs are the work item's.

`assemble_leg_views` is shared with the two leg commands, which answer with the leg they moved: the
legs, their history (`dds_service_status_history`), the pack's service names and policies and the
display names of the people in the history — and nothing else (INV 3).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import (
    WorkItemNotFoundError,
    dds_stage_of,
    is_memo,
    load_legs,
)
from app.application.dds.get_work_item import may_read_work_item
from app.application.dds.views import DdsLegView, leg_view
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.user_repository import UserRole
from app.application.reference.card_schemas import session_pack_id
from app.application.reference.queries import reference_catalog
from app.application.sessions.authorisation import can_observe
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import SessionId, UserId
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.policy import policy_of
from app.domain.dds.responders import plays_leg
from app.domain.enums import DDSStageState, RoleType, SessionState
from app.domain.roles.registry import ROLE_MODULES
from app.domain.routing.catalog import ServiceCatalog
from app.domain.routing.dial_plan import phone_extension
from app.domain.session.session import RoleStage, SimulationSession

__all__ = ["ListDdsLegs", "assemble_leg_views", "is_dds_participant"]

_SET_SERVICE_STATUS = "set_service_status"


def is_dds_participant(session: SimulationSession, stage: RoleStage, user_id: UserId) -> bool:
    """The user plays the DDS stage — its bound participant, or any ДДС participant."""
    return stage.participant_user_id == user_id or session.plays_dds(user_id)


def _is_mine(
    session: SimulationSession, stage: RoleStage, leg: DDSAssignment, user: AuthenticatedUser
) -> bool:
    """May `user` set statuses on `leg` (`DdsLegView.is_mine`, §70.4.5)?"""
    if not is_memo(session) or user.user_role is not UserRole.TRAINEE:
        return False
    if not is_dds_participant(session, stage, user.user_id):
        return False
    return plays_leg(leg, user.user_id)


def _may_act(session: SimulationSession, stage: RoleStage) -> bool:
    """The stage offers `set_service_status` right now (the memo action table)."""
    current = session.current_stage
    if session.state is not SessionState.ACTIVE or current is None:
        return False
    if current.role_stage_id != stage.role_stage_id:
        return False
    state = stage.state
    assert isinstance(state, DDSStageState)
    module = ROLE_MODULES[RoleType.DDS]
    return any(
        action.action_id == _SET_SERVICE_STATUS
        for action in module.available_actions(state, variants=session.variants)
    )


async def assemble_leg_views(
    uow: UnitOfWork,
    session: SimulationSession,
    stage: RoleStage,
    legs: Sequence[DDSAssignment],
    catalog: ServiceCatalog | None,
    viewer: AuthenticatedUser,
) -> tuple[DdsLegView, ...]:
    """Every leg in `legs` order, with its history, as `viewer` sees it."""
    history = await uow.dds_assignments.list_history([leg.assignment_id for leg in legs])
    people = {entry.actor_user_id for entry in history if entry.actor_user_id is not None}
    users = await uow.users.get_many([UserId(person) for person in people]) if people else []
    display_names = {UUID(str(user.user_id)): user.display_name_ru for user in users}
    may_act = _may_act(session, stage)
    live_calls = {
        UUID(str(call.assignment_id)): call.call_id
        for call in await uow.dds_calls.list_live(session.id)
        if call.assignment_id is not None
    }
    views: list[DdsLegView] = []
    for leg in legs:
        entry = None if catalog is None else catalog.get(leg.service_type)
        views.append(
            leg_view(
                leg,
                service_name_ru=leg.service_type if entry is None else entry.name_ru,
                policy=policy_of(catalog, leg.service_type),
                history=history,
                display_names=display_names,
                is_mine=_is_mine(session, stage, leg, viewer),
                may_act=may_act,
                live_call_id=live_calls.get(UUID(str(leg.assignment_id))),
                phone_extension=(
                    None if catalog is None else phone_extension(catalog, leg.service_type)
                ),
            )
        )
    return tuple(views)


class ListDdsLegs:
    """`listDdsLegs` (`openapi.yaml`): the legs in notification-list order, with history."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, reference: ReferencePort | None = None
    ) -> None:
        self._unit_of_work = unit_of_work
        self._reference = reference

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser
    ) -> tuple[DdsLegView, ...]:
        """Every leg of the session's DDS stage, if this caller may read the work item."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not can_observe(session, user) or not may_read_work_item(session, user):
                raise ForbiddenForRoleError(
                    f"the caller may not read the DDS legs of session {session_id}"
                )
            stage = dds_stage_of(session) or _any_dds_stage(session)
            if stage is None:
                raise WorkItemNotFoundError(session_id)
            legs, _snapshot = await load_legs(uow, session_id, stage)
            log = await uow.events.read(session_id)
            catalog = reference_catalog(self._reference).services(session_pack_id(log))
            views = await assemble_leg_views(uow, session, stage, legs, catalog, user)
            await uow.commit()
        return views


def _any_dds_stage(session: SimulationSession) -> RoleStage | None:
    """The session's DDS stage even when it is not (or no longer) the active one."""
    for stage in session.stages:
        if stage.role_type is RoleType.DDS:
            return stage
    return None

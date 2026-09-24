"""`listDdsResources` — the resource board (`openapi.yaml`, SPEC §11; D7).

A *read*, authorised the same way `getDdsWorkItem` is, but through `VisibilitySource.
RESOURCE_BOARD` — `DDSModule` lists it and `Operator112Module` does not, so the 112 trainee is
refused and the instructor is not.

"Scenario-defined resources only; the ETA numbers are `EtaProfile` values read verbatim by
`ScenarioDefinedEta` (D7) — no external maps API is involved (SPEC §11)." Nothing in this module
computes a travel time: `EmergencyResourceView.eta` is the five numbers the scenario author wrote,
copied out of `emergency_resources.eta`.

The two optional query filters of the contract, `service_type` and `status`, are applied here. The
board is small (eleven units in the demo), so filtering in Python over one indexed read keeps the
repository free of a query shape only this endpoint wants.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import dds_stage_of
from app.application.dds.views import EmergencyResourceView, resource_views
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.authorisation import can_observe
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.application.simulation.sim_time import sim_now_ms
from app.domain.common.ids import SessionId
from app.domain.enums import DDSStageState, ResourceStatus, RoleType, ServiceId
from app.domain.roles.registry import ROLE_MODULES
from app.domain.roles.visibility import VisibilitySource
from app.domain.session.session import SimulationSession

__all__ = ["ListDdsResources", "may_read_board"]


def may_read_board(session: SimulationSession, user: AuthenticatedUser) -> bool:
    """May this caller read the resource board (`VIEW_RESOURCE_BOARD`, D3)?"""
    if user.is_instructor_or_admin:
        return True
    for stage in session.stages:
        if stage.participant_user_id != user.user_id:
            continue
        module = ROLE_MODULES.get(stage.role_type)
        if module is not None and module.visibility_policy.may_read(
            VisibilitySource.RESOURCE_BOARD
        ):
            return True
    return False


class ListDdsResources:
    """`listDdsResources` (`openapi.yaml`): the scenario's units, with their statuses and ETAs."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        service_type: ServiceId | None = None,
        status: Sequence[ResourceStatus] | None = None,
    ) -> tuple[tuple[EmergencyResourceView, ...], int]:
        """The filtered board and its size, in `callsign` order."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not can_observe(session, user) or not may_read_board(session, user):
                raise ForbiddenForRoleError(
                    f"the caller may not read the resource board of session {session_id}"
                )
            board = await uow.resources.list_for_session(session_id)
            await uow.commit()

        wanted = None if not status else set(status)
        filtered = [
            stored
            for stored in board
            if (service_type is None or stored.resource.service_type == service_type)
            and (wanted is None or stored.resource.current_status in wanted)
        ]
        views = resource_views(
            filtered,
            stage_state=_stage_state(session),
            now_ms=sim_now_ms(session, self._clock.now()),
        )
        return views, len(views)


def _stage_state(session: SimulationSession) -> DDSStageState:
    """The DDS stage's state, which `EmergencyResourceView.selectable` is relative to.

    A session whose active stage is not the DDS one (the instructor watching the 112 half, say)
    reports `RECEIVED`, in which nothing is selectable — the honest answer, since no unit can be
    selected before the work item is acknowledged.
    """
    stage = dds_stage_of(session)
    if stage is not None and isinstance(stage.state, DDSStageState):
        return stage.state
    for other in session.stages:
        if other.role_type is RoleType.DDS and isinstance(other.state, DDSStageState):
            return other.state
    return DDSStageState.RECEIVED

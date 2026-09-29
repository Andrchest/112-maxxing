"""`getDdsWorkItem` — the incoming work item (`openapi.yaml`, SPEC §10, §11; D3).

A *read*, so it does not go through `DdsCommandGate`: there is no action to check, no transition
to fire and nothing to append. What it shares with the commands is D8's first gate and D3's
visibility rule, both of which live here so that `getDdsWorkItem` and `getSessionSnapshot` cannot
disagree about who may see the work item:

* the `DDS` participant of the session sees it — `VisibilitySource.HANDOFF_SNAPSHOT` is in
  `DDSModule`'s `DataVisibilityPolicy.sources`;
* an `INSTRUCTOR` or `ADMIN` sees it — SPEC §7 gives the instructor observation without
  participation;
* everyone else is `403 FORBIDDEN_FOR_ROLE`, as is a session the caller may not observe at all.

The contract's promise is structural and this module is where it has to hold: *"assembled from
`handoff_snapshots` and `dds_assignments` alone. The application service behind it is constructed
without a world-truth repository, so the data is unreachable rather than merely unrequested."*
`GetDdsWorkItem` takes a Unit of Work factory and nothing else, and reads exactly three things
through it — the legs, their snapshot and the board the resource lists are projected from.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import (
    WorkItemNotFoundError,
    dds_stage_of,
    load_legs,
    work_item_of,
)
from app.application.dds.leg_for import project_legs
from app.application.handoff.work_item import DdsWorkItemView, for_viewer, with_dds_marks
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.reference.card_schemas import pack_card_schema
from app.application.reference.queries import reference_catalog
from app.application.sessions.authorisation import can_observe
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import SessionId
from app.domain.enums import RoleType
from app.domain.roles.registry import ROLE_MODULES
from app.domain.roles.visibility import VisibilitySource
from app.domain.session.session import RoleStage, SimulationSession

__all__ = ["GetDdsWorkItem", "may_read_work_item"]


def may_read_work_item(session: SimulationSession, user: AuthenticatedUser) -> bool:
    """May this caller read the DDS work item of this session (D3, §10.9)?

    Decided by the acting role's `DataVisibilityPolicy`, never by a role name written here — the
    mirror image of `app.application.operator.get_card.may_read_card`.
    """
    if user.is_instructor_or_admin:
        return True
    for stage in session.stages:
        # Several ДДС trainees share the one DDS stage (HLD 70 §70.4.5, I3 E5b): every ДДС
        # participant reads the work item and every leg (broadcast), not only the primary one.
        dds_participant = stage.role_type is RoleType.DDS and session.plays_dds(user.user_id)
        if stage.participant_user_id != user.user_id and not dds_participant:
            continue
        module = ROLE_MODULES.get(stage.role_type)
        if module is not None and module.visibility_policy.may_read(
            VisibilitySource.HANDOFF_SNAPSHOT
        ):
            return True
    return False


class GetDdsWorkItem:
    """`getDdsWorkItem` (`openapi.yaml`): the work item, from the snapshot and the legs alone."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, reference: ReferencePort | None = None
    ) -> None:
        self._unit_of_work = unit_of_work
        self._reference = reference

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> DdsWorkItemView:
        """The stage-wide work-item projection (R3), if this caller may read it."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not can_observe(session, user) or not may_read_work_item(session, user):
                raise ForbiddenForRoleError(
                    f"the caller may not read the DDS work item of session {session_id}"
                )
            stage = dds_stage_of(session) or _any_dds_stage(session)
            if stage is None:
                raise WorkItemNotFoundError(session_id)
            legs, snapshot = await load_legs(uow, session_id, stage)
            board = await uow.resources.list_for_session(session_id)
            dispatched = await uow.resources.dispatch_history(session_id)
            log = await uow.events.read(session_id)
            await uow.commit()
        schema = pack_card_schema(reference_catalog(self._reference), log)
        view = with_dds_marks(
            work_item_of(snapshot, project_legs(legs, board, dispatched), schema), log
        )
        return for_viewer(view, legs, None if user.is_instructor_or_admin else user.user_id)


def _any_dds_stage(session: SimulationSession) -> RoleStage | None:
    """The session's DDS stage even when it is not the active one.

    The work item survives the stage: after `close` the DDS stage is terminal and
    `current_stage` moves past it, but the instructor and the trainee still ask what was received
    and what was sent. A `role_chain` with no DDS entry has nothing to answer with, which is the
    `404` above.
    """
    for stage in session.stages:
        if stage.role_type is RoleType.DDS:
            return stage
    return None

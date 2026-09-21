"""`listNotifications` — the notifications addressed to the caller's role (`openapi.yaml`).

*"Read from the `notifications` table, materialized from `NOTIFICATION_CREATED` /
`NOTIFICATION_ACKNOWLEDGED`. Filtered to `audience_role == the caller's role`; the operator
console calls the same endpoint."* Both halves matter:

* **one endpoint, two roles.** `ACKNOWLEDGE_NOTIFICATION` is held by `Operator112Module` *and*
  `DDSModule`, and `VisibilitySource.NOTIFICATIONS` is in both policies, so the 112 trainee reads
  their own notifications here too. The role the filter uses is the caller's *simulation* role —
  the role of the stage they are the participant of — not a parameter they may choose;
* **the filter is in SQL.** A role never loads another role's rows, so a bug in a view cannot leak
  one (D3). An `INSTRUCTOR` sees both audiences, which is the console's job (SPEC §7).

A notification is materialized by the tick that emitted the event
(`app.application.simulation.tick_session`), in the same transaction, so this read can never see a
log the table has not caught up with.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.views import NotificationView, notification_view
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.authorisation import can_observe
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import SessionId
from app.domain.enums import RoleType
from app.domain.roles.registry import ROLE_MODULES
from app.domain.roles.visibility import VisibilitySource
from app.domain.session.session import SimulationSession

__all__ = ["ListNotifications", "audience_roles_for"]

_TRAINEE_AUDIENCES: tuple[RoleType, ...] = (RoleType.OPERATOR_112, RoleType.DDS, RoleType.EDDS)
"""The `notifications.audience_role` CHECK values (§20.5), in report order."""


def audience_roles_for(session: SimulationSession, user: AuthenticatedUser) -> tuple[RoleType, ...]:
    """Which audiences this caller may read; empty means `403`.

    A trainee reads the audience of the role they play, and only if that role's
    `DataVisibilityPolicy` lists `NOTIFICATIONS`. An instructor or admin reads every audience.
    """
    if user.is_instructor_or_admin:
        return _TRAINEE_AUDIENCES
    roles: list[RoleType] = []
    for stage in session.stages:
        if stage.participant_user_id != user.user_id:
            continue
        module = ROLE_MODULES.get(stage.role_type)
        if (
            module is not None
            and module.visibility_policy.may_read(VisibilitySource.NOTIFICATIONS)
            and stage.role_type not in roles
        ):
            roles.append(stage.role_type)
    return tuple(roles)


class ListNotifications:
    """`listNotifications` (`openapi.yaml`): this role's notifications, newest first."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        unacknowledged_only: bool = False,
    ) -> tuple[tuple[NotificationView, ...], int]:
        """The caller's notifications and their count."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            audiences = audience_roles_for(session, user) if can_observe(session, user) else ()
            if not audiences:
                raise ForbiddenForRoleError(
                    f"the caller may not read the notifications of session {session_id}"
                )
            rows = [
                row
                for audience in audiences
                for row in await uow.notifications.list_for_incident(
                    session.incident.incident_id,
                    audience_role=audience,
                    unacknowledged_only=unacknowledged_only,
                )
            ]
            await uow.commit()

        rows.sort(
            key=lambda row: (row.created_at_offset_ms, str(row.notification_id)), reverse=True
        )
        views = tuple(notification_view(row) for row in rows)
        return views, len(views)

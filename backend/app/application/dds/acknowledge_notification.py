"""`acknowledgeNotification` — tick one notification off (`openapi.yaml`, §10.13, §40.4).

Permission `ACKNOWLEDGE_NOTIFICATION`, *"held by both `Operator112Module` and `DDSModule`"*, so
this command does **not** go through `DdsCommandGate`: that gate demands the caller be the DDS
participant of the *active* stage, and the 112 trainee acknowledging their own notification is
neither. It runs its own Unit of Work with the same row lock and the same first gate, and asks the
caller's role module for the permission instead of asking §10.9's `available_actions` for an
action id — acknowledging a notification is not a stage action and appears in no state's list.

`x-emits` is `[NOTIFICATION_ACKNOWLEDGED]`. The payload carries the additive `audience_role` key
(E9, manager ruling 4) copied from the row, which is what lets §40.4 row 38 push the
acknowledgement to that audience alone rather than to both trainee roles
(`app.application.realtime.redaction`).

A second acknowledgement is `409`: the `UPDATE` carries `WHERE acknowledged_at_offset_ms IS NULL`
and reports whether it hit a row, so two concurrent calls produce exactly one event.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.views import NotificationView, notification_view
from app.application.operator.command_context import SessionNotActiveError
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.user_repository import UserRole
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.application.timebase import session_offset_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId, UserId
from app.domain.enums import ActorType, RoleType, SessionState
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.roles.module import Permission
from app.domain.roles.registry import ROLE_MODULES
from app.domain.session.session import SimulationSession

__all__ = [
    "ACTION_ID",
    "AcknowledgeNotification",
    "NotificationAlreadyAcknowledgedError",
    "NotificationNotFoundError",
]

ACTION_ID = "acknowledge_notification"
"""`openapi.yaml`'s `x-action` for `acknowledgeNotification`."""


class NotificationNotFoundError(DomainError):
    """No such notification in this session's incident (`404`)."""

    code = "NOT_FOUND"

    def __init__(self, notification_id: UUID) -> None:
        self.notification_id = notification_id
        super().__init__(f"notification {notification_id} does not belong to this session")


class NotificationAlreadyAcknowledgedError(DomainError):
    """The notification was already acknowledged (`409`)."""

    code = "INVALID_TRANSITION"

    def __init__(self, notification_id: UUID) -> None:
        self.notification_id = notification_id
        super().__init__(f"notification {notification_id} is already acknowledged")


class AcknowledgeNotification:
    """`acknowledgeNotification` (`openapi.yaml`): one row stamped, one event appended."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, notification_id: UUID
    ) -> NotificationView:
        """Acknowledge it, if the caller's role is the one it was addressed to."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if session.state is not SessionState.ACTIVE:
                raise SessionNotActiveError(session_id, session.state)

            participant = resolve_participant(session, user)
            if user.user_role is not UserRole.TRAINEE:
                raise ForbiddenForRoleError(
                    "a trainee stage command may only be issued by a TRAINEE account"
                )
            role = _acting_role(session, UserId(participant.user_id))
            if role is None or not _may_acknowledge(role):
                raise ForbiddenForRoleError(
                    f"the caller may not acknowledge notifications of session {session_id}"
                )

            stored = await uow.notifications.get(notification_id)
            if stored is None or stored.incident_id != session.incident.incident_id:
                raise NotificationNotFoundError(notification_id)
            if stored.audience_role is not role:
                raise ForbiddenForRoleError(
                    f"notification {notification_id} is addressed to "
                    f"{stored.audience_role.value}, not to the caller's role"
                )

            now_ms = session_offset_ms(self._clock.now(), session.started_at)
            stamped = await uow.notifications.acknowledge(
                notification_id, at_offset_ms=now_ms, user_id=UserId(user.user_id)
            )
            if not stamped:
                raise NotificationAlreadyAcknowledgedError(notification_id)

            await uow.events.append(
                session_id,
                [
                    DomainEvent(
                        event_type=EventType.NOTIFICATION_ACKNOWLEDGED,
                        actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=user.user_id),
                        monotonic_offset_ms=now_ms,
                        payload={
                            "notification_id": notification_id,
                            "audience_role": stored.audience_role.value,
                            "at_offset_ms": now_ms,
                            "latency_ms": max(0, now_ms - stored.created_at_offset_ms),
                            "actor_user_id": UUID(str(user.user_id)),
                        },
                    )
                ],
            )
            await uow.commit()

        return notification_view(
            stored.model_copy(
                update={
                    "acknowledged_at_offset_ms": now_ms,
                    "acknowledged_by_user_id": UserId(user.user_id),
                }
            )
        )


def _acting_role(session: SimulationSession, user_id: UserId) -> RoleType | None:
    """The simulation role this participant plays (§10.10), or `None` for an unbound one."""
    for participant in session.participants:
        if participant.user_id == user_id and participant.assigned_role_type is not None:
            return participant.assigned_role_type
    stage = session.current_stage or session.active_stage
    if stage is not None and stage.participant_user_id == user_id:
        return stage.role_type
    return None


def _may_acknowledge(role: RoleType) -> bool:
    """Does this role's `RoleModule` hold `ACKNOWLEDGE_NOTIFICATION` (§10.9)?"""
    module = ROLE_MODULES.get(role)
    return module is not None and Permission.ACKNOWLEDGE_NOTIFICATION in module.permissions

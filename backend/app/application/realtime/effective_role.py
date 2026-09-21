"""§40.1's "effective realtime role" of a connection, and how it is re-derived (D3, D6, D8).

§40.1, verbatim:

> The connection's **effective realtime role** is fixed at connect time and never renegotiated:
> - a participant assigned to a stage → that stage's `RoleType` (`OPERATOR_112` or `DDS`);
> - a participant of a `FULL_CYCLE_SINGLE_TRAINEE` session assigned to every stage → the
>   `RoleType` of the **currently active** `RoleStage`, re-derived on every push, so that the role
>   transition changes what the same socket may see without a reconnect;
> - user role `INSTRUCTOR` or `ADMIN` → `INSTRUCTOR` (the instructor console, not a `RoleType`).

The second bullet is the interesting one: "re-derived on every push" must not mean "one query per
event". It does not have to: the events that move the active stage — `ROLE_STAGE_STARTED`,
`ROLE_STAGE_COMPLETED`, `ROLE_TRANSITION_STARTED`, `ROLE_TRANSITION_COMPLETED` — are themselves
pushed to both trainee roles (§40.4 rows 3, 24, 31, 32), so the stream already has every fact it
needs. `fold_role` folds them; `Connection` seeds the fold from the aggregate at connect time and
carries the result. A socket therefore costs one read of the session, ever.

`ROLE_TRANSITION_STARTED` deliberately does **not** move the role: during the transition pause the
trainee is still looking at the stage they just finished, and `ROLE_TRANSITION_COMPLETED` (or the
next `ROLE_STAGE_STARTED`, whichever the runner emits first) is what hands the socket the next
role's visibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.sessions.authorisation import resolve_participant
from app.domain.enums import RoleType, SessionMode
from app.domain.events.types import EventType
from app.domain.session.policy import SessionPolicy
from app.domain.session.session import SimulationSession

__all__ = [
    "INSTRUCTOR",
    "Connection",
    "EffectiveRole",
    "connection_of",
    "fold_role",
]

INSTRUCTOR: Literal["INSTRUCTOR"] = "INSTRUCTOR"
"""The instructor console. Deliberately not a `RoleType`: §40.1 calls it "not a `RoleType`", and
`EDDS` — the one `RoleType` with `implemented = False` — must never be confused with it."""

EffectiveRole = RoleType | Literal["INSTRUCTOR"]
"""What a connection is, for §40.4's purposes: a trainee `RoleType`, or the instructor console."""

#: The event types whose payload names the stage that has become active (§40.4 rows 3 and 32).
_ROLE_MOVING_EVENTS: dict[EventType, str] = {
    EventType.ROLE_STAGE_STARTED: "role_type",
    EventType.ROLE_TRANSITION_COMPLETED: "to_role_type",
}


@dataclass(frozen=True)
class Connection:
    """Everything §40.4 needs to decide what one socket may see.

    `dynamic` is §40.1's second bullet: only a `FULL_CYCLE_SINGLE_TRAINEE` participant with no
    `assigned_role_type` has a role that moves, and only that connection folds stage events.
    """

    role: EffectiveRole
    policy: SessionPolicy
    dynamic: bool

    def with_role(self, role: EffectiveRole) -> Connection:
        """The same connection at a new effective role (the fold's result)."""
        return self if role == self.role else Connection(role, self.policy, self.dynamic)


def connection_of(session: SimulationSession, user: AuthenticatedUser) -> Connection:
    """§40.1's three bullets, in order. Raises `ParticipantNotAssignedError` for a stranger.

    The caller has already decided that the session exists (`4404`); this decides `4403`, because
    a user who is neither a participant nor an instructor has no effective role at all.
    """
    policy = session.policy
    if user.is_instructor_or_admin:
        return Connection(INSTRUCTOR, policy, dynamic=False)

    participant = resolve_participant(session, user)
    if participant.assigned_role_type is not None:
        return Connection(participant.assigned_role_type, policy, dynamic=False)

    # `assigned_role_type is null` is permitted only under `ALL_STAGES_ONE_PARTICIPANT` (§10.10),
    # i.e. `FULL_CYCLE_SINGLE_TRAINEE`: the trainee plays every stage, so the role is whichever
    # stage is active now and moves with the session.
    dynamic = session.session_mode is SessionMode.FULL_CYCLE_SINGLE_TRAINEE
    return Connection(_active_role(session), policy, dynamic=dynamic)


def _active_role(session: SimulationSession) -> RoleType:
    """The `RoleType` of the currently active `RoleStage`, seeding the fold at connect time."""
    stage = session.current_stage or session.active_stage
    return stage.role_type if stage is not None else session.stages[0].role_type


def fold_role(connection: Connection, event_type: EventType, payload: Any) -> Connection:
    """Re-derive the effective role from one pushed event (§40.1, "re-derived on every push").

    A no-op for a fixed-role connection and for every event type that does not move the active
    stage, so the stream calls it unconditionally and pays a dictionary lookup per event.
    """
    if not connection.dynamic:
        return connection
    key = _ROLE_MOVING_EVENTS.get(event_type)
    if key is None:
        return connection
    value = payload.get(key) if hasattr(payload, "get") else None
    role = _as_role_type(value)
    return connection if role is None else connection.with_role(role)


def _as_role_type(value: object) -> RoleType | None:
    """A `RoleType` from a payload value, or `None` when the payload does not name a usable one."""
    if isinstance(value, RoleType):
        return value
    if isinstance(value, str):
        try:
            return RoleType(value)
        except ValueError:
            return None
    return None

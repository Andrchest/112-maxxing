"""Session read use cases (E7, D8, `openapi.yaml` `listSessions` / `getSession`).

Two reads and one shared assembler:

* `ListSessions` — `openapi.yaml`'s `listSessions`. `scope=MINE` is pushed into the repository
  statement (the sessions the caller participates in or created); `scope=ALL` is permitted for
  `INSTRUCTOR` and `ADMIN` only and a `TRAINEE` asking for it is refused with
  `ForbiddenForRoleError` *before* the read happens — so a trainee cannot learn how many sessions
  exist from a `total` either;
* `GetSession` — `openapi.yaml`'s `getSession`. A session the caller cannot observe is refused;
  `can_observe` decides, so a `TRAINEE` never sees another trainee's session;
* `SessionDetailView` — the assembled `SessionDetail` every session command returns (D8: "commands
  return the new materialized view"). E7-B's command endpoints build their response through
  `assemble_session_detail` rather than each re-deriving `monotonic_offset_ms` and `last_seq_no`.

Three fields of `SessionDetail` are not on the pure aggregate and are read alongside it:
`created_at`, `scenario_slug` and `scenario_version` (`SessionRepository.get_listing`), the
participants' `username` / `display_name_ru` (`UserRepository.get_many`) and their `joined_at`
(`SessionRepository.list_participants`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.clock import Clock
from app.application.ports.session_repository import StoredSessionListing
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.user_repository import StoredUser
from app.application.sessions.authorisation import ParticipantNotAssignedError, can_observe
from app.application.sessions.start_session import SessionNotFoundError
from app.application.timebase import session_offset_ms
from app.domain.common.errors import DomainError
from app.domain.common.ids import RoleStageId, SessionId, UserId
from app.domain.enums import RoleType, SessionState
from app.domain.events.types import EventType
from app.domain.session.session import RoleStage, SimulationSession

__all__ = [
    "ForbiddenForRoleError",
    "GetSession",
    "ListSessions",
    "ParticipantView",
    "SessionDetailView",
    "assemble_session_detail",
]


class ForbiddenForRoleError(DomainError):
    """The caller's account role does not permit this operation (`403 FORBIDDEN_FOR_ROLE`, D8)."""

    code = "FORBIDDEN_FOR_ROLE"


@dataclass(frozen=True)
class ParticipantView:
    """`openapi.yaml`'s `SessionParticipantView`, property names literal."""

    user_id: UserId
    username: str
    display_name_ru: str
    assigned_role_type: RoleType | None
    joined_at: datetime


@dataclass(frozen=True)
class SessionDetailView:
    """`openapi.yaml`'s `SessionDetail` as application data — the API maps it to pydantic.

    `session_seed` is present because it is public reproduction data, not hidden incident truth
    (`openapi.yaml`); nothing sourced from `WorldTruth` appears here.
    """

    session: SimulationSession
    scenario_slug: str
    scenario_version: int
    created_at: datetime
    participants: tuple[ParticipantView, ...]
    monotonic_offset_ms: int
    last_seq_no: int
    transition_continue_available_at_offset_ms: int | None

    @property
    def role_chain(self) -> tuple[RoleType, ...]:
        """The session's stages in order — the `role_chain` it was created from."""
        return tuple(stage.role_type for stage in self.session.stages)

    @property
    def active_role_stage_id(self) -> RoleStageId | None:
        """The stage the UI acts on: the first non-terminal one, else the last started one.

        `current_stage` is the stage a *stage-level* command is about, and it is `None` once every
        stage is terminal; `active_stage` then still names the one that ran last, which is what a
        completed session's header should show.
        """
        stage: RoleStage | None = self.session.current_stage or self.session.active_stage
        return stage.role_stage_id if stage is not None else None

    @property
    def transition_pause_seconds(self) -> int:
        """`SessionPolicy.transition_pause_seconds` for this session's mode (§10.10)."""
        return self.session.policy.transition_pause_seconds


async def assemble_session_detail(
    uow: UnitOfWork,
    session: SimulationSession,
    *,
    viewer: AuthenticatedUser,
    clock: Clock,
) -> SessionDetailView:
    """Assemble `SessionDetail` for one already-loaded aggregate, inside an open Unit of Work.

    E7-B's command endpoints call this right after their own `uow.commit()`-bound write, so a
    command's response is the materialized view of the state it just produced (D8).
    """
    listing = await uow.sessions.get_listing(session.id, viewer_user_id=viewer.user_id)
    if listing is None:  # pragma: no cover - the aggregate was just read from the same rows
        raise SessionNotFoundError(session.id)

    participants = await _participant_views(uow, session.id)
    events = await uow.events.read(session.id)
    last_seq_no = await _visible_last_seq_no(uow, session, viewer)
    transition_started_ms = _transition_started_ms(events)

    return SessionDetailView(
        session=session,
        scenario_slug=listing.scenario_slug,
        scenario_version=listing.scenario_version,
        created_at=listing.created_at,
        participants=participants,
        monotonic_offset_ms=session_offset_ms(clock.now(), session.started_at),
        last_seq_no=last_seq_no,
        transition_continue_available_at_offset_ms=_continue_available_at(
            session, transition_started_ms
        ),
    )


async def _visible_last_seq_no(
    uow: UnitOfWork, session: SimulationSession, viewer: AuthenticatedUser
) -> int:
    """`SessionDetail.last_seq_no` — "the highest `seq_no` **visible to the caller's role**".

    The role is §40.1's effective realtime role and the filter is that role's
    `DataVisibilityPolicy.visible_event_types` (§40.4), so the cursor this returns is the one the
    WebSocket's `resume` and `listSessionEvents` agree on: a client can carry it from a snapshot
    straight into `{"type":"resume","after_seq_no": …}` and be replayed exactly what it missed.

    A caller with no effective role at all — neither participant nor instructor — gets `0`. They
    cannot reach this function (`can_observe` refuses them first); answering `0` rather than the
    log's head keeps the "visible to the caller's role" reading true even if they ever could.

    The two realtime imports are deferred to call time, exactly as `domain/session/session.py`
    defers `ROLE_MODULES`: `app.application.realtime.effective_role` imports
    `app.application.sessions.authorisation`, which initialises this package, so a module-level
    import here would close the cycle `sessions -> realtime -> sessions`.
    """
    from app.application.realtime.effective_role import connection_of
    from app.application.realtime.redaction import visible_event_types

    try:
        connection = connection_of(session, viewer)
    except ParticipantNotAssignedError:
        return 0
    return await uow.events.last_seq_no(
        session.id, event_types=visible_event_types(connection.role)
    )


def _continue_available_at(
    session: SimulationSession, transition_started_ms: int | None
) -> int | None:
    """When `continueToNextStage` stops being refused; `null` outside `ROLE_TRANSITION`.

    `openapi.yaml`: "When `state` is `ROLE_TRANSITION`, the offset at which `continueToNextStage`
    stops being refused. `null` otherwise." The offset is the `ROLE_TRANSITION_STARTED` offset plus
    the mode's `transition_pause_seconds` (§10.10) — the same arithmetic the `continue` guard does.
    """
    if session.state is not SessionState.ROLE_TRANSITION or transition_started_ms is None:
        return None
    return transition_started_ms + session.policy.transition_pause_seconds * 1000


def _transition_started_ms(events: Sequence[object]) -> int | None:
    """The offset of the `ROLE_TRANSITION_STARTED` currently in effect, else `None`."""
    started: int | None = None
    for event in events:
        event_type = getattr(event, "event_type", None)
        if event_type is EventType.ROLE_TRANSITION_STARTED:
            started = int(getattr(event, "monotonic_offset_ms", 0))
        elif event_type is EventType.ROLE_TRANSITION_COMPLETED:
            started = None
    return started


async def _participant_views(uow: UnitOfWork, session_id: SessionId) -> tuple[ParticipantView, ...]:
    """`SessionParticipantView` rows: the participant table joined with the accounts."""
    rows = await uow.sessions.list_participants(session_id)
    accounts: Mapping[UserId, StoredUser] = {
        user.user_id: user for user in await uow.users.get_many([row.user_id for row in rows])
    }
    views: list[ParticipantView] = []
    for row in rows:
        account = accounts.get(row.user_id)
        views.append(
            ParticipantView(
                user_id=row.user_id,
                # A participant row whose account was deleted cannot happen — `users.id` is
                # referenced with `ON DELETE RESTRICT` (§20.3) — but the view must still render
                # rather than raise if it ever did.
                username=account.username if account is not None else str(row.user_id),
                display_name_ru=account.display_name_ru if account is not None else "",
                assigned_role_type=row.assigned_role_type,
                joined_at=row.joined_at,
            )
        )
    return tuple(views)


class ListSessions:
    """`listSessions` — the caller's sessions, or all of them for an instructor (D8)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        *,
        viewer: AuthenticatedUser,
        scope: str,
        state: SessionState | None,
        limit: int,
        offset: int,
    ) -> tuple[list[StoredSessionListing], int]:
        """The page and the unpaged total; `scope=ALL` from a `TRAINEE` raises."""
        all_scope = scope.upper() == "ALL"
        if all_scope and not viewer.is_instructor_or_admin:
            raise ForbiddenForRoleError("scope=ALL is permitted for INSTRUCTOR and ADMIN only")
        async with self._unit_of_work() as uow:
            page = await uow.sessions.list_sessions(
                viewer_user_id=viewer.user_id,
                mine_only=not all_scope,
                state=state,
                limit=limit,
                offset=offset,
            )
            await uow.commit()
        return page


class GetSession:
    """`getSession` — one session's materialized header, if the caller may observe it."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, session_id: SessionId, *, viewer: AuthenticatedUser
    ) -> SessionDetailView:
        """The detail view; raises `SessionNotFoundError` or `ParticipantNotAssignedError`."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not can_observe(session, viewer):
                # 403, not 404: `openapi.yaml` gives `getSession` both, and a trainee who guesses
                # a session id learns only that they may not see it.
                raise ForbiddenForRoleError(f"the caller may not observe session {session_id}")
            detail = await assemble_session_detail(uow, session, viewer=viewer, clock=self._clock)
            await uow.commit()
        return detail

"""`getSessionSnapshot` — the browser-refresh restore payload (SPEC §39, §42 test 13; D3, D8).

*"The single REST call the frontend makes after a refresh"* (`openapi.yaml`): the active stage,
its state, `available_actions`, the role's card **or** work item, the call state and
`last_seq_no`. The client then opens the WebSocket and sends
`{"type":"resume","after_seq_no":last_seq_no}` (`40-realtime-protocol.md` §3).

Two properties this module exists to keep:

* **`last_seq_no` is read in the same transaction as everything else.** That is what makes
  "snapshot, then resume after `last_seq_no`" lose nothing: any event appended after this
  transaction's view necessarily has a higher `seq_no` and is delivered by the resume, and any
  event already reflected here is not redelivered. A `last_seq_no` read in a second transaction
  could straddle a commit and silently drop an event — the failure §42 test 13 is about.

* **A `DDS` viewer never receives the live `OperatorCard` (D3, SPEC §10, §42 test 3).** The choice
  between `card` and `work_item` is made by the acting role's `DataVisibilityPolicy`, and this use
  case is constructed without a world-truth or caller-belief repository — it does not import
  either, which the per-layer import scan in
  `backend/tests/unit/application/sessions/test_layer_repository_isolation.py` asserts. The data
  is unreachable from here, not merely unrequested.

`work_item` is `null` for now: TODO(E9) owns `DdsWorkItem`, which is assembled from
`handoff_snapshots` and `dds_assignments` alone (`openapi.yaml`, `getDdsWorkItem`). Until it
exists a `DDS` active stage answers with `card = null` **and** `work_item = null` rather than with
a card it may not see — an empty panel is a missing feature, a leaked card is a broken invariant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.views import (
    ActionView,
    CallStateView,
    OperatorCardView,
    action_views,
    card_view,
    project_call_state,
)
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.authorisation import can_observe
from app.application.sessions.queries import (
    ForbiddenForRoleError,
    SessionDetailView,
    assemble_session_detail,
)
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import SessionId
from app.domain.enums import DDSStageState, Operator112StageState, RoleType
from app.domain.roles.registry import ROLE_MODULES
from app.domain.roles.visibility import VisibilitySource
from app.domain.session.session import RoleStage, SimulationSession

__all__ = ["GetSnapshot", "SessionSnapshotView"]

StageStateView = Operator112StageState | DDSStageState
"""`openapi.yaml`'s `StageState`: an `Operator112StageState` **or** a `DDSStageState` member."""

_INSTRUCTOR_SOURCES: frozenset[VisibilitySource] = frozenset(VisibilitySource)
"""An instructor has no `RoleModule`; SPEC §7 gives the console every panel, so every source.

`DataVisibilityPolicy` is a whitelist per *simulation* role (§10.9) and `INSTRUCTOR` is an
*account* role, so there is nothing to look up — see this task's report, "HLD gaps".
"""


@dataclass(frozen=True)
class SessionSnapshotView:
    """`openapi.yaml`'s `SessionSnapshot` as application data, property names literal.

    A frozen dataclass rather than a pydantic model: `session` is the `SessionDetailView` the
    session queries already assemble, and re-validating a whole aggregate on the way out of a
    read would buy nothing. `app.api.schemas.snapshot` maps this to the wire model.
    """

    session: SessionDetailView
    my_role_type: RoleType | None
    active_role_stage_id: UUID | None
    active_role_type: RoleType | None
    stage_state: StageStateView | None
    available_actions: tuple[ActionView, ...]
    card: OperatorCardView | None
    work_item: None
    call_state: CallStateView
    last_seq_no: int
    visible_sources: tuple[str, ...]
    server_time_utc: datetime


class GetSnapshot:
    """`getSessionSnapshot` (`openapi.yaml`): the role-filtered restore snapshot."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> SessionSnapshotView:
        """One transaction: the session, the log, the card the caller's role may see, and more."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not can_observe(session, user):
                raise ForbiddenForRoleError(f"the caller may not observe session {session_id}")

            detail = await assemble_session_detail(uow, session, viewer=user, clock=self._clock)
            events = await uow.events.read(session_id)
            last_seq_no = events[-1].seq_no if events else 0

            stage = session.current_stage or session.active_stage
            sources = _visible_sources(session, user)
            card = None
            if (
                stage is not None
                and stage.role_type is RoleType.OPERATOR_112
                and VisibilitySource.OPERATOR_CARD in sources
            ):
                card = await uow.operator_cards.get(session.incident.incident_id)

            await uow.commit()

        return SessionSnapshotView(
            session=detail,
            my_role_type=_my_role_type(session, user),
            active_role_stage_id=(None if stage is None else UUID(str(stage.role_stage_id))),
            active_role_type=None if stage is None else stage.role_type,
            stage_state=None if stage is None else stage.state,
            available_actions=_available_actions(session, stage, user),
            card=None if card is None else card_view(card),
            # TODO(E9): `DdsWorkItem`, built from `handoff_snapshots` + `dds_assignments` alone.
            work_item=None,
            call_state=project_call_state(events),
            last_seq_no=last_seq_no,
            visible_sources=tuple(sorted(source.value for source in sources)),
            server_time_utc=self._clock.now(),
        )


def _my_role_type(session: SimulationSession, user: AuthenticatedUser) -> RoleType | None:
    """The simulation role this caller plays, or `None` for an observer.

    `SessionParticipant.assigned_role_type` is authoritative when it is set; under
    `ALL_STAGES_ONE_PARTICIPANT` (§10.10) it is deliberately `null`, and the answer is then the
    role of the stage the caller is bound to.
    """
    for participant in session.participants:
        if participant.user_id != user.user_id:
            continue
        if participant.assigned_role_type is not None:
            return participant.assigned_role_type
        break
    stage = session.current_stage or session.active_stage
    if stage is not None and stage.participant_user_id == user.user_id:
        return stage.role_type
    return None


def _visible_sources(
    session: SimulationSession, user: AuthenticatedUser
) -> frozenset[VisibilitySource]:
    """`DataVisibilityPolicy.sources` for the caller's role — "the UI renders only these panels"."""
    if user.is_instructor_or_admin:
        return _INSTRUCTOR_SOURCES
    role = _my_role_type(session, user)
    module = None if role is None else ROLE_MODULES.get(role)
    return frozenset() if module is None else module.visibility_policy.sources


def _available_actions(
    session: SimulationSession, stage: RoleStage | None, user: AuthenticatedUser
) -> tuple[ActionView, ...]:
    """`RoleModule.available_actions(stage_state)` **filtered by the participant assignment**.

    A caller who is not the participant bound to the active stage gets an empty list: an
    instructor watching, or a trainee whose stage has not started, has no button to press. The
    filter is the one `openapi.yaml` describes on this field, and it is advisory only — the
    command gate re-checks both of D8's gates server-side whatever the UI shows.
    """
    if stage is None or stage.participant_user_id != user.user_id:
        return ()
    module = ROLE_MODULES.get(stage.role_type)
    if module is None:
        return ()
    return action_views(module.available_actions(stage.state))

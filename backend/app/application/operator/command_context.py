"""The ONE Operator 112 command pipeline (D5, D8, SPEC §7, §9, §10).

Nine commands, one gate. Every `/operator/*` write goes through `OperatorCommandGate.open`, which
runs D5's single Unit of Work transaction and D8's two-gate authorisation in a fixed order:

1. `SessionRepository.get_for_update` — the `SELECT … FOR UPDATE` row lock of §20.8. It is taken
   *first*, which is what serialises two concurrent commands on one session: the second waits,
   then reads the first one's committed state and allocates the next `seq_no` and the next
   `revision_no` against it. A missing session is `404 NOT_FOUND`;
2. the session is `ACTIVE`, else `409 SESSION_NOT_ACTIVE` — a `READY`, `COMPLETED`, `ABORTED` or
   `ROLE_TRANSITION` session accepts no stage command;
3. `resolve_participant` — D8's first gate, `403 PARTICIPANT_NOT_ASSIGNED`;
4. the caller is a `TRAINEE` account **and** is the participant bound to the session's active
   `RoleStage` **and** that stage's role is `OPERATOR_112`, else `403 FORBIDDEN_FOR_ROLE`. The
   account-role half is not redundant with the state machine: `edit_card` and `end_call` fire no
   trigger at all, so without it an instructor could complete a trainee's action — which SPEC §7
   forbids in as many words. An instructor or admin may *read* the card and the snapshot; they
   may never issue a command here;
5. the command's action id — `openapi.yaml`'s `x-action` for that operation — is a member of
   `Operator112Module.available_actions(stage_state)`, else `409 ACTION_NOT_AVAILABLE`. This is
   D8's second gate, and it is asked of the role module rather than of a table retyped here;
6. the use case runs: it calls the domain, persists only what changed and appends its
   `DomainEvent`s through this context;
7. `commit()`. Publishing happens inside the Unit of Work, after the commit (§20.8, §40.6).

Everything a command needs that the aggregate cannot answer is projected once, here: the session
offset (`session_offset_ms`, from persisted state only — SPEC §39), the event log, the
`GuardRuntime` built from it and the `CallTransportStatus` reading that `ring`'s guard needs.

The `tick_after_command` of D7 is deliberately **not** here: it must run *after* the transaction
commits, so it belongs to the endpoint (`app.api.deps.tick_after_command`), not inside the
transaction that would otherwise deadlock against it on the same session row.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.views import OperatorStageView, operator_stage_view
from app.application.ports.call_transport_status import CallTransportStatus
from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.user_repository import UserRole
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.guard_context import build_guard_runtime
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.application.timebase import session_offset_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import IncidentId, SessionId
from app.domain.common.state_machine import GuardRuntime
from app.domain.enums import ActorType, Operator112StageState, RoleType, SessionState
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.layers.operator_card import OperatorCard
from app.domain.roles.operator112 import Operator112Module
from app.domain.session.session import RoleStage, SimulationSession

__all__ = [
    "ActionNotAvailableError",
    "CardMissingError",
    "OperatorCommandContext",
    "OperatorCommandGate",
    "SessionNotActiveError",
]

_OPERATOR_MODULE = Operator112Module()
"""One module instance: `Operator112Module` is stateless and its tables are module-level."""


class SessionNotActiveError(DomainError):
    """The session is not `ACTIVE`, so it accepts no stage command (`409`, `openapi.yaml`)."""

    code = "SESSION_NOT_ACTIVE"

    def __init__(self, session_id: SessionId, state: SessionState) -> None:
        self.session_id = session_id
        self.state = state
        super().__init__(f"session {session_id} is {state.value}, not ACTIVE")


class ActionNotAvailableError(DomainError):
    """D8's second gate: the stage's `RoleModule` does not offer this action now (`409`)."""

    code = "ACTION_NOT_AVAILABLE"

    def __init__(self, action_id: str, stage_state: Operator112StageState) -> None:
        self.action_id = action_id
        self.stage_state = stage_state
        super().__init__(
            f"action {action_id!r} is not available in stage state {stage_state.value}"
        )


class CardMissingError(DomainError):
    """The incident has no `incident_cards` row — session creation always makes one (`404`)."""

    code = "NOT_FOUND"

    def __init__(self, incident_id: IncidentId) -> None:
        self.incident_id = incident_id
        super().__init__(f"incident {incident_id} has no operator card")


@dataclass
class OperatorCommandContext:
    """Everything one Operator 112 command acts on, inside its open transaction."""

    uow: UnitOfWork
    session: SimulationSession
    stage: RoleStage
    actor: ActorRef
    now_ms: int
    transport_ready: bool
    log: tuple[SessionEvent, ...]
    _appended: list[SessionEvent] = field(default_factory=list)

    # -- projections ---------------------------------------------------------------------------

    @property
    def session_id(self) -> SessionId:
        """The session this command is about."""
        return self.session.id

    @property
    def stage_state(self) -> Operator112StageState:
        """The active stage's Operator 112 state."""
        state = self.stage.state
        assert isinstance(state, Operator112StageState)
        return state

    @property
    def full_log(self) -> tuple[SessionEvent, ...]:
        """The log as it stands *including* what this command has appended so far."""
        return (*self.log, *self._appended)

    @property
    def last_seq_no(self) -> int:
        """The highest `seq_no` in the session's log after this command's appends."""
        events = self.full_log
        return events[-1].seq_no if events else 0

    def guard_runtime(self) -> GuardRuntime:
        """`GuardRuntime` for this command, projected from the log plus the transport reading.

        `scenario_valid` and `inference_ready` are `True` because no Operator 112 *stage* guard
        reads either: they belong to the session-level `validate` / `start` transitions, which
        this pipeline never fires (`ValidateSession` and `StartSession` own them, and each
        supplies its own reading). Passing `False` here would be equally inert but would read as
        a claim about facts this pipeline has not checked.
        """
        return build_guard_runtime(
            self.full_log,
            scenario_valid=True,
            inference_ready=True,
            transport_ready=self.transport_ready,
        )

    # -- writes --------------------------------------------------------------------------------

    async def append(self, events: Sequence[DomainEvent]) -> list[SessionEvent]:
        """Append `events` to the session's log, in order, inside this transaction."""
        stored = await self.uow.events.append(self.session_id, events)
        self._appended.extend(stored)
        return stored

    async def save_session(self, session: SimulationSession) -> None:
        """Persist a session the domain returned and make it this context's session."""
        await self.uow.sessions.save(session)
        self.session = session
        self.stage = session.stage(self.stage.role_stage_id)

    async def card(self) -> OperatorCard:
        """The incident's `OperatorCard`; every session creation makes one, so absence is a bug."""
        card = await self.uow.operator_cards.get(self.session.incident.incident_id)
        if card is None:
            raise CardMissingError(self.session.incident.incident_id)
        return card

    def stage_view(self, card: OperatorCard) -> OperatorStageView:
        """The `OperatorStageView` this command answers with (D8)."""
        return operator_stage_view(self.session, self.stage, card, self.full_log, self.last_seq_no)


class OperatorCommandGate:
    """Opens the one transaction every Operator 112 command runs in (see the module docstring)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        call_transport: CallTransportStatus,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._call_transport = call_transport

    @asynccontextmanager
    async def open(
        self, session_id: SessionId, user: AuthenticatedUser, action_id: str
    ) -> AsyncIterator[OperatorCommandContext]:
        """Run the seven steps of the module docstring around the caller's block.

        Leaving the block normally commits; an exception rolls back and publishes nothing, so a
        rejected command leaves neither a materialized change nor an event behind (D5).
        """
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if session.state is not SessionState.ACTIVE:
                raise SessionNotActiveError(session_id, session.state)

            participant = resolve_participant(session, user)
            stage = _operator_stage_for(session)
            if stage is None or stage.participant_user_id != participant.user_id:
                raise ForbiddenForRoleError(
                    f"the caller is not the OPERATOR_112 participant of the active stage of "
                    f"session {session_id}"
                )
            if user.user_role is not UserRole.TRAINEE:
                # SPEC §7: the instructor observes and intervenes; they never complete a trainee
                # action. Reading the card and the snapshot stays open to them.
                raise ForbiddenForRoleError(
                    "a trainee stage command may only be issued by a TRAINEE account"
                )

            stage_state = stage.state
            assert isinstance(stage_state, Operator112StageState)
            available = {
                action.action_id for action in _OPERATOR_MODULE.available_actions(stage_state)
            }
            if action_id not in available:
                raise ActionNotAvailableError(action_id, stage_state)

            context = OperatorCommandContext(
                uow=uow,
                session=session,
                stage=stage,
                actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=user.user_id),
                now_ms=session_offset_ms(self._clock.now(), session.started_at),
                transport_ready=await self._call_transport.caller_joined(session_id),
                log=tuple(await uow.events.read(session_id)),
            )
            yield context
            await uow.commit()


def _operator_stage_for(session: SimulationSession) -> RoleStage | None:
    """The session's active stage, if it is an `OPERATOR_112` one; `None` otherwise.

    `current_stage` — the lowest-`order_index` non-terminal stage — is the stage a *stage-level*
    command is about. A `DDS` active stage returns `None` here, which the caller renders as
    `403 FORBIDDEN_FOR_ROLE`: the 112 endpoints are simply not the endpoints of that stage.
    """
    stage = session.current_stage
    if stage is None or stage.role_type is not RoleType.OPERATOR_112:
        return None
    return stage

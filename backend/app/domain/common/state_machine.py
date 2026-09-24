"""Generic finite-state machine (HLD `10-domain-model.md` §10.8, SPEC §7, §42 item 8).

`Transition`, `TransitionTable`, `StateMachine[S]` are copied from §10.8 verbatim. `GuardContext`
is a companion value object §10.8 references but does not assign to a file: this module is the
closest owner (`GuardContext` is the `ctx` parameter of every `StateMachine` method), so it lives
here. `ActorRef` (`GuardContext.actor`) has its one home in `common/actors.py` (consolidation
ruling R1): this module imports it rather than redefining it. See this task's report, "HLD gaps",
for why `GuardContext.session/stage/card/assignment` are typed `Any` rather than the aggregate
types §10.8 names (`SimulationSession`, `RoleStage`, `OperatorCard`, `DDSAssignment`): those types
belong to other, not-yet-existing slices, and importing `EmergencyResource` here for `resources`
would create `common -> dds -> common` import cycle since `dds/resources.py` imports this module
for `Transition`/`TransitionTable`.

`StateMachine.fire` raises `InvalidTransitionError` (`common/errors.py`) when the `(state,
trigger)` pair is absent from the table, when the firing actor/role is not allowed, or when the
transition's guard (looked up by name in the `guards` mapping passed to the constructor) is
missing or returns `False` — in that order, matching `common/errors.py`'s docstring. The `machine`
name reported in the error is `type(state).__name__` (e.g. `"SessionState"`); §10.8's constructor
signature takes only `(table, guards)`, so there is no separate `name` parameter to carry it.

Guard *callables* (the predicates named by `Transition.guard_name`, e.g.
`guard_stage_terminal_and_next_exists`) live in `session/guards.py` and are wired into
`session/machine.py`'s `SESSION_STATE_MACHINE` and into both implemented
`RoleModule.state_machine`s. A guard is pure: every fact it cannot derive from the session
aggregate itself arrives on `GuardContext.runtime` (`GuardRuntime` below), which the application
layer projects from the event log, the health registry and the transport ports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.enums import ActorType, RoleType
from app.domain.events.types import EventType


class GuardRuntime(BaseModel):
    """The facts a pure guard cannot derive from the session aggregate, projected for it (§10.8).

    The application layer derives every field from the event log, the inference health registry or
    a transport port and hands the result to the domain; the guards in `session/guards.py` only
    read it. Every field defaults to the conservative value (`False` / `None`), so a default
    `GuardRuntime` denies every runtime-dependent transition rather than accidentally allowing one.
    """

    model_config = ConfigDict(frozen=True)

    scenario_valid: bool = False
    """`validate_scenario_version` passed for this session's `ScenarioVersion` (§10.15)."""

    inference_ready: bool = False
    """Every required inference component is `READY`, or `REQUIRE_INFERENCE_READY` is false (D8)."""

    transport_ready: bool = False
    """The `CallTransport` reports the caller joined the room (§10.8 `ring`)."""

    first_finalized_turn: bool = False
    """The first `ASR_FINAL` for this call has been appended (§10.8 `begin_interview`)."""

    call_connected: bool = False
    """A call is currently connected (`CALL_ANSWERED` appended, no `CALL_ENDED` after it)."""

    call_ended: bool = False
    """`CALL_ENDED` has been appended for this call (§10.8 `complete_stage`)."""

    resolution_condition_met: bool = False
    """The scenario's `expected_response.resolution_condition` evaluates true (§10.8)."""

    transition_started_ms: int | None = None
    """`monotonic_offset_ms` of the `ROLE_TRANSITION_STARTED` currently in effect, else `None`."""

    all_legs_terminal: bool = False
    """Every `DDSAssignment` leg of the DDS stage is `COMPLETED`, `NOT_ACCEPTED` or `REFUSED`
    (HLD 70 §70.4.4 `memo_all_legs_terminal`; I3 E5a). The application projects it from the legs."""


class GuardContext(BaseModel):
    """Read-only context passed to guard callables and to every `StateMachine` method (§10.8).

    Never carries a repository. `session`, `stage`, `card`, `assignment` are `Any` — see the
    module docstring; `resources` and `world_flags` are likewise loosely typed so this module
    stays import-clean of `dds/resources.py` and the (not yet existing) world-truth projection.
    `runtime` carries the application-projected facts (`GuardRuntime`).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    actor: ActorRef
    role_type: RoleType | None = None
    now_ms: int = 0
    session: Any = None
    stage: Any = None
    card: Any = None
    assignment: Any = None
    resources: Mapping[str, Any] | None = None
    world_flags: Mapping[str, bool] = Field(default_factory=dict)
    runtime: GuardRuntime = GuardRuntime()


class Transition[S: Enum](BaseModel):
    """One `(source, trigger) -> target` edge (§10.8)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    source: S
    trigger: str
    target: S
    allowed_actors: frozenset[ActorType]
    allowed_roles: frozenset[RoleType] = frozenset()
    guard_name: str | None = None
    emits: EventType | None = None


type TransitionTable[S: Enum] = Mapping[tuple[S, str], Transition[S]]


class StateMachine[S: Enum]:
    """A table-driven finite-state machine over enum `S` (§10.8)."""

    def __init__(
        self,
        table: TransitionTable[S],
        guards: Mapping[str, Callable[[GuardContext], bool]],
    ) -> None:
        self._table = table
        self._guards = guards

    def _resolve(
        self, state: S, trigger: str, ctx: GuardContext
    ) -> tuple[Transition[S] | None, str | None]:
        """Return `(transition, failure_reason)`; `failure_reason` is `None` iff firing succeeds."""
        transition = self._table.get((state, trigger))
        if transition is None:
            return None, "no such transition"
        if ctx.actor.actor_type not in transition.allowed_actors:
            return transition, f"actor {ctx.actor.actor_type.value!r} not allowed"
        if (
            transition.allowed_roles
            and ctx.actor.actor_type == ActorType.TRAINEE
            and ctx.role_type not in transition.allowed_roles
        ):
            return transition, f"role {ctx.role_type!r} not allowed"
        if transition.guard_name is not None:
            guard = self._guards.get(transition.guard_name)
            if guard is None:
                return transition, f"guard {transition.guard_name!r} is not registered"
            if not guard(ctx):
                return transition, f"guard {transition.guard_name!r} returned False"
        return transition, None

    def can_fire(self, state: S, trigger: str, ctx: GuardContext) -> bool:
        _transition, reason = self._resolve(state, trigger, ctx)
        return reason is None

    def fire(self, state: S, trigger: str, ctx: GuardContext) -> S:
        transition, reason = self._resolve(state, trigger, ctx)
        if reason is not None:
            machine = type(state).__name__
            to_state = str(transition.target.value) if transition is not None else None
            raise InvalidTransitionError(
                machine, str(state.value), trigger, reason, to_state=to_state
            )
        assert transition is not None  # `reason is None` implies a transition was found
        return transition.target

    def available_triggers(self, state: S, ctx: GuardContext) -> tuple[str, ...]:
        triggers = sorted(
            trigger
            for (source, trigger) in self._table
            if source == state and self.can_fire(source, trigger, ctx)
        )
        return tuple(triggers)

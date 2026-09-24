"""The session aggregate: `SimulationSession`, `Incident`, `RoleStage`, `SessionParticipant` and
the `create_session` factory (HLD `10-domain-model.md` §10.1, §10.8, §10.10, `20-db-schema.md`
§20.3, SPEC §7, §13, D6).

Shape (D2, and the style every other domain module already follows): every model is frozen;
behaviour never mutates, it returns a NEW aggregate value plus the `DomainEvent`s the transition
produced, `-> tuple[SimulationSession, list[DomainEvent]]`. The aggregate owns no clock, no
randomness and no id generator — `started_at`/`completed_at`, every id and `now_ms` are passed in
by the calling use case.

Fields mirror the `20-db-schema.md` §20.3 columns with two deliberate differences:

- `simulation_sessions.next_seq_no` has no field here. Sequence allocation belongs to the event
  store, not to the aggregate; a pure domain value must not carry a counter only a writer can
  advance.
- `time_scale` is carried although §20.3 has no column for it: `openapi.yaml`'s
  `SessionCreateRequest`/`SessionDetail` both make it part of the session, so the aggregate is its
  home. Persisting it is the storage slice's problem — see this task's report, "HLD gaps".

Exactly one `Incident` per session (SPEC §13, §42 test 5): `create_session` builds it and no
method on this class ever replaces it — a role change moves the session to the next `RoleStage`
against the *same* incident.

Every method builds its own `GuardContext` and goes through a `StateMachine`, so an illegal call
raises `InvalidTransitionError` and returns nothing at all; the caller's aggregate value, being
frozen, is left exactly as it was.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.common.actors import ActorRef
from app.domain.common.errors import PrefabHandoffRequiredError, RoleChainLengthError
from app.domain.common.ids import (
    IncidentId,
    RoleStageId,
    ScenarioId,
    ScenarioVersionId,
    SessionId,
    UserId,
)
from app.domain.common.state_machine import GuardContext, GuardRuntime
from app.domain.enums import (
    ActorType,
    ClosureReason,
    DDSStageState,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.session.guards import TERMINAL_STAGE_STATES
from app.domain.session.machine import SESSION_STATE_MACHINE
from app.domain.session.policy import SESSION_POLICIES, ParticipantAssignmentRule, SessionPolicy
from app.domain.session.variants import (
    PartialVariants,
    SessionVariants,
    VariantNotSupportedError,
    effective_role_chain,
    legacy_session_variants,
    resolve_variants,
    variants_payload,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.domain.roles.module import RoleModule
    from app.domain.scenario.version import ScenarioVersion

StageState = Operator112StageState | DDSStageState
"""The union `role_stages.state` carries (§20.3): one implemented role module's state enum."""

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)
"""`ROLE_STAGE_STARTED` / `ROLE_STAGE_COMPLETED` are `SIMULATION`-authored per the event catalog,
whoever fired the transition that produced them."""

NO_RUNTIME_FACTS = GuardRuntime()
"""The all-denying `GuardRuntime`, used as the `runtime=` default of every method below.

A caller that forgets to project the runtime facts therefore gets a denied transition, never an
accidentally allowed one. It is a module-level singleton because `GuardRuntime` is frozen.
"""


def _role_modules() -> Mapping[RoleType, RoleModule]:
    """`ROLE_MODULES`, looked up on call rather than imported at module level.

    `roles/operator112.py` and `roles/dds.py` import `session/guards.py` to build their state
    machines, which initialises the `app.domain.session` package; a module-level
    `from app.domain.roles.registry import ROLE_MODULES` here would therefore close an import
    cycle (`roles.registry -> roles.operator112 -> session -> roles.registry`) and fail on a
    partially initialised `roles.registry`. Nothing in this module needs the registry before a
    method is called, so the import is deferred to call time. `ScenarioVersion` is kept out of
    the runtime imports for the same reason (`scenario.validation` imports `ROLE_MODULES`); it
    is only ever a parameter annotation here, which `from __future__ import annotations` leaves
    unevaluated.
    """
    from app.domain.roles.registry import ROLE_MODULES

    return ROLE_MODULES


class Incident(BaseModel):
    """The one incident a session is about (§20.3 `incidents`, SPEC §13).

    `uq_incidents_session (session_id)` is the structural half of "role changes do not create a
    new incident"; this class is the domain half — `SimulationSession.incident` is set once, by
    `create_session`, and no method replaces it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: IncidentId
    session_id: SessionId
    scenario_version_id: ScenarioVersionId
    created_at_offset_ms: int = 0
    closed_at_offset_ms: int | None = None
    closure_reason: ClosureReason | None = None


class SessionParticipant(BaseModel):
    """One `session_participants` row (§20.3): a user, optionally pinned to a role.

    `joined_at` is a storage default (`now()`) the pure domain cannot produce and no rule here
    reads, so it has no field. `participant_id` is the row id when the caller allocated one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UserId
    assigned_role_type: RoleType | None = None
    participant_id: UUID | None = None


class RoleStage(BaseModel):
    """One `role_stages` row (§20.3): one `role_chain` entry, played against `incident_id`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role_stage_id: RoleStageId
    session_id: SessionId
    incident_id: IncidentId
    role_type: RoleType
    order_index: int
    state: StageState
    participant_user_id: UserId | None = None
    started_at_offset_ms: int | None = None
    completed_at_offset_ms: int | None = None

    @property
    def is_terminal(self) -> bool:
        """True when `state` is the terminal state of the stage's role module."""
        return self.state in TERMINAL_STAGE_STATES


class SimulationSession(BaseModel):
    """One `simulation_sessions` row plus the incident, stages and participants it owns (§20.3).

    `stages` is ordered by `order_index` — `create_session` builds it that way and every method
    preserves the order, so `stages[i].order_index == i`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: SessionId
    scenario_version_id: ScenarioVersionId
    session_mode: SessionMode
    state: SessionState
    session_seed: str
    time_scale: float = 1.0
    created_by_user_id: UserId
    started_at: datetime | None = None
    paused_total_ms: int = 0
    role_transition_started_offset_ms: int | None = None
    """The session offset a currently open `ROLE_TRANSITION` began at; `None` outside one (E17 R1).

    Simulated time does not run during a role transition, so every reader of "sim now"
    (`app.application.simulation.sim_time`) freezes at this value for as long as the transition
    is open, and `finish_role_transition` banks the interval's wall-clock length into
    `paused_total_ms`. Storing the offset rather than a `role_transition_started_at` wall stamp
    keeps this aggregate clock-free: the two are the same instant, since
    `started_at + paused_total_ms + role_transition_started_offset_ms` *is* that wall stamp.
    The value is also in the log, on `ROLE_TRANSITION_STARTED`; the column exists so that a sim
    time read needs the session row alone and never a log scan.
    """
    completed_at: datetime | None = None
    abort_reason: str | None = None
    incident: Incident
    stages: tuple[RoleStage, ...]
    participants: tuple[SessionParticipant, ...] = ()
    variants: SessionVariants
    """The resolved variant switches, immutable after creation (HLD 70 §70.2.2, D14).

    A session created before E1 carries none (`simulation_sessions.variants = '{}'`); it reads as
    the schema-1 derivation of its own stage chain (`legacy_session_variants`), which is exactly
    how it ran. `_fill_legacy_variants` supplies that when the field is absent.
    """

    @model_validator(mode="before")
    @classmethod
    def _fill_legacy_variants(cls, data: Any) -> Any:
        if not isinstance(data, Mapping) or data.get("variants") is not None:
            return data
        stages = data.get("stages") or ()
        chain = [
            stage.role_type if isinstance(stage, RoleStage) else RoleType(stage["role_type"])
            for stage in stages
        ]
        return {**data, "variants": legacy_session_variants(chain)}

    # -- projections -------------------------------------------------------------------------

    @property
    def policy(self) -> SessionPolicy:
        """`SESSION_POLICIES[session_mode]` (§10.10)."""
        return SESSION_POLICIES[self.session_mode]

    @property
    def current_stage(self) -> RoleStage | None:
        """The lowest-`order_index` stage that is not in its terminal state, else `None`."""
        for stage in self.stages:
            if not stage.is_terminal:
                return stage
        return None

    @property
    def active_stage(self) -> RoleStage | None:
        """The greatest-`order_index` stage that has been started, else `None`.

        This — not `current_stage` — is the stage a *session-level* trigger is about: by the time
        `begin_role_transition` or `complete` fires, the stage that has been running is terminal
        and `current_stage` has already moved past it (or become `None`).
        """
        started = [stage for stage in self.stages if stage.started_at_offset_ms is not None]
        if not started:
            return None
        return max(started, key=lambda stage: stage.order_index)

    def stage(self, stage_id: RoleStageId) -> RoleStage:
        """The stage with `role_stage_id == stage_id`; raises `KeyError` when there is none."""
        for candidate in self.stages:
            if candidate.role_stage_id == stage_id:
                return candidate
        raise KeyError(f"session {self.id} has no role stage {stage_id}")

    def next_stage_after(self, stage: RoleStage) -> RoleStage | None:
        """The stage whose `order_index` is `stage.order_index + 1`, else `None`."""
        for candidate in self.stages:
            if candidate.order_index == stage.order_index + 1:
                return candidate
        return None

    # -- internals ---------------------------------------------------------------------------

    def _with_stage(self, updated: RoleStage) -> tuple[RoleStage, ...]:
        return tuple(
            updated if stage.role_stage_id == updated.role_stage_id else stage
            for stage in self.stages
        )

    def _ctx(
        self,
        *,
        actor: ActorRef,
        role_type: RoleType | None,
        now_ms: int,
        runtime: GuardRuntime,
        stage: RoleStage | None,
        card: Any = None,
        assignment: Any = None,
        resources: Mapping[str, Any] | None = None,
    ) -> GuardContext:
        return GuardContext(
            actor=actor,
            role_type=role_type,
            now_ms=now_ms,
            session=self,
            stage=stage,
            card=card,
            assignment=assignment,
            resources=resources,
            runtime=runtime,
        )

    def _event(
        self,
        event_type: EventType,
        *,
        actor: ActorRef,
        now_ms: int,
        payload: Mapping[str, Any],
    ) -> DomainEvent:
        validate_payload(event_type, payload)
        return DomainEvent(
            event_type=event_type, actor=actor, monotonic_offset_ms=now_ms, payload=payload
        )

    def _role_stage_started(self, stage: RoleStage, *, now_ms: int) -> DomainEvent:
        return self._event(
            EventType.ROLE_STAGE_STARTED,
            actor=_SIMULATION,
            now_ms=now_ms,
            payload={
                "role_stage_id": str(stage.role_stage_id),
                "role_type": stage.role_type.value,
                "order_index": stage.order_index,
                "initial_state": stage.state.value,
                "participant_user_id": (
                    str(stage.participant_user_id)
                    if stage.participant_user_id is not None
                    else None
                ),
            },
        )

    def _stage_state_changed(
        self,
        *,
        stage: RoleStage,
        previous_state: StageState,
        trigger: str,
        actor: ActorRef,
        now_ms: int,
    ) -> DomainEvent:
        return self._event(
            EventType.STAGE_STATE_CHANGED,
            actor=actor,
            now_ms=now_ms,
            payload={
                "role_stage_id": str(stage.role_stage_id),
                "role_type": stage.role_type.value,
                "previous_state": previous_state.value,
                "new_state": stage.state.value,
                "trigger": trigger,
                "fired_by_actor_type": actor.actor_type.value,
                "fired_by_user_id": str(actor.actor_id) if actor.actor_id is not None else None,
                "at_offset_ms": now_ms,
            },
        )

    def _role_stage_completed(self, stage: RoleStage, *, now_ms: int) -> DomainEvent:
        started = stage.started_at_offset_ms
        return self._event(
            EventType.ROLE_STAGE_COMPLETED,
            actor=_SIMULATION,
            now_ms=now_ms,
            payload={
                "role_stage_id": str(stage.role_stage_id),
                "role_type": stage.role_type.value,
                "final_state": stage.state.value,
                "duration_ms": 0 if started is None else max(0, now_ms - started),
            },
        )

    # -- session-level behaviour -------------------------------------------------------------

    def validate_session(
        self,
        *,
        actor: ActorRef,
        now_ms: int = 0,
        runtime: GuardRuntime = NO_RUNTIME_FACTS,
    ) -> tuple[SimulationSession, list[DomainEvent]]:
        """`CREATED --validate--> READY` (SYSTEM). Emits nothing: §10.8's session table has no
        `emits` for this row.

        The §10.8 trigger is named `validate`; the method is `validate_session` because a method
        called `validate` would shadow `BaseModel.validate`, pydantic v2's deprecated v1
        compatibility classmethod, and silencing that with `# type: ignore[override]` is not
        acceptable in a strictly typed domain (E5-B ruling R1). The trigger string fired on
        `SESSION_STATE_MACHINE` below is still `"validate"`.

        A participant set the policy's `assignment_rule` cannot satisfy is rejected here, by
        `guard_scenario_valid_and_participants_assigned`, not by `create_session`.
        """
        ctx = self._ctx(
            actor=actor,
            role_type=None,
            now_ms=now_ms,
            runtime=runtime,
            stage=self.current_stage,
        )
        new_state = SESSION_STATE_MACHINE.fire(self.state, "validate", ctx)
        return self.model_copy(update={"state": new_state}), []

    def start(
        self,
        started_at: datetime,
        *,
        actor: ActorRef,
        now_ms: int = 0,
        runtime: GuardRuntime = NO_RUNTIME_FACTS,
    ) -> tuple[SimulationSession, list[DomainEvent]]:
        """`READY --start--> ACTIVE` (INSTRUCTOR). Emits `SESSION_STARTED`, then
        `ROLE_STAGE_STARTED` for the first stage, whose `started_at_offset_ms` becomes `now_ms`.
        """
        ctx = self._ctx(
            actor=actor,
            role_type=None,
            now_ms=now_ms,
            runtime=runtime,
            stage=self.stages[0] if self.stages else None,
        )
        new_state = SESSION_STATE_MACHINE.fire(self.state, "start", ctx)
        first = self.stages[0]
        started_stage = first.model_copy(update={"started_at_offset_ms": now_ms})
        updated = self.model_copy(
            update={
                "state": new_state,
                "started_at": started_at,
                "stages": self._with_stage(started_stage),
            }
        )
        events = [
            self._event(
                EventType.SESSION_STARTED,
                actor=actor,
                now_ms=now_ms,
                payload={
                    "started_at_utc": started_at.isoformat(),
                    "first_role_stage_id": str(started_stage.role_stage_id),
                    "first_role_type": started_stage.role_type.value,
                },
            ),
            updated._role_stage_started(started_stage, now_ms=now_ms),
        ]
        return updated, events

    def abort(
        self,
        reason: str,
        *,
        actor: ActorRef,
        now_ms: int = 0,
        runtime: GuardRuntime = NO_RUNTIME_FACTS,
    ) -> tuple[SimulationSession, list[DomainEvent]]:
        """`CREATED | READY | ACTIVE | ROLE_TRANSITION --abort--> ABORTED` (INSTRUCTOR, SYSTEM).

        Fires `abort_stage` on every non-terminal stage through that stage's own role machine —
        so an abort is rejected by the stage machine too if it ever becomes illegal there — and
        emits one `STAGE_STATE_CHANGED` per aborted stage, then `SESSION_ABORTED`. The incident is
        left in place (SPEC §13); closing it belongs to the closing use case.
        """
        previous_state = self.state
        ctx = self._ctx(
            actor=actor,
            role_type=None,
            now_ms=now_ms,
            runtime=runtime,
            stage=self.active_stage,
        )
        new_state = SESSION_STATE_MACHINE.fire(self.state, "abort", ctx)

        stages = self.stages
        events: list[DomainEvent] = []
        for stage in self.stages:
            if stage.is_terminal:
                continue
            module = _role_modules()[stage.role_type]
            stage_ctx = self._ctx(
                actor=actor, role_type=stage.role_type, now_ms=now_ms, runtime=runtime, stage=stage
            )
            target = module.state_machine.fire(stage.state, "abort_stage", stage_ctx)
            aborted = stage.model_copy(update={"state": target, "completed_at_offset_ms": now_ms})
            stages = tuple(aborted if s.role_stage_id == stage.role_stage_id else s for s in stages)
            events.append(
                self._stage_state_changed(
                    stage=aborted,
                    previous_state=stage.state,
                    trigger="abort_stage",
                    actor=actor,
                    now_ms=now_ms,
                )
            )

        updated = self.model_copy(
            update={"state": new_state, "abort_reason": reason, "stages": stages}
        )
        events.append(
            self._event(
                EventType.SESSION_ABORTED,
                actor=actor,
                now_ms=now_ms,
                payload={
                    "previous_state": previous_state.value,
                    "reason": reason,
                    "at_offset_ms": now_ms,
                    "aborted_by_user_id": (
                        str(actor.actor_id) if actor.actor_id is not None else None
                    ),
                },
            )
        )
        return updated, events

    def begin_role_transition(
        self,
        *,
        actor: ActorRef,
        now_ms: int = 0,
        runtime: GuardRuntime = NO_RUNTIME_FACTS,
    ) -> tuple[SimulationSession, list[DomainEvent]]:
        """`ACTIVE --begin_role_transition--> ROLE_TRANSITION` (SYSTEM). Emits
        `ROLE_TRANSITION_STARTED`. The next stage is not started yet — `finish_role_transition`
        does that after `policy.transition_pause_seconds`.

        `now_ms` is the session offset (`app.application.simulation.sim_time.running_ms`), and it
        is remembered on the aggregate as `role_transition_started_offset_ms`: from here until
        `finish_role_transition` the simulated clock is frozen at it (E17 R1)."""
        from_stage = self.active_stage
        ctx = self._ctx(
            actor=actor, role_type=None, now_ms=now_ms, runtime=runtime, stage=from_stage
        )
        new_state = SESSION_STATE_MACHINE.fire(self.state, "begin_role_transition", ctx)
        assert from_stage is not None  # the guard denies a session with no started stage
        to_stage = self.next_stage_after(from_stage)
        assert to_stage is not None  # `guard_stage_terminal_and_next_exists` checked this
        updated = self.model_copy(
            update={"state": new_state, "role_transition_started_offset_ms": now_ms}
        )
        event = self._event(
            EventType.ROLE_TRANSITION_STARTED,
            actor=_SIMULATION,
            now_ms=now_ms,
            payload={
                "from_role_stage_id": str(from_stage.role_stage_id),
                "from_role_type": from_stage.role_type.value,
                "to_role_stage_id": str(to_stage.role_stage_id),
                "to_role_type": to_stage.role_type.value,
                "pause_seconds": self.policy.transition_pause_seconds,
                "at_offset_ms": now_ms,
            },
        )
        return updated, [event]

    def finish_role_transition(
        self,
        *,
        actor: ActorRef,
        now_ms: int = 0,
        runtime: GuardRuntime = NO_RUNTIME_FACTS,
    ) -> tuple[SimulationSession, list[DomainEvent]]:
        """`ROLE_TRANSITION --finish_role_transition--> ACTIVE` (SYSTEM). Starts the next stage
        and emits `ROLE_TRANSITION_COMPLETED` then `ROLE_STAGE_STARTED`.

        **This is the one writer of `paused_total_ms`** (E17 R1). `now_ms` here is the *unfrozen*
        clock — `app.application.simulation.sim_time.transition_clock_ms`, wall elapsed minus the
        pauses already banked — because that is the only basis in which
        `guard_pause_elapsed_and_next_assigned` can observe the pause elapsing at all; a clock
        frozen at `transition_started_ms` would never reach `transition_started_ms + pause`.

        The pause interval is therefore `now_ms - role_transition_started_offset_ms`, it is added
        to `paused_total_ms`, and the events this call emits — plus the next stage's
        `started_at_offset_ms` — are stamped with the **frozen** offset, not with `now_ms`. That
        is what makes the first DDS-stage event land at the offset the transition began at rather
        than one hand-over later, and what keeps every later offset continuous with the frozen
        value (after the write, `wall_elapsed - paused_total_ms` equals that same offset again).
        """
        from_stage = self.active_stage
        ctx = self._ctx(
            actor=actor, role_type=None, now_ms=now_ms, runtime=runtime, stage=from_stage
        )
        new_state = SESSION_STATE_MACHINE.fire(self.state, "finish_role_transition", ctx)
        assert from_stage is not None  # the guard denies a session with no started stage
        to_stage = self.next_stage_after(from_stage)
        assert to_stage is not None  # `guard_pause_elapsed_and_next_assigned` checked this
        # The log is the fallback for a session whose row predates the column (the stamp and
        # `ROLE_TRANSITION_STARTED.monotonic_offset_ms` are the same number by construction), and
        # `now_ms` the fallback for neither being there — a zero-length pause, never a negative one.
        frozen_ms = self.role_transition_started_offset_ms
        if frozen_ms is None:
            frozen_ms = runtime.transition_started_ms
        if frozen_ms is None:
            frozen_ms = now_ms
        paused_ms = self.paused_total_ms + max(0, now_ms - frozen_ms)
        started = to_stage.model_copy(update={"started_at_offset_ms": frozen_ms})
        updated = self.model_copy(
            update={
                "state": new_state,
                "stages": self._with_stage(started),
                "paused_total_ms": paused_ms,
                "role_transition_started_offset_ms": None,
            }
        )
        events = [
            self._event(
                EventType.ROLE_TRANSITION_COMPLETED,
                actor=_SIMULATION,
                now_ms=frozen_ms,
                payload={
                    "to_role_stage_id": str(started.role_stage_id),
                    "to_role_type": started.role_type.value,
                    "incident_id": str(self.incident.incident_id),
                    "at_offset_ms": frozen_ms,
                },
            ),
            updated._role_stage_started(started, now_ms=frozen_ms),
        ]
        return updated, events

    def complete(
        self,
        completed_at: datetime,
        *,
        total_events: int,
        actor: ActorRef,
        now_ms: int = 0,
        runtime: GuardRuntime = NO_RUNTIME_FACTS,
    ) -> tuple[SimulationSession, list[DomainEvent]]:
        """`ACTIVE --complete--> COMPLETED` (SYSTEM). Emits `SESSION_COMPLETED`.

        `total_events` counts the session's event-log rows *including* the `SESSION_COMPLETED`
        row this call produces. Only the event store knows it — `next_seq_no` is deliberately not
        a field of this aggregate — so it is a required keyword the completing use case supplies
        (`app.application.handoff.complete_session`, which holds the repository), rather than a
        number this pure aggregate invents.
        """
        ctx = self._ctx(
            actor=actor, role_type=None, now_ms=now_ms, runtime=runtime, stage=self.active_stage
        )
        new_state = SESSION_STATE_MACHINE.fire(self.state, "complete", ctx)
        updated = self.model_copy(update={"state": new_state, "completed_at": completed_at})
        event = self._event(
            EventType.SESSION_COMPLETED,
            actor=_SIMULATION,
            now_ms=now_ms,
            payload={
                "at_offset_ms": now_ms,
                "final_session_state": new_state.value,
                "total_events": total_events,
            },
        )
        return updated, [event]

    # -- stage-level behaviour ---------------------------------------------------------------

    def fire_stage_trigger(
        self,
        stage_id: RoleStageId,
        trigger: str,
        *,
        actor: ActorRef,
        now_ms: int = 0,
        runtime: GuardRuntime = NO_RUNTIME_FACTS,
        card: Any = None,
        assignment: Any = None,
        resources: Mapping[str, Any] | None = None,
    ) -> tuple[SimulationSession, list[DomainEvent]]:
        """Fire `trigger` on one stage through `ROLE_MODULES[stage.role_type].state_machine`.

        Emits `STAGE_STATE_CHANGED`, plus `ROLE_STAGE_COMPLETED` when the target state is
        terminal — and nothing else.

        The trigger-specific event named by `Transition.emits` (`HANDOFF_CREATED`,
        `DDS_ACKNOWLEDGED`, `RESOURCE_DISPATCHED`, `DDS_INCIDENT_CLOSED`) needs payload this
        aggregate does not hold — the handoff snapshot id, the dispatched resource ids — so the
        owning use case appends it alongside the events returned here, which is what E7 already
        does for `CALL_RINGING` / `CALL_ANSWERED` (`app.application.operator`), what
        `app.application.handoff.create_handoff` does for `HANDOFF_CREATED`, and what
        `app.application.dds` does for `DDS_ACKNOWLEDGED`, `RESOURCE_DISPATCHED` and
        `DDS_INCIDENT_CLOSED` — each of those three is appended by the command that fired the
        trigger, in the `x-emits` order its operation declares.
        """
        stage = self.stage(stage_id)
        previous_state = stage.state
        module = _role_modules()[stage.role_type]
        ctx = self._ctx(
            actor=actor,
            role_type=stage.role_type,
            now_ms=now_ms,
            runtime=runtime,
            stage=stage,
            card=card,
            assignment=assignment,
            resources=resources,
        )
        target: StageState = module.state_machine.fire(stage.state, trigger, ctx)
        is_terminal = target in TERMINAL_STAGE_STATES
        moved = stage.model_copy(
            update={
                "state": target,
                "completed_at_offset_ms": now_ms if is_terminal else stage.completed_at_offset_ms,
            }
        )
        updated = self.model_copy(update={"stages": self._with_stage(moved)})
        events = [
            self._stage_state_changed(
                stage=moved,
                previous_state=previous_state,
                trigger=trigger,
                actor=actor,
                now_ms=now_ms,
            )
        ]
        if is_terminal:
            events.append(updated._role_stage_completed(moved, now_ms=now_ms))
        return updated, events


# ---------------------------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------------------------


def _bind_participants(
    stages: tuple[RoleStage, ...],
    participants: tuple[SessionParticipant, ...],
    rule: ParticipantAssignmentRule,
) -> tuple[RoleStage, ...]:
    """Set `RoleStage.participant_user_id` wherever the `assignment_rule` determines it.

    Best effort by design: a participant set the rule cannot satisfy simply leaves stages unbound,
    and `guard_scenario_valid_and_participants_assigned` refuses the `validate` transition. The
    factory never raises over participants.
    """
    if rule is ParticipantAssignmentRule.SINGLE_STAGE_ONE_PARTICIPANT:
        if len(participants) != 1 or participants[0].assigned_role_type is None:
            return stages
        only = participants[0]
        return tuple(
            stage.model_copy(update={"participant_user_id": only.user_id})
            if stage.role_type is only.assigned_role_type
            else stage
            for stage in stages
        )
    if rule is ParticipantAssignmentRule.ALL_STAGES_ONE_PARTICIPANT:
        if len(participants) != 1:
            return stages
        only = participants[0]
        return tuple(
            stage.model_copy(update={"participant_user_id": only.user_id}) for stage in stages
        )

    role_chain = {stage.role_type for stage in stages}
    if any(p.assigned_role_type not in role_chain for p in participants):
        return stages
    bound: list[RoleStage] = []
    for stage in stages:
        matching = [p for p in participants if p.assigned_role_type is stage.role_type]
        if len(matching) == 1:
            bound.append(stage.model_copy(update={"participant_user_id": matching[0].user_id}))
        else:
            bound.append(stage)
    return tuple(bound)


def create_session(
    *,
    session_id: SessionId,
    incident_id: IncidentId,
    stage_ids: Sequence[RoleStageId],
    scenario_version: ScenarioVersion,
    scenario_id: ScenarioId,
    scenario_slug: str,
    session_mode: SessionMode,
    created_by: ActorRef,
    participants: Sequence[tuple[UserId, RoleType | None]] = (),
    participant_ids: Sequence[UUID] | None = None,
    session_seed: str | None = None,
    time_scale: float = 1.0,
    variants: SessionVariants | None = None,
) -> tuple[SimulationSession, list[DomainEvent]]:
    """Build a `CREATED` session with its one `Incident` and one `RoleStage` per entry of the
    **effective** role chain, and return it with the `SESSION_CREATED` event (§10.8, §10.10, D6,
    HLD 70 §70.2.4).

    `variants` are the resolved switches (`resolve_variants`); `None` resolves an empty request
    against the scenario, i.e. takes the scenario default. `card_source` decides the effective
    chain: `CALLER_VOICE` runs the scenario's `role_chain`, `GENERATED_CARD` the suffix starting
    at DDS (`effective_role_chain`). `SESSION_CREATED.role_chain` records the effective chain and
    the additive `scenario_role_chain` the scenario's; `SESSION_CREATED.variants` records the
    switches. An empty effective chain (`GENERATED_CARD` on a chain without DDS) is
    `VariantNotSupportedError`.

    Every id is passed in: the domain calls neither `uuid4` nor a clock. `session_seed` defaults to
    `scenario_version.deterministic_seed` (D7, SPEC §42 test 7).

    Two *structural* rejections happen here, because their subject is the session's very existence:

    - `PrefabHandoffRequiredError` when the policy's `requires_prefab_handoff_for_dds_only` holds,
      the `role_chain` is exactly `[DDS]`, and the scenario has no
      `expected_response.prefab_handoff` — there would be no 112 stage to produce the handoff the
      DDS stage starts from (D6, §10.10, `409 PREFAB_HANDOFF_REQUIRED`).
    - `RoleChainLengthError` when `policy.role_chain_length` is `"EXACTLY_ONE"` and the
      effective chain has a different length — so `SINGLE_ROLE` accepts a two-stage scenario run
      under `GENERATED_CARD`, whose effective chain is `[DDS]`.

    A participant set that does not satisfy the policy's `assignment_rule` is NOT rejected here:
    stages stay unbound and `validate` refuses the transition to `READY`.
    """
    policy = SESSION_POLICIES[session_mode]
    if variants is None:
        variants = resolve_variants(PartialVariants(), scenario_version.scenario_variants)
    role_chain = effective_role_chain(scenario_version.role_chain, variants.card_source)
    if not role_chain:
        raise VariantNotSupportedError("card_source", variants.card_source.value)

    if policy.role_chain_length == "EXACTLY_ONE" and len(role_chain) != 1:
        raise RoleChainLengthError(
            f"session mode {session_mode.value} requires exactly one role_chain entry, "
            f"got {len(role_chain)}"
        )
    if (
        policy.requires_prefab_handoff_for_dds_only
        and tuple(role_chain) == (RoleType.DDS,)
        and scenario_version.expected_response.prefab_handoff is None
    ):
        raise PrefabHandoffRequiredError(
            f"session mode {session_mode.value} with role_chain [DDS] needs "
            "expected_response.prefab_handoff"
        )
    if len(stage_ids) != len(role_chain):
        raise ValueError(
            f"create_session needs one stage id per role_chain entry: got {len(stage_ids)} "
            f"for {len(role_chain)} roles"
        )
    if participant_ids is not None and len(participant_ids) != len(participants):
        raise ValueError("create_session needs one participant id per participant, or none")
    created_by_user_id = created_by.actor_id
    if created_by_user_id is None:
        raise ValueError("create_session needs a created_by ActorRef carrying an actor_id")

    incident = Incident(
        incident_id=incident_id,
        session_id=session_id,
        scenario_version_id=scenario_version.id,
        created_at_offset_ms=0,
    )
    modules = _role_modules()
    stages = tuple(
        RoleStage(
            role_stage_id=stage_ids[index],
            session_id=session_id,
            incident_id=incident_id,
            role_type=role_type,
            order_index=index,
            state=cast("StageState", modules[role_type].initial_state()),
        )
        for index, role_type in enumerate(role_chain)
    )
    session_participants = tuple(
        SessionParticipant(
            user_id=user_id,
            assigned_role_type=role_type,
            participant_id=None if participant_ids is None else participant_ids[index],
        )
        for index, (user_id, role_type) in enumerate(participants)
    )
    stages = _bind_participants(stages, session_participants, policy.assignment_rule)

    session = SimulationSession(
        id=session_id,
        scenario_version_id=scenario_version.id,
        session_mode=session_mode,
        state=SessionState.CREATED,
        session_seed=session_seed or scenario_version.deterministic_seed,
        time_scale=time_scale,
        created_by_user_id=created_by_user_id,
        incident=incident,
        stages=stages,
        participants=session_participants,
        variants=variants,
    )
    payload: Mapping[str, Any] = {
        "session_id": str(session_id),
        "scenario_id": str(scenario_id),
        "scenario_version_id": str(scenario_version.id),
        "scenario_slug": scenario_slug,
        "scenario_version": scenario_version.version,
        "session_mode": session_mode.value,
        "session_seed": session.session_seed,
        "time_scale": session.time_scale,
        "role_chain": [role.value for role in role_chain],
        "created_by_user_id": str(created_by_user_id),
        "variants": variants_payload(variants),
        "scenario_role_chain": [role.value for role in scenario_version.role_chain],
    }
    validate_payload(EventType.SESSION_CREATED, payload)
    event = DomainEvent(
        event_type=EventType.SESSION_CREATED,
        actor=created_by,
        monotonic_offset_ms=0,
        payload=payload,
    )
    return session, [event]

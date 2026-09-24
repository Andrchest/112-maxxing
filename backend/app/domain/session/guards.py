"""The guard callables named by `session/transitions.py`, and the guard registries
`SESSION_GUARDS`, `OPERATOR_112_GUARDS`, `DDS_GUARDS` and — I3 E5a — `DDS_GUARDS_MEMO` (HLD
`10-domain-model.md` §10.8, SPEC §7; HLD 70 §70.4.4).

Every `guard_name` appearing in `SESSION_TRANSITIONS`, `OPERATOR_112_TRANSITIONS` and
`DDS_TRANSITIONS` is registered in exactly one of the three mappings below; `StateMachine` denies
a transition whose named guard is missing, so an unregistered name would silently freeze a
machine. `tests/unit/domain/session/test_guard_registration.py` asserts the coverage.

Purity (D2): a guard reads only `GuardContext` — the session aggregate, the `RoleStage`, the
read-only `card`/`assignment`/`resources` projections, and `GuardContext.runtime`
(`GuardRuntime`), which carries the facts the *application* derives from the event log, the health
registry and the transport ports. No guard performs I/O, reads a clock or touches a repository.

Import direction: `roles/operator112.py` and `roles/dds.py` import this module to build their
`RoleModule.state_machine`, and `session/session.py` imports `roles/registry.py`. This module
therefore must not import `session/session.py` at runtime — `SimulationSession` and `RoleStage`
are imported under `TYPE_CHECKING` only and reached through `cast`, exactly as the E3 ruling that
typed `GuardContext.session`/`stage` as `Any` anticipated.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from app.domain.common.state_machine import GuardContext
from app.domain.enums import (
    DDSStageState,
    Operator112StageState,
    ResourceStatus,
    RoleType,
    SessionState,
)
from app.domain.session.policy import ParticipantAssignmentRule

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from app.domain.session.session import RoleStage, SimulationSession

TERMINAL_STAGE_STATES: frozenset[Operator112StageState | DDSStageState] = frozenset(
    {Operator112StageState.STAGE_COMPLETED, DDSStageState.CLOSED}
)
"""The terminal state of every implemented `RoleModule`, as one flat set.

`tests/unit/domain/session/test_guards.py` pins this literal set equal to the union of
`terminal_states()` over the implemented `ROLE_MODULES`, so adding a role with a different
terminal state cannot silently leave this set stale.
"""

_RESOURCE_PROGRESSION: tuple[ResourceStatus, ...] = (
    ResourceStatus.AVAILABLE,
    ResourceStatus.SELECTED,
    ResourceStatus.DISPATCHED,
    ResourceStatus.EN_ROUTE,
    ResourceStatus.ON_SCENE,
    ResourceStatus.WORKING,
    ResourceStatus.RETURNING,
)
"""The forward progression of `RESOURCE_STATUS_TRANSITIONS` (§10.7).

`OUT_OF_SERVICE` and `UNAVAILABLE` are deliberately absent: they are side exits, not points on the
progression, so "reached EN_ROUTE" is false for a resource that broke down before departing.
"""


# ---------------------------------------------------------------------------------------------
# Small typed accessors (`GuardContext.session`/`stage` are `Any` — see the module docstring)
# ---------------------------------------------------------------------------------------------


def _session(ctx: GuardContext) -> SimulationSession | None:
    return cast("SimulationSession | None", ctx.session)


def _stage(ctx: GuardContext) -> RoleStage | None:
    return cast("RoleStage | None", ctx.stage)


def _is_terminal(stage: RoleStage) -> bool:
    return stage.state in TERMINAL_STAGE_STATES


def _reached(ctx: GuardContext, status: ResourceStatus) -> bool:
    """True when some projected resource is at `status` or later in `_RESOURCE_PROGRESSION`.

    Status-based, and that is now the settled reading. §10.7's five per-resource timestamps
    (`dispatched_at`, `departed_at`, `arrived_at`, `work_started_at`, `returning_at`) all collapse
    into the single `EmergencyResource.status_changed_at_offset_ms` — the moment the *current*
    status was entered (`dds/resources.py`) — so the domain holds no per-resource history a richer
    reading could be built from, and inventing one would mean a new field on a §10.7 type.

    Two consequences, both intended. A resource past `status` and back (`RETURNING` after
    `WORKING`) still counts as having reached it, which is true. A resource that left the
    progression sideways (`OUT_OF_SERVICE`, `UNAVAILABLE`) stops counting — but the DDS stage
    triggers this guard serves are monotonic and are fired by `app.application.dds.stage_automation`
    on the same tick the movement happened, so a unit that breaks down later cannot take the stage
    back to `DISPATCHED`. That application also passes **only the units attached to the stage's
    assignment legs** (E9 analyst R6): `ResourceAvailability.initial_status` may be any status, so
    a scenario unit that starts `WORKING` elsewhere must not satisfy `first_en_route` on its own.
    """
    if ctx.resources is None:
        return False
    index = _RESOURCE_PROGRESSION.index(status)
    for resource in ctx.resources.values():
        current = getattr(resource, "current_status", None)
        if current in _RESOURCE_PROGRESSION and _RESOURCE_PROGRESSION.index(current) >= index:
            return True
    return False


def _participant_cardinality_holds(session: SimulationSession) -> bool:
    """The `SessionPolicy.assignment_rule` cardinality of §10.10 / this task's brief, plus the
    ДДС service binding (HLD 70 §70.4.5, I3 E5b): only a participant who plays the DDS stage may
    be bound to a service, and bound services are distinct. Under `ONE_PARTICIPANT_PER_STAGE` the
    DDS stage may hold several participants exactly when every one of them is bound."""
    if not _service_binding_holds(session):
        return False
    rule = session.policy.assignment_rule
    participants = session.participants
    if rule is ParticipantAssignmentRule.SINGLE_STAGE_ONE_PARTICIPANT:
        return len(participants) == 1 and participants[0].assigned_role_type is not None
    if rule is ParticipantAssignmentRule.ALL_STAGES_ONE_PARTICIPANT:
        return len(participants) == 1
    role_chain = {stage.role_type for stage in session.stages}
    if any(p.assigned_role_type not in role_chain for p in participants):
        return False
    for stage in session.stages:
        matching = [p for p in participants if p.assigned_role_type is stage.role_type]
        if len(matching) == 1:
            continue
        several_bound_dds = stage.role_type is RoleType.DDS and all(
            p.assigned_service_id is not None for p in matching
        )
        if not (len(matching) > 1 and several_bound_dds):
            return False
    return True


def _service_binding_holds(session: SimulationSession) -> bool:
    """Every `assigned_service_id` is non-empty, distinct, and held by a participant who plays the
    DDS stage (assigned `DDS`, or the one participant of `ALL_STAGES_ONE_PARTICIPANT`) of a chain
    that has one."""
    bound = [p for p in session.participants if p.assigned_service_id is not None]
    if not bound:
        return True
    if not any(stage.role_type is RoleType.DDS for stage in session.stages):
        return False
    services = [str(p.assigned_service_id) for p in bound]
    if any(service == "" for service in services) or len(set(services)) != len(services):
        return False
    all_stages = (
        session.policy.assignment_rule is ParticipantAssignmentRule.ALL_STAGES_ONE_PARTICIPANT
    )
    return all(
        p.assigned_role_type is RoleType.DDS or (all_stages and p.assigned_role_type is None)
        for p in bound
    )


# ---------------------------------------------------------------------------------------------
# Session guards (§10.8 "Session state machine")
# ---------------------------------------------------------------------------------------------


def guard_scenario_valid_and_participants_assigned(ctx: GuardContext) -> bool:
    """`CREATED --validate--> READY`: the scenario version passed validation, the policy's
    assignment-rule cardinality holds for the participant set, and every `RoleStage` is bound to a
    participant.

    This is where a participant set the factory could not bind surfaces: `create_session` builds
    the aggregate regardless, so a bad set is reported as an `InvalidTransitionError` on
    `validate` rather than as a construction failure (§10.8's "`assignment_rule` is satisfiable
    for the participant set").
    """
    session = _session(ctx)
    if session is None or not ctx.runtime.scenario_valid:
        return False
    if not _participant_cardinality_holds(session):
        return False
    return all(stage.participant_user_id is not None for stage in session.stages)


def guard_inference_ready(ctx: GuardContext) -> bool:
    """`READY --start--> ACTIVE`: every required inference component is `READY`, or
    `REQUIRE_INFERENCE_READY` is false (D8) — the application collapses both into the flag."""
    return ctx.runtime.inference_ready


def guard_stage_terminal_and_next_exists(ctx: GuardContext) -> bool:
    """`ACTIVE --begin_role_transition--> ROLE_TRANSITION`: the stage that has been running is in
    its terminal state and `role_chain` has a next entry."""
    session, stage = _session(ctx), _stage(ctx)
    if session is None or stage is None or not _is_terminal(stage):
        return False
    return session.next_stage_after(stage) is not None


def guard_stage_terminal_and_last(ctx: GuardContext) -> bool:
    """`ACTIVE --complete--> COMPLETED`: the running stage is terminal and is the last
    `role_chain` entry."""
    session, stage = _session(ctx), _stage(ctx)
    if session is None or stage is None or not _is_terminal(stage):
        return False
    return session.next_stage_after(stage) is None


def guard_pause_elapsed_and_next_assigned(ctx: GuardContext) -> bool:
    """`ROLE_TRANSITION --finish_role_transition--> ACTIVE`: `now_ms >= transition_started_ms +
    policy.transition_pause_seconds * 1000` and the next stage has an assigned participant."""
    session, stage = _session(ctx), _stage(ctx)
    if session is None or stage is None:
        return False
    started_ms = ctx.runtime.transition_started_ms
    if started_ms is None:
        return False
    if ctx.now_ms < started_ms + session.policy.transition_pause_seconds * 1000:
        return False
    next_stage = session.next_stage_after(stage)
    return next_stage is not None and next_stage.participant_user_id is not None


SESSION_GUARDS: Mapping[str, Callable[[GuardContext], bool]] = {
    "guard_scenario_valid_and_participants_assigned": (
        guard_scenario_valid_and_participants_assigned
    ),
    "guard_inference_ready": guard_inference_ready,
    "guard_stage_terminal_and_next_exists": guard_stage_terminal_and_next_exists,
    "guard_stage_terminal_and_last": guard_stage_terminal_and_last,
    "guard_pause_elapsed_and_next_assigned": guard_pause_elapsed_and_next_assigned,
}


# ---------------------------------------------------------------------------------------------
# Stage guards shared by both implemented role modules
# ---------------------------------------------------------------------------------------------


def guard_participant_assigned_to_stage(ctx: GuardContext) -> bool:
    """The firing actor is the participant bound to this `RoleStage` (`answer`, `acknowledge`).

    An unbound stage (`participant_user_id is None`) denies every actor, including an actor whose
    `actor_id` is also `None`.
    """
    stage = _stage(ctx)
    if stage is None or stage.participant_user_id is None:
        return False
    return ctx.actor.actor_id == stage.participant_user_id


# ---------------------------------------------------------------------------------------------
# Operator 112 stage guards (§10.8 "Operator 112 stage machine")
# ---------------------------------------------------------------------------------------------


def guard_session_active_and_transport_ready(ctx: GuardContext) -> bool:
    """`WAITING_FOR_CALL --ring--> RINGING`: the session is `ACTIVE` and the `CallTransport`
    reports the caller joined."""
    session = _session(ctx)
    if session is None or session.state is not SessionState.ACTIVE:
        return False
    return ctx.runtime.transport_ready


def guard_first_finalized_turn(ctx: GuardContext) -> bool:
    """`CONNECTED --begin_interview--> INTERVIEW`: the first `ASR_FINAL` for this call landed."""
    return ctx.runtime.first_finalized_turn


def guard_call_still_connected(ctx: GuardContext) -> bool:
    """`HANDOFF_PREPARATION --back_to_interview--> INTERVIEW`: there is no going back to the
    interview once the call is over."""
    return ctx.runtime.call_connected and not ctx.runtime.call_ended


def guard_call_ended(ctx: GuardContext) -> bool:
    """`HANDED_OFF --complete_stage--> STAGE_COMPLETED`: `CALL_ENDED` has been appended."""
    return ctx.runtime.call_ended


def guard_at_least_one_recipient_service(ctx: GuardContext) -> bool:
    """`HANDOFF_PREPARATION --create_handoff--> HANDED_OFF`:
    `len(card.values["recipients.services"]) >= 1`. No card projection at all denies."""
    if ctx.card is None:
        return False
    values = cast("Mapping[str, Any]", getattr(ctx.card, "values", {}))
    services = values.get("recipients.services")
    if not isinstance(services, Sequence) or isinstance(services, str | bytes):
        return False
    return len(services) >= 1


OPERATOR_112_GUARDS: Mapping[str, Callable[[GuardContext], bool]] = {
    "guard_session_active_and_transport_ready": guard_session_active_and_transport_ready,
    "guard_participant_assigned_to_stage": guard_participant_assigned_to_stage,
    "guard_first_finalized_turn": guard_first_finalized_turn,
    "guard_call_still_connected": guard_call_still_connected,
    "guard_at_least_one_recipient_service": guard_at_least_one_recipient_service,
    "guard_call_ended": guard_call_ended,
}


# ---------------------------------------------------------------------------------------------
# DDS stage guards (§10.8 "DDS stage machine")
# ---------------------------------------------------------------------------------------------


def guard_at_least_one_selected_available(ctx: GuardContext) -> bool:
    """`dispatch` / `dispatch_additional`: at least one projected resource is in `SELECTED`."""
    if ctx.resources is None:
        return False
    return any(
        getattr(resource, "current_status", None) is ResourceStatus.SELECTED
        for resource in ctx.resources.values()
    )


def guard_no_resource_selected(ctx: GuardContext) -> bool:
    """`RESOURCE_SELECTION --back_to_acknowledged--> ACKNOWLEDGED`: nothing is `SELECTED`, so
    stepping back loses no work."""
    if ctx.resources is None:
        return True
    return not any(
        getattr(resource, "current_status", None) is ResourceStatus.SELECTED
        for resource in ctx.resources.values()
    )


def guard_additional_dispatch_allowed(ctx: GuardContext) -> bool:
    """`DISPATCHED --open_resource_selection--> RESOURCE_SELECTION`: no dispatched resource has
    reached `EN_ROUTE` yet."""
    return not _reached(ctx, ResourceStatus.EN_ROUTE)


def guard_any_dispatched_reached_en_route(ctx: GuardContext) -> bool:
    """`DISPATCHED --first_en_route--> EN_ROUTE`."""
    return _reached(ctx, ResourceStatus.EN_ROUTE)


def guard_any_dispatched_reached_on_scene(ctx: GuardContext) -> bool:
    """`EN_ROUTE --first_arrived--> ARRIVED`."""
    return _reached(ctx, ResourceStatus.ON_SCENE)


def guard_any_dispatched_reached_working(ctx: GuardContext) -> bool:
    """`ARRIVED --work_started--> WORKING`."""
    return _reached(ctx, ResourceStatus.WORKING)


def guard_resolution_condition(ctx: GuardContext) -> bool:
    """`WORKING --incident_resolved--> RESOLVED`: the scenario's
    `expected_response.resolution_condition` evaluates true.

    Evaluating the `Condition` against the live `WorldState` belongs to the world-engine /
    simulation slice, not to this pure domain guard, which only reads the projected verdict.
    `app.application.simulation.tick_session.TickSession.resolution_condition_met` (E6) is what
    computes it; `app.api.container` binds that method as the verdict source.
    """
    return ctx.runtime.resolution_condition_met


def _memo_mode(session: SimulationSession | None) -> bool:
    """The session runs `dds_mode: MEMO_STATUSES` (HLD 70 §70.2.4) — read off the aggregate."""
    if session is None:
        return False
    variants = getattr(session, "variants", None)
    mode = getattr(variants, "dds_mode", None)
    return getattr(mode, "value", mode) == "MEMO_STATUSES"


def memo_all_legs_terminal(ctx: GuardContext) -> bool:
    """`ACKNOWLEDGED --close--> RESOLVED` (I3 E5a, HLD 70 §70.4.4, D16): `dds_mode =
    MEMO_STATUSES` **and** every leg is `COMPLETED`, `NOT_ACCEPTED` or `REFUSED`.

    Registered in the picker registry too, where it always denies — which is what keeps the
    additive row invisible to picker sessions. The legs' verdict arrives as
    `GuardRuntime.all_legs_terminal`, projected by the application from the legs it loaded.
    """
    return _memo_mode(_session(ctx)) and ctx.runtime.all_legs_terminal


def guard_any_dds_participant(ctx: GuardContext) -> bool:
    """The memo reading of `guard_participant_assigned_to_stage` (HLD 70 §70.4.4): the firing
    actor is **any** ДДС participant of the session — the stage's own, or one assigned `DDS`
    (several ДДС trainees share the one DDS stage, §70.4.5)."""
    stage, session = _stage(ctx), _session(ctx)
    actor_id = ctx.actor.actor_id
    if actor_id is None:
        return False
    if stage is not None and stage.participant_user_id == actor_id:
        return True
    if session is None:
        return False
    return bool(session.plays_dds(actor_id))


DDS_GUARDS: Mapping[str, Callable[[GuardContext], bool]] = {
    "guard_participant_assigned_to_stage": guard_participant_assigned_to_stage,
    "memo_all_legs_terminal": memo_all_legs_terminal,
    "guard_at_least_one_selected_available": guard_at_least_one_selected_available,
    "guard_no_resource_selected": guard_no_resource_selected,
    "guard_additional_dispatch_allowed": guard_additional_dispatch_allowed,
    "guard_any_dispatched_reached_en_route": guard_any_dispatched_reached_en_route,
    "guard_any_dispatched_reached_on_scene": guard_any_dispatched_reached_on_scene,
    "guard_any_dispatched_reached_working": guard_any_dispatched_reached_working,
    "guard_resolution_condition": guard_resolution_condition,
}

DDS_GUARDS_MEMO: Mapping[str, Callable[[GuardContext], bool]] = {
    "guard_participant_assigned_to_stage": guard_any_dds_participant,
    "memo_all_legs_terminal": memo_all_legs_terminal,
}
"""The memo registry (HLD 70 §70.4.4), for the machine over `MEMO_DDS_TRANSITIONS`.

It holds exactly the guards that view's rows name. The resource-driven guards §70.4.4 says "deny
there" are absent because their rows are: the memo machine has no `dispatch`, `first_en_route`,
`incident_resolved`, … row to fire, so each is refused before any guard is asked.
"""

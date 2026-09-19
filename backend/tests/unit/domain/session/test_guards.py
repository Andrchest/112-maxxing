"""One allow case and one deny case for every guard named in the three §10.8 transition tables.

Every case is driven through the *real* machine (`SESSION_STATE_MACHINE.can_fire` /
`ROLE_MODULES[role].state_machine.can_fire`) rather than by calling the guard function, so a guard
that is registered under the wrong name, or wired into the wrong machine, fails here too. The
actor/role of each case is one the row's `allowed_actors`/`allowed_roles` permits, so the only
thing that can flip `can_fire` is the guard itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from app.domain.common.state_machine import GuardContext, GuardRuntime, StateMachine
from app.domain.enums import (
    ActorType,
    DDSStageState,
    Operator112StageState,
    ResourceStatus,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.roles.registry import ROLE_MODULES
from app.domain.session.guards import TERMINAL_STAGE_STATES
from app.domain.session.machine import SESSION_STATE_MACHINE
from app.domain.session.session import SessionParticipant

from tests.unit.domain.session import _builders as b

OP = RoleType.OPERATOR_112
DDS = RoleType.DDS
NO_FACTS = GuardRuntime()


def _op_machine() -> StateMachine[Any]:
    return ROLE_MODULES[OP].state_machine


def _dds_machine() -> StateMachine[Any]:
    return ROLE_MODULES[DDS].state_machine


# ---------------------------------------------------------------------------------------------
# TERMINAL_STAGE_STATES is not a hand-maintained literal
# ---------------------------------------------------------------------------------------------


def test_terminal_stage_states_equals_union_of_implemented_role_modules() -> None:
    union: set[Any] = set()
    for module in ROLE_MODULES.values():
        if module.implemented:
            union |= set(module.terminal_states())
    assert set(TERMINAL_STAGE_STATES) == union


# ---------------------------------------------------------------------------------------------
# Session guards
# ---------------------------------------------------------------------------------------------


def _two_stage_session(
    *,
    state: SessionState,
    first_state: Operator112StageState,
    second_state: DDSStageState,
    bind_second: bool = True,
    first_started_ms: int | None = 0,
) -> Any:
    stages = [
        b.build_stage(
            order_index=0,
            role_type=OP,
            state=first_state,
            participant_user_id=b.user("op"),
            started_at_offset_ms=first_started_ms,
        ),
        b.build_stage(
            order_index=1,
            role_type=DDS,
            state=second_state,
            participant_user_id=b.user("dds") if bind_second else None,
        ),
    ]
    return b.build_session(
        session_mode=SessionMode.MULTI_TRAINEE,
        state=state,
        stages=stages,
        participants=[
            SessionParticipant(user_id=b.user("op"), assigned_role_type=OP),
            SessionParticipant(user_id=b.user("dds"), assigned_role_type=DDS),
        ],
    )


def _session_case(
    session: Any, trigger: str, *, actor: Any, now_ms: int = 0, runtime: GuardRuntime, stage: Any
) -> bool:
    ctx = GuardContext(actor=actor, now_ms=now_ms, session=session, stage=stage, runtime=runtime)
    return SESSION_STATE_MACHINE.can_fire(session.state, trigger, ctx)


def test_guard_scenario_valid_and_participants_assigned_allows() -> None:
    session = _two_stage_session(
        state=SessionState.CREATED,
        first_state=Operator112StageState.WAITING_FOR_CALL,
        second_state=DDSStageState.RECEIVED,
        first_started_ms=None,
    )
    assert _session_case(
        session,
        "validate",
        actor=b.SYSTEM,
        runtime=GuardRuntime(scenario_valid=True),
        stage=session.current_stage,
    )


@pytest.mark.parametrize(
    "scenario_valid,bind_second",
    [(False, True), (True, False)],
    ids=["scenario-invalid", "second-stage-unbound"],
)
def test_guard_scenario_valid_and_participants_assigned_denies(
    scenario_valid: bool, bind_second: bool
) -> None:
    session = _two_stage_session(
        state=SessionState.CREATED,
        first_state=Operator112StageState.WAITING_FOR_CALL,
        second_state=DDSStageState.RECEIVED,
        bind_second=bind_second,
        first_started_ms=None,
    )
    assert not _session_case(
        session,
        "validate",
        actor=b.SYSTEM,
        runtime=GuardRuntime(scenario_valid=scenario_valid),
        stage=session.current_stage,
    )


def test_guard_scenario_valid_denies_when_cardinality_broken() -> None:
    """`ONE_PARTICIPANT_PER_STAGE` with a participant whose role is outside the chain."""
    stages = [
        b.build_stage(
            order_index=0,
            role_type=OP,
            state=Operator112StageState.WAITING_FOR_CALL,
            participant_user_id=b.user("op"),
        )
    ]
    session = b.build_session(
        session_mode=SessionMode.MULTI_TRAINEE,
        state=SessionState.CREATED,
        stages=stages,
        participants=[
            SessionParticipant(user_id=b.user("op"), assigned_role_type=OP),
            SessionParticipant(user_id=b.user("dds"), assigned_role_type=DDS),
        ],
    )
    assert not _session_case(
        session,
        "validate",
        actor=b.SYSTEM,
        runtime=GuardRuntime(scenario_valid=True),
        stage=session.current_stage,
    )


@pytest.mark.parametrize("ready,expected", [(True, True), (False, False)], ids=["allow", "deny"])
def test_guard_inference_ready(ready: bool, expected: bool) -> None:
    session = _two_stage_session(
        state=SessionState.READY,
        first_state=Operator112StageState.WAITING_FOR_CALL,
        second_state=DDSStageState.RECEIVED,
        first_started_ms=None,
    )
    assert (
        _session_case(
            session,
            "start",
            actor=b.INSTRUCTOR,
            runtime=GuardRuntime(inference_ready=ready),
            stage=session.stages[0],
        )
        is expected
    )


@pytest.mark.parametrize(
    "first_state,expected",
    [
        (Operator112StageState.STAGE_COMPLETED, True),
        (Operator112StageState.INTERVIEW, False),
    ],
    ids=["allow", "deny-stage-not-terminal"],
)
def test_guard_stage_terminal_and_next_exists(
    first_state: Operator112StageState, expected: bool
) -> None:
    session = _two_stage_session(
        state=SessionState.ACTIVE,
        first_state=first_state,
        second_state=DDSStageState.RECEIVED,
    )
    assert (
        _session_case(
            session,
            "begin_role_transition",
            actor=b.SYSTEM,
            runtime=GuardRuntime(),
            stage=session.active_stage,
        )
        is expected
    )


def test_guard_stage_terminal_and_next_exists_denies_when_last_stage() -> None:
    stages = [
        b.build_stage(
            order_index=0,
            role_type=OP,
            state=Operator112StageState.STAGE_COMPLETED,
            participant_user_id=b.user("op"),
            started_at_offset_ms=0,
        )
    ]
    session = b.build_session(
        session_mode=SessionMode.SINGLE_ROLE, state=SessionState.ACTIVE, stages=stages
    )
    assert not _session_case(
        session,
        "begin_role_transition",
        actor=b.SYSTEM,
        runtime=GuardRuntime(),
        stage=session.active_stage,
    )


def test_guard_stage_terminal_and_last_allows() -> None:
    stages = [
        b.build_stage(
            order_index=0,
            role_type=OP,
            state=Operator112StageState.STAGE_COMPLETED,
            participant_user_id=b.user("op"),
            started_at_offset_ms=0,
        )
    ]
    session = b.build_session(
        session_mode=SessionMode.SINGLE_ROLE, state=SessionState.ACTIVE, stages=stages
    )
    assert _session_case(
        session, "complete", actor=b.SYSTEM, runtime=GuardRuntime(), stage=session.active_stage
    )


def test_guard_stage_terminal_and_last_denies_when_a_next_stage_exists() -> None:
    session = _two_stage_session(
        state=SessionState.ACTIVE,
        first_state=Operator112StageState.STAGE_COMPLETED,
        second_state=DDSStageState.RECEIVED,
    )
    assert not _session_case(
        session, "complete", actor=b.SYSTEM, runtime=GuardRuntime(), stage=session.active_stage
    )


@pytest.mark.parametrize(
    "now_ms,started_ms,bind_second,expected",
    [
        (10_000, 0, True, True),
        (9_999, 0, True, False),
        (10_000, None, True, False),
        (10_000, 0, False, False),
    ],
    ids=["allow", "deny-pause-not-elapsed", "deny-no-transition-start", "deny-next-unassigned"],
)
def test_guard_pause_elapsed_and_next_assigned(
    now_ms: int, started_ms: int | None, bind_second: bool, expected: bool
) -> None:
    session = _two_stage_session(
        state=SessionState.ROLE_TRANSITION,
        first_state=Operator112StageState.STAGE_COMPLETED,
        second_state=DDSStageState.RECEIVED,
        bind_second=bind_second,
    )
    assert session.policy.transition_pause_seconds == 10
    assert (
        _session_case(
            session,
            "finish_role_transition",
            actor=b.SYSTEM,
            now_ms=now_ms,
            runtime=GuardRuntime(transition_started_ms=started_ms),
            stage=session.active_stage,
        )
        is expected
    )


# ---------------------------------------------------------------------------------------------
# Operator 112 stage guards
# ---------------------------------------------------------------------------------------------


def _op_ctx(
    *,
    session_state: SessionState = SessionState.ACTIVE,
    stage_state: Operator112StageState,
    participant_bound: bool = True,
    actor: Any,
    runtime: GuardRuntime = NO_FACTS,
    card: Any = None,
) -> GuardContext:
    stage = b.build_stage(
        order_index=0,
        role_type=OP,
        state=stage_state,
        participant_user_id=b.user("op") if participant_bound else None,
        started_at_offset_ms=0,
    )
    session = b.build_session(
        session_mode=SessionMode.SINGLE_ROLE, state=session_state, stages=[stage]
    )
    return GuardContext(
        actor=actor, role_type=OP, session=session, stage=stage, card=card, runtime=runtime
    )


@pytest.mark.parametrize(
    "session_state,transport_ready,expected",
    [
        (SessionState.ACTIVE, True, True),
        (SessionState.ACTIVE, False, False),
        (SessionState.READY, True, False),
    ],
    ids=["allow", "deny-transport", "deny-session-not-active"],
)
def test_guard_session_active_and_transport_ready(
    session_state: SessionState, transport_ready: bool, expected: bool
) -> None:
    ctx = _op_ctx(
        session_state=session_state,
        stage_state=Operator112StageState.WAITING_FOR_CALL,
        actor=b.SIMULATION,
        runtime=GuardRuntime(transport_ready=transport_ready),
    )
    assert _op_machine().can_fire(Operator112StageState.WAITING_FOR_CALL, "ring", ctx) is expected


@pytest.mark.parametrize(
    "user_name,bound,expected",
    [("op", True, True), ("dds", True, False), ("op", False, False)],
    ids=["allow", "deny-other-user", "deny-stage-unbound"],
)
def test_guard_participant_assigned_to_stage_operator(
    user_name: str, bound: bool, expected: bool
) -> None:
    ctx = _op_ctx(
        stage_state=Operator112StageState.RINGING,
        participant_bound=bound,
        actor=b.actor(ActorType.TRAINEE, user_name),
    )
    assert _op_machine().can_fire(Operator112StageState.RINGING, "answer", ctx) is expected


@pytest.mark.parametrize("flag,expected", [(True, True), (False, False)], ids=["allow", "deny"])
def test_guard_first_finalized_turn(flag: bool, expected: bool) -> None:
    ctx = _op_ctx(
        stage_state=Operator112StageState.CONNECTED,
        actor=b.SIMULATION,
        runtime=GuardRuntime(first_finalized_turn=flag),
    )
    assert (
        _op_machine().can_fire(Operator112StageState.CONNECTED, "begin_interview", ctx) is expected
    )


@pytest.mark.parametrize(
    "connected,ended,expected",
    [(True, False, True), (True, True, False), (False, False, False)],
    ids=["allow", "deny-call-ended", "deny-not-connected"],
)
def test_guard_call_still_connected(connected: bool, ended: bool, expected: bool) -> None:
    ctx = _op_ctx(
        stage_state=Operator112StageState.HANDOFF_PREPARATION,
        actor=b.actor(ActorType.TRAINEE, "op"),
        runtime=GuardRuntime(call_connected=connected, call_ended=ended),
    )
    assert (
        _op_machine().can_fire(Operator112StageState.HANDOFF_PREPARATION, "back_to_interview", ctx)
        is expected
    )


@pytest.mark.parametrize("flag,expected", [(True, True), (False, False)], ids=["allow", "deny"])
def test_guard_call_ended(flag: bool, expected: bool) -> None:
    ctx = _op_ctx(
        stage_state=Operator112StageState.HANDED_OFF,
        actor=b.actor(ActorType.TRAINEE, "op"),
        runtime=GuardRuntime(call_ended=flag),
    )
    assert (
        _op_machine().can_fire(Operator112StageState.HANDED_OFF, "complete_stage", ctx) is expected
    )


@pytest.mark.parametrize(
    "services,expected",
    [(["FIRE_RESCUE"], True), ([], False), (None, False)],
    ids=["allow", "deny-empty", "deny-key-absent"],
)
def test_guard_at_least_one_recipient_service(services: Any, expected: bool) -> None:
    ctx = _op_ctx(
        stage_state=Operator112StageState.HANDOFF_PREPARATION,
        actor=b.actor(ActorType.TRAINEE, "op"),
        card=b.card(services),
    )
    assert (
        _op_machine().can_fire(Operator112StageState.HANDOFF_PREPARATION, "create_handoff", ctx)
        is expected
    )


def test_guard_at_least_one_recipient_service_denies_without_a_card_projection() -> None:
    ctx = _op_ctx(
        stage_state=Operator112StageState.HANDOFF_PREPARATION,
        actor=b.actor(ActorType.TRAINEE, "op"),
        card=None,
    )
    assert not _op_machine().can_fire(
        Operator112StageState.HANDOFF_PREPARATION, "create_handoff", ctx
    )


# ---------------------------------------------------------------------------------------------
# DDS stage guards
# ---------------------------------------------------------------------------------------------


def _dds_ctx(
    *,
    stage_state: DDSStageState,
    participant_bound: bool = True,
    actor: Any,
    runtime: GuardRuntime = NO_FACTS,
    board: Any = None,
) -> GuardContext:
    stage = b.build_stage(
        order_index=0,
        role_type=DDS,
        state=stage_state,
        participant_user_id=b.user("dds") if participant_bound else None,
        started_at_offset_ms=0,
    )
    session = b.build_session(
        session_mode=SessionMode.SINGLE_ROLE, state=SessionState.ACTIVE, stages=[stage]
    )
    return GuardContext(
        actor=actor, role_type=DDS, session=session, stage=stage, resources=board, runtime=runtime
    )


@pytest.mark.parametrize(
    "user_name,expected", [("dds", True), ("op", False)], ids=["allow", "deny"]
)
def test_guard_participant_assigned_to_stage_dds(user_name: str, expected: bool) -> None:
    ctx = _dds_ctx(stage_state=DDSStageState.RECEIVED, actor=b.actor(ActorType.TRAINEE, user_name))
    assert _dds_machine().can_fire(DDSStageState.RECEIVED, "acknowledge", ctx) is expected


@pytest.mark.parametrize(
    "board,expected",
    [
        (b.resources(ResourceStatus.SELECTED, ResourceStatus.AVAILABLE), True),
        (b.resources(ResourceStatus.AVAILABLE), False),
        (None, False),
    ],
    ids=["allow", "deny-none-selected", "deny-no-board"],
)
def test_guard_at_least_one_selected_available(board: Any, expected: bool) -> None:
    ctx = _dds_ctx(
        stage_state=DDSStageState.RESOURCE_SELECTION,
        actor=b.actor(ActorType.TRAINEE, "dds"),
        board=board,
    )
    assert _dds_machine().can_fire(DDSStageState.RESOURCE_SELECTION, "dispatch", ctx) is expected


@pytest.mark.parametrize(
    "board,expected",
    [
        (b.resources(ResourceStatus.AVAILABLE), True),
        (b.resources(ResourceStatus.SELECTED), False),
    ],
    ids=["allow", "deny"],
)
def test_guard_no_resource_selected(board: Any, expected: bool) -> None:
    ctx = _dds_ctx(
        stage_state=DDSStageState.RESOURCE_SELECTION,
        actor=b.actor(ActorType.TRAINEE, "dds"),
        board=board,
    )
    assert (
        _dds_machine().can_fire(DDSStageState.RESOURCE_SELECTION, "back_to_acknowledged", ctx)
        is expected
    )


@pytest.mark.parametrize(
    "board,expected",
    [
        (b.resources(ResourceStatus.DISPATCHED), True),
        (b.resources(ResourceStatus.EN_ROUTE), False),
    ],
    ids=["allow", "deny-already-en-route"],
)
def test_guard_additional_dispatch_allowed(board: Any, expected: bool) -> None:
    ctx = _dds_ctx(
        stage_state=DDSStageState.DISPATCHED,
        actor=b.actor(ActorType.TRAINEE, "dds"),
        board=board,
    )
    assert (
        _dds_machine().can_fire(DDSStageState.DISPATCHED, "open_resource_selection", ctx)
        is expected
    )


_REACHED_CASES: tuple[tuple[str, DDSStageState, str, ResourceStatus, ResourceStatus], ...] = (
    (
        "en_route",
        DDSStageState.DISPATCHED,
        "first_en_route",
        ResourceStatus.EN_ROUTE,
        ResourceStatus.DISPATCHED,
    ),
    (
        "on_scene",
        DDSStageState.EN_ROUTE,
        "first_arrived",
        ResourceStatus.ON_SCENE,
        ResourceStatus.EN_ROUTE,
    ),
    (
        "working",
        DDSStageState.ARRIVED,
        "work_started",
        ResourceStatus.WORKING,
        ResourceStatus.ON_SCENE,
    ),
)


@pytest.mark.parametrize(
    "name,state,trigger,allow_status,deny_status",
    _REACHED_CASES,
    ids=[c[0] for c in _REACHED_CASES],
)
def test_guard_any_dispatched_reached(
    name: str,
    state: DDSStageState,
    trigger: str,
    allow_status: ResourceStatus,
    deny_status: ResourceStatus,
) -> None:
    allow_ctx = _dds_ctx(stage_state=state, actor=b.SIMULATION, board=b.resources(allow_status))
    deny_ctx = _dds_ctx(stage_state=state, actor=b.SIMULATION, board=b.resources(deny_status))
    assert _dds_machine().can_fire(state, trigger, allow_ctx)
    assert not _dds_machine().can_fire(state, trigger, deny_ctx)


def test_guard_any_dispatched_reached_counts_later_statuses() -> None:
    """`WORKING` is past `EN_ROUTE` in the §10.7 forward progression, so it counts as reached;
    `OUT_OF_SERVICE` is a side exit and does not."""
    reached = _dds_ctx(
        stage_state=DDSStageState.DISPATCHED,
        actor=b.SIMULATION,
        board=b.resources(ResourceStatus.WORKING),
    )
    broken = _dds_ctx(
        stage_state=DDSStageState.DISPATCHED,
        actor=b.SIMULATION,
        board=b.resources(ResourceStatus.OUT_OF_SERVICE),
    )
    assert _dds_machine().can_fire(DDSStageState.DISPATCHED, "first_en_route", reached)
    assert not _dds_machine().can_fire(DDSStageState.DISPATCHED, "first_en_route", broken)


@pytest.mark.parametrize("flag,expected", [(True, True), (False, False)], ids=["allow", "deny"])
def test_guard_resolution_condition(flag: bool, expected: bool) -> None:
    ctx = _dds_ctx(
        stage_state=DDSStageState.WORKING,
        actor=b.SIMULATION,
        runtime=GuardRuntime(resolution_condition_met=flag),
    )
    assert _dds_machine().can_fire(DDSStageState.WORKING, "incident_resolved", ctx) is expected


@pytest.mark.parametrize(
    "board,expected",
    [(b.resources(ResourceStatus.SELECTED), True), (b.resources(ResourceStatus.EN_ROUTE), False)],
    ids=["allow", "deny"],
)
def test_guard_at_least_one_selected_available_on_dispatch_additional(
    board: Any, expected: bool
) -> None:
    """The self-transition rows reuse the same guard; pin that they are wired too."""
    ctx = _dds_ctx(
        stage_state=DDSStageState.EN_ROUTE, actor=b.actor(ActorType.TRAINEE, "dds"), board=board
    )
    assert _dds_machine().can_fire(DDSStageState.EN_ROUTE, "dispatch_additional", ctx) is expected


# ---------------------------------------------------------------------------------------------
# A guard callable is never reached through an un-permitted actor
# ---------------------------------------------------------------------------------------------


def test_registered_guards_are_callables() -> None:
    from app.domain.session.guards import DDS_GUARDS, OPERATOR_112_GUARDS, SESSION_GUARDS

    for mapping in (SESSION_GUARDS, OPERATOR_112_GUARDS, DDS_GUARDS):
        for name, guard in mapping.items():
            assert isinstance(guard, Callable)  # type: ignore[arg-type]
            assert name.startswith("guard_")

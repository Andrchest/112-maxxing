"""SPEC §42 invariant test 8: "Invalid state-machine transitions fail."

Table-driven and exhaustive: for each of the four SPEC §7 / §10.7 machines (`SESSION_TRANSITIONS`,
`OPERATOR_112_TRANSITIONS`, `DDS_TRANSITIONS`, `RESOURCE_STATUS_TRANSITIONS`), every `(state,
trigger)` pair is tried. The set of states comes from the matching enum (`list(SessionState)`,
etc.); the set of triggers comes from the table itself (`{trigger for (_, trigger) in table}`) —
neither is retyped here. A pair present in the table must succeed (`fire` returns the row's
`target`, given an actor/role that row's `allowed_actors`/`allowed_roles` permits and a fully
permissive guard registry — guard *callables* are a later slice, see `common/state_machine.py`);
a pair absent from the table must raise `InvalidTransitionError` and leave the caller's `state`
value unchanged.

The guard registry here is deliberately permissive (every `guard_name` the table references maps
to `lambda ctx: True`): this file tests the *tables* — the row is or is not covered — not guard
*business logic*, which needs `SimulationSession`/`RoleStage`/`OperatorCard`/`DDSAssignment` data
this task does not own (`TODO(E5)`).

A second exhaustive-adjacent test below (`test_pinned_*`) pins a handful of transitions SPEC §7 /
the HLD tables make illegal, so a future accidental widening of a table is caught even if the
full cross-product test above is ever narrowed. Per this task's brief, both were run by hand with
a row temporarily added to `SESSION_TRANSITIONS` that would legalise the first pinned case (the
pinned test failed), then removed again (the pinned test passed) — see the task report.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any

import pytest
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.state_machine import (
    ActorRef,
    GuardContext,
    StateMachine,
    Transition,
    TransitionTable,
)
from app.domain.dds.resources import RESOURCE_STATUS_TRANSITIONS
from app.domain.enums import (
    ActorType,
    DDSStageState,
    Operator112StageState,
    ResourceStatus,
    RoleType,
    SessionState,
)
from app.domain.session.transitions import (
    DDS_TRANSITIONS,
    OPERATOR_112_TRANSITIONS,
    SESSION_TRANSITIONS,
)

# ---------------------------------------------------------------------------------------------
# Shared machinery
# ---------------------------------------------------------------------------------------------


def _permissive_guards(table: TransitionTable[Any]) -> dict[str, Callable[[GuardContext], bool]]:
    names = {row.guard_name for row in table.values() if row.guard_name is not None}
    return dict.fromkeys(names, lambda _ctx: True)


def _actor_and_role_for(transition: Transition[Any]) -> tuple[ActorType, RoleType | None]:
    """Pick one `(actor_type, role_type)` this row's `allowed_actors`/`allowed_roles` permits."""
    if ActorType.TRAINEE in transition.allowed_actors:
        role = next(iter(transition.allowed_roles)) if transition.allowed_roles else None
        return ActorType.TRAINEE, role
    return next(iter(transition.allowed_actors)), None


def _assert_exhaustive(machine_name: str, table: TransitionTable[Any], states: list[Any]) -> None:
    machine: StateMachine[Any] = StateMachine(table, _permissive_guards(table))
    triggers = sorted({trigger for (_source, trigger) in table})
    assert triggers, f"{machine_name}: table has no rows at all"

    for state, trigger in itertools.product(states, triggers):
        key = (state, trigger)
        before = state
        if key in table:
            transition = table[key]
            actor_type, role_type = _actor_and_role_for(transition)
            ctx = GuardContext(actor=ActorRef(actor_type=actor_type), role_type=role_type)
            result = machine.fire(state, trigger, ctx)
            assert result == transition.target, (
                f"{machine_name}: {state!r} -{trigger}-> expected {transition.target!r}, "
                f"got {result!r}"
            )
        else:
            ctx = GuardContext(actor=ActorRef(actor_type=ActorType.SYSTEM))
            with pytest.raises(InvalidTransitionError):
                machine.fire(state, trigger, ctx)
            assert state == before, f"{machine_name}: {state!r} mutated by a rejected {trigger!r}"


# ---------------------------------------------------------------------------------------------
# Exhaustive per-machine tests
# ---------------------------------------------------------------------------------------------


def test_session_transitions_exhaustive() -> None:
    _assert_exhaustive("SESSION_TRANSITIONS", SESSION_TRANSITIONS, list(SessionState))


def test_operator_112_transitions_exhaustive() -> None:
    _assert_exhaustive(
        "OPERATOR_112_TRANSITIONS", OPERATOR_112_TRANSITIONS, list(Operator112StageState)
    )


def test_dds_transitions_exhaustive() -> None:
    _assert_exhaustive("DDS_TRANSITIONS", DDS_TRANSITIONS, list(DDSStageState))


def test_resource_status_transitions_exhaustive() -> None:
    _assert_exhaustive(
        "RESOURCE_STATUS_TRANSITIONS", RESOURCE_STATUS_TRANSITIONS, list(ResourceStatus)
    )


# ---------------------------------------------------------------------------------------------
# Pinned illegal transitions (SPEC §7 / the HLD tables make these illegal by omission)
# ---------------------------------------------------------------------------------------------

_PINNED_ILLEGAL: tuple[tuple[str, TransitionTable[Any], Any, str], ...] = (
    ("SESSION_TRANSITIONS", SESSION_TRANSITIONS, SessionState.CREATED, "complete"),
    ("SESSION_TRANSITIONS", SESSION_TRANSITIONS, SessionState.COMPLETED, "start"),
    (
        "OPERATOR_112_TRANSITIONS",
        OPERATOR_112_TRANSITIONS,
        Operator112StageState.WAITING_FOR_CALL,
        "create_handoff",
    ),
    ("DDS_TRANSITIONS", DDS_TRANSITIONS, DDSStageState.RECEIVED, "dispatch"),
)


@pytest.mark.parametrize(
    "machine_name,table,state,trigger",
    _PINNED_ILLEGAL,
    ids=[row[0] + ":" + row[3] for row in _PINNED_ILLEGAL],
)
def test_pinned_illegal_transitions_raise(
    machine_name: str, table: TransitionTable[Any], state: Any, trigger: str
) -> None:
    machine: StateMachine[Any] = StateMachine(table, _permissive_guards(table))
    ctx = GuardContext(actor=ActorRef(actor_type=ActorType.SYSTEM))
    with pytest.raises(InvalidTransitionError) as excinfo:
        machine.fire(state, trigger, ctx)
    assert excinfo.value.trigger == trigger
    assert (state, trigger) not in table, (
        f"{machine_name}: {state!r} -{trigger}-> is in the table — "
        "this pinned case is no longer illegal"
    )

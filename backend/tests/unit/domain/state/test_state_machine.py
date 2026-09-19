"""Unit tests for the generic `StateMachine[S]` mechanics (HLD `10-domain-model.md` §10.8).

Uses a tiny synthetic two-trigger machine so the mechanics (table lookup, actor/role checks,
guard lookup/evaluation, `InvalidTransitionError` field values, `available_triggers`) are tested
independently of the real SPEC §7 tables (those get their own exhaustive coverage in
`backend/tests/invariants/test_inv_08_invalid_transitions.py`).
"""

from __future__ import annotations

from enum import Enum

import pytest
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.state_machine import ActorRef, GuardContext, StateMachine, Transition
from app.domain.enums import ActorType, RoleType


class _DoorState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LOCKED = "LOCKED"


_TABLE = {
    (_DoorState.OPEN, "close"): Transition(
        source=_DoorState.OPEN,
        trigger="close",
        target=_DoorState.CLOSED,
        allowed_actors=frozenset({ActorType.TRAINEE}),
        allowed_roles=frozenset({RoleType.DDS}),
    ),
    (_DoorState.CLOSED, "open"): Transition(
        source=_DoorState.CLOSED,
        trigger="open",
        target=_DoorState.OPEN,
        allowed_actors=frozenset({ActorType.TRAINEE, ActorType.SYSTEM}),
    ),
    (_DoorState.CLOSED, "lock"): Transition(
        source=_DoorState.CLOSED,
        trigger="lock",
        target=_DoorState.LOCKED,
        allowed_actors=frozenset({ActorType.SYSTEM}),
        guard_name="guard_key_present",
    ),
}


def _ctx(
    actor_type: ActorType, role_type: RoleType | None = None, key: bool = False
) -> GuardContext:
    return GuardContext(
        actor=ActorRef(actor_type=actor_type), role_type=role_type, world_flags={"key_present": key}
    )


def test_fire_returns_target_for_a_valid_transition() -> None:
    machine = StateMachine(_TABLE, {})
    ctx = _ctx(ActorType.TRAINEE, RoleType.DDS)
    assert machine.fire(_DoorState.OPEN, "close", ctx) == _DoorState.CLOSED


def test_fire_raises_for_a_pair_absent_from_the_table() -> None:
    machine = StateMachine(_TABLE, {})
    ctx = _ctx(ActorType.TRAINEE, RoleType.DDS)
    with pytest.raises(InvalidTransitionError) as excinfo:
        machine.fire(_DoorState.LOCKED, "open", ctx)
    err = excinfo.value
    assert err.machine == "_DoorState"
    assert err.from_state == "LOCKED"
    assert err.trigger == "open"
    assert err.to_state is None


def test_fire_raises_when_actor_type_not_allowed() -> None:
    machine = StateMachine(_TABLE, {})
    ctx = _ctx(ActorType.INSTRUCTOR)
    with pytest.raises(InvalidTransitionError) as excinfo:
        machine.fire(_DoorState.OPEN, "close", ctx)
    assert "actor" in excinfo.value.reason
    assert excinfo.value.to_state == "CLOSED"


def test_fire_raises_when_role_not_allowed_for_a_trainee() -> None:
    machine = StateMachine(_TABLE, {})
    ctx = _ctx(ActorType.TRAINEE, RoleType.OPERATOR_112)
    with pytest.raises(InvalidTransitionError) as excinfo:
        machine.fire(_DoorState.OPEN, "close", ctx)
    assert "role" in excinfo.value.reason


def test_role_check_is_skipped_for_a_non_trainee_actor() -> None:
    """`CLOSED -open-> OPEN` allows TRAINEE or SYSTEM with no role restriction at all."""
    machine = StateMachine(_TABLE, {})
    ctx = GuardContext(actor=ActorRef(actor_type=ActorType.SYSTEM), role_type=None)
    assert machine.fire(_DoorState.CLOSED, "open", ctx) == _DoorState.OPEN


def test_fire_raises_when_guard_not_registered() -> None:
    machine = StateMachine(_TABLE, {})
    ctx = _ctx(ActorType.SYSTEM)
    with pytest.raises(InvalidTransitionError) as excinfo:
        machine.fire(_DoorState.CLOSED, "lock", ctx)
    assert "not registered" in excinfo.value.reason


def test_fire_raises_when_guard_returns_false() -> None:
    machine = StateMachine(_TABLE, {"guard_key_present": lambda ctx: False})
    ctx = _ctx(ActorType.SYSTEM)
    with pytest.raises(InvalidTransitionError) as excinfo:
        machine.fire(_DoorState.CLOSED, "lock", ctx)
    assert "returned False" in excinfo.value.reason


def test_fire_succeeds_when_guard_returns_true() -> None:
    machine = StateMachine(_TABLE, {"guard_key_present": lambda ctx: True})
    ctx = _ctx(ActorType.SYSTEM)
    assert machine.fire(_DoorState.CLOSED, "lock", ctx) == _DoorState.LOCKED


def test_can_fire_mirrors_fire_without_raising() -> None:
    machine = StateMachine(_TABLE, {})
    ctx = _ctx(ActorType.TRAINEE, RoleType.DDS)
    assert machine.can_fire(_DoorState.OPEN, "close", ctx) is True
    assert machine.can_fire(_DoorState.LOCKED, "open", ctx) is False


def test_available_triggers_lists_only_firable_triggers_sorted() -> None:
    machine = StateMachine(_TABLE, {"guard_key_present": lambda ctx: True})
    ctx = GuardContext(actor=ActorRef(actor_type=ActorType.SYSTEM))
    assert machine.available_triggers(_DoorState.CLOSED, ctx) == ("lock", "open")


def test_a_failed_fire_does_not_change_the_caller_side_state() -> None:
    """`fire` raises rather than returning a new state; the caller's `state` variable, being an
    immutable `Enum` value, is therefore left exactly as it was."""
    machine = StateMachine(_TABLE, {})
    state = _DoorState.LOCKED
    ctx = _ctx(ActorType.TRAINEE, RoleType.DDS)
    with pytest.raises(InvalidTransitionError):
        state = machine.fire(state, "close", ctx)
    assert state is _DoorState.LOCKED

"""No production state machine is built with an empty or incomplete guard mapping.

After E5-A every `guard_name` in `SESSION_TRANSITIONS`, `OPERATOR_112_TRANSITIONS` and
`DDS_TRANSITIONS` must resolve to a registered callable in the mapping the corresponding machine
was constructed with — `StateMachine._resolve` denies a transition whose named guard is missing,
so an unregistered name silently freezes the machine rather than raising. `EDDSModule`'s stub is
the one exception: it has no transitions at all, hence no guard names to register.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from app.domain.common.state_machine import GuardContext, TransitionTable
from app.domain.enums import RoleType
from app.domain.roles.registry import ROLE_MODULES
from app.domain.session.guards import DDS_GUARDS, OPERATOR_112_GUARDS, SESSION_GUARDS
from app.domain.session.machine import SESSION_STATE_MACHINE
from app.domain.session.transitions import (
    DDS_TRANSITIONS,
    OPERATOR_112_TRANSITIONS,
    SESSION_TRANSITIONS,
)

_CASES: tuple[
    tuple[str, TransitionTable[Any], Mapping[str, Callable[[GuardContext], bool]]], ...
] = (
    ("SESSION_TRANSITIONS", SESSION_TRANSITIONS, SESSION_GUARDS),
    ("OPERATOR_112_TRANSITIONS", OPERATOR_112_TRANSITIONS, OPERATOR_112_GUARDS),
    ("DDS_TRANSITIONS", DDS_TRANSITIONS, DDS_GUARDS),
)


@pytest.mark.parametrize("name,table,guards", _CASES, ids=[case[0] for case in _CASES])
def test_every_guard_name_is_registered(
    name: str, table: TransitionTable[Any], guards: Mapping[str, Callable[[GuardContext], bool]]
) -> None:
    referenced = {row.guard_name for row in table.values() if row.guard_name is not None}
    missing = sorted(referenced - set(guards))
    assert not missing, f"{name}: unregistered guard name(s) {missing}"


@pytest.mark.parametrize("name,table,guards", _CASES, ids=[case[0] for case in _CASES])
def test_no_guard_is_registered_without_a_row_using_it(
    name: str, table: TransitionTable[Any], guards: Mapping[str, Callable[[GuardContext], bool]]
) -> None:
    referenced = {row.guard_name for row in table.values() if row.guard_name is not None}
    unused = sorted(set(guards) - referenced)
    assert not unused, f"{name}: guard(s) registered but never referenced: {unused}"


def test_production_machines_carry_a_non_empty_guard_mapping() -> None:
    machines = [
        ("SESSION_STATE_MACHINE", SESSION_STATE_MACHINE),
        ("Operator112Module", ROLE_MODULES[RoleType.OPERATOR_112].state_machine),
        ("DDSModule", ROLE_MODULES[RoleType.DDS].state_machine),
    ]
    for name, machine in machines:
        guards = machine._guards
        assert guards, f"{name} was built with an empty guard mapping"


def test_edds_stub_is_the_only_transition_less_machine() -> None:
    edds = ROLE_MODULES[RoleType.EDDS]
    assert edds.implemented is False
    assert not edds.state_machine._table

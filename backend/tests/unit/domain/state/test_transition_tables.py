"""Structural checks on the four HLD `10-domain-model.md` §10.8/§10.7 transition tables.

Row *counts* below are derived by hand from the HLD "Who may fire" tables (counting one row per
distinct `(From, Trigger)` cell, expanding multi-state `From` cells — e.g. Operator 112
`abort_stage`'s six source states — into one row each) and pinned here so an accidental dropped
or duplicated row is caught; the exhaustive membership itself is
`backend/tests/invariants/test_inv_08_invalid_transitions.py`'s job, not this file's.
"""

from __future__ import annotations

import pytest
from app.domain.common.state_machine import TransitionTable
from app.domain.dds.resources import RESOURCE_STATUS_TRANSITIONS
from app.domain.enums import (
    ActorType,
    DDSStageState,
    Operator112StageState,
    ResourceStatus,
    SessionState,
)
from app.domain.session.transitions import (
    DDS_TRANSITIONS,
    OPERATOR_112_TRANSITIONS,
    SESSION_TRANSITIONS,
)

_EXPECTED_ROW_COUNTS = {
    "SESSION_TRANSITIONS": (SESSION_TRANSITIONS, 9),
    "OPERATOR_112_TRANSITIONS": (OPERATOR_112_TRANSITIONS, 13),
    "DDS_TRANSITIONS": (DDS_TRANSITIONS, 22),  # I3 E5a: + ACKNOWLEDGED --close--> RESOLVED
    "RESOURCE_STATUS_TRANSITIONS": (RESOURCE_STATUS_TRANSITIONS, 15),
}


@pytest.mark.parametrize(
    "name,table,expected", [(name, table, n) for name, (table, n) in _EXPECTED_ROW_COUNTS.items()]
)
def test_row_count(name: str, table: TransitionTable, expected: int) -> None:
    assert len(table) == expected, f"{name} has {len(table)} rows, expected {expected}"


@pytest.mark.parametrize(
    "table",
    [SESSION_TRANSITIONS, OPERATOR_112_TRANSITIONS, DDS_TRANSITIONS, RESOURCE_STATUS_TRANSITIONS],
)
def test_every_row_is_keyed_by_its_own_source_and_trigger(table: TransitionTable) -> None:
    for (source, trigger), row in table.items():
        assert row.source == source
        assert row.trigger == trigger


@pytest.mark.parametrize(
    "table",
    [SESSION_TRANSITIONS, OPERATOR_112_TRANSITIONS, DDS_TRANSITIONS, RESOURCE_STATUS_TRANSITIONS],
)
def test_every_row_names_at_least_one_allowed_actor(table: TransitionTable) -> None:
    for row in table.values():
        assert row.allowed_actors, f"{row.source!r} -{row.trigger}-> has no allowed_actors"


@pytest.mark.parametrize(
    "table",
    [SESSION_TRANSITIONS, OPERATOR_112_TRANSITIONS, DDS_TRANSITIONS, RESOURCE_STATUS_TRANSITIONS],
)
def test_allowed_roles_only_set_when_trainee_is_an_allowed_actor(table: TransitionTable) -> None:
    """`allowed_roles` restricts the TRAINEE case (§10.8); a row with no TRAINEE actor has no use
    for it, so every non-empty `allowed_roles` here implies `TRAINEE in allowed_actors`."""
    for row in table.values():
        if row.allowed_roles:
            assert ActorType.TRAINEE in row.allowed_actors


def test_session_transitions_has_no_role_restriction() -> None:
    """`SimulationSession`-level actors are never "playing" a `RoleType`."""
    assert all(not row.allowed_roles for row in SESSION_TRANSITIONS.values())


def test_dds_dispatch_additional_is_a_self_transition_for_its_three_states() -> None:
    self_transitions = {
        state: row
        for (state, trigger), row in DDS_TRANSITIONS.items()
        if trigger == "dispatch_additional"
    }
    assert set(self_transitions) == {
        DDSStageState.EN_ROUTE,
        DDSStageState.ARRIVED,
        DDSStageState.WORKING,
    }
    for state, row in self_transitions.items():
        assert row.target == state


def test_operator_112_abort_stage_covers_every_non_terminal_state() -> None:
    abort_sources = {
        source for (source, trigger) in OPERATOR_112_TRANSITIONS if trigger == "abort_stage"
    }
    assert abort_sources == set(Operator112StageState) - {Operator112StageState.STAGE_COMPLETED}


def test_dds_abort_stage_covers_every_non_terminal_state() -> None:
    abort_sources = {source for (source, trigger) in DDS_TRANSITIONS if trigger == "abort_stage"}
    assert abort_sources == set(DDSStageState) - {DDSStageState.CLOSED}


def test_resource_status_breakdown_covers_the_four_active_states() -> None:
    breakdown_sources = {
        source for (source, trigger) in RESOURCE_STATUS_TRANSITIONS if trigger == "breakdown"
    }
    assert breakdown_sources == {
        ResourceStatus.DISPATCHED,
        ResourceStatus.EN_ROUTE,
        ResourceStatus.ON_SCENE,
        ResourceStatus.WORKING,
    }


def test_terminal_states_have_no_outgoing_rows_except_abort() -> None:
    """`COMPLETED`/`ABORTED` (session), `STAGE_COMPLETED` (Operator 112), `CLOSED` (DDS) are
    terminal per §10.8's tables ("— terminal")."""
    session_sources = {source for (source, _trigger) in SESSION_TRANSITIONS}
    assert SessionState.COMPLETED not in session_sources
    assert SessionState.ABORTED not in session_sources

    operator_sources = {source for (source, _trigger) in OPERATOR_112_TRANSITIONS}
    assert Operator112StageState.STAGE_COMPLETED not in operator_sources

    dds_sources = {source for (source, _trigger) in DDS_TRANSITIONS}
    assert DDSStageState.CLOSED not in dds_sources

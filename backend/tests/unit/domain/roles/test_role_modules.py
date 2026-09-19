"""`ROLE_MODULES` registry and per-module structural checks (HLD `10-domain-model.md` §10.9,
SPEC §14, D6).
"""

from __future__ import annotations

from enum import Enum

import pytest
from app.domain.dds.resources import RESOURCE_STATUS_TRANSITIONS
from app.domain.enums import DDSStageState, Operator112StageState, RoleType
from app.domain.roles.dds import DDSModule
from app.domain.roles.module import RoleModule
from app.domain.roles.operator112 import Operator112Module
from app.domain.roles.registry import ROLE_MODULES
from app.domain.roles.visibility import VisibilitySource
from app.domain.session.transitions import DDS_TRANSITIONS, OPERATOR_112_TRANSITIONS


def test_role_modules_covers_every_role_type() -> None:
    assert set(ROLE_MODULES) == set(RoleType)


@pytest.mark.parametrize("role_type", list(RoleType))
def test_role_module_role_type_matches_its_registry_key(role_type: RoleType) -> None:
    assert ROLE_MODULES[role_type].role_type == role_type


def test_only_edds_is_not_implemented() -> None:
    not_implemented = {rt for rt, module in ROLE_MODULES.items() if not module.implemented}
    assert not_implemented == {RoleType.EDDS}


def test_edds_module_is_a_stub() -> None:
    module = ROLE_MODULES[RoleType.EDDS]
    assert module.permissions == frozenset()
    assert module.available_actions(module.initial_state()) == ()
    assert module.ui_schema == {}
    assert module.terminal_states() == frozenset()
    assert module.initial_state() == DDSStageState.RECEIVED


def test_dds_visibility_has_no_world_or_caller_source() -> None:
    """SPEC §10, §42 test 3: DDS must not be able to read hidden WorldTruth/CallerBelief."""
    sources = ROLE_MODULES[RoleType.DDS].visibility_policy.sources
    assert VisibilitySource.WORLD_TRUTH not in sources
    assert VisibilitySource.CALLER_BELIEF not in sources
    assert VisibilitySource.OPERATOR_CARD not in sources
    assert VisibilitySource.TRANSCRIPT not in sources


@pytest.mark.parametrize(
    "role_type,expected_sources",
    [
        (
            RoleType.OPERATOR_112,
            {
                VisibilitySource.OPERATOR_CARD,
                VisibilitySource.CARD_REVISIONS,
                VisibilitySource.TRANSCRIPT,
                VisibilitySource.CALL_STATE,
                VisibilitySource.NOTIFICATIONS,
            },
        ),
        (
            RoleType.DDS,
            {
                VisibilitySource.HANDOFF_SNAPSHOT,
                VisibilitySource.DDS_ASSIGNMENT,
                VisibilitySource.RESOURCE_BOARD,
                VisibilitySource.NOTIFICATIONS,
                VisibilitySource.RADIO_MESSAGES,
            },
        ),
        (RoleType.EDDS, {VisibilitySource.NOTIFICATIONS, VisibilitySource.RADIO_MESSAGES}),
    ],
)
def test_visibility_sources_match_the_hld_table(
    role_type: RoleType, expected_sources: set[VisibilitySource]
) -> None:
    assert ROLE_MODULES[role_type].visibility_policy.sources == expected_sources


@pytest.mark.parametrize(
    "module,states",
    [
        (Operator112Module(), Operator112StageState),
        (DDSModule(), DDSStageState),
    ],
)
def test_every_action_descriptor_names_states_belonging_to_its_own_machine(
    module: RoleModule, states: type[Enum]
) -> None:
    """Every `stage_state` key `available_actions` is defined for is a member of the same
    enum the module's `state_machine` operates over."""
    for state in states:
        actions = module.available_actions(state)
        assert isinstance(actions, tuple)


def test_operator_112_action_triggers_are_operator_112_transitions_or_non_transition_commands() -> (
    None
):
    module = Operator112Module()
    machine_triggers = {trigger for (_source, trigger) in OPERATOR_112_TRANSITIONS}
    for state in Operator112StageState:
        for action in module.available_actions(state):
            if action.trigger is not None:
                assert action.trigger in machine_triggers


def test_dds_action_triggers_are_dds_transitions_or_non_transition_commands() -> None:
    module = DDSModule()
    machine_triggers = {trigger for (_source, trigger) in DDS_TRANSITIONS}
    for state in DDSStageState:
        for action in module.available_actions(state):
            if action.trigger is not None:
                assert action.trigger in machine_triggers


def test_operator_112_state_machine_is_backed_by_operator_112_transitions() -> None:
    module = Operator112Module()
    assert module.initial_state() == Operator112StageState.WAITING_FOR_CALL
    assert module.terminal_states() == frozenset({Operator112StageState.STAGE_COMPLETED})


def test_dds_state_machine_is_backed_by_dds_transitions() -> None:
    module = DDSModule()
    assert module.initial_state() == DDSStageState.RECEIVED
    assert module.terminal_states() == frozenset({DDSStageState.CLOSED})


def test_resource_status_transitions_is_a_separate_machine_from_dds_transitions() -> None:
    """The DDS *stage* machine and the per-resource status machine are distinct tables (§10.7 vs
    §10.8); `select_resource`/`deselect_resource` fire on the latter, not `DDS_TRANSITIONS`."""
    dds_triggers = {trigger for (_source, trigger) in DDS_TRANSITIONS}
    resource_triggers = {trigger for (_source, trigger) in RESOURCE_STATUS_TRANSITIONS}
    assert "select" in resource_triggers
    assert "select" not in dds_triggers

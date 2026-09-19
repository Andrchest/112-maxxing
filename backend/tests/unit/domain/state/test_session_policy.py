"""`SessionPolicy`/`SESSION_POLICIES` against the §10.10 table (HLD `10-domain-model.md`, SPEC §1,
§13)."""

from __future__ import annotations

import pytest
from app.domain.enums import SessionMode
from app.domain.session.policy import SESSION_POLICIES, ParticipantAssignmentRule, SessionPolicy

_EXPECTED = {
    SessionMode.SINGLE_ROLE: SessionPolicy(
        session_mode=SessionMode.SINGLE_ROLE,
        assignment_rule=ParticipantAssignmentRule.SINGLE_STAGE_ONE_PARTICIPANT,
        role_chain_length="EXACTLY_ONE",
        transition_pause_seconds=0,
        show_asr_partials=True,
        report_visible_to_trainee_before_release=True,
        requires_prefab_handoff_for_dds_only=True,
    ),
    SessionMode.FULL_CYCLE_SINGLE_TRAINEE: SessionPolicy(
        session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE,
        assignment_rule=ParticipantAssignmentRule.ALL_STAGES_ONE_PARTICIPANT,
        role_chain_length="ONE_OR_MORE",
        transition_pause_seconds=20,
        show_asr_partials=True,
        report_visible_to_trainee_before_release=True,
        requires_prefab_handoff_for_dds_only=False,
    ),
    SessionMode.MULTI_TRAINEE: SessionPolicy(
        session_mode=SessionMode.MULTI_TRAINEE,
        assignment_rule=ParticipantAssignmentRule.ONE_PARTICIPANT_PER_STAGE,
        role_chain_length="ONE_OR_MORE",
        transition_pause_seconds=10,
        show_asr_partials=True,
        report_visible_to_trainee_before_release=False,
        requires_prefab_handoff_for_dds_only=False,
    ),
    SessionMode.ASSESSMENT: SessionPolicy(
        session_mode=SessionMode.ASSESSMENT,
        assignment_rule=ParticipantAssignmentRule.SINGLE_STAGE_ONE_PARTICIPANT,
        role_chain_length="ONE_OR_MORE",
        transition_pause_seconds=0,
        show_asr_partials=False,
        report_visible_to_trainee_before_release=False,
        requires_prefab_handoff_for_dds_only=True,
    ),
}


def test_session_policies_covers_every_session_mode() -> None:
    assert set(SESSION_POLICIES) == set(SessionMode)


@pytest.mark.parametrize("mode", list(SessionMode))
def test_session_policy_matches_the_hld_table(mode: SessionMode) -> None:
    assert SESSION_POLICIES[mode] == _EXPECTED[mode]


def test_session_policies_are_frozen() -> None:
    with pytest.raises(Exception, match=r"frozen"):
        SESSION_POLICIES[SessionMode.SINGLE_ROLE].transition_pause_seconds = 99  # type: ignore[misc]

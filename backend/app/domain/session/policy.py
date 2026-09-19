"""`SessionPolicy` and `SESSION_POLICIES` (HLD `10-domain-model.md` §10.10, SPEC §1, §13)."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.enums import SessionMode


class ParticipantAssignmentRule(str, Enum):
    SINGLE_STAGE_ONE_PARTICIPANT = "SINGLE_STAGE_ONE_PARTICIPANT"
    ALL_STAGES_ONE_PARTICIPANT = "ALL_STAGES_ONE_PARTICIPANT"
    ONE_PARTICIPANT_PER_STAGE = "ONE_PARTICIPANT_PER_STAGE"


class SessionPolicy(BaseModel):
    """One row of the §10.10 table."""

    model_config = ConfigDict(frozen=True)

    session_mode: SessionMode
    assignment_rule: ParticipantAssignmentRule
    role_chain_length: Literal["EXACTLY_ONE", "ONE_OR_MORE"]
    transition_pause_seconds: int
    show_asr_partials: bool
    report_visible_to_trainee_before_release: bool
    requires_prefab_handoff_for_dds_only: bool


SESSION_POLICIES: Mapping[SessionMode, SessionPolicy] = {
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

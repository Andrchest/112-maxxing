"""`create_session`: stages, participant binding, the two structural rejections, and the one
incident per session (SPEC §13, §42 test 5; HLD §10.8, §10.10, D6).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.common.errors import PrefabHandoffRequiredError, RoleChainLengthError
from app.domain.common.state_machine import GuardRuntime
from app.domain.enums import (
    DDSStageState,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.events.catalog import validate_payload
from app.domain.events.types import EventType
from app.domain.roles.registry import ROLE_MODULES
from app.domain.session.session import create_session

from tests.unit.domain.session import _builders as b

OP = RoleType.OPERATOR_112
DDS = RoleType.DDS


def _create(
    *,
    session_mode: SessionMode = SessionMode.MULTI_TRAINEE,
    role_chain: tuple[RoleType, ...] = (OP, DDS),
    participants: Any = (),
    with_prefab_handoff: bool = True,
) -> Any:
    version = b.scenario_version(role_chain=role_chain, with_prefab_handoff=with_prefab_handoff)
    scenario_id, slug = b.scenario_ids()
    return create_session(
        session_id=b.SESSION_ID,
        incident_id=b.INCIDENT_ID,
        stage_ids=b.stage_ids(len(role_chain)),
        scenario_version=version,
        scenario_id=scenario_id,
        scenario_slug=slug,
        session_mode=session_mode,
        created_by=b.INSTRUCTOR,
        participants=participants,
    )


# ---------------------------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------------------------


def test_create_session_builds_one_stage_per_role_chain_entry_in_initial_state() -> None:
    session, events = _create()
    assert session.state is SessionState.CREATED
    assert [stage.role_type for stage in session.stages] == [OP, DDS]
    assert [stage.order_index for stage in session.stages] == [0, 1]
    assert session.stages[0].state == ROLE_MODULES[OP].initial_state()
    assert session.stages[1].state == ROLE_MODULES[DDS].initial_state()
    assert session.stages[0].state is Operator112StageState.WAITING_FOR_CALL
    assert session.stages[1].state is DDSStageState.RECEIVED
    assert len(events) == 1
    assert events[0].event_type is EventType.SESSION_CREATED


def test_session_created_payload_satisfies_the_catalog() -> None:
    _session, events = _create()
    validate_payload(EventType.SESSION_CREATED, events[0].payload)
    assert events[0].payload["role_chain"] == ["OPERATOR_112", "DDS"]
    assert events[0].payload["scenario_slug"] == "apartment-fire"


def test_session_seed_defaults_to_the_scenario_deterministic_seed() -> None:
    session, _events = _create()
    assert session.session_seed == "apartment-fire-v1"


def test_explicit_session_seed_overrides_the_scenario_seed() -> None:
    version = b.scenario_version()
    scenario_id, slug = b.scenario_ids()
    session, _events = create_session(
        session_id=b.SESSION_ID,
        incident_id=b.INCIDENT_ID,
        stage_ids=b.stage_ids(2),
        scenario_version=version,
        scenario_id=scenario_id,
        scenario_slug=slug,
        session_mode=SessionMode.MULTI_TRAINEE,
        created_by=b.INSTRUCTOR,
        session_seed="override",
        time_scale=2.0,
    )
    assert session.session_seed == "override"
    assert session.time_scale == 2.0


def test_exactly_one_incident_belonging_to_this_session() -> None:
    session, _events = _create()
    assert session.incident.incident_id == b.INCIDENT_ID
    assert session.incident.session_id == session.id
    assert {stage.incident_id for stage in session.stages} == {b.INCIDENT_ID}


def test_create_session_rejects_a_stage_id_count_mismatch() -> None:
    version = b.scenario_version()
    scenario_id, slug = b.scenario_ids()
    with pytest.raises(ValueError, match="one stage id per role_chain entry"):
        create_session(
            session_id=b.SESSION_ID,
            incident_id=b.INCIDENT_ID,
            stage_ids=b.stage_ids(1),
            scenario_version=version,
            scenario_id=scenario_id,
            scenario_slug=slug,
            session_mode=SessionMode.MULTI_TRAINEE,
            created_by=b.INSTRUCTOR,
        )


# ---------------------------------------------------------------------------------------------
# Structural rejections
# ---------------------------------------------------------------------------------------------


def test_prefab_handoff_required_for_a_dds_only_chain_under_single_role() -> None:
    with pytest.raises(PrefabHandoffRequiredError) as excinfo:
        _create(
            session_mode=SessionMode.SINGLE_ROLE,
            role_chain=(DDS,),
            with_prefab_handoff=False,
            participants=[(b.user("dds"), DDS)],
        )
    assert excinfo.value.code == "PREFAB_HANDOFF_REQUIRED"


def test_prefab_handoff_present_makes_the_dds_only_chain_creatable() -> None:
    session, _events = _create(
        session_mode=SessionMode.SINGLE_ROLE,
        role_chain=(DDS,),
        with_prefab_handoff=True,
        participants=[(b.user("dds"), DDS)],
    )
    assert [stage.role_type for stage in session.stages] == [DDS]


def test_prefab_handoff_not_required_when_the_chain_is_not_dds_only() -> None:
    session, _events = _create(
        session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE,
        role_chain=(OP, DDS),
        with_prefab_handoff=False,
        participants=[(b.user("both"), None)],
    )
    assert len(session.stages) == 2


def test_role_chain_length_exactly_one_is_enforced() -> None:
    with pytest.raises(RoleChainLengthError):
        _create(session_mode=SessionMode.SINGLE_ROLE, role_chain=(OP, DDS))


def test_role_chain_length_one_or_more_accepts_a_two_entry_chain() -> None:
    session, _events = _create(session_mode=SessionMode.ASSESSMENT, role_chain=(OP, DDS))
    assert len(session.stages) == 2


# ---------------------------------------------------------------------------------------------
# Participant binding — one allow per rule, plus the deny surfacing at `validate`
# ---------------------------------------------------------------------------------------------


def _validates(session: Any) -> bool:
    try:
        session.validate_session(actor=b.SYSTEM, runtime=GuardRuntime(scenario_valid=True))
    except Exception:
        return False
    return True


def test_single_stage_one_participant_binds_only_the_matching_role() -> None:
    session, _events = _create(
        session_mode=SessionMode.ASSESSMENT,
        role_chain=(OP, DDS),
        participants=[(b.user("op"), OP)],
    )
    assert session.stages[0].participant_user_id == b.user("op")
    assert session.stages[1].participant_user_id is None
    # A stage without a participant is exactly what `validate` refuses.
    assert not _validates(session)


def test_single_stage_one_participant_allows_a_single_stage_chain() -> None:
    session, _events = _create(
        session_mode=SessionMode.SINGLE_ROLE,
        role_chain=(OP,),
        participants=[(b.user("op"), OP)],
    )
    assert session.stages[0].participant_user_id == b.user("op")
    assert _validates(session)


def test_single_stage_one_participant_denies_a_null_role() -> None:
    session, _events = _create(
        session_mode=SessionMode.SINGLE_ROLE,
        role_chain=(OP,),
        participants=[(b.user("op"), None)],
    )
    assert session.stages[0].participant_user_id is None
    assert not _validates(session)


def test_all_stages_one_participant_binds_every_stage() -> None:
    session, _events = _create(
        session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE,
        participants=[(b.user("both"), None)],
    )
    assert [stage.participant_user_id for stage in session.stages] == [
        b.user("both"),
        b.user("both"),
    ]
    assert _validates(session)


def test_all_stages_one_participant_denies_two_participants() -> None:
    session, _events = _create(
        session_mode=SessionMode.FULL_CYCLE_SINGLE_TRAINEE,
        participants=[(b.user("a"), None), (b.user("b"), None)],
    )
    assert [stage.participant_user_id for stage in session.stages] == [None, None]
    assert not _validates(session)


def test_one_participant_per_stage_binds_each_role() -> None:
    session, _events = _create(
        session_mode=SessionMode.MULTI_TRAINEE,
        participants=[(b.user("op"), OP), (b.user("dds"), DDS)],
    )
    assert [stage.participant_user_id for stage in session.stages] == [
        b.user("op"),
        b.user("dds"),
    ]
    assert _validates(session)


def test_one_participant_per_stage_denies_a_participant_outside_the_chain() -> None:
    session, _events = _create(
        session_mode=SessionMode.MULTI_TRAINEE,
        participants=[
            (b.user("op"), OP),
            (b.user("dds"), DDS),
            (b.user("edds"), RoleType.EDDS),
        ],
    )
    assert [stage.participant_user_id for stage in session.stages] == [None, None]
    assert not _validates(session)


def test_one_participant_per_stage_denies_two_participants_for_one_role() -> None:
    session, _events = _create(
        session_mode=SessionMode.MULTI_TRAINEE,
        participants=[(b.user("op"), OP), (b.user("op2"), OP), (b.user("dds"), DDS)],
    )
    assert session.stages[0].participant_user_id is None
    assert not _validates(session)


def test_participant_ids_are_carried_when_supplied() -> None:
    version = b.scenario_version()
    scenario_id, slug = b.scenario_ids()
    session, _events = create_session(
        session_id=b.SESSION_ID,
        incident_id=b.INCIDENT_ID,
        stage_ids=b.stage_ids(2),
        scenario_version=version,
        scenario_id=scenario_id,
        scenario_slug=slug,
        session_mode=SessionMode.MULTI_TRAINEE,
        created_by=b.INSTRUCTOR,
        participants=[(b.user("op"), OP), (b.user("dds"), DDS)],
        participant_ids=[b.det_uuid("p0"), b.det_uuid("p1")],
    )
    assert [p.participant_id for p in session.participants] == [
        b.det_uuid("p0"),
        b.det_uuid("p1"),
    ]

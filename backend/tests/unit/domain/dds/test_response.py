"""The per-leg response machine and the memo stage guards (I3 E5a, HLD 70 §70.4.1–§70.4.5; D16).

Pure domain: `fire_response_trigger` over `SERVICE_RESPONSE_TRANSITIONS`, `trigger_for`, the
policy guards (103 `NO_REFUSAL`), and the two memo stage guards — `memo_all_legs_terminal` (the
additive `ACKNOWLEDGED --close--> RESOLVED` row: allowed in memo mode only when every leg is
terminal, denied in picker mode) and `guard_any_dds_participant` — each with an allow and a deny.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import AssignmentId, IncidentId, RoleStageId, SnapshotId, UserId
from app.domain.common.state_machine import GuardContext, GuardRuntime
from app.domain.dds.assignment import DDSAssignment, fire_response_trigger, handoff_received_keys
from app.domain.dds.policy import NO_REFUSAL, StatusPolicy, allows_refusal, policy_of
from app.domain.dds.response import (
    CLOSABLE_RESPONSE_STATUSES,
    SERVICE_RESPONSE_LABELS_RU,
    TERMINAL_RESPONSE_STATUSES,
    ServiceResponseStatus,
    StatusSource,
    trigger_for,
)
from app.domain.enums import (
    ActorType,
    DDSStageState,
    RoleType,
    ServiceId,
    SessionMode,
    SessionState,
)
from app.domain.events.catalog import validate_payload
from app.domain.events.types import EventType
from app.domain.roles.dds import DDSModule
from app.domain.routing.catalog import LEGACY_REFERENCE
from app.domain.session.session import SessionParticipant, SimulationSession
from app.domain.session.variants import (
    CardSource,
    DdsBrigadeCall,
    DdsCardCheck,
    DdsMode,
    SessionVariants,
)

from tests.unit.domain.session import _builders as b

S = ServiceResponseStatus
TRAINEE = ActorRef(actor_type=ActorType.TRAINEE, actor_id=b.user("dds"))
SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)


def _leg(status: S = S.RECEIVED, *, bound: UserId | None = None) -> DDSAssignment:
    return DDSAssignment(
        assignment_id=AssignmentId(b.det_uuid("leg")),
        incident_id=IncidentId(b.INCIDENT_ID),
        role_stage_id=RoleStageId(b.det_uuid("stage:0")),
        snapshot_id=SnapshotId(b.det_uuid("snapshot")),
        service_type=ServiceId("FIRE_RESCUE"),
        state=DDSStageState.RECEIVED,
        received_at_offset_ms=0,
        response_status=status,
        bound_user_id=bound,
    )


def _fire(
    leg: DDSAssignment,
    trigger: str,
    *,
    actor: ActorRef = TRAINEE,
    policy: StatusPolicy = StatusPolicy.DEFAULT,
    comment_ru: str | None = None,
    order_number: str | None = None,
) -> tuple[DDSAssignment, dict[str, object]]:
    moved, event = fire_response_trigger(
        leg,
        trigger,
        actor=actor,
        now_ms=5_000,
        source=StatusSource.TRAINEE if actor is TRAINEE else StatusSource.SYSTEM,
        status_policy=policy,
        order_number=order_number,
        comment_ru=comment_ru,
    )
    return moved, dict(event.payload)


# ---------------------------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------------------------


def test_the_nine_memo_statuses_and_their_labels() -> None:
    assert [status.value for status in S] == [
        "ADDED",
        "RECEIVED",
        "ACCEPTED",
        "NOT_ACCEPTED",
        "RESPONSE_STARTED",
        "ARRIVED",
        "WORKING",
        "COMPLETED",
        "REFUSED",
    ]
    assert SERVICE_RESPONSE_LABELS_RU[S.NOT_ACCEPTED] == "Не принята"
    assert SERVICE_RESPONSE_LABELS_RU[S.REFUSED] == "Отказ от выполнения работ"
    assert {S.COMPLETED, S.REFUSED} == TERMINAL_RESPONSE_STATUSES
    assert {S.COMPLETED, S.NOT_ACCEPTED, S.REFUSED} == CLOSABLE_RESPONSE_STATUSES


def test_the_103_policy_is_catalog_data() -> None:
    catalog = LEGACY_REFERENCE.services("legacy-r1")
    assert policy_of(catalog, "AMBULANCE") is NO_REFUSAL
    assert policy_of(catalog, "FIRE_RESCUE") is StatusPolicy.DEFAULT
    assert policy_of(catalog, "NOT_A_SERVICE") is StatusPolicy.DEFAULT
    assert not allows_refusal(NO_REFUSAL)


# ---------------------------------------------------------------------------------------------
# One step, and its event
# ---------------------------------------------------------------------------------------------


def test_a_step_moves_the_leg_and_records_one_status_event() -> None:
    moved, payload = _fire(_leg(S.RECEIVED), "accept", order_number="Н-1", comment_ru="ok")

    assert moved.response_status is S.ACCEPTED
    assert moved.response_status_at_offset_ms == 5_000
    assert (moved.order_number, moved.last_comment_ru) == ("Н-1", "ok")
    validate_payload(EventType.DDS_SERVICE_STATUS_SET, payload)
    assert payload["previous_status"] == "RECEIVED"
    assert payload["new_status"] == "ACCEPTED"
    assert payload["trigger"] == "accept"
    assert payload["source"] == "TRAINEE"
    assert payload["completion_reason"] is None
    assert payload["actor_user_id"] == UUID(str(b.user("dds")))


def test_receive_is_the_systems_and_never_the_trainees() -> None:
    moved, payload = _fire(_leg(S.ADDED), "receive", actor=SIMULATION)
    assert moved.response_status is S.RECEIVED
    assert payload["actor_user_id"] is None
    with pytest.raises(InvalidTransitionError):
        _fire(_leg(S.ADDED), "receive")


@pytest.mark.parametrize("comment", [None, "", "  "])
def test_decline_and_refuse_need_a_comment(comment: str | None) -> None:
    with pytest.raises(InvalidTransitionError):
        _fire(_leg(S.RECEIVED), "decline", comment_ru=comment)
    with pytest.raises(InvalidTransitionError):
        _fire(_leg(S.WORKING), "refuse", comment_ru=comment)


def test_decline_with_a_comment_and_its_correction() -> None:
    declined, _ = _fire(_leg(S.RECEIVED), "decline", comment_ru="Не наша компетенция")
    assert declined.response_status is S.NOT_ACCEPTED
    corrected, payload = _fire(declined, "accept")
    assert corrected.response_status is S.ACCEPTED
    assert payload["previous_status"] == "NOT_ACCEPTED"


def test_the_103_policy_refuses_decline_and_refuse_and_opens_the_shortcut() -> None:
    with pytest.raises(InvalidTransitionError):
        _fire(_leg(S.RECEIVED), "decline", policy=NO_REFUSAL, comment_ru="x")
    with pytest.raises(InvalidTransitionError):
        _fire(_leg(S.ARRIVED), "refuse", policy=NO_REFUSAL, comment_ru="x")
    for status in (S.RECEIVED, S.ACCEPTED, S.RESPONSE_STARTED, S.ARRIVED, S.WORKING):
        moved, payload = _fire(_leg(status), "complete_without_brigade", policy=NO_REFUSAL)
        assert moved.response_status is S.COMPLETED
        assert payload["completion_reason"] == "WITHOUT_BRIGADE"


def test_the_shortcut_is_closed_to_a_default_service() -> None:
    with pytest.raises(InvalidTransitionError):
        _fire(_leg(S.RECEIVED), "complete_without_brigade")


def test_a_bound_leg_answers_only_its_participant() -> None:
    """`guard_leg_actor_bound` (§70.4.5): allow the bound user, deny another trainee; SIMULATION
    plays any leg."""
    mine = _leg(S.RECEIVED, bound=b.user("dds"))
    assert _fire(mine, "accept")[0].response_status is S.ACCEPTED
    theirs = _leg(S.RECEIVED, bound=b.user("other"))
    with pytest.raises(InvalidTransitionError):
        _fire(theirs, "accept")
    assert _fire(theirs, "accept", actor=SIMULATION)[0].response_status is S.ACCEPTED


def test_handoff_received_keys_name_the_responder_and_the_first_status() -> None:
    assert handoff_received_keys(_leg(S.ADDED)) == {
        "responder": "TRAINEE",
        "bound_user_id": None,
        "initial_response_status": "ADDED",
    }


# ---------------------------------------------------------------------------------------------
# trigger_for — the pencil's target status → the one trigger
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,target,policy,expected",
    [
        (S.RECEIVED, S.ACCEPTED, StatusPolicy.DEFAULT, "accept"),
        (S.RECEIVED, S.NOT_ACCEPTED, StatusPolicy.DEFAULT, "decline"),
        (S.NOT_ACCEPTED, S.ACCEPTED, StatusPolicy.DEFAULT, "accept"),
        (S.ACCEPTED, S.RESPONSE_STARTED, StatusPolicy.DEFAULT, "start_response"),
        (S.WORKING, S.COMPLETED, StatusPolicy.DEFAULT, "complete"),
        (S.WORKING, S.COMPLETED, NO_REFUSAL, "complete"),
        (S.ARRIVED, S.COMPLETED, NO_REFUSAL, "complete_without_brigade"),
        (S.ARRIVED, S.REFUSED, StatusPolicy.DEFAULT, "refuse"),
        (S.ARRIVED, S.COMPLETED, StatusPolicy.DEFAULT, None),
        (S.ACCEPTED, S.ARRIVED, StatusPolicy.DEFAULT, None),
        (S.COMPLETED, S.ACCEPTED, StatusPolicy.DEFAULT, None),
    ],
)
def test_trigger_for(current: S, target: S, policy: StatusPolicy, expected: str | None) -> None:
    assert trigger_for(current, target, policy) == expected


# ---------------------------------------------------------------------------------------------
# The memo stage guards (§70.4.4): allow + deny
# ---------------------------------------------------------------------------------------------


def _variants(mode: DdsMode) -> SessionVariants:
    return SessionVariants(
        card_source=CardSource.GENERATED_CARD,
        dds_mode=mode,
        dds_card_check=DdsCardCheck.OFF,
        dds_brigade_call=DdsBrigadeCall.OFF,
    )


def _session(mode: DdsMode, state: DDSStageState) -> SimulationSession:
    stage = b.build_stage(
        order_index=0, role_type=RoleType.DDS, state=state, participant_user_id=b.user("dds")
    )
    session = b.build_session(
        session_mode=SessionMode.MULTI_TRAINEE,
        state=SessionState.ACTIVE,
        stages=[stage],
        participants=[
            SessionParticipant(user_id=b.user("dds"), assigned_role_type=RoleType.DDS),
            SessionParticipant(user_id=b.user("dds2"), assigned_role_type=RoleType.DDS),
            SessionParticipant(user_id=b.user("op"), assigned_role_type=RoleType.OPERATOR_112),
        ],
    )
    return session.model_copy(update={"variants": _variants(mode)})


def _can_close(mode: DdsMode, *, all_terminal: bool) -> bool:
    session = _session(mode, DDSStageState.ACKNOWLEDGED)
    ctx = GuardContext(
        actor=TRAINEE,
        role_type=RoleType.DDS,
        session=session,
        stage=session.stages[0],
        runtime=GuardRuntime(all_legs_terminal=all_terminal),
    )
    machine = DDSModule().state_machine_for(session.variants)
    return machine.can_fire(DDSStageState.ACKNOWLEDGED, "close", ctx)


def test_the_memo_close_row_is_allowed_when_every_leg_is_terminal() -> None:
    assert _can_close(DdsMode.MEMO_STATUSES, all_terminal=True)


def test_the_memo_close_row_is_denied_while_a_leg_is_open() -> None:
    assert not _can_close(DdsMode.MEMO_STATUSES, all_terminal=False)


def test_the_memo_close_row_is_denied_in_picker_mode() -> None:
    """The guard is registered in the picker registry too, where it always denies."""
    assert not _can_close(DdsMode.RESOURCE_PICKER, all_terminal=True)


def test_the_memo_close_lands_in_resolved_then_closes() -> None:
    session = _session(DdsMode.MEMO_STATUSES, DDSStageState.ACKNOWLEDGED)
    runtime = GuardRuntime(all_legs_terminal=True)
    moved, first = session.fire_stage_trigger(
        session.stages[0].role_stage_id, "close", actor=TRAINEE, runtime=runtime
    )
    assert moved.stages[0].state is DDSStageState.RESOLVED
    closed, second = moved.fire_stage_trigger(
        moved.stages[0].role_stage_id, "close", actor=TRAINEE, runtime=runtime
    )
    assert closed.stages[0].state is DDSStageState.CLOSED
    assert [event.event_type for event in [*first, *second]] == [
        EventType.STAGE_STATE_CHANGED,
        EventType.STAGE_STATE_CHANGED,
        EventType.ROLE_STAGE_COMPLETED,
    ]


def _can_acknowledge(mode: DdsMode, user_name: str) -> bool:
    session = _session(mode, DDSStageState.RECEIVED)
    ctx = GuardContext(
        actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=b.user(user_name)),
        role_type=RoleType.DDS,
        session=session,
        stage=session.stages[0],
    )
    machine = DDSModule().state_machine_for(session.variants)
    return machine.can_fire(DDSStageState.RECEIVED, "acknowledge", ctx)


def test_memo_acknowledge_is_open_to_any_dds_participant() -> None:
    """`DDS_GUARDS_MEMO`'s `guard_participant_assigned_to_stage` (§70.4.4): allow both ДДС
    participants, deny the 112 one."""
    assert _can_acknowledge(DdsMode.MEMO_STATUSES, "dds")
    assert _can_acknowledge(DdsMode.MEMO_STATUSES, "dds2")
    assert not _can_acknowledge(DdsMode.MEMO_STATUSES, "op")


def test_picker_acknowledge_keeps_the_stage_participant_rule() -> None:
    assert _can_acknowledge(DdsMode.RESOURCE_PICKER, "dds")
    assert not _can_acknowledge(DdsMode.RESOURCE_PICKER, "dds2")


def test_the_memo_machine_refuses_a_resource_trigger() -> None:
    session = _session(DdsMode.MEMO_STATUSES, DDSStageState.ACKNOWLEDGED)
    ctx = GuardContext(
        actor=TRAINEE, role_type=RoleType.DDS, session=session, stage=session.stages[0]
    )
    with pytest.raises(InvalidTransitionError):
        DDSModule().state_machine_for(session.variants).fire(
            DDSStageState.ACKNOWLEDGED, "open_resource_selection", ctx
        )

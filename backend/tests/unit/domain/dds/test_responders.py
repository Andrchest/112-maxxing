"""Several ДДС trainees and scripted responders, in the pure domain (I3 E5b, HLD 70 §70.4.5).

* `assign_responders` — who plays each leg: the participant bound to its service, the one trainee
  when nobody is bound, else the script;
* `guard_leg_actor_bound` — a trainee may never move a `SCRIPTED` leg, nor a leg bound to another;
* `due_scripted_steps` / `fire_due_scripted_steps` — the script is walked one step at a time,
  each step stamped with its **due** offset, so the stream is the same however the running offset
  is sampled (INV 7 at the unit level);
* the session binding — `validate` requires distinct services held by ДДС participants, and a
  DDS stage holds several participants only when each is bound.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from app.application.dds.stage_automation import fire_due_scripted_steps
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import AssignmentId, IncidentId, RoleStageId, SnapshotId, UserId
from app.domain.common.state_machine import GuardRuntime
from app.domain.dds.assignment import DDSAssignment, fire_response_trigger
from app.domain.dds.policy import StatusPolicy
from app.domain.dds.responders import (
    DEFAULT_SCRIPT,
    ScriptedStep,
    assign_responders,
    due_scripted_steps,
    plays_leg,
    script_for,
    script_problems,
)
from app.domain.dds.response import LegResponder, ServiceResponseStatus, StatusSource
from app.domain.enums import (
    ActorType,
    DDSStageState,
    RoleType,
    ServiceId,
    SessionMode,
    SessionState,
)
from app.domain.session.session import create_session

from tests.unit.domain.session import _builders as b

S = ServiceResponseStatus
ONE = b.user("dds-one")
TWO = b.user("dds-two")


def _leg(service: str, *, received_at: int = 0, status: S = S.ADDED) -> DDSAssignment:
    return DDSAssignment(
        assignment_id=AssignmentId(b.det_uuid(f"leg:{service}")),
        incident_id=IncidentId(b.INCIDENT_ID),
        role_stage_id=RoleStageId(b.det_uuid("stage:0")),
        snapshot_id=SnapshotId(b.det_uuid("snapshot")),
        service_type=ServiceId(service),
        state=DDSStageState.RECEIVED,
        received_at_offset_ms=received_at,
        response_status=status,
    )


# ---------------------------------------------------------------------------------------------
# Who plays a leg
# ---------------------------------------------------------------------------------------------


def test_nobody_bound_leaves_every_leg_to_the_one_trainee() -> None:
    legs = assign_responders([_leg("FIRE_RESCUE"), _leg("POLICE")], {})
    assert {(leg.responder, leg.bound_user_id) for leg in legs} == {(LegResponder.TRAINEE, None)}


def test_a_bound_service_is_its_trainees_and_the_rest_are_scripted() -> None:
    fire, police, gas = assign_responders(
        [_leg("FIRE_RESCUE"), _leg("POLICE"), _leg("GAS_SERVICE")],
        {"FIRE_RESCUE": ONE, "POLICE": TWO},
    )
    assert (fire.responder, fire.bound_user_id) == (LegResponder.TRAINEE, ONE)
    assert (police.responder, police.bound_user_id) == (LegResponder.TRAINEE, TWO)
    assert (gas.responder, gas.bound_user_id) == (LegResponder.SCRIPTED, None)
    assert plays_leg(fire, ONE) and not plays_leg(fire, TWO)
    assert not plays_leg(gas, ONE) and not plays_leg(gas, TWO)


def test_the_leg_guard_refuses_a_trainee_on_a_scripted_or_foreign_leg() -> None:
    fire, gas = assign_responders([_leg("FIRE_RESCUE"), _leg("GAS_SERVICE")], {"FIRE_RESCUE": ONE})
    for leg, user in ((gas, ONE), (fire, TWO)):
        received = leg.model_copy(update={"response_status": S.RECEIVED})
        with pytest.raises(InvalidTransitionError):
            fire_response_trigger(
                received,
                "accept",
                actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=user),
                now_ms=1,
                source=StatusSource.TRAINEE,
            )
    moved, _event = fire_response_trigger(
        gas.model_copy(update={"response_status": S.RECEIVED}),
        "accept",
        actor=ActorRef(actor_type=ActorType.SIMULATION),
        now_ms=1,
        source=StatusSource.SCRIPTED_RESPONDER,
    )
    assert moved.response_status is S.ACCEPTED


# ---------------------------------------------------------------------------------------------
# The script
# ---------------------------------------------------------------------------------------------


def test_the_default_script_is_the_hld_schedule() -> None:
    assert [(step.after_ms, step.status) for step in DEFAULT_SCRIPT] == [
        (0, S.RECEIVED),
        (15_000, S.ACCEPTED),
        (60_000, S.RESPONSE_STARTED),
        (180_000, S.ARRIVED),
        (200_000, S.WORKING),
        (600_000, S.COMPLETED),
    ]
    assert script_problems(DEFAULT_SCRIPT) == []
    assert script_problems(DEFAULT_SCRIPT, StatusPolicy.NO_REFUSAL) == []
    assert script_for("DEFAULT", "POLICE") == DEFAULT_SCRIPT
    assert script_for(None, "POLICE") == DEFAULT_SCRIPT
    own = (ScriptedStep(after_ms=5, status=S.ACCEPTED),)
    assert script_for({ServiceId("POLICE"): own}, "POLICE") == own
    assert script_for({ServiceId("POLICE"): own}, "GAS_SERVICE") == DEFAULT_SCRIPT


def test_due_steps_follow_the_legs_status_and_the_running_offset() -> None:
    assert [at for _step, at in due_scripted_steps(S.ADDED, 5_000, DEFAULT_SCRIPT, 4_999)] == []
    assert [at for _step, at in due_scripted_steps(S.ADDED, 5_000, DEFAULT_SCRIPT, 70_000)] == [
        5_000,
        20_000,
        65_000,
    ]
    after_accept = due_scripted_steps(S.ACCEPTED, 5_000, DEFAULT_SCRIPT, 1_000_000)
    assert [step.status for step, _at in after_accept] == [
        S.RESPONSE_STARTED,
        S.ARRIVED,
        S.WORKING,
        S.COMPLETED,
    ]


def _walk(ticks: Sequence[int]) -> list[tuple[int, str, str, str]]:
    """Fire the due scripted steps of three scripted legs at every offset of `ticks`."""
    responders = {
        ServiceId("POLICE"): (
            ScriptedStep(after_ms=100, status=S.RECEIVED),
            ScriptedStep(after_ms=1_250, status=S.NOT_ACCEPTED, comment_ru="Не наше"),
        ),
        ServiceId("GAS_SERVICE"): (
            ScriptedStep(after_ms=700, status=S.ACCEPTED, order_number="Г-7"),
            ScriptedStep(after_ms=700, status=S.RESPONSE_STARTED),
            ScriptedStep(after_ms=2_900, status=S.ARRIVED),
        ),
    }
    legs = list(
        assign_responders(
            [
                _leg("FIRE_RESCUE", received_at=50),
                _leg("POLICE", received_at=50),
                _leg("GAS_SERVICE", received_at=50),
            ],
            {"FIRE_RESCUE": ONE},
        )
    )
    scripted = [leg for leg in legs if leg.responder is LegResponder.SCRIPTED]
    stream: list[tuple[int, str, str, str]] = []
    for now in ticks:
        moved, events = fire_due_scripted_steps(
            scripted, responders, now, policy=lambda _leg: StatusPolicy.DEFAULT
        )
        by_id = {leg.assignment_id: leg for leg in moved}
        scripted = [by_id.get(leg.assignment_id, leg) for leg in scripted]
        stream.extend(
            (
                event.monotonic_offset_ms,
                str(event.payload["service_type"]),
                str(event.payload["new_status"]),
                str(event.payload["source"]),
            )
            for event in events
        )
    return stream


def test_the_scripted_stream_is_the_same_at_any_tick_rate() -> None:
    """INV 7 at the unit level: steps are stamped with their due offsets, never the tick's."""
    fine = _walk(range(100, 4_001, 100))
    coarse = _walk([900, 1_800, 2_700, 3_600, 4_000])
    once = _walk([4_000])
    assert fine == coarse == once
    assert fine == [
        (150, "POLICE", "RECEIVED", "SCRIPTED_RESPONDER"),
        (750, "GAS_SERVICE", "RECEIVED", "SCRIPTED_RESPONDER"),
        (750, "GAS_SERVICE", "ACCEPTED", "SCRIPTED_RESPONDER"),
        (750, "GAS_SERVICE", "RESPONSE_STARTED", "SCRIPTED_RESPONDER"),
        (1_300, "POLICE", "NOT_ACCEPTED", "SCRIPTED_RESPONDER"),
        (2_950, "GAS_SERVICE", "ARRIVED", "SCRIPTED_RESPONDER"),
    ]


def test_an_unplayable_step_stops_only_its_own_leg() -> None:
    """A script the catalog's policy no longer allows (decline under `NO_REFUSAL`) stops there."""
    police, gas = assign_responders([_leg("POLICE"), _leg("GAS_SERVICE")], {"FIRE_RESCUE": ONE})
    responders = {
        ServiceId("POLICE"): (
            ScriptedStep(after_ms=0, status=S.RECEIVED),
            ScriptedStep(after_ms=10, status=S.NOT_ACCEPTED, comment_ru="Нет"),
            ScriptedStep(after_ms=20, status=S.ACCEPTED),
        ),
    }
    moved, events = fire_due_scripted_steps(
        [police, gas],
        responders,
        20,
        policy=lambda leg: (
            StatusPolicy.NO_REFUSAL if leg.service_type == "POLICE" else StatusPolicy.DEFAULT
        ),
    )
    statuses = {leg.service_type: leg.response_status for leg in moved}
    assert statuses == {"POLICE": S.RECEIVED, "GAS_SERVICE": S.RECEIVED}
    assert len(events) == 2


# ---------------------------------------------------------------------------------------------
# The session binding (`validate`)
# ---------------------------------------------------------------------------------------------


def _validated(
    mode: SessionMode,
    participants: Sequence[tuple[UserId, RoleType | None]],
    services: dict[UserId, ServiceId],
) -> object:
    chain = (RoleType.DDS,)
    session, _events = create_session(
        session_id=b.SESSION_ID,
        incident_id=b.INCIDENT_ID,
        stage_ids=b.stage_ids(len(chain)),
        scenario_version=b.scenario_version(role_chain=chain),
        scenario_id=b.scenario_ids()[0],
        scenario_slug=b.scenario_ids()[1],
        session_mode=mode,
        created_by=b.INSTRUCTOR,
        participants=participants,
        assigned_services=services,
    )
    ready, _ = session.validate_session(actor=b.SYSTEM, runtime=GuardRuntime(scenario_valid=True))
    assert ready.state is SessionState.READY
    return ready


def test_two_bound_dds_trainees_share_the_stage_the_first_is_primary() -> None:
    ready = _validated(
        SessionMode.MULTI_TRAINEE,
        [(ONE, RoleType.DDS), (TWO, RoleType.DDS)],
        {ONE: ServiceId("FIRE_RESCUE"), TWO: ServiceId("POLICE")},
    )
    stage = ready.stages[0]  # type: ignore[attr-defined]
    assert stage.participant_user_id == ONE
    assert ready.dds_service_bindings == {"FIRE_RESCUE": ONE, "POLICE": TWO}  # type: ignore[attr-defined]
    assert ready.plays_dds(TWO)  # type: ignore[attr-defined]


def test_one_bound_trainee_in_single_role_is_valid() -> None:
    _validated(SessionMode.SINGLE_ROLE, [(ONE, RoleType.DDS)], {ONE: ServiceId("FIRE_RESCUE")})


@pytest.mark.parametrize(
    ("participants", "services"),
    [
        ([(ONE, RoleType.DDS), (TWO, RoleType.DDS)], {ONE: "FIRE_RESCUE", TWO: "FIRE_RESCUE"}),
        ([(ONE, RoleType.DDS), (TWO, RoleType.DDS)], {ONE: "FIRE_RESCUE"}),
        ([(ONE, RoleType.DDS), (TWO, RoleType.DDS)], {}),
        ([(ONE, RoleType.DDS)], {ONE: ""}),
    ],
    ids=["same-service", "one-unbound", "none-bound", "empty-id"],
)
def test_validate_refuses_an_unusable_binding(
    participants: list[tuple[UserId, RoleType | None]], services: dict[UserId, str]
) -> None:
    chain = (RoleType.DDS,)
    session, _events = create_session(
        session_id=b.SESSION_ID,
        incident_id=b.INCIDENT_ID,
        stage_ids=b.stage_ids(len(chain)),
        scenario_version=b.scenario_version(role_chain=chain),
        scenario_id=b.scenario_ids()[0],
        scenario_slug=b.scenario_ids()[1],
        session_mode=SessionMode.MULTI_TRAINEE,
        created_by=b.INSTRUCTOR,
        participants=participants,
        assigned_services={user: ServiceId(service) for user, service in services.items()},
    )
    with pytest.raises(InvalidTransitionError):
        session.validate_session(actor=b.SYSTEM, runtime=GuardRuntime(scenario_valid=True))

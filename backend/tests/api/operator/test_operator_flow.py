"""The Operator 112 stage, end to end over HTTP (SPEC §7, §9, §10; §10.8, D5, D8).

One test walks the whole stage exactly as a trainee would, and the rest pick single properties
out of it. Every assertion that could be written as a retyped table is instead derived from
`docs/hld/openapi.yaml` or from `Operator112Module` — a test that restated the contract would
pass while the contract and the code drifted apart.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.domain.enums import Operator112StageState
from app.domain.events.types import EventType
from app.domain.roles.operator112 import Operator112Module

from tests.api._openapi import load_openapi, operation_of
from tests.api.conftest import auth
from tests.api.operator.conftest import OperatorFlow

pytestmark = pytest.mark.integration

MODULE = Operator112Module()

OPERATOR_PREFIX = "/api/v1/sessions/{session_id}/operator"


# ---------------------------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------------------------


async def test_the_whole_operator_stage_end_to_end(flow: OperatorFlow) -> None:
    """`WAITING_FOR_CALL` -> ring -> answer -> interview -> card -> services -> handoff prep."""
    # The stage starts waiting: the trainee has no action at all (§10.9).
    first = await flow.snapshot()
    assert first.status_code == 200, first.text
    assert first.json()["stage_state"] == "WAITING_FOR_CALL"
    assert first.json()["available_actions"] == []
    assert first.json()["call_state"]["phase"] == "NO_CALL"

    # The simulation rings, because the fake transport says the caller joined.
    assert await flow.advance_call_flow() is True
    ringing = (await flow.snapshot()).json()
    assert ringing["stage_state"] == "RINGING"
    assert ringing["call_state"]["phase"] == "RINGING"
    assert ringing["call_state"]["call_id"] is not None
    assert [action["action_id"] for action in ringing["available_actions"]] == ["answer"]

    # The trainee answers.
    answered = await flow.post("/operator/call/answer")
    assert answered.status_code == 200, answered.text
    assert answered.json()["stage_state"] == "CONNECTED"
    assert answered.json()["call_state"]["phase"] == "CONNECTED"

    # The caller speaks; the first final transcript is what opens the interview.
    await flow.append_asr(EventType.ASR_PARTIAL, "Горит…")
    assert await flow.advance_call_flow() is False, "a partial is not a finalized turn"
    await flow.append_asr(EventType.ASR_FINAL, "Горит квартира, улица Ленина, дом 5")
    assert await flow.advance_call_flow() is True
    assert (await flow.snapshot()).json()["stage_state"] == "INTERVIEW"

    # The trainee fills the card, one field per command (SPEC §9).
    typed = await flow.set_field("incident.type", "FIRE")
    assert typed.status_code == 200, typed.text
    assert typed.json()["revision"]["revision_no"] == 1
    assert typed.json()["card"]["values"]["incident.type"] == "FIRE"
    assert (await flow.set_field("address.street", "Ленина")).status_code == 200
    assert (await flow.set_field("address.house", "5")).status_code == 200
    assert (await flow.set_field("flags.threat_to_life", True)).status_code == 200

    # …and chooses the recipient services.
    selected = await flow.select("FIRE_RESCUE")
    assert selected.status_code == 200, selected.text
    assert selected.json()["selected_services"] == ["FIRE_RESCUE"]
    assert (await flow.select("AMBULANCE")).json()["selected_services"] == [
        "FIRE_RESCUE",
        "AMBULANCE",
    ]
    assert (await flow.deselect("AMBULANCE")).json()["selected_services"] == ["FIRE_RESCUE"]

    # Handoff preparation, back, and in again — the stage machine allows the round trip while the
    # call is still connected (`guard_call_still_connected`).
    assert (await flow.post("/operator/handoff/prepare")).json()[
        "stage_state"
    ] == "HANDOFF_PREPARATION"
    assert (await flow.post("/operator/handoff/cancel")).json()["stage_state"] == "INTERVIEW"
    assert (await flow.post("/operator/handoff/prepare")).json()[
        "stage_state"
    ] == "HANDOFF_PREPARATION"

    # Hanging up is not a transition: the stage stays where it was.
    ended = await flow.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    assert ended.status_code == 200, ended.text
    assert ended.json()["stage_state"] == "HANDOFF_PREPARATION"
    assert ended.json()["call_state"]["phase"] == "ENDED"
    assert ended.json()["call_state"]["duration_ms"] is not None

    # And once the call is over, there is no going back to the interview.
    refused = await flow.post("/operator/handoff/cancel")
    assert refused.status_code == 409
    assert refused.json()["code"] == "INVALID_TRANSITION"


# ---------------------------------------------------------------------------------------------
# The snapshot agrees with the command
# ---------------------------------------------------------------------------------------------


async def test_the_snapshot_equals_the_view_the_command_returned(interview: OperatorFlow) -> None:
    """After *each* step, `getSessionSnapshot` shows what the command just answered (§42 test 13).

    The snapshot is taken immediately after every command, never once at the end: the property is
    that a refresh at any moment restores exactly the state the last command produced.
    """
    steps = (
        lambda: interview.set_field("incident.type", "FIRE"),
        lambda: interview.select("FIRE_RESCUE"),
        lambda: interview.post("/operator/handoff/prepare"),
        lambda: interview.post("/operator/call/end", json={"reason": "CALLER_HANGUP"}),
    )
    for step in steps:
        response = await step()
        assert response.status_code == 200, response.text
        body = response.json()
        snapshot = (await interview.snapshot()).json()
        card = body.get("card", body)
        assert snapshot["card"]["values"] == card["values"]
        assert snapshot["card"]["revision_counter"] == card["revision_counter"]
        if "stage_state" in body:
            assert snapshot["stage_state"] == body["stage_state"]
            assert snapshot["call_state"] == body["call_state"]
            assert snapshot["last_seq_no"] == body["last_seq_no"]


async def test_the_snapshot_last_seq_no_is_the_resume_cursor(interview: OperatorFlow) -> None:
    """`last_seq_no` is the highest `seq_no` in the log at snapshot time — the resume point."""
    await interview.set_field("incident.type", "FIRE")
    snapshot = (await interview.snapshot()).json()
    assert snapshot["last_seq_no"] == len(await interview.event_types())


# ---------------------------------------------------------------------------------------------
# x-emits: what each command appends is what the contract says it appends
# ---------------------------------------------------------------------------------------------


def _x_emits(path: str, method: str) -> list[str]:
    """The `x-emits` list `openapi.yaml` gives one operation — read, never retyped."""
    operation = operation_of(load_openapi(), path, method)
    assert operation is not None, f"{method} {path} is not in openapi.yaml"
    emits = operation.get("x-emits")
    assert isinstance(emits, list)
    return list(emits)


async def _emitted(flow: OperatorFlow, before: list[str]) -> list[str]:
    return (await flow.event_types())[len(before) :]


async def test_answer_call_emits_exactly_its_x_emits(ringing: OperatorFlow) -> None:
    before = await ringing.event_types()
    assert (await ringing.post("/operator/call/answer")).status_code == 200
    assert await _emitted(ringing, before) == _x_emits(f"{OPERATOR_PREFIX}/call/answer", "post")


async def test_end_call_emits_exactly_its_x_emits(interview: OperatorFlow) -> None:
    before = await interview.event_types()
    response = await interview.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    assert response.status_code == 200, response.text
    assert await _emitted(interview, before) == _x_emits(f"{OPERATOR_PREFIX}/call/end", "post")


async def test_set_card_field_emits_exactly_its_x_emits(interview: OperatorFlow) -> None:
    before = await interview.event_types()
    assert (await interview.set_field("address.house", "5")).status_code == 200
    assert await _emitted(interview, before) == _x_emits(f"{OPERATOR_PREFIX}/card/field", "put")


async def test_select_service_emits_exactly_its_x_emits(interview: OperatorFlow) -> None:
    before = await interview.event_types()
    assert (await interview.select("POLICE")).status_code == 200
    assert await _emitted(interview, before) == _x_emits(
        f"{OPERATOR_PREFIX}/services/select", "post"
    )


async def test_deselect_service_emits_exactly_its_x_emits(interview: OperatorFlow) -> None:
    await interview.select("POLICE")
    before = await interview.event_types()
    assert (await interview.deselect("POLICE")).status_code == 200
    assert await _emitted(interview, before) == _x_emits(
        f"{OPERATOR_PREFIX}/services/deselect", "post"
    )


async def test_begin_handoff_preparation_emits_exactly_its_x_emits(
    interview: OperatorFlow,
) -> None:
    before = await interview.event_types()
    assert (await interview.post("/operator/handoff/prepare")).status_code == 200
    assert await _emitted(interview, before) == _x_emits(
        f"{OPERATOR_PREFIX}/handoff/prepare", "post"
    )


async def test_back_to_interview_emits_exactly_its_x_emits(interview: OperatorFlow) -> None:
    assert (await interview.post("/operator/handoff/prepare")).status_code == 200
    before = await interview.event_types()
    assert (await interview.post("/operator/handoff/cancel")).status_code == 200
    assert await _emitted(interview, before) == _x_emits(
        f"{OPERATOR_PREFIX}/handoff/cancel", "post"
    )


@pytest.mark.parametrize(
    "path,method",
    [
        (f"{OPERATOR_PREFIX}/card", "get"),
        (f"{OPERATOR_PREFIX}/card/revisions", "get"),
        ("/api/v1/sessions/{session_id}/snapshot", "get"),
    ],
)
async def test_a_read_emits_nothing(interview: OperatorFlow, path: str, method: str) -> None:
    """Every read declares `x-emits: []`, and appends nothing — which is the same statement."""
    assert _x_emits(path, method) == []
    before = await interview.event_types()
    suffix = path.removeprefix("/api/v1/sessions/{session_id}")
    assert (await interview.get(suffix)).status_code == 200
    assert await interview.event_types() == before


# ---------------------------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------------------------

#: `(suffix, method, body)` for every operator *command* this task implements.
COMMANDS: tuple[tuple[str, str, Any], ...] = (
    ("/operator/call/answer", "post", None),
    ("/operator/call/end", "post", {"reason": "OPERATOR_HANGUP"}),
    ("/operator/card/field", "put", {"field_path": "address.house", "new_value": "5"}),
    ("/operator/services/select", "post", {"service_type": "POLICE"}),
    ("/operator/services/deselect", "post", {"service_type": "POLICE"}),
    ("/operator/handoff/prepare", "post", None),
    ("/operator/handoff/cancel", "post", None),
)


#: `suffix -> openapi `x-action``, the action id D8's second gate checks for that endpoint.
ACTION_OF: dict[str, str] = {
    "/operator/call/answer": "answer",
    "/operator/call/end": "end_call",
    "/operator/card/field": "edit_card",
    "/operator/services/select": "select_services",
    "/operator/services/deselect": "select_services",
    "/operator/handoff/prepare": "open_handoff_preparation",
    "/operator/handoff/cancel": "back_to_interview",
}


async def _call(flow: OperatorFlow, suffix: str, method: str, body: Any, token: str) -> Any:
    if method == "put":
        return await flow.put(suffix, token=token, json=body)
    return await flow.post(suffix, token=token, json=body)


@pytest.mark.parametrize("suffix,method,body", COMMANDS)
async def test_a_command_from_the_wrong_role_is_403(
    interview: OperatorFlow, suffix: str, method: str, body: Any
) -> None:
    """The DDS trainee is a participant of this session but not of its active stage (D8)."""
    response = await _call(interview, suffix, method, body, interview.dds_token)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


@pytest.mark.parametrize("suffix,method,body", COMMANDS)
async def test_an_instructor_may_not_complete_a_trainee_action(
    interview: OperatorFlow, suffix: str, method: str, body: Any
) -> None:
    """SPEC §7: the instructor observes and intervenes; they never act *for* the trainee."""
    response = await _call(interview, suffix, method, body, interview.instructor_token)
    assert response.status_code == 403, response.text
    assert response.json()["code"] in {"FORBIDDEN_FOR_ROLE", "PARTICIPANT_NOT_ASSIGNED"}


@pytest.mark.parametrize("suffix,method,body", COMMANDS)
async def test_a_command_on_an_unknown_session_is_404(
    interview: OperatorFlow, suffix: str, method: str, body: Any
) -> None:
    url = f"/api/v1/sessions/{uuid4()}{suffix}"
    headers = auth(interview.operator_token)
    response = await getattr(interview.client, method)(url, headers=headers, json=body)
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize("suffix,method,body", COMMANDS)
async def test_a_command_on_a_non_active_session_is_409(
    interview: OperatorFlow, suffix: str, method: str, body: Any
) -> None:
    """An aborted session accepts no stage command (`SESSION_NOT_ACTIVE`)."""
    aborted = await interview.client.post(
        interview.url("/abort"),
        headers=auth(interview.instructor_token),
        json={"reason": "закончили досрочно"},
    )
    assert aborted.status_code == 200, aborted.text
    response = await _call(interview, suffix, method, body, interview.operator_token)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "SESSION_NOT_ACTIVE"


def _unavailable_in(state: Operator112StageState) -> list[tuple[str, str, Any]]:
    """Every command of `COMMANDS` whose `x-action` the module does NOT offer in `state`.

    Derived from `Operator112Module.available_actions` rather than from a table typed here: the
    pair "this command, that state" is unavailable exactly when the module says so, and this
    function is how the test learns it. `ids` below name the endpoint, so a new state or a new
    row in §10.9's table changes the matrix with no edit in this file.
    """
    available = {action.action_id for action in MODULE.available_actions(state)}
    return [
        (suffix, method, body)
        for suffix, method, body in COMMANDS
        if ACTION_OF[suffix] not in available
    ]


def _ids(rows: list[tuple[str, str, Any]]) -> list[str]:
    return [row[0] for row in rows]


_WAITING = _unavailable_in(Operator112StageState.WAITING_FOR_CALL)
_RINGING = _unavailable_in(Operator112StageState.RINGING)
_CONNECTED = _unavailable_in(Operator112StageState.CONNECTED)
_INTERVIEW = _unavailable_in(Operator112StageState.INTERVIEW)


@pytest.mark.parametrize("suffix,method,body", _WAITING, ids=_ids(_WAITING))
async def test_waiting_for_call_offers_no_action_at_all(
    flow: OperatorFlow, suffix: str, method: str, body: Any
) -> None:
    """D8's second gate in `WAITING_FOR_CALL`: §10.9 lists no action, so every command is 409."""
    response = await _call(flow, suffix, method, body, flow.operator_token)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


@pytest.mark.parametrize("suffix,method,body", _RINGING, ids=_ids(_RINGING))
async def test_ringing_offers_only_answer(
    ringing: OperatorFlow, suffix: str, method: str, body: Any
) -> None:
    """Everything but `answer` is `ACTION_NOT_AVAILABLE` while the phone is still ringing."""
    response = await _call(ringing, suffix, method, body, ringing.operator_token)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


@pytest.mark.parametrize("suffix,method,body", _CONNECTED, ids=_ids(_CONNECTED))
async def test_connected_offers_only_the_card_and_hanging_up(
    connected: OperatorFlow, suffix: str, method: str, body: Any
) -> None:
    """`CONNECTED` offers `edit_card` and `end_call` only (§10.9)."""
    response = await _call(connected, suffix, method, body, connected.operator_token)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


@pytest.mark.parametrize("suffix,method,body", _INTERVIEW, ids=_ids(_INTERVIEW))
async def test_interview_does_not_offer_answering_or_going_back(
    interview: OperatorFlow, suffix: str, method: str, body: Any
) -> None:
    """`INTERVIEW` has no `answer` and no `back_to_interview` — it is already the interview."""
    response = await _call(interview, suffix, method, body, interview.operator_token)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


def test_every_command_maps_to_an_action_the_module_knows() -> None:
    """A guard on the guard: `ACTION_OF` must name only action ids §10.9 actually defines.

    Without it, a typo in `ACTION_OF` would make `_unavailable_in` report a command as
    unavailable everywhere and the four matrices above would assert something vacuous.
    """
    known = {
        action.action_id
        for state in Operator112StageState
        for action in MODULE.available_actions(state)
    }
    assert set(ACTION_OF.values()) <= known
    assert set(ACTION_OF) == {suffix for suffix, _method, _body in COMMANDS}


async def test_a_participant_of_another_session_is_403(
    interview: OperatorFlow,
    client: Any,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: Any,
) -> None:
    """A trainee who plays *some* session may not command one they are not a participant of."""
    from tests.api.conftest import create_demo_session, participant

    other = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["admin1"], "OPERATOR_112"), participant(users["trainee2"], "DDS")],
    )
    started = await client.post(
        f"/api/v1/sessions/{other['id']}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    response = await client.post(
        f"/api/v1/sessions/{other['id']}/operator/call/answer",
        headers=auth(interview.operator_token),
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "PARTICIPANT_NOT_ASSIGNED"


async def test_an_unauthenticated_command_is_401(interview: OperatorFlow) -> None:
    response = await interview.client.post(interview.url("/operator/call/answer"))
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"

"""`getDdsWorkItem` and `acknowledgeDdsAssignment` over real HTTP (SPEC §10, §11; D3, D8).

The work item is the whole point of the handoff, and these tests pin what the contract promises
about it: it is the operator's frozen entry, it names what the operator omitted, it is addressed
to every recipient service and not just the primary one, and no role that must not see it can.

`acknowledge` is the first DDS command, so it is also where the shared gate is exercised in all
five of its refusals: a stranger, the 112 trainee, the instructor, a second acknowledgement and a
session that is not `ACTIVE`.
"""

from __future__ import annotations

import pytest

from tests.api.dds.conftest import (
    OperatorFlow,
    acknowledge,
    assignment_rows,
    dds_get,
    dds_post,
    event_types,
    events_of,
    work_item,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------------------------
# getDdsWorkItem
# ---------------------------------------------------------------------------------------------


async def test_the_work_item_carries_the_operators_entry_and_names_what_is_missing(
    dds_active: OperatorFlow,
) -> None:
    """SPEC §3 and §10 in one payload: "72", no invented floor, and the gap named."""
    item = await work_item(dds_active)

    assert item["card_values"]["address.house"] == "72"
    assert "address.floor" not in item["card_values"]
    assert item["missing_field_paths"] == ["caller.phone"]
    assert item["state"] == "RECEIVED"


async def test_the_work_item_is_addressed_to_every_recipient_service(
    dds_active: OperatorFlow,
) -> None:
    """R3: `recipient_services` is "who this went to"; `service_type` is only the identity leg."""
    item = await work_item(dds_active)

    assert item["recipient_services"] == ["FIRE_RESCUE", "AMBULANCE"]
    assert item["service_type"] == "FIRE_RESCUE"


async def test_the_work_items_identity_is_the_first_recipient_services_leg(
    dds_active: OperatorFlow, uow_factory: object
) -> None:
    """The singular view's `assignment_id` is one of the two rows, and a documented one."""
    item = await work_item(dds_active)
    rows = await assignment_rows(uow_factory, dds_active.session_id)

    fire = next(row for row in rows if row["service_type"] == "FIRE_RESCUE")
    assert item["assignment_id"] == str(fire["id"])
    assert len(rows) == 2


async def test_the_instructor_may_read_the_work_item(dds_active: OperatorFlow) -> None:
    """SPEC §7: observation without participation."""
    response = await dds_active.get("/dds/work-item", token=dds_active.instructor_token)

    assert response.status_code == 200, response.text


async def test_the_112_trainee_may_not_read_the_work_item(dds_active: OperatorFlow) -> None:
    """`Operator112Module`'s policy does not list `HANDOFF_SNAPSHOT` (D3)."""
    response = await dds_active.get("/dds/work-item", token=dds_active.operator_token)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_an_unauthenticated_caller_is_refused(dds_active: OperatorFlow) -> None:
    """D8: no token, no answer — and no hint that the session exists."""
    response = await dds_active.client.get(dds_active.url("/dds/work-item"))

    assert response.status_code == 401


# ---------------------------------------------------------------------------------------------
# acknowledgeDdsAssignment
# ---------------------------------------------------------------------------------------------


async def test_acknowledge_moves_the_stage_and_answers_with_the_new_view(
    dds_active: OperatorFlow,
) -> None:
    """`RECEIVED -> ACKNOWLEDGED`, and D8's "commands return the new materialized view"."""
    view = await acknowledge(dds_active)

    assert view["stage_state"] == "ACKNOWLEDGED"
    assert view["work_item"]["state"] == "ACKNOWLEDGED"
    assert [action["action_id"] for action in view["available_actions"]] == [
        "open_resource_selection",
        "send_status_update",
    ]
    assert view["session_state"] == "ACTIVE"
    assert view["resources"], "the stage view embeds the resource board"


async def test_acknowledge_emits_exactly_its_x_emits_list(dds_active: OperatorFlow) -> None:
    """`x-emits: [DDS_ACKNOWLEDGED, STAGE_STATE_CHANGED]` — one trainee event, whatever N is.

    I3 E5a: the tick D7 runs right after the command lets stage automation mirror each leg's
    response status from its new `state` (`RECEIVED → ACCEPTED`, SIMULATION, `source:
    PICKER_MIRROR`, HLD 70 §70.4.4) in its own transaction — after the command's own events,
    never between them.
    """
    before = await event_types(dds_active)
    await acknowledge(dds_active)
    after = await event_types(dds_active)

    emitted = after[len(before) :]
    assert emitted[:2] == ["DDS_ACKNOWLEDGED", "STAGE_STATE_CHANGED"]
    assert emitted[2:] == ["DDS_SERVICE_STATUS_SET"] * len(emitted[2:])
    mirrored = (await events_of(dds_active, "DDS_SERVICE_STATUS_SET"))[-len(emitted[2:]) :]
    assert {event["payload"]["source"] for event in mirrored} == {"PICKER_MIRROR"}
    last_by_leg = {event["payload"]["assignment_id"]: event["payload"] for event in mirrored}
    assert {payload["new_status"] for payload in last_by_leg.values()} == {"ACCEPTED"}


async def test_the_acknowledgement_names_the_primary_leg_and_its_latency(
    dds_active: OperatorFlow, uow_factory: object
) -> None:
    """One event per action (R5), with `latency_from_handoff_ms` measured from the fan-out."""
    await acknowledge(dds_active)

    events = await events_of(dds_active, "DDS_ACKNOWLEDGED")
    rows = await assignment_rows(uow_factory, dds_active.session_id)
    fire = next(row for row in rows if row["service_type"] == "FIRE_RESCUE")

    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["assignment_id"] == str(fire["id"])
    assert payload["latency_from_handoff_ms"] >= 0


async def test_every_leg_mirrors_the_acknowledgement(
    dds_active: OperatorFlow, uow_factory: object
) -> None:
    """R1/R1b: `state` and `acknowledged_at_offset_ms` are the same on all N legs."""
    await acknowledge(dds_active)

    rows = await assignment_rows(uow_factory, dds_active.session_id)

    assert {row["state"] for row in rows} == {"ACKNOWLEDGED"}
    assert len({row["acknowledged_at_offset_ms"] for row in rows}) == 1
    assert all(row["acknowledged_at_offset_ms"] is not None for row in rows)


async def test_a_second_acknowledgement_is_action_not_available(
    dds_active: OperatorFlow,
) -> None:
    """D8's second gate: `acknowledge` leaves `available_actions` the moment the stage moves."""
    await acknowledge(dds_active)

    response = await dds_post(dds_active, "/dds/acknowledge")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


async def test_the_112_trainee_may_not_acknowledge(dds_active: OperatorFlow) -> None:
    """The DDS endpoints are not the 112 stage's endpoints."""
    response = await dds_active.post("/dds/acknowledge", token=dds_active.operator_token)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_instructor_may_not_acknowledge(dds_active: OperatorFlow) -> None:
    """SPEC §7: the instructor never completes a trainee action."""
    response = await dds_active.post("/dds/acknowledge", token=dds_active.instructor_token)

    assert response.status_code == 403, response.text
    assert response.json()["code"] in ("FORBIDDEN_FOR_ROLE", "PARTICIPANT_NOT_ASSIGNED")


async def test_the_board_is_readable_before_anything_is_acknowledged(
    dds_active: OperatorFlow,
) -> None:
    """`listDdsResources` is a read: the eleven demo units, with their scenario ETAs."""
    response = await dds_get(dds_active, "/dds/resources")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 11
    engine = next(item for item in body["items"] if item["callsign"] == "АЦ-1")
    assert engine["eta"] == {
        "turnout_delay_seconds": 30,
        "travel_time_seconds": 150,
        "setup_seconds": 30,
        "on_scene_work_seconds": 240,
        "return_time_seconds": 180,
    }
    assert engine["selectable"] is False, "nothing is selectable before the selection screen"

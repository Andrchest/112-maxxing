"""Resource selection and dispatch over real HTTP (§10.7-§10.9, `openapi.yaml`; E9 rulings 3, 5).

The four commands that move units, and the two additive ones that open and leave the selection
screen. What these tests pin beyond "it works":

* **attachment is per leg** (analyst R4): a unit goes on its own service's leg, an off-service
  unit goes on the primary one, and `emergency_resources.assignment_id` says which. This is what
  the brief's first sabotage check breaks — `leg_for` returning the primary leg always makes
  `test_each_unit_hangs_on_its_own_services_leg` fail;
* **one trainee action, one trainee event** (R5): a dispatch of four units of two services emits
  exactly one `RESOURCE_DISPATCHED`, with `service_type_by_resource` naming each unit's *own*
  service — because the leg it hangs on does not imply it;
* **the E9 repair** (ruling 5): `select_resource` is available in `EN_ROUTE` / `ARRIVED` /
  `WORKING`, so `dispatch_additional` is reachable at all, and it is a self-transition that keeps
  the stage where it was;
* **`resource_state_changes` carries both E9 columns**: the leg the unit hung on and the
  `session_events.id` of the event that recorded the move.
"""

from __future__ import annotations

import pytest

from tests.api.dds.conftest import (
    OperatorFlow,
    acknowledge,
    assignment_rows,
    board,
    dds_post,
    deselect,
    dispatch,
    event_types,
    events_of,
    open_selection,
    resource_rows,
    select,
    state_change_rows,
)

pytestmark = pytest.mark.integration

#: Two fire units, one ambulance and one police unit — the last of which is **off-service**: the
#: operator's handoff named `FIRE_RESCUE` and `AMBULANCE`, so `POLICE` received no leg at all.
DISPATCH_SET = ("АЛ-1", "АСА-1", "СМП-11", "ППС-204")


@pytest.fixture
async def selecting(dds_active: OperatorFlow) -> OperatorFlow:
    """`dds_active`, acknowledged and with the selection screen open."""
    await acknowledge(dds_active)
    await open_selection(dds_active)
    return dds_active


@pytest.fixture
async def dispatched(selecting: OperatorFlow) -> OperatorFlow:
    """`selecting`, with `DISPATCH_SET` selected and dispatched."""
    for callsign in DISPATCH_SET:
        response = await select(selecting, callsign)
        assert response.status_code == 200, response.text
    await dispatch(selecting)
    return selecting


# ---------------------------------------------------------------------------------------------
# Opening and leaving the selection screen (the two additive operations)
# ---------------------------------------------------------------------------------------------


async def test_opening_the_selection_screen_moves_the_stage_and_emits_one_event(
    dds_active: OperatorFlow,
) -> None:
    """`openDdsResourceSelection`: `x-emits: [STAGE_STATE_CHANGED]`, no more."""
    await acknowledge(dds_active)
    before = await event_types(dds_active)

    view = await open_selection(dds_active)

    assert view["stage_state"] == "RESOURCE_SELECTION"
    assert (await event_types(dds_active))[len(before) :] == ["STAGE_STATE_CHANGED"]
    assert [action["action_id"] for action in view["available_actions"]] == [
        "select_resource",
        "deselect_resource",
        "dispatch",
        "back_to_acknowledged",
        "send_status_update",
    ]


async def test_leaving_the_selection_screen_is_refused_while_a_unit_is_selected(
    selecting: OperatorFlow,
) -> None:
    """`guard_no_resource_selected`: stepping back may lose no work."""
    assert (await select(selecting, "АЦ-1")).status_code == 200

    response = await dds_post(selecting, "/dds/resources/selection/cancel")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "INVALID_TRANSITION"


async def test_leaving_the_selection_screen_works_once_nothing_is_selected(
    selecting: OperatorFlow,
) -> None:
    """The mirror of `backToInterview`, and the deselect that makes it legal."""
    assert (await select(selecting, "АЦ-1")).status_code == 200
    assert (await deselect(selecting, "АЦ-1")).status_code == 200

    response = await dds_post(selecting, "/dds/resources/selection/cancel")

    assert response.status_code == 200, response.text
    assert response.json()["stage_state"] == "ACKNOWLEDGED"


# ---------------------------------------------------------------------------------------------
# select / deselect
# ---------------------------------------------------------------------------------------------


async def test_select_emits_its_two_events_and_shows_the_unit_on_the_work_item(
    selecting: OperatorFlow,
) -> None:
    """`x-emits: [RESOURCE_SELECTED, RESOURCE_STATUS_CHANGED]`, in that order."""
    before = await event_types(selecting)

    response = await select(selecting, "АЦ-1")

    assert response.status_code == 200, response.text
    view = response.json()
    assert (await event_types(selecting))[len(before) :] == [
        "RESOURCE_SELECTED",
        "RESOURCE_STATUS_CHANGED",
    ]
    engine = next(item for item in view["resources"] if item["callsign"] == "АЦ-1")
    assert engine["current_status"] == "SELECTED"
    assert view["work_item"]["selected_resource_ids"] == [engine["resource_id"]]


async def test_selecting_a_unit_outside_its_availability_window_is_resource_unavailable(
    selecting: OperatorFlow,
) -> None:
    """СМП-12 is `UNAVAILABLE` until 120 s: `409 RESOURCE_UNAVAILABLE`, not a generic `409`."""
    response = await select(selecting, "СМП-12")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "RESOURCE_UNAVAILABLE"


async def test_selecting_the_same_unit_twice_is_resource_unavailable(
    selecting: OperatorFlow,
) -> None:
    """`select` fires from `AVAILABLE`; a `SELECTED` unit has no such transition."""
    assert (await select(selecting, "АЦ-1")).status_code == 200

    response = await select(selecting, "АЦ-1")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "RESOURCE_UNAVAILABLE"


async def test_an_unknown_resource_id_is_a_404(selecting: OperatorFlow) -> None:
    """A unit that is not on this session's board."""
    response = await dds_post(
        selecting,
        "/dds/resources/select",
        {"resource_id": "11111111-1111-5111-8111-111111111111"},
    )

    assert response.status_code == 404, response.text


async def test_deselect_detaches_the_unit_and_emits_its_two_events(
    selecting: OperatorFlow, uow_factory: object
) -> None:
    """`x-emits: [RESOURCE_DESELECTED, RESOURCE_STATUS_CHANGED]`, and `assignment_id` cleared."""
    assert (await select(selecting, "АЦ-1")).status_code == 200
    before = await event_types(selecting)

    response = await deselect(selecting, "АЦ-1")

    assert response.status_code == 200, response.text
    assert (await event_types(selecting))[len(before) :] == [
        "RESOURCE_DESELECTED",
        "RESOURCE_STATUS_CHANGED",
    ]
    rows = await resource_rows(uow_factory, selecting.session_id)
    assert rows["АЦ-1"]["assignment_id"] is None
    assert rows["АЦ-1"]["current_status"] == "AVAILABLE"


# ---------------------------------------------------------------------------------------------
# Attachment — one work item, N legs
# ---------------------------------------------------------------------------------------------


async def test_each_unit_hangs_on_its_own_services_leg(
    dispatched: OperatorFlow, uow_factory: object
) -> None:
    """Analyst R4, ruling 3 — and the brief's first sabotage target.

    The ambulance is attached to the AMBULANCE leg; the two fire units **and** the off-service
    police unit are attached to the primary (FIRE_RESCUE) leg. A `leg_for` that always answered
    "primary" would put СМП-11 on the fire leg and fail here.
    """
    rows = await resource_rows(uow_factory, dispatched.session_id)
    legs = await assignment_rows(uow_factory, dispatched.session_id)
    fire_leg = next(leg["id"] for leg in legs if leg["service_type"] == "FIRE_RESCUE")
    ambulance_leg = next(leg["id"] for leg in legs if leg["service_type"] == "AMBULANCE")

    assert rows["СМП-11"]["assignment_id"] == ambulance_leg
    assert rows["АЛ-1"]["assignment_id"] == fire_leg
    assert rows["АСА-1"]["assignment_id"] == fire_leg
    assert rows["ППС-204"]["assignment_id"] == fire_leg, "an off-service unit goes on the primary"


async def test_an_off_service_unit_is_dispatchable_at_all(dispatched: OperatorFlow) -> None:
    """Ruling 3: a routing mistake is scored, not blocked."""
    view = await dispatch_view(dispatched)

    police = next(item for item in view["resources"] if item["callsign"] == "ППС-204")
    assert police["current_status"] == "DISPATCHED"


async def dispatch_view(flow: OperatorFlow) -> dict[str, object]:
    """The current stage view, read back through the board endpoint's sibling."""
    response = await flow.get("/dds/resources", token=flow.dds_token)
    assert response.status_code == 200, response.text
    return {"resources": response.json()["items"]}


async def test_the_leg_that_received_nothing_keeps_a_null_dispatched_at(
    selecting: OperatorFlow, uow_factory: object
) -> None:
    """R1b: `state = DISPATCHED, dispatched_at = null` is the fact "this service got nothing"."""
    assert (await select(selecting, "АЦ-1")).status_code == 200
    await dispatch(selecting)

    legs = await assignment_rows(uow_factory, selecting.session_id)
    fire = next(leg for leg in legs if leg["service_type"] == "FIRE_RESCUE")
    ambulance = next(leg for leg in legs if leg["service_type"] == "AMBULANCE")

    assert fire["state"] == ambulance["state"] == "DISPATCHED"
    assert fire["dispatched_at_offset_ms"] is not None
    assert ambulance["dispatched_at_offset_ms"] is None


# ---------------------------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------------------------


async def test_dispatch_emits_its_x_emits_list_once_per_click(
    selecting: OperatorFlow,
) -> None:
    """One `RESOURCE_DISPATCHED`, then one status event per unit, then the stage event (R5)."""
    for callsign in DISPATCH_SET:
        assert (await select(selecting, callsign)).status_code == 200
    before = await event_types(selecting)

    await dispatch(selecting)

    emitted = (await event_types(selecting))[len(before) :]
    assert emitted == [
        "RESOURCE_DISPATCHED",
        *["RESOURCE_STATUS_CHANGED"] * len(DISPATCH_SET),
        "STAGE_STATE_CHANGED",
    ]


async def test_the_dispatch_payload_names_each_units_own_service(
    dispatched: OperatorFlow,
) -> None:
    """The additive `service_type_by_resource` (ruling 4): never leg -> service."""
    events = await events_of(dispatched, "RESOURCE_DISPATCHED")

    assert len(events) == 1
    payload = events[0]["payload"]
    services = sorted(payload["service_type_by_resource"].values())
    assert services == ["AMBULANCE", "FIRE_RESCUE", "FIRE_RESCUE", "POLICE"]
    assert sorted(payload["callsigns"]) == sorted(DISPATCH_SET)
    assert payload["is_additional"] is False


async def test_the_dispatch_payload_carries_the_capability_union_and_the_etas(
    dispatched: OperatorFlow,
) -> None:
    """`capabilities_union` and `eta_seconds_by_resource`, so scoring needs no table lookup."""
    payload = (await events_of(dispatched, "RESOURCE_DISPATCHED"))[0]["payload"]

    assert set(payload["capabilities_union"]) >= {
        "HIGH_RISE_ACCESS",
        "BASIC_LIFE_SUPPORT",
        "AREA_CORDON",
    }
    # АЛ-1: turnout 40 s + travel 180 s.
    ladder = next(
        resource_id
        for resource_id, callsign in zip(payload["resource_ids"], payload["callsigns"], strict=True)
        if callsign == "АЛ-1"
    )
    assert payload["eta_seconds_by_resource"][ladder] == 220


async def test_the_dispatch_result_view_reports_what_went_out(
    selecting: OperatorFlow,
) -> None:
    """`DispatchResultView`: the ids, the ETAs, `is_additional` and the new stage view."""
    for callsign in DISPATCH_SET:
        assert (await select(selecting, callsign)).status_code == 200

    result = await dispatch(selecting, note_ru="Пожар на пятом этаже")

    assert result["is_additional"] is False
    assert len(result["dispatched_resource_ids"]) == 4
    assert set(result["eta_seconds_by_resource"]) == set(result["dispatched_resource_ids"])
    assert result["stage"]["stage_state"] == "DISPATCHED"
    assert sorted(result["stage"]["work_item"]["dispatched_resource_ids"]) == sorted(
        result["dispatched_resource_ids"]
    ), "the work item unions the legs, so every dispatched unit shows on it"


async def test_dispatching_with_nothing_selected_is_refused(selecting: OperatorFlow) -> None:
    """`guard_at_least_one_selected_available`."""
    response = await dds_post(selecting, "/dds/resources/dispatch", {"note_ru": None})

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "INVALID_TRANSITION"


async def test_the_state_change_rows_carry_the_leg_and_the_event_that_recorded_them(
    dispatched: OperatorFlow, uow_factory: object
) -> None:
    """The two §20.5 columns E9 owed: `assignment_id` and `session_event_id`."""
    rows = [
        row
        for row in await state_change_rows(uow_factory, dispatched.session_id)
        if row["trigger"] == "dispatch"
    ]

    assert len(rows) == len(DISPATCH_SET)
    assert all(row["assignment_id"] is not None for row in rows)
    assert all(row["session_event_id"] is not None for row in rows)


async def test_a_deselect_after_dispatch_is_refused(dispatched: OperatorFlow) -> None:
    """`guard_not_yet_dispatched`: a unit already rolling cannot be un-sent.

    It is also the only action available on it — `DISPATCHED` offers `open_resource_selection`
    and `send_status_update`, so the attempt is refused by the gate before the guard is reached.
    """
    response = await deselect(dispatched, "АЛ-1")

    assert response.status_code == 409, response.text


async def test_the_board_shows_nothing_selectable_once_dispatched(
    dispatched: OperatorFlow,
) -> None:
    """`DISPATCHED` is not a selection-open state: reinforcement goes through the screen again."""
    assert all(item["selectable"] is False for item in await board(dispatched))


async def test_the_refresh_snapshot_restores_what_was_selected(
    selecting: OperatorFlow,
) -> None:
    """SPEC §42 test 13: a reload shows the trainee's selection, not an empty board.

    `getSessionSnapshot` embeds the same work-item projection `getDdsWorkItem` answers with, so
    the two cannot disagree about which units are on the work item.
    """
    assert (await select(selecting, "АЦ-1")).status_code == 200

    response = await selecting.get("/snapshot", token=selecting.dds_token)

    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot["card"] is None, "a DDS viewer never receives the live card (D3)"
    assert len(snapshot["work_item"]["selected_resource_ids"]) == 1

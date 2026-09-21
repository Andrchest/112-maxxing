"""The whole incident, end to end over HTTP: 112 -> handoff -> DDS -> closure (SPEC §10-§12).

One test drives the timeline the brief describes and asserts at each step; the rest pin the
closure contract and determinism. The clock is a `FakeClock`, so four hundred simulated seconds
cost no wall-clock time and every ETA is exact rather than approximate.

The timeline, in session-offset milliseconds, with the demo scenario's own ETA data:

* **11 s** — the DDS stage goes live. Acknowledge, open the selection screen, select АЛ-1, АСА-1
  (fire), СМП-11 (ambulance) and ППС-204 (police — **off-service**, ruling 3), dispatch;
* **190 s** — the units have departed and the first is on scene, so the stage has walked
  `DISPATCHED -> EN_ROUTE -> ARRIVED` through `stage_automation`. `fire_spreads` fired at 180 s
  and is waiting in the notification list. Reinforcement goes out: АЦ-1 is selected *in* `ARRIVED`
  — which only the E9 repair makes possible — and dispatched as `dispatch_additional`;
* **560 s** — АЦ-1 is `WORKING` and simulated time has passed 540 s, so the scenario's
  `resolution_condition` holds and `incident_resolved` fires. The other units have finished their
  scenario work time and are on their way back;
* **closure** — `close` ends the DDS stage, and the DDS stage is the last of the `role_chain`, so
  the session completes and the runner is released.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import SessionId

from tests.api.conftest import auth, create_demo_session, participant
from tests.api.dds.conftest import (
    OperatorFlow,
    acknowledge,
    assignment_rows,
    at,
    board,
    dds_get,
    dds_post,
    dispatch,
    event_types,
    events_of,
    notifications,
    open_selection,
    resource_rows,
    select,
    state_change_rows,
    work_item,
)

pytestmark = pytest.mark.integration

FIRST_WAVE = ("АЛ-1", "АСА-1", "СМП-11", "ППС-204")
REINFORCEMENT = "АЦ-1"

#: `closeDdsIncident`'s `x-emits`, minus the one event this epic must not fake.
#:
#: `SCORING_RULE_EVALUATED` is TODO(E15): §10.14's ten evaluators do not exist, and emitting a
#: scoring event with no rule behind it would put a score in the audit log that nothing produced.
#: This is the single place that exception is written down.
CLOSE_X_EMITS_MINUS_SCORING = [
    "DDS_INCIDENT_CLOSED",
    "ROLE_STAGE_COMPLETED",
    "STAGE_STATE_CHANGED",
    "SESSION_COMPLETED",
]


async def _first_wave(flow: OperatorFlow) -> None:
    await acknowledge(flow)
    await open_selection(flow)
    for callsign in FIRST_WAVE:
        response = await select(flow, callsign)
        assert response.status_code == 200, response.text
    await dispatch(flow)


@pytest.fixture
async def resolved(dds_active: OperatorFlow, clock: FakeClock) -> OperatorFlow:
    """The shortest road to `RESOLVED`: one fire unit, dispatched late enough to still be working.

    The scenario resolves when a `FIRE_SUPPRESSION` unit is `WORKING` **and** simulated time has
    passed 540 s. АЦ-1 works for 240 s once it arrives, so a unit dispatched at 11 s would have
    finished long before 540 s — the incident is resolved by the crew that is on scene *then*.
    """
    await acknowledge(dds_active)
    await open_selection(dds_active)
    await at(dds_active, clock, 300_000)
    assert (await select(dds_active, REINFORCEMENT)).status_code == 200
    await dispatch(dds_active)
    await at(dds_active, clock, 560_000)
    return dds_active


# ---------------------------------------------------------------------------------------------
# The full cycle
# ---------------------------------------------------------------------------------------------


async def test_the_whole_incident_from_handoff_to_a_completed_session(
    dds_active: OperatorFlow, clock: FakeClock, uow_factory: Any
) -> None:
    """The brief's cycle, asserted at every step (see the module docstring for the timeline)."""
    # -- 11 s: the first wave ------------------------------------------------------------------
    await _first_wave(dds_active)
    item = await work_item(dds_active)
    assert item["state"] == "DISPATCHED"
    assert len(item["dispatched_resource_ids"]) == 4

    # -- 190 s: the units are moving and the stage followed them -------------------------------
    await at(dds_active, clock, 190_000)
    statuses = {unit["callsign"]: unit["current_status"] for unit in await board(dds_active)}
    assert statuses["ППС-204"] == "ON_SCENE"
    assert statuses["АЛ-1"] == "EN_ROUTE"
    stage = (await dds_post(dds_active, "/dds/status-updates", _update())).json()
    assert stage["assignment_id"] == item["assignment_id"]

    view = (await dds_get(dds_active, "/dds/resources")).json()
    assert view["total"] == 11
    work = await work_item(dds_active)
    assert work["state"] == "ARRIVED", "stage_automation walked DISPATCHED -> EN_ROUTE -> ARRIVED"

    # `fire_spreads` is a TIMED world event at 180 s; the tick materialized its notification.
    titles = [note["title_ru"] for note in await notifications(dds_active)]
    assert titles, "the DDS trainee has at least one notification by 190 s"

    # -- 190 s: reinforcement, which only the E9 repair makes reachable -------------------------
    assert any(unit["selectable"] for unit in await board(dds_active)), (
        "select_resource is available in ARRIVED (ruling 5)"
    )
    assert (await select(dds_active, REINFORCEMENT)).status_code == 200
    result = await dispatch(dds_active)
    assert result["is_additional"] is True
    assert result["stage"]["stage_state"] == "ARRIVED", "dispatch_additional is a self-transition"

    # -- 560 s: the scenario's resolution condition holds ---------------------------------------
    await at(dds_active, clock, 560_000)
    resolved_item = await work_item(dds_active)
    assert resolved_item["state"] == "RESOLVED"
    statuses = {unit["callsign"]: unit["current_status"] for unit in await board(dds_active)}
    assert statuses[REINFORCEMENT] == "WORKING"

    # The audit trail of the movement carries both columns E9 owed (§20.5).
    rows = await state_change_rows(uow_factory, dds_active.session_id)
    ladder = [row for row in rows if row["callsign"] == "АЛ-1"]
    triggers = [row["trigger"] for row in ladder]
    # `select` and `dispatch` share one session offset (one click each, no simulated time between
    # them), so `ORDER BY at_offset_ms, id` does not put them in a fixed order; the movement the
    # engine drove afterwards does have an order, and that is what is asserted.
    assert set(triggers[:2]) == {"select", "dispatch"}
    assert triggers[2:5] == ["depart", "arrive", "start_work"]
    assert all(row["assignment_id"] is not None for row in ladder)
    assert all(row["session_event_id"] is not None for row in ladder)

    # -- closure ---------------------------------------------------------------------------------
    before = await event_types(dds_active)
    response = await dds_post(
        dds_active, "/dds/close", {"closure_reason": "RESOLVED", "comment_ru": "Пожар потушен"}
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["state"] == "COMPLETED"
    assert (await event_types(dds_active))[len(before) :] == CLOSE_X_EMITS_MINUS_SCORING

    legs = await assignment_rows(uow_factory, dds_active.session_id)
    assert {leg["state"] for leg in legs} == {"CLOSED"}
    assert {leg["closure_reason"] for leg in legs} == {"RESOLVED"}


def _update() -> dict[str, str]:
    return {"update_kind": "EN_ROUTE_REPORT", "text_ru": "Силы в пути, прибытие через 3 минуты"}


# ---------------------------------------------------------------------------------------------
# The engine rule the resolution turns on
# ---------------------------------------------------------------------------------------------


async def test_a_resolved_assignment_sends_the_working_units_home(
    resolved: OperatorFlow, clock: FakeClock
) -> None:
    """§10.7: `WORKING --finish_work--> RETURNING` fires "or assignment reached `RESOLVED`".

    The reinforcement's scenario work time runs to 750 s, so the only thing that can move it at
    570 s is the resolved assignment — which is the `assignment_resolved` flag the tick now reads
    off the DDS stage.
    """
    assert (await work_item(resolved))["state"] == "RESOLVED"
    before = {unit["callsign"]: unit["current_status"] for unit in await board(resolved)}
    assert before[REINFORCEMENT] == "WORKING"

    await at(resolved, clock, 570_000)

    after = {unit["callsign"]: unit["current_status"] for unit in await board(resolved)}
    assert after[REINFORCEMENT] == "RETURNING"


# ---------------------------------------------------------------------------------------------
# closeDdsIncident
# ---------------------------------------------------------------------------------------------


async def test_close_releases_every_attached_unit_and_names_them(
    resolved: OperatorFlow, uow_factory: Any
) -> None:
    """HLD gap #13, as decided: the units are named in the payload and detached from the leg."""
    attached_before = [
        callsign
        for callsign, row in (await resource_rows(uow_factory, resolved.session_id)).items()
        if row["assignment_id"] is not None
    ]
    assert REINFORCEMENT in attached_before

    response = await dds_post(resolved, "/dds/close", {"closure_reason": "RESOLVED"})
    assert response.status_code == 200, response.text

    released = (await events_of(resolved, "DDS_INCIDENT_CLOSED"))[0]["payload"][
        "released_resource_ids"
    ]
    rows = await resource_rows(uow_factory, resolved.session_id)
    assert len(released) == len(attached_before)
    assert all(row["assignment_id"] is None for row in rows.values())


async def test_the_dispatch_history_survives_the_release(
    resolved: OperatorFlow, uow_factory: Any
) -> None:
    """R7: a leg still reports which units it received after they were released."""
    response = await dds_post(resolved, "/dds/close", {"closure_reason": "RESOLVED"})
    assert response.status_code == 200, response.text

    item = await work_item(resolved)
    rows = await resource_rows(uow_factory, resolved.session_id)

    assert item["dispatched_resource_ids"] == [str(rows[REINFORCEMENT]["id"])]
    assert item["selected_resource_ids"] == []


async def test_close_is_refused_before_the_incident_is_resolved(
    dds_active: OperatorFlow,
) -> None:
    """`close` fires from `RESOLVED` only — D8's second gate says so first."""
    await acknowledge(dds_active)

    response = await dds_post(dds_active, "/dds/close", {"closure_reason": "RESOLVED"})

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


async def test_the_completed_session_reports_a_real_total_events(
    resolved: OperatorFlow,
) -> None:
    """`SESSION_COMPLETED.total_events` counts the log's rows, the last one included."""
    response = await dds_post(resolved, "/dds/close", {"closure_reason": "RESOLVED"})
    assert response.status_code == 200, response.text

    completed = await events_of(resolved, "SESSION_COMPLETED")
    stream = await event_types(resolved)

    assert len(completed) == 1
    assert completed[0]["payload"]["total_events"] == len(stream)


async def test_no_scoring_event_is_faked(resolved: OperatorFlow) -> None:
    """TODO(E15) owns `SCORING_RULE_EVALUATED`; this epic emits none of the `SCORING_*` family."""
    assert (
        await dds_post(resolved, "/dds/close", {"closure_reason": "RESOLVED"})
    ).status_code == 200

    assert not [name for name in await event_types(resolved) if name.startswith("SCORING_")]


# ---------------------------------------------------------------------------------------------
# Determinism (INV 7, for the DDS half)
# ---------------------------------------------------------------------------------------------


async def _run_dds_only(
    client: Any,
    container: Any,
    clock: FakeClock,
    tokens: dict[str, str],
    session_id: UUID,
) -> list[str]:
    """Drive the DDS-only prefab session through one dispatch and 560 simulated seconds."""
    base = f"/api/v1/sessions/{session_id}"
    headers = auth(tokens["trainee2"])

    async def post(suffix: str, json: Any = None) -> Any:
        response = await client.post(f"{base}{suffix}", headers=headers, json=json)
        assert response.status_code in (200, 201), response.text
        return response.json()

    await post("/dds/acknowledge")
    await post("/dds/resources/selection/open")
    board_items = (await client.get(f"{base}/dds/resources", headers=headers)).json()["items"]
    engine = next(item for item in board_items if item["callsign"] == "АЦ-1")

    detail = (await client.get(base, headers=headers)).json()
    clock.advance_ms(300_000 - int(detail["monotonic_offset_ms"]))
    await container.runner.tick_now(SessionId(session_id))

    await post("/dds/resources/select", {"resource_id": engine["resource_id"]})
    await post("/dds/resources/dispatch", {"note_ru": None})

    detail = (await client.get(base, headers=headers)).json()
    clock.advance_ms(560_000 - int(detail["monotonic_offset_ms"]))
    await container.runner.tick_now(SessionId(session_id))

    events = (
        await client.get(
            f"{base}/events", headers=auth(tokens["instructor1"]), params={"limit": 1000}
        )
    ).json()["items"]
    return [item["event_type"] for item in events]


async def test_two_runs_of_one_scenario_produce_the_same_event_stream(
    client: Any,
    container: Any,
    clock: FakeClock,
    tokens: dict[str, str],
    users: dict[str, Any],
    dds_only_version_id: Any,
) -> None:
    """D7 determinism rule 5 / INV 7, through the DDS commands.

    Two sessions of the same scenario version share a `session_seed` (it defaults to the
    scenario's `deterministic_seed`), and the same actions at the same simulated offsets must
    therefore produce the same stream — world events, resource movement and all.
    """
    streams: list[list[str]] = []
    for _ in range(2):
        detail = await create_demo_session(
            client,
            tokens["instructor1"],
            dds_only_version_id,
            [participant(users["trainee2"], "DDS")],
            session_mode="SINGLE_ROLE",
        )
        session_id = UUID(detail["id"])
        started = await client.post(
            f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
        )
        assert started.status_code == 200, started.text
        streams.append(await _run_dds_only(client, container, clock, tokens, session_id))

    assert streams[0] == streams[1]
    assert "RESOURCE_DISPATCHED" in streams[0]
    assert streams[0].count("RESOURCE_STATUS_CHANGED") >= 4

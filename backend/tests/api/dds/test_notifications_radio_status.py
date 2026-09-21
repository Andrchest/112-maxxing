"""Notifications, radio traffic and status updates over real HTTP (SPEC §11, §12; §20.5, §40.4).

The three surfaces the world event engine and the DDS trainee talk to each other through:

* **notifications** are a table, materialized from `NOTIFICATION_CREATED` inside the very tick
  that emits it, and read back filtered by the caller's role. The demo scenario supplies real
  ones: `fire_spreads` at 180 s and `second_report_balcony` a minute after the handoff;
* **radio messages** have no table at all — they are projected from the log — so the tests here
  seed a `RADIO_MESSAGE_CREATED` through the event store, exactly as the world engine does, and
  read it back through the endpoint;
* **status updates** are neither: one event, no transition, available from `ACKNOWLEDGED` to
  `RESOLVED`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from app.application.testing.fakes import FakeClock
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType, RoleType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

from tests.api.dds.conftest import (
    OperatorFlow,
    acknowledge,
    at,
    dds_get,
    dds_post,
    event_types,
    events_of,
    notifications,
)

pytestmark = pytest.mark.integration

UPDATE = {"update_kind": "ON_SCENE_REPORT", "text_ru": "Прибыли, работаем по второму этажу"}


async def _append_radio(flow: OperatorFlow, to_role: RoleType, text_ru: str) -> None:
    """Append one `RADIO_MESSAGE_CREATED` the way the world engine does (D9, §20.8)."""
    async with flow.container.unit_of_work() as uow:
        await uow.events.append(
            SessionId(flow.session_id),
            [
                DomainEvent(
                    event_type=EventType.RADIO_MESSAGE_CREATED,
                    actor=ActorRef(actor_type=ActorType.SIMULATION),
                    monotonic_offset_ms=90_000,
                    payload={
                        "radio_message_id": str(uuid4()),
                        "from_callsign": "АЦ-2",
                        "to_role": to_role.value,
                        "text_ru": text_ru,
                        "resource_id": None,
                        "source_world_event_id": "ac2_breakdown",
                        "at_offset_ms": 90_000,
                    },
                )
            ],
        )
        await uow.commit()


# ---------------------------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------------------------


async def test_the_scenarios_notifications_reach_the_dds_trainee(
    dds_active: OperatorFlow, clock: FakeClock
) -> None:
    """`fire_spreads` is a TIMED world event at 180 s addressed to `DDS` (SPEC §12)."""
    await at(dds_active, clock, 185_000)

    items = await notifications(dds_active)

    assert items, "the DDS trainee has notifications by 185 s"
    assert {item["audience_role"] for item in items} == {"DDS"}
    assert all(item["acknowledged_at_offset_ms"] is None for item in items)


async def test_the_notification_row_is_written_by_the_tick_that_emitted_the_event(
    dds_active: OperatorFlow, clock: FakeClock
) -> None:
    """D5: the table and the log commit together — one row per `NOTIFICATION_CREATED`."""
    await at(dds_active, clock, 185_000)

    created = await events_of(dds_active, "NOTIFICATION_CREATED")
    items = await notifications(dds_active)

    assert len(items) == len(created)
    assert {item["notification_id"] for item in items} == {
        event["payload"]["notification_id"] for event in created
    }


async def test_ticking_twice_does_not_duplicate_a_notification(
    dds_active: OperatorFlow, clock: FakeClock
) -> None:
    """The ids are derived from the world event, and the insert is "do nothing on conflict"."""
    await at(dds_active, clock, 185_000)
    before = len(await notifications(dds_active))

    await dds_active.container.runner.tick_now(SessionId(dds_active.session_id))

    assert len(await notifications(dds_active)) == before


async def test_the_stage_view_counts_the_unacknowledged_ones(
    dds_active: OperatorFlow, clock: FakeClock
) -> None:
    """`DdsStageView.unacknowledged_notification_count`, and it drops when one is ticked off."""
    await at(dds_active, clock, 185_000)
    view = await acknowledge(dds_active)
    outstanding = view["unacknowledged_notification_count"]
    assert outstanding >= 1

    first = (await notifications(dds_active))[0]
    response = await dds_post(
        dds_active, f"/dds/notifications/{first['notification_id']}/acknowledge"
    )
    assert response.status_code == 200, response.text

    later = (await dds_post(dds_active, "/dds/resources/selection/open")).json()
    assert later["unacknowledged_notification_count"] == outstanding - 1


async def test_acknowledging_a_notification_emits_the_event_with_its_audience(
    dds_active: OperatorFlow, clock: FakeClock
) -> None:
    """The additive `audience_role` key (ruling 4) is what §40.4 row 38's filter needs."""
    await at(dds_active, clock, 185_000)
    first = (await notifications(dds_active))[0]
    before = await event_types(dds_active)

    response = await dds_post(
        dds_active, f"/dds/notifications/{first['notification_id']}/acknowledge"
    )

    assert response.status_code == 200, response.text
    assert response.json()["acknowledged_at_offset_ms"] is not None
    assert (await event_types(dds_active))[len(before) :] == ["NOTIFICATION_ACKNOWLEDGED"]
    payload = (await events_of(dds_active, "NOTIFICATION_ACKNOWLEDGED"))[0]["payload"]
    assert payload["audience_role"] == "DDS"
    assert payload["latency_ms"] >= 0


async def test_a_second_acknowledgement_of_one_notification_is_409(
    dds_active: OperatorFlow, clock: FakeClock
) -> None:
    """The conditional `UPDATE` reports whether it hit a row, so exactly one event is emitted."""
    await at(dds_active, clock, 185_000)
    first = (await notifications(dds_active))[0]
    path = f"/dds/notifications/{first['notification_id']}/acknowledge"
    assert (await dds_post(dds_active, path)).status_code == 200

    response = await dds_post(dds_active, path)

    assert response.status_code == 409, response.text
    assert len(await events_of(dds_active, "NOTIFICATION_ACKNOWLEDGED")) == 1


async def test_the_112_trainee_sees_none_of_the_dds_notifications(
    dds_active: OperatorFlow, clock: FakeClock
) -> None:
    """The filter is in SQL: a role never even loads another role's rows (D3)."""
    await at(dds_active, clock, 185_000)

    response = await dds_active.get("/dds/notifications", token=dds_active.operator_token)

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


async def test_the_112_trainee_may_not_acknowledge_a_dds_notification(
    dds_active: OperatorFlow, clock: FakeClock
) -> None:
    """`ACKNOWLEDGE_NOTIFICATION` is held by both roles; the *audience* is what restricts it."""
    await at(dds_active, clock, 185_000)
    first = (await notifications(dds_active))[0]

    response = await dds_active.post(
        f"/dds/notifications/{first['notification_id']}/acknowledge",
        token=dds_active.operator_token,
    )

    assert response.status_code == 403, response.text


async def test_unacknowledged_only_filters_the_list(
    dds_active: OperatorFlow, clock: FakeClock
) -> None:
    await at(dds_active, clock, 185_000)
    items = await notifications(dds_active)
    assert (
        await dds_post(dds_active, f"/dds/notifications/{items[0]['notification_id']}/acknowledge")
    ).status_code == 200

    outstanding = await notifications(dds_active, unacknowledged_only=True)

    assert len(outstanding) == len(items) - 1
    assert all(item["acknowledged_at_offset_ms"] is None for item in outstanding)


async def test_an_unknown_notification_is_a_404(dds_active: OperatorFlow) -> None:
    response = await dds_post(dds_active, f"/dds/notifications/{UUID(int=1)}/acknowledge")

    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------------------------
# Radio messages
# ---------------------------------------------------------------------------------------------


async def test_radio_traffic_addressed_to_dds_is_projected_from_the_log(
    dds_active: OperatorFlow,
) -> None:
    """No table: `listRadioMessages` folds `RADIO_MESSAGE_CREATED` rows (§20.1)."""
    await _append_radio(dds_active, RoleType.DDS, "АЦ-2 — неисправность, возвращаемся")

    response = await dds_get(dds_active, "/dds/radio-messages")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["text_ru"] for item in body["items"]] == ["АЦ-2 — неисправность, возвращаемся"]
    assert body["items"][0]["from_callsign"] == "АЦ-2"
    assert body["items"][0]["to_role"] == "DDS"
    assert body["last_seq_no"] == body["items"][0]["seq_no"]


async def test_radio_traffic_for_another_role_is_not_shown(dds_active: OperatorFlow) -> None:
    """`to_role == the caller's role`, the contract's own filter."""
    await _append_radio(dds_active, RoleType.OPERATOR_112, "Для 112")

    response = await dds_get(dds_active, "/dds/radio-messages")

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


async def test_after_seq_no_pages_the_radio_log(dds_active: OperatorFlow) -> None:
    """The cursor a console polls with is the one the previous page returned."""
    await _append_radio(dds_active, RoleType.DDS, "Первое")
    await _append_radio(dds_active, RoleType.DDS, "Второе")

    first = (await dds_get(dds_active, "/dds/radio-messages", {"limit": 1})).json()
    second = (
        await dds_get(dds_active, "/dds/radio-messages", {"after_seq_no": first["last_seq_no"]})
    ).json()

    assert [item["text_ru"] for item in first["items"]] == ["Первое"]
    assert [item["text_ru"] for item in second["items"]] == ["Второе"]


async def test_the_112_trainee_reads_their_own_radio_log(dds_active: OperatorFlow) -> None:
    """One endpoint, two roles — `VisibilitySource.RADIO_MESSAGES` is in both policies."""
    await _append_radio(dds_active, RoleType.OPERATOR_112, "Для 112")

    response = await dds_active.get("/dds/radio-messages", token=dds_active.operator_token)

    assert response.status_code == 200, response.text
    assert [item["text_ru"] for item in response.json()["items"]] == ["Для 112"]


# ---------------------------------------------------------------------------------------------
# Status updates
# ---------------------------------------------------------------------------------------------


async def test_a_status_update_is_one_event_and_no_transition(
    dds_active: OperatorFlow,
) -> None:
    """`x-emits: [DDS_STATUS_UPDATE_SENT]`, and the stage stays exactly where it was."""
    view = await acknowledge(dds_active)
    before = await event_types(dds_active)

    response = await dds_post(dds_active, "/dds/status-updates", UPDATE)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["update_kind"] == "ON_SCENE_REPORT"
    assert body["text_ru"] == UPDATE["text_ru"]
    assert body["assignment_id"] == view["work_item"]["assignment_id"]
    assert (await event_types(dds_active))[len(before) :] == ["DDS_STATUS_UPDATE_SENT"]


async def test_a_status_update_is_refused_before_the_work_item_is_acknowledged(
    dds_active: OperatorFlow,
) -> None:
    """§10.9: `send_status_update` is available from `ACKNOWLEDGED` on, not in `RECEIVED`."""
    response = await dds_post(dds_active, "/dds/status-updates", UPDATE)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


async def test_an_empty_status_update_is_rejected_by_the_contract(
    dds_active: OperatorFlow,
) -> None:
    """`text_ru` is `minLength: 1` in `openapi.yaml`."""
    await acknowledge(dds_active)

    response = await dds_post(
        dds_active, "/dds/status-updates", {"update_kind": "SITUATION_UPDATE", "text_ru": ""}
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_the_status_update_names_the_acting_trainee(dds_active: OperatorFlow) -> None:
    """SPEC §8: every trainee action is attributable."""
    await acknowledge(dds_active)
    assert (await dds_post(dds_active, "/dds/status-updates", UPDATE)).status_code == 201

    payload: dict[str, Any] = (await events_of(dds_active, "DDS_STATUS_UPDATE_SENT"))[0]["payload"]

    assert payload["actor_user_id"] == str(UUID(str(dds_active.dds_user_id)))

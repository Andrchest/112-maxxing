"""H2 (E20-H): `acknowledgeNotification` and `listNotifications` must agree on the caller's role.

E20-C's real §46 walk created a `FULL_CYCLE_SINGLE_TRAINEE` session with the trainee's
`assigned_role_type` set to their *first* role (`OPERATOR_112`, as the walk's own `POST /sessions`
body did — see `docs/DOD_WALK.md` item 12b). Once that trainee reached the `DDS` stage,
`listNotifications` could show them a `DDS`-audience notification (it walks every `RoleStage` the
participant is bound to) but `acknowledgeNotification` rejected it with `403 FORBIDDEN_FOR_ROLE`,
because it preferred the stale `assigned_role_type` over the stage they are actually playing now.

Bite proof: reverting `acknowledge_notification.py`'s role check to compare against a single
`_acting_role(...)` that prefers `SessionParticipant.assigned_role_type` (the pre-fix shape) turns
`test_a_full_cycle_trainee_lists_and_acknowledges_the_dds_notification` red with exactly the 403
this module reproduces from the walk.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from app.application.testing.fakes import FakeClock
from app.domain.events.types import EventType

from tests.api.conftest import auth, create_demo_session, participant
from tests.api.dds.conftest import at, dds_get, dds_post
from tests.api.handoff.conftest import OperatorFlow, fill_card, prepare_handoff

pytestmark = pytest.mark.integration


async def _full_cycle_flow_with_explicit_first_role(
    client: Any,
    container: Any,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: Any,
) -> OperatorFlow:
    """A `FULL_CYCLE_SINGLE_TRAINEE` session whose lone participant is *explicitly* pinned to
    `OPERATOR_112` at creation — legal under `ALL_STAGES_ONE_PARTICIPANT` (§10.10 only forbids it
    the other way around: `SINGLE_STAGE_ONE_PARTICIPANT` requires a role), and exactly what the
    real walk's session-creation call did.
    """
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee1"], "OPERATOR_112")],
        session_mode="FULL_CYCLE_SINGLE_TRAINEE",
    )
    session_id = UUID(detail["id"])
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "ACTIVE"
    return OperatorFlow(
        client=client,
        container=container,
        session_id=session_id,
        operator_token=tokens["trainee1"],
        dds_token=tokens["trainee1"],
        instructor_token=tokens["instructor1"],
        operator_user_id=users["trainee1"],
        dds_user_id=users["trainee1"],
    )


async def _reach_dds_stage(flow: OperatorFlow, clock: FakeClock) -> None:
    assert await flow.advance_call_flow() is True
    assert (await flow.post("/operator/call/answer")).status_code == 200
    await flow.append_asr(EventType.ASR_FINAL, "Горит квартира на улице Ленина, дом 5")
    assert await flow.advance_call_flow() is True

    await fill_card(flow)
    await prepare_handoff(flow, "FIRE_RESCUE", "AMBULANCE")
    assert (await flow.post("/operator/handoff", json={})).status_code == 201
    assert (
        await flow.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200

    completed = await flow.post("/operator/stage/complete")
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "ROLE_TRANSITION"

    clock.advance_ms(21_000)  # FULL_CYCLE_SINGLE_TRAINEE's pause is 20 s (§10.10)
    continued = await flow.post("/stage/continue")
    assert continued.status_code == 200, continued.text
    assert continued.json()["state"] == "ACTIVE"


async def test_a_full_cycle_trainee_lists_and_acknowledges_the_dds_notification(
    client: Any,
    container: Any,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: Any,
    clock: FakeClock,
) -> None:
    flow = await _full_cycle_flow_with_explicit_first_role(
        client, container, tokens, users, demo_version_id
    )
    await _reach_dds_stage(flow, clock)

    # `fire_spreads` (DDS-audience, TIMED at 180s) is now live for the DDS stage.
    await at(flow, clock, 185_000)

    listed = await dds_get(flow, "/dds/notifications")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items, "the DDS trainee has notifications by 185 s"
    assert {item["audience_role"] for item in items} == {"DDS"}

    first = items[0]
    ack = await dds_post(flow, f"/dds/notifications/{first['notification_id']}/acknowledge")
    assert ack.status_code == 200, ack.text
    assert ack.json()["acknowledged_at_offset_ms"] is not None

    # SINGLE_ROLE/MULTI_TRAINEE stays exactly as forbidding as before: a real regression is
    # `tests.api.dds.test_notifications_radio_status.
    # test_the_112_trainee_may_not_acknowledge_a_dds_notification`, which this change does not
    # touch (it never runs `audience_roles_for`'s multi-stage branch, since the OPERATOR_112
    # trainee there is bound to no `DDS` stage at all).

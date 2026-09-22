"""`SINGLE_ROLE [DDS]`, end to end over real HTTP (E17-D, R6).

D6: a `role_chain` of `[DDS]` under `SINGLE_ROLE` needs the scenario's
`expected_response.prefab_handoff`, absent which the mode is rejected at session creation with
`409 PREFAB_HANDOFF_REQUIRED` (`openapi.yaml`'s `createSession` description). `dds_only_session`
(`tests.api.handoff.conftest`) is exactly that scenario, started; this module drives the one
trainee through acknowledge -> dispatch -> resolve -> close and proves the session completes with
no 112 stage anywhere in its timeline.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import UserId

from tests.api.dds.conftest import (
    acknowledge,
    at,
    dispatch,
    event_types,
    open_selection,
    select,
    work_item,
)
from tests.api.handoff.conftest import OperatorFlow

pytestmark = pytest.mark.integration


@pytest.fixture
def prefab_flow(
    client: Any,
    container: Any,
    tokens: dict[str, str],
    users: dict[str, UserId],
    dds_only_session: UUID,
) -> OperatorFlow:
    """`OperatorFlow` over the started `SINGLE_ROLE [DDS]` session, `trainee2` playing it alone."""
    return OperatorFlow(
        client=client,
        container=container,
        session_id=dds_only_session,
        operator_token=tokens["trainee2"],
        dds_token=tokens["trainee2"],
        instructor_token=tokens["instructor1"],
        operator_user_id=users["trainee2"],
        dds_user_id=users["trainee2"],
    )


async def test_the_dds_only_session_completes_with_no_operator_stage_at_all(
    prefab_flow: OperatorFlow, clock: FakeClock
) -> None:
    flow = prefab_flow
    started = await flow.event_types()
    assert "HANDOFF_RECEIVED" in started, "the prefab card was materialised inside startSession"
    assert not {"CALL_RINGING", "CALL_ANSWERED"} & set(started), (
        "no 112 call ever happens in this mode: the card is prefab, not typed against a caller"
    )

    await acknowledge(flow)
    await open_selection(flow)
    # Dispatched late enough (mirrors `tests.api.dds.test_full_cycle`'s `resolved` fixture): АЦ-1
    # works for 240 s once it arrives, so a unit dispatched at 0 s would have finished long before
    # 540 s and `resolution_condition` (a `FIRE_SUPPRESSION` unit `WORKING` past 540 s) would never
    # hold.
    await at(flow, clock, 300_000)
    assert (await select(flow, "АЦ-1")).status_code == 200
    await dispatch(flow)

    await at(flow, clock, 560_000)
    item = await work_item(flow)
    assert item["state"] == "RESOLVED"

    before = await event_types(flow)
    closed = await flow.post("/dds/close", json={"closure_reason": "RESOLVED"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "COMPLETED"

    after = (await event_types(flow))[len(before) :]
    assert "ROLE_TRANSITION_STARTED" not in after
    assert "ROLE_TRANSITION_COMPLETED" not in after
    assert not {"CALL_RINGING", "CALL_ANSWERED"} & set(await event_types(flow)), (
        "no 112 call ever ran in this mode's timeline"
    )


async def test_an_operator_command_is_forbidden_in_this_mode(prefab_flow: OperatorFlow) -> None:
    """No `OPERATOR_112` stage exists in this `role_chain`."""
    response = await prefab_flow.post("/operator/call/answer")
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"

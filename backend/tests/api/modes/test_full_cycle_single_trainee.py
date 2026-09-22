"""`FULL_CYCLE_SINGLE_TRAINEE`, end to end over real HTTP (E17-D, R6).

One trainee (`assigned_role_type: null`, §10.10 `ALL_STAGES_ONE_PARTICIPANT`) plays both the
`OPERATOR_112` and the `DDS` stage of one session, across the `ROLE_TRANSITION` pause
(`transition_pause_seconds: 20`). SPEC §13's whole point is asserted directly: **the same
`Incident` survives the hand-over**, and — `40-realtime-protocol.md` §2 — the same socket's
*effective role* re-derives to the active stage's `RoleType` without a reconnect, which this
module proves at the snapshot level (`my_role_type` flips from `OPERATOR_112` to `DDS` with no
new participant row and no new token).

CONCURRENCY (E17-B is changing simulated-time behaviour across the pause): every simulated-time
target here is computed *relative to the server's own reported offset* right before it is used
(`session_offset_ms(flow)`, never a literal added to "the offset before the pause"), and the one
assertion made about `seq_no`/offsets across the transition is that they never decrease — never a
concrete value.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from app.application.testing.fakes import FakeClock
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.dds.conftest import (
    acknowledge,
    at,
    dispatch,
    event_types,
    open_selection,
    select,
    session_offset_ms,
)
from tests.api.handoff.conftest import OperatorFlow, fill_card, prepare_handoff

pytestmark = pytest.mark.integration


async def _incident_ids(uow_factory: Any, session_id: Any) -> list[str]:
    async with uow_factory() as uow:
        assert isinstance(uow, SqlAlchemyUnitOfWork)
        result = await uow.session.execute(
            sa.text("SELECT id FROM incidents WHERE session_id = :session_id"),
            {"session_id": session_id},
        )
        ids = [str(row[0]) for row in result.all()]
        await uow.commit()
    return ids


async def test_one_trainee_carries_one_incident_across_both_stages(
    full_cycle_flow: OperatorFlow, clock: FakeClock, uow_factory: Any
) -> None:
    flow = full_cycle_flow
    incidents_before = await _incident_ids(uow_factory, flow.session_id)
    assert len(incidents_before) == 1

    # -- the OPERATOR_112 half, same trainee throughout -----------------------------------------
    snapshot = (await flow.snapshot()).json()
    assert snapshot["my_role_type"] == "OPERATOR_112", (
        "the stage-bound role, derived server-side: no `assigned_role_type` row names it"
    )

    assert await flow.advance_call_flow() is True
    assert (await flow.post("/operator/call/answer")).status_code == 200
    await flow.append_asr(EventType.ASR_FINAL, "Горит квартира на улице Ленина, дом 5")
    assert await flow.advance_call_flow() is True

    await fill_card(flow)
    await prepare_handoff(flow, "FIRE_RESCUE", "AMBULANCE")
    handoff = await flow.post("/operator/handoff", json={})
    assert handoff.status_code == 201, handoff.text
    assert (
        await flow.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200

    completed = await flow.post("/operator/stage/complete")
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "ROLE_TRANSITION"

    # -- the pause: E17-B owns what the sim clock does here, so only monotonicity is checked ----
    clock.advance_ms(21_000)  # FULL_CYCLE_SINGLE_TRAINEE's pause is 20 s (§10.10)

    continued = await flow.post("/stage/continue")  # the same trainee holds the next stage too
    assert continued.status_code == 200, continued.text
    assert continued.json()["state"] == "ACTIVE"

    # -- the DDS half, same trainee, the same socket's role re-derived server-side --------------
    snapshot = (await flow.snapshot()).json()
    assert snapshot["my_role_type"] == "DDS"
    assert snapshot["active_role_type"] == "DDS"
    assert snapshot["card"] is None, "D3: never the live card once the DDS stage is active"
    assert snapshot["work_item"] is not None

    await acknowledge(flow)
    await open_selection(flow)
    # Dispatched late enough that the unit is still `WORKING` past 540 simulated seconds (mirrors
    # `tests.api.dds.test_full_cycle`'s `resolved` fixture) — the *delta* is fixed by SPEC/the
    # scenario's own ETA data, the *base* is read from the server so the transition's own
    # simulated-time cost (E17-B) never has to be predicted here.
    base = await session_offset_ms(flow)
    await at(flow, clock, base + 300_000)
    assert (await select(flow, "АЦ-1")).status_code == 200
    await dispatch(flow)
    base = await session_offset_ms(flow)
    await at(flow, clock, base + 260_000)

    before = await event_types(flow)
    closed = await flow.post("/dds/close", json={"closure_reason": "RESOLVED"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "COMPLETED"
    after = (await event_types(flow))[len(before) :]
    assert after[0] == "DDS_INCIDENT_CLOSED"

    # SPEC §13 / §42 test 5: still exactly one Incident, across the whole cycle.
    assert await _incident_ids(uow_factory, flow.session_id) == incidents_before

    # The log's `seq_no` is strictly increasing end to end, transition included — no gap, no
    # duplicate, whatever E17-B lands on for the pause's own effect on simulated time.
    all_events = (
        await flow.client.get(
            f"/api/v1/sessions/{flow.session_id}/events",
            headers={"Authorization": f"Bearer {flow.instructor_token}"},
            params={"limit": 1000},
        )
    ).json()["items"]
    seq_nos = [item["seq_no"] for item in all_events]
    offsets = [item["monotonic_offset_ms"] for item in all_events]
    assert seq_nos == sorted(seq_nos)
    assert len(seq_nos) == len(set(seq_nos))

    # `monotonic_offset_ms` is *not* asserted monotonic over the whole log here, deliberately:
    # this module's own `append_asr` call stamps a literal test offset regardless of the real
    # clock (a test-helper artefact, not production's), and a resource's own scripted
    # `availability.available_from_ms` (`scenarios/examples/apartment-fire/v1.yaml`, "СМП-12" at
    # 120 s) is appended at *its* scheduled offset once a large `at()` jump crosses it, which can
    # legitimately land earlier than the offset the jump landed the tick at — a pre-existing
    # engine characteristic this module does not own and must not assert away. R1's actual claim
    # is narrower and is exactly what the two lines below check: the transition boundary itself.
    transition_index = next(
        index
        for index, item in enumerate(all_events)
        if item["event_type"] == "ROLE_TRANSITION_STARTED"
    )
    first_dds_index = next(
        index
        for index, item in enumerate(all_events)
        if index > transition_index and item["event_type"] == "ROLE_STAGE_STARTED"
    )
    assert offsets[first_dds_index] >= offsets[transition_index], (
        "R1: the first DDS-stage event's offset is at least the transition-start offset"
    )

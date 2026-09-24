"""Completing the **session** from the 112 stage — `SESSION_COMPLETED.total_events` (E9).

`completeOperatorStage` fires `begin_role_transition` when the `role_chain` has a next entry and
`complete` when it does not. The second branch needs a chain of `[OPERATOR_112]` alone, which
rule R18 permits (it only requires the chain's roles to be implemented), so this module builds
one straight through the repository and plays it out over HTTP.

Two things are pinned:

* `total_events` is the **real** row count of the session's log, including the
  `SESSION_COMPLETED` row itself — not the `0` the aggregate used to emit;
* one `SCORING_RULE_EVALUATED` per demo-scenario rule follows `SESSION_COMPLETED` (epic E15-B):
  `operator_only_version_id` is the demo document's own ten `scoring_rules`, only `role_chain` is
  overridden, and every rule produces exactly one `ScoreResult` — applicable or not (R7) — so the
  count is the same ten regardless of the shorter chain.

The same chain also exercises the HLD gap of `create_handoff._next_dds_stage_id`: with no DDS
stage there is nobody to receive the handoff, so `assignment_ids` is empty and no
`HANDOFF_RECEIVED` is appended — while the snapshot itself is still frozen and recorded.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from app.api.container import Container
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.conftest import auth, create_demo_session, participant
from tests.api.handoff.conftest import (
    CARD_ENTRIES,
    OperatorFlow,
    raw_role_chain_version,
    read_assignments,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def operator_only_version_id(unit_of_work: Any) -> ScenarioVersionId:
    """The demo document with `role_chain: [OPERATOR_112]` — a chain that ends at the 112 desk."""
    return await raw_role_chain_version(unit_of_work, "operator-only", ["OPERATOR_112"])


@pytest.fixture
async def operator_only(
    client: httpx.AsyncClient,
    container: Container,
    tokens: dict[str, str],
    users: dict[str, UserId],
    operator_only_version_id: ScenarioVersionId,
) -> OperatorFlow:
    """A started `[OPERATOR_112]` session, driven to `INTERVIEW` with the card filled."""
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        operator_only_version_id,
        [participant(users["trainee1"], "OPERATOR_112")],
    )
    session_id = UUID(detail["id"])
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text

    flow = OperatorFlow(
        client=client,
        container=container,
        session_id=session_id,
        operator_token=tokens["trainee1"],
        dds_token=tokens["trainee2"],
        instructor_token=tokens["instructor1"],
        operator_user_id=users["trainee1"],
        dds_user_id=users["trainee2"],
    )
    assert await flow.advance_call_flow() is True  # ring
    assert (await flow.post("/operator/call/answer")).status_code == 200
    await flow.append_asr(EventType.ASR_FINAL, "Горит квартира")
    assert await flow.advance_call_flow() is True  # begin_interview

    for field_path, value in CARD_ENTRIES:
        assert (await flow.set_field(field_path, value)).status_code == 200
    assert (await flow.select("FIRE_RESCUE")).status_code == 200
    assert (await flow.post("/operator/handoff/prepare")).status_code == 200
    return flow


async def test_a_chain_without_dds_freezes_the_snapshot_and_creates_no_leg(
    operator_only: OperatorFlow, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """HLD gap #14: the trainee's work is recorded; nobody receives it."""
    before = await operator_only.event_types()

    response = await operator_only.post("/operator/handoff", json={})

    assert response.status_code == 201, response.text
    assert response.json()["assignment_ids"] == []
    assert response.json()["snapshot"]["card_values"]["address.house"] == "72"
    assert (await operator_only.event_types())[len(before) :] == [
        "HANDOFF_CREATED",
        "STAGE_STATE_CHANGED",
        # I3 E4a (HLD 70 §70.4.6): handed off, no leg — WORKED, never COMPLETED by an empty list.
        "DDS_CARD_STATUS_CHANGED",
    ]
    assert await read_assignments(uow_factory, operator_only.session_id) == []


async def test_completing_the_last_stage_completes_the_session(
    operator_only: OperatorFlow, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """`ACTIVE --complete--> COMPLETED`, with `total_events` counting the log it ends."""
    assert (await operator_only.post("/operator/handoff", json={})).status_code == 201
    assert (
        await operator_only.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200

    response = await operator_only.post("/operator/stage/complete")

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "COMPLETED"

    types = await operator_only.event_types()
    completed_index = types.index("SESSION_COMPLETED")
    assert types[completed_index - 2 : completed_index + 1] == [
        "STAGE_STATE_CHANGED",
        "ROLE_STAGE_COMPLETED",
        "SESSION_COMPLETED",
    ]
    assert "ROLE_TRANSITION_STARTED" not in types
    # Epic E15-B: only SCORING_* may follow SESSION_COMPLETED (R2).
    assert all(name.startswith("SCORING_") for name in types[completed_index + 1 :])

    async with uow_factory() as uow:
        events = await uow.events.read(SessionId(operator_only.session_id))
        await uow.commit()
    completed = next(event for event in events if event.event_type.value == "SESSION_COMPLETED")
    assert completed.payload["total_events"] == completed.seq_no, (
        "total_events counts every row of the session's log up to and including itself, not the "
        "SCORING_RULE_EVALUATED rows a later, separate transaction appends after it (R2)"
    )
    assert completed.payload["final_session_state"] == "COMPLETED"


async def test_completing_writes_one_scoring_event_per_demo_rule(
    operator_only: OperatorFlow,
) -> None:
    """Epic E15-B: `SCORING_RULE_EVALUATED` follows `SESSION_COMPLETED`, one per scenario rule."""
    before = await operator_only.event_types()
    assert (await operator_only.post("/operator/handoff", json={})).status_code == 201
    assert (
        await operator_only.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200
    assert (await operator_only.post("/operator/stage/complete")).status_code == 200

    after = await operator_only.event_types()
    appended = after[len(before) :]
    completed_index = appended.index("SESSION_COMPLETED")
    scoring = appended[completed_index + 1 :]

    assert scoring == ["SCORING_RULE_EVALUATED"] * 10
    assert all(name != "SCORING_RULE_EVALUATED" for name in appended[:completed_index])


async def test_a_completed_session_accepts_no_further_command(
    operator_only: OperatorFlow, clock: FakeClock
) -> None:
    """`409 SESSION_NOT_ACTIVE`: the gate's second step, on a session that is over."""
    assert (await operator_only.post("/operator/handoff", json={})).status_code == 201
    assert (
        await operator_only.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200
    assert (await operator_only.post("/operator/stage/complete")).status_code == 200

    again = await operator_only.post("/operator/stage/complete")
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "SESSION_NOT_ACTIVE"

    clock.advance_ms(60_000)
    continued = await operator_only.post("/stage/continue", token=operator_only.instructor_token)
    assert continued.status_code == 409, continued.text
    assert continued.json()["code"] == "INVALID_TRANSITION"


async def test_the_completed_session_row_and_its_stage_are_terminal(
    operator_only: OperatorFlow, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """The materialized state matches the event: `COMPLETED`, with `completed_at` set."""
    assert (await operator_only.post("/operator/handoff", json={})).status_code == 201
    assert (
        await operator_only.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200
    assert (await operator_only.post("/operator/stage/complete")).status_code == 200

    async with uow_factory() as uow:
        row = (
            await uow.session.execute(
                sa.text(
                    "SELECT state, completed_at FROM simulation_sessions WHERE id = :session_id"
                ),
                {"session_id": operator_only.session_id},
            )
        ).one()
        stages = (
            await uow.session.execute(
                sa.text("SELECT state FROM role_stages WHERE session_id = :session_id"),
                {"session_id": operator_only.session_id},
            )
        ).all()
        await uow.commit()

    assert row.state == "COMPLETED"
    assert row.completed_at is not None
    assert [stage[0] for stage in stages] == ["STAGE_COMPLETED"]

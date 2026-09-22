"""`getInstructorSessionOverview` end to end (E17-A, R4): `INSTRUCTOR`/`ADMIN` only, every session
state after creation, `WorldTruth`/`CallerBelief`/gate internals present, the N DDS legs verbatim,
and a read that writes nothing.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from app.domain.common.ids import ScenarioVersionId, UserId

from tests.api.instructor.conftest import (
    OperatorFlow,
    auth,
    created_session_id,
    overview,
)

pytestmark = pytest.mark.integration


async def _counts(uow_factory: Any, session_id: Any) -> tuple[int, int]:
    """`(session_events rows, score_results rows)` — a read must move neither."""
    async with uow_factory() as uow:
        events = await uow.session.execute(
            sa.text("SELECT count(*) FROM session_events WHERE session_id = :s"),
            {"s": session_id},
        )
        scores = await uow.session.execute(
            sa.text("SELECT count(*) FROM score_results WHERE session_id = :s"),
            {"s": session_id},
        )
        result = (int(events.scalar_one()), int(scores.scalar_one()))
        await uow.commit()
    return result


# ---------------------------------------------------------------------------------------------
# INSTRUCTOR 200 in every session state after creation
# ---------------------------------------------------------------------------------------------


async def test_a_freshly_created_session_is_visible(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """`READY` — before `startSession`, the overview already reads (D3's live read has no
    `409 REPORT_NOT_READY`-style gate; that gate belongs to `getSessionReport`, not this)."""
    session_id = await created_session_id(client, tokens, users, demo_version_id)
    response = await client.get(
        f"/api/v1/instructor/sessions/{session_id}/overview",
        headers=auth(tokens["instructor1"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session"]["state"] == "READY"
    assert body["stages"], "the role chain's stages, even unstarted"
    assert body["handoff"] is None
    assert body["assignments"] == []
    assert body["gate_turns"] == []
    assert body["resources"], "the scenario's board is seeded at createSession"
    assert body["call_state"]["phase"] == "NO_CALL"


async def test_an_active_operator_stage_is_visible(flow: OperatorFlow) -> None:
    response = await overview(flow)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session"]["state"] == "ACTIVE"
    assert body["card"] is not None, "the operator card, live"
    assert body["handoff"] is None
    assert body["assignments"] == []


async def test_a_role_transition_is_visible(in_transition: OperatorFlow) -> None:
    response = await overview(in_transition)
    assert response.status_code == 200, response.text
    assert response.json()["session"]["state"] == "ROLE_TRANSITION"


async def test_an_active_dds_stage_is_visible(dds_active: OperatorFlow) -> None:
    response = await overview(dds_active)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session"]["state"] == "ACTIVE"
    assert body["handoff"] is not None, "the DDS stage has been handed the snapshot"
    assert len(body["assignments"]) == 2, "FIRE_RESCUE + AMBULANCE, one leg per recipient service"


async def test_a_completed_session_is_visible(completed: OperatorFlow) -> None:
    response = await overview(completed)
    assert response.status_code == 200, response.text
    assert response.json()["session"]["state"] == "COMPLETED"


async def test_an_aborted_session_is_visible(dds_active: OperatorFlow) -> None:
    aborted = await dds_active.client.post(
        f"/api/v1/sessions/{dds_active.session_id}/abort",
        headers=auth(dds_active.instructor_token),
        json={"reason": "учебная остановка"},
    )
    assert aborted.status_code == 200, aborted.text

    response = await overview(dds_active)
    assert response.status_code == 200, response.text
    assert response.json()["session"]["state"] == "ABORTED"


# ---------------------------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------------------------


async def test_a_trainee_gets_403(dds_active: OperatorFlow) -> None:
    """`x-visibility: INSTRUCTOR` — even the DDS trainee who is IN this session is refused."""
    response = await overview(dds_active, token=dds_active.dds_token)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_an_unknown_session_is_a_404(completed: OperatorFlow) -> None:
    response = await completed.client.get(
        "/api/v1/instructor/sessions/00000000-0000-4000-8000-0000000000ff/overview",
        headers=auth(completed.instructor_token),
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------------------------
# The hidden layers, and the N legs verbatim
# ---------------------------------------------------------------------------------------------


async def test_world_truth_caller_belief_and_gate_turns_are_present(
    dds_active: OperatorFlow,
) -> None:
    """The one live endpoint that exposes `WorldTruth`/`CallerBelief` at all (D3, D11)."""
    response = await overview(dds_active)
    assert response.status_code == 200, response.text
    body = response.json()

    world_truth = body["world_truth"]
    assert world_truth["incident_id"] == body["session"]["incident_id"]
    assert world_truth["facts"], "the scenario instantiates world facts at createSession"

    caller_belief = body["caller_belief"]
    assert caller_belief["incident_id"] == body["session"]["incident_id"]
    assert caller_belief["emotion"]
    assert isinstance(caller_belief["stress_level"], float)

    assert isinstance(body["gate_turns"], list)


async def test_assignments_are_the_n_legs_verbatim_not_the_trainees_union(
    resolved: OperatorFlow,
) -> None:
    """`resolved` dispatched units to the FIRE_RESCUE leg only — the AMBULANCE leg received
    none. The trainee's `getDdsWorkItem` would show the *union* (one work item); the instructor's
    `assignments` must show the two legs apart, one dispatched and one not (`openapi.yaml`'s
    `DdsWorkItem` description: "per-service `dds_assignments` rows verbatim... `null` on a
    recipient service that received no unit")."""
    response = await overview(resolved)
    assert response.status_code == 200, response.text
    assignments = response.json()["assignments"]
    assert len(assignments) == 2

    by_service = {item["service_type"]: item for item in assignments}
    assert set(by_service) == {"FIRE_RESCUE", "AMBULANCE"}
    assert {item["assignment_id"] for item in assignments} == {
        by_service["FIRE_RESCUE"]["assignment_id"],
        by_service["AMBULANCE"]["assignment_id"],
    }, "two distinct assignment ids, not one aggregated work item"
    assert by_service["FIRE_RESCUE"]["dispatched_at_offset_ms"] is not None
    assert by_service["AMBULANCE"]["dispatched_at_offset_ms"] is None
    assert by_service["AMBULANCE"]["dispatched_resource_ids"] == []


# ---------------------------------------------------------------------------------------------
# A read: no new event, no new row
# ---------------------------------------------------------------------------------------------


async def test_the_overview_writes_nothing(completed: OperatorFlow, uow_factory: Any) -> None:
    before = await _counts(uow_factory, UUID(str(completed.session_id)))

    response = await overview(completed)
    assert response.status_code == 200, response.text

    after = await _counts(uow_factory, UUID(str(completed.session_id)))
    assert after == before

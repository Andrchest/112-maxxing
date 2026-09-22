"""`SINGLE_ROLE [OPERATOR_112]`, end to end over real HTTP (E17-D, R6).

The one mode whose whole `role_chain` is a single `OPERATOR_112` stage: `SessionPolicy.
role_chain_length` is `"EXACTLY_ONE"` (§10.10), so `completeOperatorStage` never finds a next
stage to hand off to and fires `complete` on the session directly — no `ROLE_TRANSITION` is ever
entered, and `score_completed_session` runs from the operator router, not the DDS one
(`app.application.handoff.complete_operator_stage`'s own docstring names this branch explicitly).
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.conftest import auth
from tests.api.handoff.conftest import OperatorFlow, prepare_handoff
from tests.api.modes.conftest import fill_card

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


async def test_the_single_operator_stage_completes_the_session_with_no_role_transition(
    single_role_operator_flow: OperatorFlow, uow_factory: Any
) -> None:
    flow = single_role_operator_flow
    incidents_before = await _incident_ids(uow_factory, flow.session_id)
    assert len(incidents_before) == 1

    assert await flow.advance_call_flow() is True  # ring
    assert (await flow.post("/operator/call/answer")).status_code == 200
    await flow.append_asr(EventType.ASR_FINAL, "Горит квартира на улице Ленина, дом 5")
    assert await flow.advance_call_flow() is True  # begin_interview

    await fill_card(flow)
    await prepare_handoff(flow, "FIRE_RESCUE")
    handoff = await flow.post("/operator/handoff", json={})
    assert handoff.status_code == 201, handoff.text

    ended = await flow.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    assert ended.status_code == 200, ended.text

    before = await flow.event_types()
    completed = await flow.post("/operator/stage/complete")

    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "COMPLETED"

    new = (await flow.event_types())[len(before) :]
    assert "ROLE_TRANSITION_STARTED" not in new, (
        "SINGLE_ROLE's chain has no next stage: `complete`, not `begin_role_transition`, fires"
    )
    # `SESSION_COMPLETED` is appended in the same transaction as the stage events; the
    # `SCORING_RULE_EVALUATED` rows that follow it are epic E15-B's, appended in a second, later
    # Unit of Work (`app.application.handoff.complete_session`'s own docstring) — their count is
    # scenario/scoring detail no epic of this brief owns, so only the ordering that matters here is
    # pinned.
    assert new[:3] == ["STAGE_STATE_CHANGED", "ROLE_STAGE_COMPLETED", "SESSION_COMPLETED"]
    assert all(event_type == "SCORING_RULE_EVALUATED" for event_type in new[3:])

    # SPEC §13 / §42 test 5 holds for a one-stage chain too: still exactly one Incident.
    assert await _incident_ids(uow_factory, flow.session_id) == incidents_before


async def test_a_dds_command_is_forbidden_in_this_mode(
    single_role_operator_flow: OperatorFlow,
) -> None:
    """No `DDS` stage exists in this `role_chain`; a `DDS` endpoint is simply not this stage's."""
    flow = single_role_operator_flow
    response = await flow.post("/dds/acknowledge")
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_an_uninvolved_trainee_cannot_observe_the_session(
    single_role_operator_flow: OperatorFlow,
) -> None:
    flow = single_role_operator_flow
    response = await flow.client.get(
        f"/api/v1/sessions/{flow.session_id}",
        headers=auth(flow.dds_token),
    )
    assert response.status_code == 403, response.text

"""`getSessionSnapshot` — the role-filtered restore payload (SPEC §39, §42 tests 3 and 13; D3).

Two properties, and the second is the one that matters most:

1. a refresh restores the state the last command produced — stage, actions, card, call state and
   the `last_seq_no` the WebSocket resumes from;
2. **a DDS viewer never receives the live `OperatorCard`.** That is tested by building a session
   whose *active* stage is a DDS one, through the repositories, and asking for the snapshot as
   the DDS trainee: `card` must be `null`. `work_item` is `null` here too — the stage was moved
   by hand and was never handed off to, so there is no `HandoffSnapshot` to project (the full
   112 -> DDS run is `backend/tests/api/handoff/` and
   `backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py`). An empty panel is a
   missing handoff; a card on a DDS screen is a broken invariant (D3, SPEC §10).
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from app.domain.common.ids import SessionId
from app.domain.enums import DDSStageState, Operator112StageState
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.conftest import auth
from tests.api.operator.conftest import OperatorFlow

pytestmark = pytest.mark.integration


async def test_the_snapshot_restores_the_operator_console(interview: OperatorFlow) -> None:
    """Everything the 112 console needs after F5, in one call (SPEC §39, §42 test 13)."""
    await interview.set_field("incident.type", "FIRE")
    await interview.select("FIRE_RESCUE")

    snapshot = (await interview.snapshot()).json()
    assert snapshot["session"]["id"] == str(interview.session_id)
    assert snapshot["my_role_type"] == "OPERATOR_112"
    assert snapshot["active_role_type"] == "OPERATOR_112"
    assert snapshot["stage_state"] == "INTERVIEW"
    assert snapshot["card"]["values"]["incident.type"] == "FIRE"
    assert snapshot["card"]["values"]["recipients.services"] == ["FIRE_RESCUE"]
    assert snapshot["work_item"] is None
    assert snapshot["call_state"]["phase"] == "CONNECTED"
    assert snapshot["last_seq_no"] >= 1
    assert "OPERATOR_CARD" in snapshot["visible_sources"]
    assert "WORLD_TRUTH" not in snapshot["visible_sources"]
    assert [action["action_id"] for action in snapshot["available_actions"]] == [
        action.action_id for action in _module().available_actions(Operator112StageState.INTERVIEW)
    ]


def _module() -> object:
    from app.domain.roles.operator112 import Operator112Module

    return Operator112Module()


async def test_the_instructor_sees_the_card_but_holds_no_actions(
    interview: OperatorFlow,
) -> None:
    """The console observes; `available_actions` is filtered by the participant assignment."""
    await interview.set_field("incident.type", "FIRE")
    snapshot = (await interview.snapshot(token=interview.instructor_token)).json()
    assert snapshot["card"]["values"]["incident.type"] == "FIRE"
    assert snapshot["my_role_type"] is None
    assert snapshot["available_actions"] == []
    assert "WORLD_TRUTH" in snapshot["visible_sources"], "the console sees every panel (SPEC §7)"


async def test_the_dds_trainee_gets_no_card_while_the_112_stage_is_active(
    interview: OperatorFlow,
) -> None:
    """The DDS trainee may observe the session, but the live card is not theirs to see (D3)."""
    await interview.set_field("incident.type", "FIRE")
    snapshot = (await interview.snapshot(token=interview.dds_token)).json()
    assert snapshot["card"] is None
    assert snapshot["work_item"] is None
    assert snapshot["my_role_type"] == "DDS"
    assert "OPERATOR_CARD" not in snapshot["visible_sources"]
    assert snapshot["available_actions"] == [], "the 112 stage is not the DDS trainee's stage"


async def test_a_dds_active_stage_never_yields_the_card(
    interview: OperatorFlow, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """§42 test 3, structurally: with the DDS stage *active*, `card` is still `null`.

    The 112 stage is driven to its terminal state through the repositories rather than through
    `createHandoff` / `completeOperatorStage`, so that this test keeps asserting the *shape* —
    an `ACTIVE` session whose `current_stage` is the DDS one — independently of the handoff path
    that `backend/tests/api/handoff/` covers end to end.
    """
    await interview.set_field("incident.type", "FIRE")
    await interview.set_field("address.house", "5")

    async with uow_factory() as uow:
        session = await uow.sessions.get_for_update(SessionId(interview.session_id))
        assert session is not None
        operator_stage, dds_stage = session.stages
        finished = session.model_copy(
            update={
                "stages": (
                    operator_stage.model_copy(
                        update={
                            "state": Operator112StageState.STAGE_COMPLETED,
                            "completed_at_offset_ms": 1,
                        }
                    ),
                    dds_stage.model_copy(
                        update={
                            "state": DDSStageState.RECEIVED,
                            "started_at_offset_ms": 2,
                        }
                    ),
                )
            }
        )
        await uow.sessions.save(finished)
        await uow.commit()

    as_dds = (await interview.snapshot(token=interview.dds_token)).json()
    assert as_dds["active_role_type"] == "DDS"
    assert as_dds["stage_state"] == "RECEIVED"
    assert as_dds["card"] is None, "a DDS viewer never receives the live OperatorCard (D3)"
    assert as_dds["work_item"] is None, "no handoff was made, so there is nothing to project"

    # And not even the 112 trainee gets the card through a DDS-active stage: the decision is the
    # *active stage's*, so the panel is gone for everyone but the instructor.
    as_operator = (await interview.snapshot()).json()
    assert as_operator["active_role_type"] == "DDS"
    assert as_operator["card"] is None


async def test_an_unknown_session_is_404_and_a_stranger_is_403(
    interview: OperatorFlow,
    tokens: dict[str, str],
    users: dict[str, object],
    demo_version_id: object,
) -> None:
    """`openapi.yaml` gives `getSessionSnapshot` a 403 and a 404, and both are reachable."""
    from tests.api.conftest import create_demo_session, participant

    missing = await interview.client.get(
        f"/api/v1/sessions/{uuid4()}/snapshot", headers=auth(interview.operator_token)
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"

    # A session `trainee1` neither participates in nor created: `can_observe` says no, and the
    # trainee is not told it exists.
    other = await create_demo_session(
        interview.client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["admin1"], "OPERATOR_112"), participant(users["trainee2"], "DDS")],
    )
    stranger = await interview.client.get(
        f"/api/v1/sessions/{other['id']}/snapshot", headers=auth(interview.operator_token)
    )
    assert stranger.status_code == 403, stranger.text
    assert stranger.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_snapshot_session_id_round_trips(interview: OperatorFlow) -> None:
    """A sanity check on the mapping: the embedded `SessionDetail` is this session's."""
    snapshot = (await interview.snapshot()).json()
    assert UUID(snapshot["session"]["id"]) == interview.session_id
    assert snapshot["active_role_stage_id"] == snapshot["session"]["active_role_stage_id"]

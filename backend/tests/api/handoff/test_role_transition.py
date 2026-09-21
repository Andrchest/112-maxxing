"""`completeOperatorStage` and `continueToNextStage` — the seam between the two roles (E9).

SPEC §13 is the assertion that matters most here: **the same `Incident` carries over.** A role
change moves the session to the next `RoleStage` against the incident that already exists; it
never creates a second one (§42 test 5). Around that:

* `complete_stage` is guarded by `guard_call_ended`, so a stage whose call is still up cannot be
  completed;
* the session machine then parks the session in `ROLE_TRANSITION` (`role_chain` has a next entry)
  and nothing but `continueToNextStage` moves it;
* the pause is `SessionPolicy.transition_pause_seconds` — ten seconds under `MULTI_TRAINEE` —
  read against the session's own `ROLE_TRANSITION_STARTED` offset, not a frontend timer. These
  tests move a `FakeClock` rather than sleeping (see the package conftest);
* the DDS stage opens in `RECEIVED` with the `dds_assignments` legs already there.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import sqlalchemy as sa
from app.application.testing.fakes import FakeClock
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.handoff.conftest import OperatorFlow, read_assignments

pytestmark = pytest.mark.integration


async def _incident_ids(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork], session_id: Any
) -> list[str]:
    async with uow_factory() as uow:
        result = await uow.session.execute(
            sa.text("SELECT id FROM incidents WHERE session_id = :session_id"),
            {"session_id": session_id},
        )
        ids = [str(row[0]) for row in result.all()]
        await uow.commit()
    return ids


# ---------------------------------------------------------------------------------------------
# completeOperatorStage
# ---------------------------------------------------------------------------------------------


async def test_completing_the_stage_starts_the_role_transition(
    handed_off: OperatorFlow,
) -> None:
    """`x-emits: [ROLE_STAGE_COMPLETED, STAGE_STATE_CHANGED, ROLE_TRANSITION_STARTED]`."""
    assert (
        await handed_off.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200
    before = await handed_off.event_types()

    response = await handed_off.post("/operator/stage/complete")

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "ROLE_TRANSITION"
    new = (await handed_off.event_types())[len(before) :]
    assert new == ["STAGE_STATE_CHANGED", "ROLE_STAGE_COMPLETED", "ROLE_TRANSITION_STARTED"]


async def test_a_stage_whose_call_is_still_up_cannot_be_completed(
    handed_off: OperatorFlow,
) -> None:
    """`guard_call_ended`: the trainee hangs up first (§10.8)."""
    before = await handed_off.event_types()

    response = await handed_off.post("/operator/stage/complete")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "INVALID_TRANSITION"
    assert await handed_off.event_types() == before


async def test_completing_before_the_handoff_is_not_an_available_action(
    prepared: OperatorFlow,
) -> None:
    """D8's second gate: `complete_stage` belongs to `HANDED_OFF` alone (§10.9)."""
    assert (
        await prepared.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200

    response = await prepared.post("/operator/stage/complete")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


# ---------------------------------------------------------------------------------------------
# continueToNextStage
# ---------------------------------------------------------------------------------------------


async def test_continuing_before_the_pause_elapses_is_refused(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    """`409 INVALID_TRANSITION` — `MULTI_TRAINEE`'s pause is ten seconds (§10.10)."""
    before = await in_transition.event_types()
    clock.advance_ms(9_000)

    response = await in_transition.post("/stage/continue", token=in_transition.dds_token)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "INVALID_TRANSITION"
    assert await in_transition.event_types() == before, "a refused continue appends nothing"

    # And the moment the pause has genuinely elapsed, the very same call succeeds.
    clock.advance_ms(2_000)
    allowed = await in_transition.post("/stage/continue", token=in_transition.dds_token)
    assert allowed.status_code == 200, allowed.text


async def test_continuing_starts_the_dds_stage_on_the_same_incident(
    in_transition: OperatorFlow, clock: FakeClock, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """SPEC §13, §42 test 5: one incident per session, carried across the role change."""
    incidents_before = await _incident_ids(uow_factory, in_transition.session_id)
    before = await in_transition.event_types()
    clock.advance_ms(11_000)

    response = await in_transition.post("/stage/continue", token=in_transition.dds_token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "ACTIVE"
    new = (await in_transition.event_types())[len(before) :]
    assert new == ["ROLE_TRANSITION_COMPLETED", "ROLE_STAGE_STARTED"]

    assert await _incident_ids(uow_factory, in_transition.session_id) == incidents_before
    assert len(incidents_before) == 1


async def test_the_dds_stage_opens_in_received_with_its_legs_already_there(
    dds_active: OperatorFlow, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """The legs were written by `createHandoff`; continuing does not create them again."""
    snapshot = (await dds_active.snapshot(token=dds_active.dds_token)).json()

    assert snapshot["active_role_type"] == "DDS"
    assert snapshot["stage_state"] == "RECEIVED"
    assert [action["action_id"] for action in snapshot["available_actions"]] == ["acknowledge"]

    legs = await read_assignments(uow_factory, dds_active.session_id)
    assert len(legs) == 2
    assert {leg["state"] for leg in legs} == {"RECEIVED"}
    assert str(legs[0]["role_stage_id"]) == snapshot["active_role_stage_id"]


async def test_the_instructor_may_continue_the_exercise(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    """SPEC §7: the instructor runs the exercise and may move it along."""
    clock.advance_ms(11_000)

    response = await in_transition.post("/stage/continue", token=in_transition.instructor_token)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "ACTIVE"


async def test_a_trainee_who_does_not_hold_the_next_stage_may_not_continue(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    """The 112 trainee's stage is over; the next stage is somebody else's console."""
    clock.advance_ms(11_000)

    response = await in_transition.post("/stage/continue")

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_continuing_an_active_session_is_refused(handed_off: OperatorFlow) -> None:
    """`finish_role_transition` has no row from `ACTIVE` (§10.8)."""
    response = await handed_off.post("/stage/continue", token=handed_off.dds_token)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "INVALID_TRANSITION"

"""`MULTI_TRAINEE` with two distinct participants, end to end over real HTTP (E17-D, R6).

`create_demo_session`'s own default mode (`tests.api.conftest`) is already `MULTI_TRAINEE`, and
`flow`/`handed_off`/`in_transition`/`dds_active` (`tests.api.operator.conftest`,
`tests.api.handoff.conftest`) already build it with two *distinct* users — `trainee1` on
`OPERATOR_112`, `trainee2` on `DDS` (`ONE_PARTICIPANT_PER_STAGE`, §10.10). What no existing
module proves is the three things R6 asks for about that split:

1. each trainee may act **only** on their own stage — the operator user gets `403` on a `DDS`
   command and the DDS user gets `403` on an `OPERATOR_112` one, in both directions and on both
   sides of the hand-over;
2. the second user's (`DDS`'s) view is `DDS`-redacted **before their own stage is even active**:
   their snapshot never carries the live `OperatorCard` or the DDS work item before the hand-over
   completes, and `GET /events` — documented (`app.api.routers.realtime`'s own docstring) to be
   byte-identical to the WebSocket's own redaction — never carries an `OPERATOR_112`-only event
   type (`CARD_FIELD_CHANGED`) for them, though the instructor's unredacted view does;
3. only the next-stage holder or the instructor may `continueToNextStage` (§10.8's guard, restated
   here for `MULTI_TRAINEE` specifically rather than relied on from `tests/api/handoff`).

CONCURRENCY: no concrete offset is asserted anywhere near the transition (E17-B); no exact
dispatch/closure payload key set is asserted (E17-A).
"""

from __future__ import annotations

import pytest
from app.application.testing.fakes import FakeClock

from tests.api.dds.conftest import event_types as _dds_event_types
from tests.api.handoff.conftest import OperatorFlow

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------------------------
# 1. Each trainee may act only on their own stage
# ---------------------------------------------------------------------------------------------


async def test_the_operator_trainee_cannot_issue_a_dds_command_before_the_handover(
    handed_off: OperatorFlow,
) -> None:
    response = await handed_off.post("/dds/acknowledge", token=handed_off.operator_token)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_dds_trainee_cannot_issue_a_dds_command_before_the_handover(
    handed_off: OperatorFlow,
) -> None:
    """The `DDS` participant is bound to the *next* stage, not the active one — still `403`."""
    response = await handed_off.post("/dds/acknowledge", token=handed_off.dds_token)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_dds_trainee_may_act_once_their_stage_is_active(
    dds_active: OperatorFlow,
) -> None:
    response = await dds_active.post("/dds/acknowledge", token=dds_active.dds_token)
    assert response.status_code == 200, response.text


async def test_the_operator_trainee_may_not_act_once_the_dds_stage_is_active(
    dds_active: OperatorFlow,
) -> None:
    """Their own stage is `STAGE_COMPLETED`, and it is no longer the session's active stage."""
    response = await dds_active.put(
        "/operator/card/field",
        token=dds_active.operator_token,
        json={"field_path": "description.text", "new_value": "x"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_dds_trainee_may_not_issue_an_operator_command(dds_active: OperatorFlow) -> None:
    response = await dds_active.put(
        "/operator/card/field",
        token=dds_active.dds_token,
        json={"field_path": "description.text", "new_value": "x"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


# ---------------------------------------------------------------------------------------------
# 2. The second user's (DDS's) view is DDS-redacted before their own stage starts
# ---------------------------------------------------------------------------------------------


async def test_the_dds_trainees_snapshot_never_carries_the_operator_card(
    handed_off: OperatorFlow,
) -> None:
    """`createHandoff` has already run (legs exist), and still: not the card, not the work item —
    the DDS stage is not the *active* one yet, and `getSessionSnapshot`'s `work_item` branch is
    gated on that, not merely on the legs existing (`app.application.sessions.get_snapshot`)."""
    operator_view = (await handed_off.snapshot(token=handed_off.operator_token)).json()
    assert operator_view["card"] is not None
    assert operator_view["card"]["values"]["description.text"], "the operator's own card, live"

    dds_view = (await handed_off.snapshot(token=handed_off.dds_token)).json()
    assert dds_view["card"] is None, "D3: the DDS participant never receives the live card"
    assert dds_view["work_item"] is None, "not the active stage yet, so no work item either"
    assert dds_view["available_actions"] == [], "not their stage's turn"


async def test_events_visible_to_the_dds_trainee_exclude_operator_only_event_types(
    handed_off: OperatorFlow,
) -> None:
    """§40.4: `CARD_FIELD_CHANGED` is `OPERATOR_112`-only. Same redaction function as the
    WebSocket (`app.application.realtime.redaction.redact`, `GET /events` and the socket are
    documented byte-identical), so this is a faithful stand-in for "the DDS trainee's WS frames
    are DDS-redacted" without needing a second live socket in this module."""
    operator_seen = await _dds_event_types(handed_off, token=handed_off.operator_token)
    dds_seen = await _dds_event_types(handed_off, token=handed_off.dds_token)
    instructor_seen = await _dds_event_types(handed_off, token=handed_off.instructor_token)

    assert "CARD_FIELD_CHANGED" in operator_seen
    assert "CARD_FIELD_CHANGED" in instructor_seen, "the instructor sees every event type (§40.1)"
    assert "CARD_FIELD_CHANGED" not in dds_seen, "the DDS trainee never sees an operator-only type"


# ---------------------------------------------------------------------------------------------
# 3. Only the next-stage holder or the instructor may continue
# ---------------------------------------------------------------------------------------------


async def test_the_operator_trainee_may_not_continue_their_own_finished_stage(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    """The 112 trainee's stage is over; the next stage belongs to a different user entirely."""
    clock.advance_ms(11_000)  # MULTI_TRAINEE's pause is 10 s (§10.10)

    response = await in_transition.post("/stage/continue", token=in_transition.operator_token)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_dds_trainee_may_continue_once_the_pause_has_elapsed(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    clock.advance_ms(11_000)

    response = await in_transition.post("/stage/continue", token=in_transition.dds_token)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "ACTIVE"


async def test_the_instructor_may_also_continue(
    in_transition: OperatorFlow, clock: FakeClock
) -> None:
    clock.advance_ms(11_000)

    response = await in_transition.post("/stage/continue", token=in_transition.instructor_token)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "ACTIVE"

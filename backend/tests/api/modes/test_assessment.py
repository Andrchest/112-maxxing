"""`ASSESSMENT`, end to end over real HTTP (E17-D, R6).

`SessionPolicy` (§10.10): `show_asr_partials=False`, `report_visible_to_trainee_before_release=
False`, `requires_prefab_handoff_for_dds_only=True` — the same shape `SINGLE_ROLE` has except for
those two flags. This module proves the two flags' actual effect, on a session that completes
without instructor intervention (the `[OPERATOR_112]`-only scenario `assessment_flow` shares with
`single_role_operator_flow`; see `tests.api.modes.conftest`'s docstring for why `ASSESSMENT` and
`SINGLE_ROLE` need the same one-stage shape here):

* `ASR_PARTIAL` withheld from the trainee, delivered to the instructor whole (§40.4's one `◆`
  row) — `app.application.realtime.redaction.redact` drops the *whole* event, not merely a key,
  and only for a `RoleType` connection, never for `INSTRUCTOR`;
* the trainee's report is `403 REPORT_NOT_RELEASED` until an instructor releases it, `200`
  after — and the score itself (the checksum) is identical before and after release, because
  release flips a flag and computes nothing.
"""

from __future__ import annotations

import pytest
from app.domain.events.types import EventType

from tests.api.handoff.conftest import OperatorFlow, fill_card, prepare_handoff
from tests.api.modes.conftest import release, report

pytestmark = pytest.mark.integration


async def _complete(flow: OperatorFlow) -> None:
    """Drive the one `OPERATOR_112` stage to `SESSION_COMPLETED` (no `DDS` stage in this chain)."""
    assert await flow.advance_call_flow() is True
    assert (await flow.post("/operator/call/answer")).status_code == 200
    await flow.append_asr(EventType.ASR_FINAL, "Горит квартира на улице Ленина, дом 5")
    assert await flow.advance_call_flow() is True

    await fill_card(flow)
    await prepare_handoff(flow, "FIRE_RESCUE")
    assert (await flow.post("/operator/handoff", json={})).status_code == 201
    assert (
        await flow.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    ).status_code == 200

    completed = await flow.post("/operator/stage/complete")
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "COMPLETED"


async def _events(flow: OperatorFlow, *, token: str) -> list[str]:
    response = await flow.get("/events", token=token, params={"limit": 1000})
    assert response.status_code == 200, response.text
    return [item["event_type"] for item in response.json()["items"]]


# ---------------------------------------------------------------------------------------------
# ASR partials withheld from the trainee, kept for the instructor
# ---------------------------------------------------------------------------------------------


async def test_asr_partial_is_withheld_from_the_trainee_but_not_the_instructor(
    assessment_flow: OperatorFlow,
) -> None:
    flow = assessment_flow
    assert await flow.advance_call_flow() is True
    assert (await flow.post("/operator/call/answer")).status_code == 200
    await flow.append_asr(EventType.ASR_PARTIAL, "Горит кварти")

    trainee_seen = await _events(flow, token=flow.operator_token)
    instructor_seen = await _events(flow, token=flow.instructor_token)

    assert "ASR_PARTIAL" not in trainee_seen, "ASSESSMENT: show_asr_partials is false (§10.10)"
    assert "ASR_PARTIAL" in instructor_seen, "the whole-event withhold is per-role, not global"


# ---------------------------------------------------------------------------------------------
# The report stays behind the release gate for the trainee, and release changes nothing scored
# ---------------------------------------------------------------------------------------------


async def test_the_trainee_report_is_refused_until_released_then_matches_bit_for_bit(
    assessment_flow: OperatorFlow,
) -> None:
    flow = assessment_flow
    await _complete(flow)

    before_release = await report(flow)  # as the instructor
    assert before_release.status_code == 200, before_release.text
    checksum_before = before_release.json()["score_report"]["checksum"]

    refused = await report(flow, token=flow.operator_token)
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "REPORT_NOT_RELEASED"

    released = await release(flow)
    assert released.status_code == 200, released.text
    assert released.json()["released"] is True

    after_release = await report(flow)  # as the instructor, again
    assert after_release.status_code == 200, after_release.text
    assert after_release.json()["score_report"]["checksum"] == checksum_before, (
        "release flips a flag; it computes nothing (E16 D11)"
    )

    trainee_now = await report(flow, token=flow.operator_token)
    assert trainee_now.status_code == 200, trainee_now.text
    assert trainee_now.json()["score_report"]["checksum"] == checksum_before

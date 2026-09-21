"""The caller's identity never reaches the OPERATOR_112 view (D3, SPEC §21, E11 follow-up ruling).

`CallerProfile.identity_ru` is persona data that, in practice, *contains* facts the trainee is
scored on obtaining by asking. The demo scenario's is "Соседка Ирина Петровна из квартиры 41",
which names `caller.full_name` ("Соколова Ирина Петровна") and `address.apartment` (41 is the
caller's own flat, and the digits are the kind of thing a widget must not volunteer). Putting any
of it on the ringing phone widget would move Caller Knowledge into the Operator view — the exact
merge D3 forbids, and the one `openapi.yaml`'s `CallStateView` rules out in as many words:
"nothing about the caller's hidden knowledge appears here".

So this asserts the absence, on all three surfaces the trainee actually sees:

1. the `CALL_RINGING` payload in `session_events`;
2. the operator snapshot's `call_state` (`getSessionSnapshot`);
3. the live WebSocket frame delivered to an `OPERATOR_112` socket (§40.3).

It is a substring test over every meaningful token of the persona's identity, not an equality
check, so a "helpful" partial display ("Ирина Петровна", "кв. 41") fails it too.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import redis.asyncio as redis_asyncio
from app.application.operator.call_flow import CALLER_DISPLAY_RU
from app.config.settings import Settings
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.infrastructure.realtime.redis_publisher import RedisEventPublisher

from tests.api.realtime.conftest import ASGIWebSocket, websocket
from tests.api.voice.conftest import OperatorFlow

pytestmark = pytest.mark.integration

__all__ = ["websocket"]

#: The demo scenario's `caller_profile.identity_ru`
#: (`scenarios/examples/apartment-fire/v1.yaml`).
DEMO_IDENTITY_RU = "Соседка Ирина Петровна из квартиры 41"

#: Every token of it that would be a leak on its own, plus the `caller.full_name` fact value and
#: the flat number as bare digits. A display that contains any of these has revealed something the
#: trainee is supposed to ask for.
FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    DEMO_IDENTITY_RU,
    "Соседка",
    "соседка",
    "Ирина",
    "Петровна",
    "Соколова",
    "квартиры 41",
    "квартира 41",
    "кв. 41",
    # No bare " 41": `str(payload)` renders integers as `: 41…`, so an offset of 41/410-419 ms
    # would fail this test at random (the E11-0 "27" lesson). The three above cover the flat.
)


@pytest.fixture
def publisher(redis_client: redis_asyncio.Redis, api_settings: Settings) -> RedisEventPublisher:
    """The real Redis fan-out: surface (3) is about what actually reaches a subscriber."""
    return RedisEventPublisher(redis_client, api_settings.session_cache_ttl_s)


def assert_clean(text: str, where: str) -> None:
    """`text` contains no fragment of the caller's identity."""
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in text, f"{where} leaked {fragment!r} from the caller profile"


# -- 1. the event payload ----------------------------------------------------------------------


async def test_the_call_ringing_payload_carries_the_neutral_line(flow: OperatorFlow) -> None:
    assert await flow.advance_call_flow() is True

    async with flow.container.unit_of_work() as uow:
        events = await uow.events.read(SessionId(flow.session_id))
        await uow.commit()
    payload = next(
        dict(event.payload) for event in events if event.event_type is EventType.CALL_RINGING
    )

    assert payload["caller_display_ru"] == CALLER_DISPLAY_RU
    assert CALLER_DISPLAY_RU == "Входящий вызов 112"
    assert_clean(str(payload), "the CALL_RINGING payload")


# -- 2. the operator snapshot ------------------------------------------------------------------


async def test_the_operator_snapshot_call_state_carries_the_neutral_line(
    ringing: OperatorFlow,
) -> None:
    call_state = (await ringing.snapshot()).json()["call_state"]

    assert call_state["caller_display_ru"] == CALLER_DISPLAY_RU
    assert_clean(str(call_state), "the operator snapshot call_state")


async def test_no_operator_facing_response_of_a_ringing_call_leaks_the_identity(
    ringing: OperatorFlow,
) -> None:
    """The whole snapshot body, not just the call state — a leak anywhere in it is still a leak."""
    assert_clean((await ringing.snapshot()).text, "the operator snapshot")

    answered = await ringing.post("/operator/call/answer")
    assert answered.status_code == 200, answered.text
    assert_clean(answered.text, "the answerCall response")


# -- 3. the WebSocket frame ----------------------------------------------------------------------


async def test_the_operator_websocket_frame_for_call_ringing_carries_the_neutral_line(
    ringing: OperatorFlow,
    websocket: Callable[..., ASGIWebSocket],
) -> None:
    """§40.3: the socket applies the OPERATOR_112 role filter to the unredacted envelope."""
    async with websocket(SessionId(ringing.session_id), token=ringing.operator_token) as socket:
        await socket.send_json({"type": "resume", "after_seq_no": 0})
        frames = await socket.receive_until("resume_complete")

    ringing_frames: list[dict[str, Any]] = [
        frame
        for frame in frames
        if frame.get("type") == "event" and frame.get("event_type") == EventType.CALL_RINGING.value
    ]
    assert ringing_frames, "the operator socket never received CALL_RINGING"

    for frame in ringing_frames:
        assert frame["payload"]["caller_display_ru"] == CALLER_DISPLAY_RU
    for frame in frames:
        assert_clean(str(frame), "an OPERATOR_112 WebSocket frame")


# -- the instructor-facing catalogue field is a different field and keeps the identity ------------


async def test_the_scenario_catalogue_still_shows_the_persona_to_an_instructor(
    ringing: OperatorFlow,
) -> None:
    """`ScenarioVersionSummary.caller_display_ru` is `CallerProfile.identity_ru` and stays so.

    Same property name, different schema, different audience: an instructor picking a scenario
    must see who the caller is. Asserting it here is what keeps the ruling a *separation* rather
    than a deletion — if this ever starts returning the neutral line, the catalogue broke.
    """
    session = (
        await ringing.client.get(
            f"/api/v1/sessions/{ringing.session_id}",
            headers={"Authorization": f"Bearer {ringing.instructor_token}"},
        )
    ).json()
    version_id = session["scenario_version_id"]

    response = await ringing.client.get(
        f"/api/v1/scenarios/versions/{version_id}/summary",
        headers={"Authorization": f"Bearer {ringing.instructor_token}"},
    )
    assert response.status_code == 200, response.text

    assert response.json()["caller_display_ru"] == DEMO_IDENTITY_RU

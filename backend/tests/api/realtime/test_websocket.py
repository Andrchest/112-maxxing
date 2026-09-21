"""`WS /api/v1/ws/sessions/{id}` against the real application, PostgreSQL and Redis (E7-C).

Everything §40.1-§40.6 promises a *client*, asserted on the raw frames: the close codes, the
replay/resume handshake, live delivery through a real Unit of Work commit, the role filter on the
wire, the rate limit, the malformed-frame rejection, the heartbeat as a gap detector, recovery
when the fan-out was lost, and resource hygiene.

No Redis `FLUSHALL` is issued anywhere (the instance is shared): "Redis was lost" is simulated by
`LostFanOutPublisher` — a commit that reaches PostgreSQL and refreshes §40.6's read cache but whose
pub/sub message never arrives, which is exactly the state a client sees when a message is dropped.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from app.api.container import Container
from app.config.settings import Settings
from app.domain.common.ids import ScenarioVersionId, SessionId
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.conftest import create_demo_session, participant
from tests.api.realtime.conftest import ASGIWebSocket, append_events, domain_event

pytestmark = pytest.mark.integration

UNKNOWN_SESSION = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def api_settings(test_settings: Settings) -> Settings:
    """As `tests/api`, plus a heartbeat short enough for a test to observe one (§40.2)."""
    return test_settings.model_copy(
        update={
            "runner_enabled": False,
            "require_inference_ready": False,
            "cors_allow_origins": [],
            "api_port": 8100,
            "ws_heartbeat_s": 1,
        }
    )


@pytest.fixture
async def session_id(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
) -> SessionId:
    """A 112 → DDS session with `trainee1` on 112 and `trainee2` on DDS."""
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [
            participant(users["trainee1"], "OPERATOR_112"),
            participant(users["trainee2"], "DDS"),
        ],
    )
    return SessionId(detail["id"])


# ---------------------------------------------------------------------------------------------
# §40.1 — the close codes
# ---------------------------------------------------------------------------------------------


async def test_a_missing_token_is_4401(
    websocket: Callable[..., ASGIWebSocket], session_id: SessionId
) -> None:
    async with websocket(session_id) as socket:
        assert await socket.expect_close() == 4401


async def test_an_invalid_token_is_4401(
    websocket: Callable[..., ASGIWebSocket], session_id: SessionId
) -> None:
    async with websocket(session_id, token="not-a-jwt") as socket:
        assert await socket.expect_close() == 4401


async def test_an_unknown_session_is_4404(
    websocket: Callable[..., ASGIWebSocket], tokens: dict[str, str]
) -> None:
    async with websocket(UNKNOWN_SESSION, token=tokens["instructor1"]) as socket:
        assert await socket.expect_close() == 4404


async def test_a_non_participant_trainee_is_4403(
    client: httpx.AsyncClient,
    websocket: Callable[..., ASGIWebSocket],
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
) -> None:
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [
            participant(users["trainee1"], "OPERATOR_112"),
            participant(users["instructor1"], "DDS"),
        ],
    )
    async with websocket(detail["id"], token=tokens["trainee2"]) as socket:
        assert await socket.expect_close() == 4403


async def test_a_cursor_ahead_of_the_log_is_4409_after_an_error_frame(
    websocket: Callable[..., ASGIWebSocket], tokens: dict[str, str], session_id: SessionId
) -> None:
    async with websocket(session_id, token=tokens["trainee1"]) as socket:
        await socket.send_json({"type": "resume", "after_seq_no": 900})
        frame = await socket.receive()
        assert frame["type"] == "error"
        assert frame["code"] == "INVALID_RESUME_CURSOR"
        assert await socket.expect_close() == 4409


async def test_a_malformed_frame_is_4400_after_an_error_frame(
    websocket: Callable[..., ASGIWebSocket], tokens: dict[str, str], session_id: SessionId
) -> None:
    """§40.2: "Any other `type`, any non-JSON payload […] closes the socket (`4400`)"."""
    async with websocket(session_id, token=tokens["trainee1"]) as socket:
        await socket.send_text("{not json")
        frame = await socket.receive()
        assert frame == {"type": "error", "code": "INVALID_FRAME", "detail": "expected resume"}
        assert await socket.expect_close() == 4400


async def test_a_command_frame_is_refused_rather_than_executed(
    websocket: Callable[..., ASGIWebSocket], tokens: dict[str, str], session_id: SessionId
) -> None:
    """§40.2, SPEC §34: "The client can never send a command over this socket"."""
    async with websocket(session_id, token=tokens["trainee1"]) as socket:
        await socket.send_json({"type": "setCardField", "field_path": "address", "value": "x"})
        assert (await socket.receive())["code"] == "INVALID_FRAME"
        assert await socket.expect_close() == 4400


async def test_more_than_the_frame_limit_per_second_is_4429(
    websocket: Callable[..., ASGIWebSocket],
    tokens: dict[str, str],
    session_id: SessionId,
    container: Container,
) -> None:
    """§40.2: "more than 10 frames per second closes the socket (`4429`)"."""
    limit = container.settings.ws_max_frames_per_s
    async with websocket(session_id, token=tokens["trainee1"]) as socket:
        for _ in range(limit + 1):
            await socket.send_json({"type": "resume", "after_seq_no": 0})
        assert await socket.expect_close() == 4429


async def test_the_server_going_away_closes_with_1001(
    websocket: Callable[..., ASGIWebSocket], tokens: dict[str, str], session_id: SessionId
) -> None:
    """§40.5 "Backend restart": the connection task is cancelled, and `1001` reaches the client."""
    socket = websocket(session_id, token=tokens["trainee1"])
    await socket.__aenter__()
    await socket.send_json({"type": "resume", "after_seq_no": 0})
    await socket.receive_until("resume_complete")

    assert socket._task is not None
    socket._task.cancel()
    assert await socket.expect_close() == 1001
    await socket.aclose()


# ---------------------------------------------------------------------------------------------
# §40.3 — replay, resume_complete, live tail
# ---------------------------------------------------------------------------------------------


async def test_resume_from_zero_replays_then_goes_live_in_order(
    websocket: Callable[..., ASGIWebSocket],
    tokens: dict[str, str],
    session_id: SessionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """§40.3 steps 1-5, end to end, against a real commit-then-publish (D5)."""
    replayed = await append_events(
        unit_of_work,
        session_id,
        domain_event(EventType.SESSION_STARTED, first_role_type="OPERATOR_112"),
        domain_event(EventType.CARD_FIELD_CHANGED, field_path="address", new_value="Ленина 1"),
    )
    async with websocket(session_id, token=tokens["trainee1"]) as socket:
        await socket.send_json({"type": "resume", "after_seq_no": 0})
        frames = await socket.receive_until("resume_complete")

        events = [frame for frame in frames if frame["type"] == "event"]
        assert [frame["seq_no"] for frame in events] == replayed
        complete = frames[-1]
        assert complete["live"] is True
        assert complete["replayed_count"] == len(events)

        live = await append_events(
            unit_of_work,
            session_id,
            domain_event(EventType.SERVICE_SELECTED, service_type="FIRE"),
            domain_event(EventType.CALL_ENDED, call_id="c1", duration_ms=5000),
        )
        assert [(await socket.receive())["seq_no"] for _ in live] == live


async def test_an_operator_socket_never_receives_the_hidden_event_types(
    websocket: Callable[..., ASGIWebSocket],
    tokens: dict[str, str],
    session_id: SessionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """§40.4 rows 1, 10 and 40, asserted on the **raw frames**, live and replayed (D3)."""
    async with websocket(session_id, token=tokens["trainee1"]) as socket:
        await socket.send_json({"type": "resume", "after_seq_no": 0})
        replay = await socket.receive_until("resume_complete")
        assert all(frame.get("event_type") != "SESSION_CREATED" for frame in replay), (
            "the createSession event is instructor-only (§40.4 row 1)"
        )

        await append_events(
            unit_of_work,
            session_id,
            domain_event(EventType.WORLD_TRUTH_MUTATED, revision=1),
            domain_event(EventType.CALLER_RESPONSE_PLANNED, withheld_count=3),
            domain_event(EventType.CARD_FIELD_CHANGED, field_path="address"),
        )
        frame = await socket.receive()
        assert frame["type"] == "event"
        assert frame["event_type"] == "CARD_FIELD_CHANGED"


async def test_an_instructor_socket_receives_them(
    websocket: Callable[..., ASGIWebSocket],
    tokens: dict[str, str],
    session_id: SessionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    async with websocket(session_id, token=tokens["instructor1"]) as socket:
        await socket.send_json({"type": "resume", "after_seq_no": 0})
        await socket.receive_until("resume_complete")

        await append_events(
            unit_of_work,
            session_id,
            domain_event(EventType.WORLD_TRUTH_MUTATED, revision=1),
            domain_event(EventType.CALLER_RESPONSE_PLANNED, withheld_count=3),
        )
        first = await socket.receive()
        second = await socket.receive()
        assert first["event_type"] == "WORLD_TRUTH_MUTATED"
        assert second["event_type"] == "CALLER_RESPONSE_PLANNED"
        assert first["redacted_keys"] == []


async def test_a_second_resume_restarts_the_mechanism_from_the_new_cursor(
    websocket: Callable[..., ASGIWebSocket],
    tokens: dict[str, str],
    session_id: SessionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """§40.2: a client behind the heartbeat's `last_seq_no` re-sends `resume` and heals the gap."""
    seq_nos = await append_events(
        unit_of_work,
        session_id,
        domain_event(EventType.SESSION_STARTED),
        domain_event(EventType.CARD_FIELD_CHANGED, field_path="address"),
    )
    async with websocket(session_id, token=tokens["trainee1"]) as socket:
        await socket.send_json({"type": "resume", "after_seq_no": seq_nos[-1]})
        first = await socket.receive_until("resume_complete")
        assert [f for f in first if f["type"] == "event"] == []

        await socket.send_json({"type": "resume", "after_seq_no": 0})
        second = await socket.receive_until("resume_complete")
        assert [f["seq_no"] for f in second if f["type"] == "event"] == seq_nos


async def test_a_heartbeat_reveals_a_lost_fan_out_and_a_resume_recovers_it(
    websocket: Callable[..., ASGIWebSocket],
    tokens: dict[str, str],
    session_id: SessionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    silent_unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """§40.6: "Loss ⇒ clients fall back to replay from PostgreSQL on the next heartbeat gap".

    The event is committed to PostgreSQL through a Unit of Work whose publisher publishes nothing
    — a lost Redis message, without touching the shared instance. The client sees nothing live,
    then a heartbeat whose `last_seq_no` is ahead of its own, and recovers by re-resuming.
    """
    await append_events(unit_of_work, session_id, domain_event(EventType.SESSION_STARTED))
    async with websocket(session_id, token=tokens["trainee1"]) as socket:
        await socket.send_json({"type": "resume", "after_seq_no": 0})
        frames = await socket.receive_until("resume_complete")
        cursor = frames[-1]["last_seq_no"]

        missed = await append_events(
            silent_unit_of_work,
            session_id,
            domain_event(EventType.CARD_FIELD_CHANGED, field_path="address"),
        )
        heartbeat = await socket.receive(15.0)
        assert heartbeat["type"] == "heartbeat", "no live event was fanned out"
        assert heartbeat["last_seq_no"] > cursor, "the heartbeat is the gap detector (§40.2)"

        await socket.send_json({"type": "resume", "after_seq_no": cursor})
        recovered = await socket.receive_until("resume_complete")
        assert [f["seq_no"] for f in recovered if f["type"] == "event"] == missed


async def test_the_publisher_refreshes_the_last_seq_no_cache_key(
    session_id: SessionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    redis_client: Any,
) -> None:
    """§40.6's `session:{id}:last_seq_no`, "refreshed on publish", with its TTL."""
    seq_nos = await append_events(unit_of_work, session_id, domain_event(EventType.SESSION_STARTED))
    key = f"session:{str(session_id).lower()}:last_seq_no"
    assert int(await redis_client.get(key)) == seq_nos[-1]
    assert 0 < int(await redis_client.ttl(key)) <= 3600


# ---------------------------------------------------------------------------------------------
# §40.1 and §40.6 — the token, and resource hygiene
# ---------------------------------------------------------------------------------------------


async def test_the_token_is_never_logged(
    websocket: Callable[..., ASGIWebSocket],
    tokens: dict[str, str],
    session_id: SessionId,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """§40.1: "The token is never logged" (SPEC §41)."""
    token = tokens["trainee1"]
    with caplog.at_level(logging.DEBUG):
        async with websocket(session_id, token=token) as socket:
            await socket.send_json({"type": "resume", "after_seq_no": 0})
            await socket.receive_until("resume_complete")
        async with websocket(session_id, token="forged." + token) as refused:
            assert await refused.expect_close() == 4401
    assert token not in caplog.text
    assert "token=" not in caplog.text


async def test_token_expiry_after_connect_does_not_drop_the_socket(
    websocket: Callable[..., ASGIWebSocket],
    tokens: dict[str, str],
    session_id: SessionId,
    container: Container,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """§40.1: "Token expiry during a live session does **not** drop the socket" (SPEC §39).

    The account is deactivated outright, which is strictly stronger than an expiry: every later
    REST call from that token is `401`, and the socket keeps streaming. `trainee1` is shared
    reference data (`tests/api/conftest.py`'s `users`), but `UserRepository.upsert` is
    `ON CONFLICT DO UPDATE`, so the next test that asks for `users` upserts it straight back to
    `is_active=True` — this test's deactivation does not leak into whatever runs next.
    """
    async with websocket(session_id, token=tokens["trainee1"]) as socket:
        await socket.send_json({"type": "resume", "after_seq_no": 0})
        await socket.receive_until("resume_complete")

        async with unit_of_work() as uow:
            user = await uow.users.get_by_username("trainee1")
            assert user is not None
            await uow.users.upsert(
                user_id=user.user_id,
                username=user.username,
                display_name_ru=user.display_name_ru,
                user_role=user.user_role,
                password_hash=user.password_hash,
                is_active=False,
            )
            await uow.commit()

        seq_nos = await append_events(
            unit_of_work, session_id, domain_event(EventType.CARD_FIELD_CHANGED, field_path="a")
        )
        frame = await socket.receive()
        assert frame["seq_no"] == seq_nos[-1], "the socket outlives the credential (§40.1)"
    assert container is not None


async def test_twenty_connects_leave_no_task_and_no_redis_subscriber_behind(
    websocket: Callable[..., ASGIWebSocket],
    tokens: dict[str, str],
    session_id: SessionId,
    redis_subscriber_count: Callable[[Any], Any],
) -> None:
    """§40.6 resource hygiene: every subscription and task is released on disconnect."""
    assert await redis_subscriber_count(session_id) == 0
    before = len(asyncio.all_tasks())

    for _ in range(20):
        async with websocket(session_id, token=tokens["trainee1"]) as socket:
            await socket.send_json({"type": "resume", "after_seq_no": 0})
            await socket.receive_until("resume_complete")
            assert await redis_subscriber_count(session_id) == 1

    await asyncio.sleep(0.1)
    assert await redis_subscriber_count(session_id) == 0
    assert len(asyncio.all_tasks()) == before

"""`listSessionEvents` over the real application, database and Redis (E7-C).

The REST twin of the replay: same envelopes, same §40.4 filter, and — asserted here — *the same
JSON*, because §40.2 says the WebSocket's `event` frame is byte-identical to this endpoint's item.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from app.application.realtime.effective_role import Connection
from app.application.realtime.event_stream import EventFrame
from app.application.realtime.redaction import redact, source_of_row
from app.domain.common.ids import ScenarioVersionId, SessionId
from app.domain.enums import RoleType, SessionMode
from app.domain.events.types import EventType
from app.domain.session.policy import SESSION_POLICIES
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.conftest import auth, create_demo_session, participant
from tests.api.realtime.conftest import append_events, domain_event

pytestmark = pytest.mark.integration


async def _session_with_events(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> tuple[SessionId, list[int]]:
    """A 112 → DDS session plus a log that spans all three §40.4 verdicts."""
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [
            participant(users["trainee1"], "OPERATOR_112"),
            participant(users["trainee2"], "DDS"),
        ],
    )
    session_id = SessionId(detail["id"])
    seq_nos = await append_events(
        unit_of_work,
        session_id,
        domain_event(EventType.SESSION_STARTED, first_role_type="OPERATOR_112"),
        domain_event(EventType.WORLD_TRUTH_MUTATED, revision=1, source_world_event_id="w1"),
        domain_event(
            EventType.CALLER_UTTERANCE_INTERRUPTED,
            call_id="c1",
            planned_text="я живу на пятом этаже",
            delivered_text="я живу",
            delivered_audio_ms=800,
            cutoff_latency_ms=120,
        ),
        domain_event(EventType.HANDOFF_RECEIVED, snapshot_id="s1", service_type="FIRE"),
    )
    return session_id, seq_nos


async def test_an_operator_never_receives_a_world_truth_event(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """§40.4 rows 40 and 18: `WORLD_TRUTH_MUTATED` and `HANDOFF_RECEIVED` are not this role's."""
    session_id, _ = await _session_with_events(client, tokens, users, demo_version_id, unit_of_work)
    response = await client.get(
        f"/api/v1/sessions/{session_id}/events", headers=auth(tokens["trainee1"])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    types = [item["event_type"] for item in body["items"]]
    assert types == ["SESSION_STARTED", "CALLER_UTTERANCE_INTERRUPTED"]
    assert body["has_more"] is False


async def test_the_interrupted_utterance_loses_planned_text_for_the_trainee(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """§40.4 row 14: "what the caller *would* have said is unrevealed information (SPEC §21)"."""
    session_id, _ = await _session_with_events(client, tokens, users, demo_version_id, unit_of_work)
    trainee = (
        await client.get(
            f"/api/v1/sessions/{session_id}/events",
            headers=auth(tokens["trainee1"]),
            params={"event_type": "CALLER_UTTERANCE_INTERRUPTED"},
        )
    ).json()["items"][0]
    assert "planned_text" not in trainee["payload"]
    assert trainee["payload"]["delivered_text"] == "я живу"
    assert trainee["redacted_keys"] == ["planned_text"]
    assert "я живу на пятом этаже" not in json.dumps(trainee, ensure_ascii=False)

    instructor = (
        await client.get(
            f"/api/v1/sessions/{session_id}/events",
            headers=auth(tokens["instructor1"]),
            params={"event_type": "CALLER_UTTERANCE_INTERRUPTED"},
        )
    ).json()["items"][0]
    assert instructor["payload"]["planned_text"] == "я живу на пятом этаже"
    assert instructor["redacted_keys"] == []


async def test_the_dds_trainee_sees_the_handoff_the_operator_does_not(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    session_id, _ = await _session_with_events(client, tokens, users, demo_version_id, unit_of_work)
    body = (
        await client.get(f"/api/v1/sessions/{session_id}/events", headers=auth(tokens["trainee2"]))
    ).json()
    assert [item["event_type"] for item in body["items"]] == [
        "SESSION_STARTED",
        "HANDOFF_RECEIVED",
    ]


async def test_last_seq_no_is_the_highest_visible_to_the_role(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """`openapi.yaml`'s definition, and the one `getSession` now answers with too (E7-C)."""
    session_id, seq_nos = await _session_with_events(
        client, tokens, users, demo_version_id, unit_of_work
    )
    started, _world, interrupted, handoff = seq_nos

    page = await client.get(
        f"/api/v1/sessions/{session_id}/events", headers=auth(tokens["trainee1"])
    )
    assert page.json()["last_seq_no"] == interrupted

    detail = await client.get(f"/api/v1/sessions/{session_id}", headers=auth(tokens["trainee1"]))
    assert detail.json()["last_seq_no"] == interrupted, "SessionDetail and the page agree"

    dds_detail = await client.get(
        f"/api/v1/sessions/{session_id}", headers=auth(tokens["trainee2"])
    )
    assert dds_detail.json()["last_seq_no"] == handoff

    console = await client.get(
        f"/api/v1/sessions/{session_id}", headers=auth(tokens["instructor1"])
    )
    assert console.json()["last_seq_no"] == max(seq_nos)
    assert started < handoff


async def test_paging_is_exclusive_and_reports_has_more(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    session_id, _ = await _session_with_events(client, tokens, users, demo_version_id, unit_of_work)
    whole = (
        await client.get(
            f"/api/v1/sessions/{session_id}/events", headers=auth(tokens["instructor1"])
        )
    ).json()
    every = [item["seq_no"] for item in whole["items"]]
    assert len(every) > 2, "the fixture must produce more events than one page holds"

    first = (
        await client.get(
            f"/api/v1/sessions/{session_id}/events",
            headers=auth(tokens["instructor1"]),
            params={"limit": 2},
        )
    ).json()
    assert [item["seq_no"] for item in first["items"]] == every[:2]
    assert first["has_more"] is True

    second = (
        await client.get(
            f"/api/v1/sessions/{session_id}/events",
            headers=auth(tokens["instructor1"]),
            params={"after_seq_no": first["items"][-1]["seq_no"], "limit": 1000},
        )
    ).json()
    assert [item["seq_no"] for item in second["items"]] == every[2:]
    assert second["has_more"] is False


async def test_a_stranger_is_forbidden_and_an_unknown_session_is_not_found(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
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
    session_id = detail["id"]
    forbidden = await client.get(
        f"/api/v1/sessions/{session_id}/events", headers=auth(tokens["trainee2"])
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_FOR_ROLE"

    missing = await client.get(
        "/api/v1/sessions/11111111-1111-4111-8111-111111111111/events",
        headers=auth(tokens["instructor1"]),
    )
    assert missing.status_code == 404

    anonymous = await client.get(f"/api/v1/sessions/{session_id}/events")
    assert anonymous.status_code == 401


async def test_the_rest_item_and_the_websocket_event_frame_are_byte_identical(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, Any],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """§40.2: "The envelope is byte-identical to what `GET .../events` returns"."""
    session_id, _ = await _session_with_events(client, tokens, users, demo_version_id, unit_of_work)
    items = (
        await client.get(f"/api/v1/sessions/{session_id}/events", headers=auth(tokens["trainee1"]))
    ).json()["items"]

    connection = Connection(
        RoleType.OPERATOR_112, SESSION_POLICIES[SessionMode.MULTI_TRAINEE], False
    )
    async with unit_of_work() as uow:
        rows = await uow.events.read(session_id)
        await uow.commit()

    frames = []
    for row in rows:
        envelope = redact(source_of_row(row), connection.role, connection.policy)
        if envelope is not None:
            frames.append(EventFrame.of(envelope).model_dump(mode="json"))

    assert len(frames) == len(items)
    for item, frame in zip(items, frames, strict=True):
        assert frame["type"] == "event"
        assert {key: value for key, value in frame.items() if key != "type"} == item

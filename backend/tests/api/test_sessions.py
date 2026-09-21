"""The session lifecycle through HTTP: create → start → get → list → abort (D6, D7, D8)."""

from __future__ import annotations

import httpx
import pytest
from app.api.container import Container
from app.api.main import create_app
from app.application.testing.fakes import FakeInferenceReadiness
from app.domain.common.ids import ScenarioVersionId, UserId

from tests.api.conftest import auth, create_demo_session, participant

pytestmark = pytest.mark.integration


def _participants(users: dict[str, UserId]) -> list[dict[str, object]]:
    """The demo scenario's chain is `[OPERATOR_112, DDS]`: one trainee per stage."""
    return [
        participant(users["trainee1"], "OPERATOR_112"),
        participant(users["trainee2"], "DDS"),
    ]


async def test_create_start_get_list_abort(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """The whole lifecycle over HTTP, with `REQUIRE_INFERENCE_READY=false`."""
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    session_id = created["id"]
    assert created["state"] == "READY"
    assert created["scenario_slug"] == "apartment-fire"
    assert created["role_chain"] == ["OPERATOR_112", "DDS"]
    assert len(created["participants"]) == 2
    assert created["monotonic_offset_ms"] == 0
    assert created["last_seq_no"] >= 1, "SESSION_CREATED is already in the log"

    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "ACTIVE"
    assert started.json()["started_at"] is not None

    fetched = await client.get(f"/api/v1/sessions/{session_id}", headers=auth(tokens["trainee1"]))
    assert fetched.status_code == 200
    assert fetched.json()["state"] == "ACTIVE"
    assert fetched.json()["id"] == session_id

    listed = await client.get("/api/v1/sessions", headers=auth(tokens["trainee1"]))
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == session_id
    assert body["items"][0]["my_role_type"] == "OPERATOR_112"

    aborted = await client.post(
        f"/api/v1/sessions/{session_id}/abort",
        headers=auth(tokens["instructor1"]),
        json={"reason": "закончили раньше"},
    )
    assert aborted.status_code == 200, aborted.text
    assert aborted.json()["state"] == "ABORTED"
    assert aborted.json()["abort_reason"] == "закончили раньше"


async def test_start_is_503_when_inference_is_required_and_not_ready(
    container: Container,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """`REQUIRE_INFERENCE_READY=true` + a not-ready readiness port ⇒ `503 INFERENCE_NOT_READY`.

    The `ProblemCode` is the contract's, and the session is still `READY` afterwards: the guard
    refuses the transition before anything is written (D8, SPEC §37).
    """
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    session_id = created["id"]

    strict = Container(
        container.settings.model_copy(update={"require_inference_ready": True}),
        engine=container.engine,
        session_factory=container.session_factory,
        redis=container.redis,
        unit_of_work=container.unit_of_work,
        hasher=container.hasher,
        tokens=container.tokens,
        inference=FakeInferenceReadiness(ready=False),
        owns_engine=False,
        owns_redis=False,
    )
    transport = httpx.ASGITransport(app=create_app(strict))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as strict_client:
        response = await strict_client.post(
            f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
        )

    assert response.status_code == 503, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "INFERENCE_NOT_READY"

    still_ready = await client.get(
        f"/api/v1/sessions/{session_id}", headers=auth(tokens["instructor1"])
    )
    assert still_ready.json()["state"] == "READY"


async def test_a_trainee_cannot_see_another_trainees_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """`getSession` is `403` and `listSessions` is empty for an unrelated trainee (D8)."""
    created = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee1"], None)],
        session_mode="FULL_CYCLE_SINGLE_TRAINEE",
    )
    session_id = created["id"]

    refused = await client.get(f"/api/v1/sessions/{session_id}", headers=auth(tokens["trainee2"]))
    assert refused.status_code == 403
    assert refused.json()["code"] == "FORBIDDEN_FOR_ROLE"

    listed = await client.get("/api/v1/sessions", headers=auth(tokens["trainee2"]))
    assert listed.status_code == 200
    assert listed.json() == {"items": [], "total": 0}

    own = await client.get("/api/v1/sessions", headers=auth(tokens["trainee1"]))
    assert own.json()["total"] == 1


async def test_scope_all_is_refused_for_a_trainee_and_allowed_for_an_instructor(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """`scope=ALL` is INSTRUCTOR/ADMIN only — a trainee learns not even the total."""
    await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee1"], None)],
        session_mode="FULL_CYCLE_SINGLE_TRAINEE",
    )

    refused = await client.get(
        "/api/v1/sessions", headers=auth(tokens["trainee2"]), params={"scope": "ALL"}
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "FORBIDDEN_FOR_ROLE"

    allowed = await client.get(
        "/api/v1/sessions", headers=auth(tokens["admin1"]), params={"scope": "ALL"}
    )
    assert allowed.status_code == 200
    assert allowed.json()["total"] == 1
    # The admin is not a participant, so `my_role_type` is null — they observe, they do not play.
    assert allowed.json()["items"][0]["my_role_type"] is None


async def test_a_trainee_cannot_create_a_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """`createSession` is INSTRUCTOR/ADMIN (`openapi.yaml`)."""
    response = await client.post(
        "/api/v1/sessions",
        headers=auth(tokens["trainee1"]),
        json={
            "scenario_version_id": str(demo_version_id),
            "session_mode": "MULTI_TRAINEE",
            "participants": _participants(users),
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_create_against_an_unknown_version_is_404(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    """A `scenario_version_id` that does not exist is `404 NOT_FOUND`."""
    response = await client.post(
        "/api/v1/sessions",
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": "00000000-0000-4000-8000-000000000000",
            "session_mode": "MULTI_TRAINEE",
            "participants": _participants(users),
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_aborting_twice_is_409(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """An illegal state-machine trigger is `409 INVALID_TRANSITION` (D8)."""
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    session_id = created["id"]
    body = {"reason": "первый раз"}

    first = await client.post(
        f"/api/v1/sessions/{session_id}/abort", headers=auth(tokens["instructor1"]), json=body
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/sessions/{session_id}/abort", headers=auth(tokens["instructor1"]), json=body
    )
    assert second.status_code == 409
    assert second.headers["content-type"].startswith("application/problem+json")
    assert second.json()["code"] == "INVALID_TRANSITION"


async def test_getting_an_unknown_session_is_404(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """A session id that does not exist is `404`, not `403`: there is nothing to hide."""
    response = await client.get(
        "/api/v1/sessions/00000000-0000-4000-8000-000000000000",
        headers=auth(tokens["instructor1"]),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"

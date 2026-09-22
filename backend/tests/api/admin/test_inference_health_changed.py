"""A `voice:health` transition becomes `INFERENCE_HEALTH_CHANGED`, and nothing else (E18-B).

The subscriber (`app.infrastructure.health.VoiceHealthSubscriber`) is a thin pub/sub loop; the
decision about what to write is `AppendInferenceHealthChanged`, and that is what these tests drive,
with real PostgreSQL sessions created over HTTP. The loop itself is covered by the unit test beside
it.

This module sits under `tests/api/admin/` because the append path is also what makes
`clearInferenceFatal`'s `x-emits: [INFERENCE_HEALTH_CHANGED]` true, and because the sessions it
needs already exist as fixtures here.

The rule under test is SPEC §39's closing line — **never silently reset the simulation**. Health
changes health: the session's state, its card, its incident and every event already written are
compared before and after, field for field.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from app.api.container import Container
from app.application.inference_health import AppendInferenceHealthChanged, HealthTransition
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.events.types import EventType
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.conftest import auth, create_demo_session, participant

pytestmark = pytest.mark.integration

TRANSITION = json.dumps(
    {
        "service": "tts",
        "from": "READY",
        "to": "NOT_READY",
        "detail": "synthesis timed out",
        "at": "2026-09-22T10:00:00Z",
    }
)
"""One `voice:health` message, `60-inference-ops.md` §4.3's shape literally."""


def _participants(users: dict[str, UserId]) -> list[dict[str, Any]]:
    return [
        participant(users["trainee1"], "OPERATOR_112"),
        participant(users["trainee2"], "DDS"),
    ]


async def _events(unit_of_work: Callable[[], SqlAlchemyUnitOfWork], session_id: str) -> list[Any]:
    async with unit_of_work() as uow:
        events = await uow.events.read(SessionId(session_id))
        await uow.commit()
        return events


async def _active_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> dict[str, Any]:
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    started = await client.post(
        f"/api/v1/sessions/{created['id']}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    body: dict[str, Any] = started.json()
    return body


async def test_one_event_per_active_session_and_none_for_a_ready_one(
    container: Container,
    client: httpx.AsyncClient,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """Exactly one `INFERENCE_HEALTH_CHANGED` per ACTIVE session; a READY session gets none."""
    active = await _active_session(client, tokens, users, demo_version_id)
    not_started = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    before_active = await _events(unit_of_work, active["id"])
    before_ready = await _events(unit_of_work, not_started["id"])

    appended = await AppendInferenceHealthChanged(container.unit_of_work, container.clock)(
        HealthTransition.model_validate_json(TRANSITION)
    )

    assert [str(one) for one in appended] == [active["id"]]
    after_active = await _events(unit_of_work, active["id"])
    after_ready = await _events(unit_of_work, not_started["id"])
    assert len(after_active) == len(before_active) + 1
    assert len(after_ready) == len(before_ready), "a READY session's log is not touched"
    event = after_active[-1]
    assert event.event_type is EventType.INFERENCE_HEALTH_CHANGED
    assert event.actor_type.value == "SYSTEM"
    assert dict(event.payload) == {
        "component": "tts",
        "previous_status": "READY",
        "new_status": "NOT_READY",
        "detail": "synthesis timed out",
    }
    # Nothing that was already written was rewritten (SPEC §39).
    assert [one.id for one in after_active[:-1]] == [one.id for one in before_active]


async def test_the_session_state_card_and_incident_are_unchanged(
    container: Container,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """ "An OOM changes health, never simulation state" (§4.4) — asserted field for field."""
    active = await _active_session(client, tokens, users, demo_version_id)
    headers = auth(tokens["instructor1"])
    before = (await client.get(f"/api/v1/sessions/{active['id']}", headers=headers)).json()
    card_before = (
        await client.get(
            f"/api/v1/sessions/{active['id']}/operator/card", headers=auth(tokens["trainee1"])
        )
    ).json()

    await AppendInferenceHealthChanged(container.unit_of_work, container.clock)(
        HealthTransition.model_validate_json(TRANSITION)
    )

    after = (await client.get(f"/api/v1/sessions/{active['id']}", headers=headers)).json()
    card_after = (
        await client.get(
            f"/api/v1/sessions/{active['id']}/operator/card", headers=auth(tokens["trainee1"])
        )
    ).json()
    assert after["state"] == before["state"] == "ACTIVE"
    assert after["incident_id"] == before["incident_id"]
    assert after["started_at"] == before["started_at"]
    assert after["last_seq_no"] > before["last_seq_no"], "the log only ever grows"
    volatile = {"last_seq_no", "monotonic_offset_ms"}
    assert {key: value for key, value in after.items() if key not in volatile} == {
        key: value for key, value in before.items() if key not in volatile
    }
    assert card_after["revision_counter"] == card_before["revision_counter"]
    assert card_after["values"] == card_before["values"]
    assert card_after["card_id"] == card_before["card_id"]


async def test_no_active_session_means_no_write(
    container: Container,
    client: httpx.AsyncClient,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """A health transition with nothing running is not an error and writes nothing."""
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    before = await _events(unit_of_work, created["id"])

    appended = await AppendInferenceHealthChanged(container.unit_of_work, container.clock)(
        HealthTransition.model_validate_json(TRANSITION)
    )

    assert appended == []
    assert len(await _events(unit_of_work, created["id"])) == len(before)


@pytest.mark.parametrize(
    "message",
    [
        pytest.param("not json", id="not-json"),
        pytest.param('{"service": "tts"}', id="no-states"),
        pytest.param('{"service": "tts", "from": "READY", "to": "MELTED"}', id="unknown-state"),
        pytest.param("[]", id="not-an-object"),
    ],
)
async def test_a_malformed_message_is_dropped_not_raised(
    container: Container,
    client: httpx.AsyncClient,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
    message: str,
) -> None:
    """Redis is a fan-out bus, never a source of truth: an unreadable message costs one log line."""
    active = await _active_session(client, tokens, users, demo_version_id)
    before = await _events(unit_of_work, active["id"])

    appended = await AppendInferenceHealthChanged(
        container.unit_of_work, container.clock
    ).from_message(message)

    assert appended == []
    assert len(await _events(unit_of_work, active["id"])) == len(before)

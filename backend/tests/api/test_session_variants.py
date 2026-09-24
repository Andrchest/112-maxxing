"""Variant switches over HTTP (I3 E1, HLD `70-i3-alignment.md` §70.2, §70.11, D14).

* the round trip: `createSession` with explicit `variants` → `getSession` echoes them →
  `SESSION_CREATED.variants` and `simulation_sessions.variants` hold the same values;
* `card_source: GENERATED_CARD` on the demo runs the effective chain `[DDS]` and materialises the
  prefab handoff at start; `CALLER_VOICE` keeps today's full chain — and so does a request with no
  `variants` at all (P5);
* every unimplemented value is `409 VARIANT_NOT_AVAILABLE`, a value outside the scenario's
  `supported` is `409 VARIANT_NOT_SUPPORTED`, and neither writes anything;
* a session row written before E1 (`variants = '{}'`) reads as the schema-1 derivation;
* the scenario reads carry `ScenarioVariantsView`, after the implemented-values filter.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from app.application.scenarios.import_scenarios import canonical_content, content_digest
from app.domain.common.ids import ScenarioId, ScenarioVersionId, SessionId, UserId
from app.domain.scenario.validation import VALIDATION_RULE_NUMBERS
from app.domain.scenario.version import ScenarioVersion
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.conftest import auth, participant
from tests.fixtures.scenarios import demo_document

pytestmark = pytest.mark.integration

GENERATED_CARD = {
    "card_source": "GENERATED_CARD",
    "dds_mode": "RESOURCE_PICKER",
    "dds_card_check": "OFF",
    "dds_brigade_call": "OFF",
}
CALLER_VOICE = {**GENERATED_CARD, "card_source": "CALLER_VOICE"}


async def _create(
    client: httpx.AsyncClient,
    token: str,
    version_id: ScenarioVersionId,
    participants: list[dict[str, Any]],
    *,
    session_mode: str,
    variants: dict[str, str] | None,
) -> httpx.Response:
    body: dict[str, Any] = {
        "scenario_version_id": str(version_id),
        "session_mode": session_mode,
        "participants": participants,
    }
    if variants is not None:
        body["variants"] = variants
    return await client.post("/api/v1/sessions", headers=auth(token), json=body)


async def _session_count(unit_of_work: Callable[[], SqlAlchemyUnitOfWork]) -> int:
    async with unit_of_work() as uow:
        count = (
            await uow.session.execute(sa.text("SELECT count(*) FROM simulation_sessions"))
        ).scalar_one()
        await uow.commit()
    return int(count)


async def _import(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], slug: str, document: dict[str, Any]
) -> ScenarioVersionId:
    """Store `document` as version 1 of scenario `slug` (idempotent across tests)."""
    version = ScenarioVersion(**document)
    content = canonical_content(version)
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(slug)
        if stored is None:
            await uow.scenarios.add_scenario(
                ScenarioId(UUID(document["scenario_id"])), slug, version.title
            )
            await uow.scenarios.add_version(version, content, content_digest(content))
            version_id: ScenarioVersionId = version.id
        else:
            found = await uow.scenarios.find_version(stored.scenario_id, 1)
            assert found is not None
            version_id = found.scenario_version_id
        await uow.commit()
    return version_id


# ---------------------------------------------------------------------------------------------
# The record: request → SessionDetail → SESSION_CREATED → simulation_sessions
# ---------------------------------------------------------------------------------------------


async def test_explicit_variants_round_trip_to_the_event_and_the_row(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    created = await _create(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee2"], "DDS")],
        session_mode="SINGLE_ROLE",
        variants=GENERATED_CARD,
    )
    assert created.status_code == 201, created.text
    assert created.json()["variants"] == GENERATED_CARD
    session_id = created.json()["id"]

    fetched = await client.get(
        f"/api/v1/sessions/{session_id}", headers=auth(tokens["instructor1"])
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["variants"] == GENERATED_CARD
    assert fetched.json()["role_chain"] == ["DDS"]
    assert fetched.json()["scenario_role_chain"] == ["OPERATOR_112", "DDS"]

    async with unit_of_work() as uow:
        events = await uow.events.read(SessionId(UUID(session_id)))
        row_variants = (
            await uow.session.execute(
                sa.text("SELECT variants FROM simulation_sessions WHERE id = :id"),
                {"id": session_id},
            )
        ).scalar_one()
        await uow.commit()
    session_created = events[0]
    assert session_created.event_type.value == "SESSION_CREATED"
    assert session_created.payload["variants"] == GENERATED_CARD
    assert session_created.payload["role_chain"] == ["DDS"]
    assert session_created.payload["scenario_role_chain"] == ["OPERATOR_112", "DDS"]
    assert row_variants == GENERATED_CARD


async def test_no_variants_keeps_todays_caller_voice_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """P5: a request without `variants` on the schema-1 demo is exactly today's session."""
    created = await _create(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee1"], "OPERATOR_112"), participant(users["trainee2"], "DDS")],
        session_mode="MULTI_TRAINEE",
        variants=None,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["variants"] == CALLER_VOICE
    assert body["role_chain"] == ["OPERATOR_112", "DDS"]
    assert body["scenario_role_chain"] == ["OPERATOR_112", "DDS"]


# ---------------------------------------------------------------------------------------------
# The flow switch on the demo scenario
# ---------------------------------------------------------------------------------------------


async def test_generated_card_on_the_demo_runs_dds_on_the_prefab_handoff(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    created = await _create(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee2"], "DDS")],
        session_mode="SINGLE_ROLE",
        variants={"card_source": "GENERATED_CARD"},
    )
    assert created.status_code == 201, created.text
    assert [stage["role_type"] for stage in created.json()["stages"]] == ["DDS"]
    session_id = created.json()["id"]

    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text

    async with unit_of_work() as uow:
        events = await uow.events.read(SessionId(UUID(session_id)))
        snapshots = (
            await uow.session.execute(
                sa.text(
                    "SELECT h.recipient_services FROM handoff_snapshots h"
                    " JOIN incidents i ON i.id = h.incident_id WHERE i.session_id = :id"
                ),
                {"id": session_id},
            )
        ).all()
        await uow.commit()
    types = [event.event_type.value for event in events]
    assert "HANDOFF_CREATED" not in types, "no trainee created this handoff (§10.13)"
    assert types.count("HANDOFF_RECEIVED") == 2
    received = [event for event in events if event.event_type.value == "HANDOFF_RECEIVED"]
    assert {event.payload["service_type"] for event in received} == {"FIRE_RESCUE", "AMBULANCE"}
    assert len(snapshots) == 1

    snapshot = await client.get(
        f"/api/v1/sessions/{session_id}/snapshot", headers=auth(tokens["trainee2"])
    )
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["active_role_type"] == "DDS"
    assert snapshot.json()["work_item"]["recipient_services"] == ["FIRE_RESCUE", "AMBULANCE"]


async def test_caller_voice_keeps_the_full_chain_and_no_prefab(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    created = await _create(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee1"], "OPERATOR_112"), participant(users["trainee2"], "DDS")],
        session_mode="MULTI_TRAINEE",
        variants={"card_source": "CALLER_VOICE"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role_chain"] == ["OPERATOR_112", "DDS"]
    session_id = created.json()["id"]
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text

    async with unit_of_work() as uow:
        events = await uow.events.read(SessionId(UUID(session_id)))
        await uow.commit()
    assert "HANDOFF_RECEIVED" not in [event.event_type.value for event in events]


# ---------------------------------------------------------------------------------------------
# The two refusals
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variants",
    [
        {"dds_mode": "MEMO_STATUSES"},
        {"dds_card_check": "ON"},
        {"dds_brigade_call": "ON"},
    ],
)
async def test_every_unimplemented_value_is_409_variant_not_available(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    variants: dict[str, str],
) -> None:
    before = await _session_count(unit_of_work)
    response = await _create(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee2"], "DDS")],
        session_mode="SINGLE_ROLE",
        variants={"card_source": "GENERATED_CARD", **variants},
    )

    assert response.status_code == 409, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VARIANT_NOT_AVAILABLE"
    assert await _session_count(unit_of_work) == before


async def test_a_value_outside_supported_is_409_variant_not_supported(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    isolated_scenario_catalog: None,
) -> None:
    """A schema-2 scenario that declares only the caller refuses `GENERATED_CARD`.

    `isolated_scenario_catalog` truncates `scenarios` after the test, so the extra scenario this
    imports never leaks into the shared catalog `listScenarios` tests count."""
    document: dict[str, Any] = copy.deepcopy(demo_document())
    document["id"] = str(uuid4())
    document["scenario_id"] = str(uuid4())
    document["schema_version"] = 2
    document["variants"] = {
        "supported": {
            "card_source": ["CALLER_VOICE"],
            "dds_mode": ["RESOURCE_PICKER"],
            "dds_card_check": ["OFF"],
            "dds_brigade_call": ["OFF"],
        },
        "default": CALLER_VOICE,
    }
    version_id = await _import(unit_of_work, "caller-only-schema-2", document)
    before = await _session_count(unit_of_work)

    response = await _create(
        client,
        tokens["instructor1"],
        version_id,
        [participant(users["trainee2"], "DDS")],
        session_mode="SINGLE_ROLE",
        variants={"card_source": "GENERATED_CARD"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "VARIANT_NOT_SUPPORTED"
    assert await _session_count(unit_of_work) == before


# ---------------------------------------------------------------------------------------------
# Rows written before E1, and the scenario reads
# ---------------------------------------------------------------------------------------------


async def test_a_session_row_without_variants_reads_as_the_schema_1_derivation(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """Migration 0009 leaves `'{}'` on every existing row (no backfill, §70.8)."""
    created = await _create(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee1"], "OPERATOR_112"), participant(users["trainee2"], "DDS")],
        session_mode="MULTI_TRAINEE",
        variants=None,
    )
    session_id = created.json()["id"]
    async with unit_of_work() as uow:
        await uow.session.execute(
            sa.text("UPDATE simulation_sessions SET variants = '{}'::jsonb WHERE id = :id"),
            {"id": session_id},
        )
        await uow.commit()

    fetched = await client.get(
        f"/api/v1/sessions/{session_id}", headers=auth(tokens["instructor1"])
    )

    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["variants"] == CALLER_VOICE


async def test_scenario_reads_carry_the_filtered_variants_view(
    client: httpx.AsyncClient, tokens: dict[str, str], demo_version_id: ScenarioVersionId
) -> None:
    """The demo is schema 1: derived support, `dds_card_check: ON` filtered out (E5)."""
    expected = {
        "supported": {
            "card_source": ["CALLER_VOICE", "GENERATED_CARD"],
            "dds_mode": ["RESOURCE_PICKER"],
            "dds_card_check": ["OFF"],
            "dds_brigade_call": ["OFF"],
        },
        "default": CALLER_VOICE,
    }
    summary = await client.get(
        f"/api/v1/scenarios/versions/{demo_version_id}/summary", headers=auth(tokens["trainee1"])
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["variants"] == expected

    scenarios = await client.get("/api/v1/scenarios", headers=auth(tokens["instructor1"]))
    demo = next(item for item in scenarios.json()["items"] if item["slug"] == "apartment-fire")
    versions = await client.get(
        f"/api/v1/scenarios/{demo['scenario_id']}/versions", headers=auth(tokens["instructor1"])
    )
    assert versions.status_code == 200, versions.text
    listed = next(item for item in versions.json()["items"] if item["id"] == str(demo_version_id))
    assert listed["variants"] == expected


def _r32_document() -> dict[str, Any]:
    """The demo as schema 2 whose declared default lies outside its declared support (R32)."""
    document: dict[str, Any] = copy.deepcopy(demo_document())
    document["schema_version"] = 2
    document["variants"] = {
        "supported": {
            "card_source": ["GENERATED_CARD"],
            "dds_mode": ["RESOURCE_PICKER"],
            "dds_card_check": ["OFF"],
            "dds_brigade_call": ["OFF"],
        },
        "default": CALLER_VOICE,
    }
    return document


async def test_validating_an_r32_document_answers_a_report_with_rule_32(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """`ScenarioValidationIssue.rule_number` reaches R40 (was capped at 30, which made the report
    for any rule ≥ 31 a response-validation 500)."""
    response = await client.post(
        "/api/v1/scenarios/validate",
        headers=auth(tokens["instructor1"]),
        json={"format": "JSON", "content": json.dumps(_r32_document(), ensure_ascii=False)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] is False
    assert {issue["rule_number"] for issue in body["issues"]} == {32}
    assert body["checked_rule_count"] == len(VALIDATION_RULE_NUMBERS)


async def test_importing_an_r32_document_is_422_with_rule_32_in_the_report(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    document = _r32_document()
    document["id"] = str(uuid4())
    document["scenario_id"] = str(uuid4())
    response = await client.post(
        "/api/v1/scenarios/import",
        headers=auth(tokens["instructor1"]),
        json={"format": "JSON", "content": json.dumps(document, ensure_ascii=False)},
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "SCENARIO_INVALID"
    issues = body["validation_report"]["issues"]
    assert {issue["rule_number"] for issue in issues} == {32}

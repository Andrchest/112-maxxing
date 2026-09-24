"""Routing and the notification list end to end (I3 E2b′; HLD 70 §70.6.4, §70.7, C10, D18).

On pack `v046_24-r1` (E3a′'s v2 card, the real classifier and catalog):

* INV 4 — a routing-relevant `setCardField` appends `CARD_FIELD_CHANGED` + `RECIPIENTS_RESOLVED`
  and makes exactly one card revision; the resolver never writes the card;
* `createHandoff` appends the final `RECIPIENTS_RESOLVED {final: true}` immediately before
  `HANDOFF_CREATED`; the snapshot and `HANDOFF_CREATED.recipient_services` hold auto ∪ manual, and
  one leg is created per service of it;
* the removal rule: `409 SERVICE_REMOVAL_FORBIDDEN` under v2, `200` under v1 (C10);
* the schema-2 prefab path (GENERATED_CARD) does the same as `createHandoff`, with a SIMULATION
  `HANDOFF_CREATED`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import yaml
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.enums import ActorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.engine import NOT_APPLICABLE_NOTE_RU, score
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.conftest import auth, participant
from tests.api.operator.conftest import OperatorFlow
from tests.api.operator.test_card_schema_v2 import (  # noqa: F401 - pytest fixtures
    _example_version_id,
    v2_interview,
    v2_version_id,
)

pytestmark = pytest.mark.integration

EXAMPLE_PATH = (
    Path(__file__).resolve().parents[4] / "scenarios/examples/street-rubbish-fire/v1.yaml"
)

IMAGE_19 = (
    ("incident.types", ["1"]),
    ("q.fire.where", ["на улице"]),
    ("q.fire.sign_street", ["открытое пламя / дым"]),
    ("q.fire.access", ["no_access"]),
    ("q.fire.street_object", ["мусор"]),
)


async def _events(flow: OperatorFlow) -> list[SessionEvent]:
    async with flow.container.unit_of_work() as uow:
        events = await uow.events.read(SessionId(flow.session_id))
        await uow.commit()
    return list(events)


async def _fill_image_19(flow: OperatorFlow) -> None:
    for path, value in IMAGE_19:
        response = await flow.set_field(path, value)
        assert response.status_code == 200, response.text


async def test_a_routing_field_appends_recipients_resolved_and_one_revision(
    v2_interview: OperatorFlow,  # noqa: F811
) -> None:
    """INV 4: CARD_FIELD_CHANGED + RECIPIENTS_RESOLVED, and no second card revision."""
    before = len(await _events(v2_interview))
    response = await v2_interview.set_field("incident.types", ["1"])
    assert response.status_code == 200, response.text
    assert response.json()["card"]["revision_counter"] == 1
    appended = (await _events(v2_interview))[before:]
    assert [e.event_type for e in appended] == [
        EventType.CARD_FIELD_CHANGED,
        EventType.RECIPIENTS_RESOLVED,
    ]
    resolved = appended[1]
    assert resolved.actor_type is ActorType.SIMULATION
    assert resolved.payload["final"] is False
    assert resolved.payload["pack_id"] == "v046_24-r1"
    assert resolved.payload["card_revision_id"] == appended[0].payload["revision_id"]
    page = await v2_interview.get("/operator/card/revisions")
    assert page.json()["total"] == 1


async def test_a_non_routing_field_appends_no_resolution(
    v2_interview: OperatorFlow,  # noqa: F811
) -> None:
    before = len(await _events(v2_interview))
    response = await v2_interview.set_field("description.text", "Горит мусор")
    assert response.status_code == 200, response.text
    appended = (await _events(v2_interview))[before:]
    assert [e.event_type for e in appended] == [EventType.CARD_FIELD_CHANGED]


async def test_image_19_resolves_to_its_bar(v2_interview: OperatorFlow) -> None:  # noqa: F811
    await _fill_image_19(v2_interview)
    resolved = [
        e for e in await _events(v2_interview) if e.event_type is EventType.RECIPIENTS_RESOLVED
    ]
    assert len(resolved) == len(IMAGE_19)
    assert set(resolved[-1].payload["auto_services"]) == {"FIRE_RESCUE", "TSODD", "OATI"}
    assert resolved[-1].payload["candidate_codes"] == ["1010101", "1010102"]
    assert resolved[-1].payload["notification_list"] == resolved[-1].payload["auto_services"]


async def test_selection_view_carries_auto_manual_and_no_removal_under_v2(
    v2_interview: OperatorFlow,  # noqa: F811
) -> None:
    await _fill_image_19(v2_interview)
    response = await v2_interview.select("POLICE")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected_services"] == ["POLICE"]
    assert set(body["auto_services"]) == {"FIRE_RESCUE", "TSODD", "OATI"}
    assert body["notification_list"][-1] == "POLICE"
    assert set(body["notification_list"]) == {"FIRE_RESCUE", "TSODD", "OATI", "POLICE"}
    assert "GOR_KHOZYAYSTVO" in body["informed_services"]
    assert body["removal_allowed"] is False
    assert body["classifier_code"] is None
    assert body["candidate_codes"] == ["1010101", "1010102"]
    # the v2 picker offers the displayed, non-deprecated catalog — not the six legacy ids
    assert "UTILITY_EMERGENCY" not in body["available_services"]
    assert "GOR_KHOZYAYSTVO" not in body["available_services"]
    assert "MOSLIFT" in body["available_services"]


async def test_removal_is_forbidden_under_v2(v2_interview: OperatorFlow) -> None:  # noqa: F811
    assert (await v2_interview.select("POLICE")).status_code == 200
    before = len(await _events(v2_interview))
    for service in ("POLICE", "FIRE_RESCUE"):
        response = await v2_interview.deselect(service)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "SERVICE_REMOVAL_FORBIDDEN"
    assert len(await _events(v2_interview)) == before
    card = await v2_interview.get("/operator/card")
    assert card.json()["values"]["recipients.services"] == ["POLICE"]


async def test_removal_still_works_under_v1(interview: OperatorFlow) -> None:
    assert (await interview.select("POLICE")).status_code == 200
    response = await interview.deselect("POLICE")
    assert response.status_code == 200, response.text
    assert response.json()["selected_services"] == []
    assert response.json()["removal_allowed"] is True
    assert "RECIPIENTS_RESOLVED" not in await interview.event_types()


async def test_create_handoff_freezes_the_union_after_a_final_resolution(
    v2_interview: OperatorFlow,  # noqa: F811
) -> None:
    await _fill_image_19(v2_interview)
    for path, value in (("address.okrug", "СЗАО"), ("address.district", "Щукино")):
        assert (await v2_interview.set_field(path, value)).status_code == 200
    assert (await v2_interview.select("POLICE")).status_code == 200
    assert (await v2_interview.post("/operator/handoff/prepare")).status_code == 200
    before = len(await _events(v2_interview))

    response = await v2_interview.post("/operator/handoff", json={})
    assert response.status_code == 201, response.text
    union = [
        "FIRE_RESCUE",
        "TSODD",
        "OATI",
        "DDS_DISTRICT_SHCHUKINO",
        "DDS_PREFECTURE_SZAO",
        "POLICE",
    ]
    assert response.json()["snapshot"]["recipient_services"] == union
    assert len(response.json()["assignment_ids"]) == len(union)

    appended = (await _events(v2_interview))[before:]
    types = [e.event_type for e in appended]
    assert types[:2] == [EventType.RECIPIENTS_RESOLVED, EventType.HANDOFF_CREATED]
    final, created = appended[0], appended[1]
    assert final.payload["final"] is True
    assert final.payload["notification_list"] == union
    assert final.payload["manual_services"] == ["POLICE"]
    assert created.actor_type is ActorType.TRAINEE
    assert created.payload["recipient_services"] == union
    assert created.payload["manual_recipient_services"] == ["POLICE"]
    assert created.payload["auto_recipient_services"] == union[:-1]
    assert "GOR_KHOZYAYSTVO" in created.payload["informed_services"]
    received = [
        e.payload["service_type"] for e in appended if e.event_type is EventType.HANDOFF_RECEIVED
    ]
    assert received == union
    # the card's own `recipients.services` stays the manual part
    card = await v2_interview.get("/operator/card")
    assert card.json()["values"]["recipients.services"] == ["POLICE"]


async def test_create_handoff_needs_no_manual_service_when_auto_exists(
    v2_interview: OperatorFlow,  # noqa: F811
) -> None:
    await _fill_image_19(v2_interview)
    assert (await v2_interview.post("/operator/handoff/prepare")).status_code == 200
    response = await v2_interview.post("/operator/handoff", json={})
    assert response.status_code == 201, response.text
    assert set(response.json()["snapshot"]["recipient_services"]) == {
        "FIRE_RESCUE",
        "TSODD",
        "OATI",
    }


async def test_the_prefab_path_resolves_and_hands_off_the_union(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    demo_version_id: ScenarioVersionId,
) -> None:
    version_id = await _example_version_id(unit_of_work, demo_version_id)
    created = await client.post(
        "/api/v1/sessions",
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(version_id),
            "session_mode": "SINGLE_ROLE",
            "participants": [participant(users["trainee2"], "DDS")],
        },
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text

    async with unit_of_work() as uow:
        events = list(await uow.events.read(session_id))  # type: ignore[arg-type]
        await uow.commit()
    types = [e.event_type for e in events]
    resolved_at = types.index(EventType.RECIPIENTS_RESOLVED)
    assert types[resolved_at + 1] == EventType.HANDOFF_CREATED
    after = [t for t in types[resolved_at + 2 :] if t is not EventType.DDS_CARD_STATUS_CHANGED]
    assert after and all(t is EventType.HANDOFF_RECEIVED for t in after)
    final, handoff = events[resolved_at], events[resolved_at + 1]
    assert final.payload["final"] is True
    assert handoff.actor_type is ActorType.SIMULATION
    assert handoff.payload["manual_recipient_services"] == ["FIRE_RESCUE", "TSODD", "OATI"]
    assert set(handoff.payload["recipient_services"]) == {
        "FIRE_RESCUE",
        "TSODD",
        "OATI",
        "DDS_DISTRICT_SHCHUKINO",
        "DDS_PREFECTURE_SZAO",
    }
    received = [
        e.payload["service_type"] for e in events if e.event_type is EventType.HANDOFF_RECEIVED
    ]
    assert received == handoff.payload["recipient_services"]


async def test_a_prefab_handoff_never_scores_a_112_rule(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    demo_version_id: ScenarioVersionId,
) -> None:
    """Manager decision on E2b′ Q4: on a chain with no OPERATOR_112 stage (GENERATED_CARD,
    effective chain `[DDS]`) every OPERATOR_112-scoped rule is non-applicable, zero/zero —
    HANDOFF-evaluated ones included, whatever SIMULATION `HANDOFF_CREATED` the prefab emitted.
    It holds through `applies_to_roles` and the effective chain `SESSION_CREATED.role_chain`
    records (E1); nothing in scoring had to change."""
    version_id = await _example_version_id(unit_of_work, demo_version_id)
    created = await client.post(
        "/api/v1/sessions",
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(version_id),
            "session_mode": "SINGLE_ROLE",
            "participants": [participant(users["trainee2"], "DDS")],
        },
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    async with unit_of_work() as uow:
        events = list(await uow.events.read(session_id))  # type: ignore[arg-type]
        await uow.commit()
    session_created = next(e for e in events if e.event_type is EventType.SESSION_CREATED)
    assert session_created.payload["role_chain"] == ["DDS"]
    handoff = next(e for e in events if e.event_type is EventType.HANDOFF_CREATED)
    assert handoff.actor_type is ActorType.SIMULATION

    document = yaml.safe_load(EXAMPLE_PATH.read_text(encoding="utf-8"))
    # Only the two 112-scoped rules: the example's DDS rules need a closed session to bound their
    # evidence, and the session is still running — which is exactly when a 112 HANDOFF rule would
    # already have its `HANDOFF_CREATED` to read.
    document["scoring_rules"] = [
        {
            "rule_id": "op_services_at_handoff",
            "name_ru": "Службы при передаче",
            "description_ru": "112-правило, оцениваемое при передаче.",
            "category": "SERVICE_ROUTING",
            "max_points": 12,
            "critical": True,
            "evaluator_type": "SERVICE_SELECTION",
            "applies_to_roles": ["OPERATOR_112"],
            "min_evidence": 1,
            "config": {
                "required_services": ["FIRE_RESCUE", "AMBULANCE"],
                "forbidden_services": ["TSODD"],
                "points_per_required": 6,
                "penalty_per_forbidden": -3,
                "all_or_nothing": False,
                "evaluated_at": "HANDOFF",
            },
        },
        {
            "rule_id": "op_handoff_completeness",
            "name_ru": "Полнота переданной карточки",
            "description_ru": "112-правило над HANDOFF_CREATED.card_values.",
            "category": "CARD_QUALITY",
            "max_points": 12,
            "critical": True,
            "evaluator_type": "HANDOFF_COMPLETENESS",
            "applies_to_roles": ["OPERATOR_112"],
            "min_evidence": 1,
            "config": {
                "required_field_paths": ["address.locality", "address.apartment"],
                "points_per_field": 6,
                "all_or_nothing": False,
                "penalty_per_missing": -2,
                "treat_false_as_present": True,
            },
        },
    ]
    version = ScenarioVersion.model_validate(document)
    report = score(version, events)
    by_id = {result.rule_id: result for result in report.results}
    for rule_id in ("op_services_at_handoff", "op_handoff_completeness"):
        result = by_id[rule_id]
        assert (result.points_awarded, result.max_points) == (0.0, 0.0), rule_id
        assert result.passed and not result.critical_failure
        assert [item.note_ru for item in result.evidence] == [NOT_APPLICABLE_NOTE_RU]
    assert report.critical_errors == ()
    assert (report.total_points, report.total_max_points) == (0.0, 0.0)

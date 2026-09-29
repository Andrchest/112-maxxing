"""Card schema v2 end to end (I3 E3a; HLD 70 §70.5, D17).

* A 112 session on pack `v046_24-r1` writes v2 paths, is refused a v1-only path
  (`422 CARD_FIELD_UNKNOWN`) and an option code outside a field's options
  (`422 CARD_OPTION_UNKNOWN`), and accepts a field hidden by `visible_when` (advisory);
  its card view says `card_schema: v2` and carries the v2 field specs.
* The schema-2 example `street-rubbish-fire` under `GENERATED_CARD` reaches the ДДС with the
  prefab in v2 paths, and the ДДС work item carries the pack's v2 field specs — read from the
  reference pack the session recorded, never from the scenario (INV 3).
* `getCardSchema` serves `v1` and `v2`, and `404` for an unknown id.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.api.container import Container
from app.domain.common.ids import ScenarioVersionId, UserId
from app.domain.enums import ActorType
from app.domain.events.types import EventType
from app.domain.scenario.validation import validate_scenario_document
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.reference.file_catalog import FileReferenceCatalog

from tests.api.conftest import auth, participant
from tests.api.operator.conftest import OperatorFlow
from tests.fixtures.scenarios import demo_document

pytestmark = pytest.mark.integration

V2_SLUG = "card-schema-v2-demo"
EXAMPLE_SLUG = "street-rubbish-fire"


def _v2_document() -> dict[str, Any]:
    """The demo scenario moved onto pack `v046_24-r1`: its v1-only card paths replaced."""
    document = copy.deepcopy(demo_document())
    document["schema_version"] = 2
    document["reference_pack"] = "v046_24-r1"
    document["id"] = "2b8e6f3a-9c41-4d7e-8a15-3f0c6d2b9e47"
    document["scenario_id"] = "6d4a1c9e-2f7b-4e38-b5a0-9e3c7f1d8b26"
    prefab = document["expected_response"]["prefab_handoff"]["card_values"]
    for v1_only in ("incident.type", "people.trapped_count", "flags.threat_to_life"):
        prefab.pop(v1_only)
    prefab["incident.types"] = ["1"]
    for rule in document["scoring_rules"]:
        paths = rule["config"].get("required_field_paths")
        if paths is not None:
            rule["config"]["required_field_paths"] = [
                "incident.types" if path == "incident.type" else path for path in paths
            ]
    assert validate_scenario_document(document, reference=FileReferenceCatalog().catalog()) == []
    return document


@pytest.fixture
async def v2_version_id(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], isolated_scenario_catalog: None
) -> ScenarioVersionId:
    from tests.api.test_session_variants import _import

    return await _import(unit_of_work, V2_SLUG, _v2_document())


@pytest.fixture
async def v2_interview(
    client: httpx.AsyncClient,
    container: Container,
    tokens: dict[str, str],
    users: dict[str, UserId],
    v2_version_id: ScenarioVersionId,
) -> OperatorFlow:
    """An `INTERVIEW`-state 112 stage of a `CALLER_VOICE` session on pack `v046_24-r1`."""
    created = await client.post(
        "/api/v1/sessions",
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(v2_version_id),
            "session_mode": "MULTI_TRAINEE",
            "participants": [
                participant(users["trainee1"], "OPERATOR_112"),
                participant(users["trainee2"], "DDS"),
            ],
            "variants": {"card_source": "CALLER_VOICE"},
        },
    )
    assert created.status_code == 201, created.text
    session_id = UUID(created.json()["id"])
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    flow = OperatorFlow(
        client=client,
        container=container,
        session_id=session_id,
        operator_token=tokens["trainee1"],
        dds_token=tokens["trainee2"],
        instructor_token=tokens["instructor1"],
        operator_user_id=users["trainee1"],
        dds_user_id=users["trainee2"],
    )
    assert await flow.advance_call_flow() is True
    answered = await flow.post("/operator/call/answer")
    assert answered.status_code == 200, answered.text
    await flow.append_asr(EventType.ASR_FINAL, "На улице горит мусор")
    assert await flow.advance_call_flow() is True
    return flow


async def test_a_v2_session_writes_v2_paths_and_renders_the_v2_schema(
    v2_interview: OperatorFlow,
) -> None:
    response = await v2_interview.set_field("incident.types", ["1"])
    assert response.status_code == 200, response.text
    card = response.json()["card"]
    assert card["card_schema"] == "v2"
    assert card["values"] == {"incident.types": ["1"]}
    specs = {spec["field_path"]: spec for spec in card["field_specs"]}
    assert "incident.type" not in specs
    types = specs["incident.types"]
    assert types["control"] == "CHIPS" and types["routing_relevant"] is True
    assert {"code": "1", "label_ru": "101", "classifier_features": None, "routing": None} in (
        types["options"]
    )
    assert specs["q.fire.where"]["visible_when"] == {
        "field_path": "incident.types",
        "op": "CONTAINS",
        "value": "1",
    }

    read = await v2_interview.get("/operator/card")
    assert read.status_code == 200, read.text
    assert read.json()["card_schema"] == "v2"


async def test_a_v1_only_path_is_unknown_under_v2(v2_interview: OperatorFlow) -> None:
    response = await v2_interview.set_field("incident.type", "FIRE")
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "CARD_FIELD_UNKNOWN"


@pytest.mark.parametrize(
    ("path", "value"),
    [("q.fire.where", ["на крыше"]), ("address.district", "Нигде"), ("incident.types", ["99"])],
)
async def test_a_value_outside_the_options_is_card_option_unknown(
    v2_interview: OperatorFlow, path: str, value: Any
) -> None:
    response = await v2_interview.set_field(path, value)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "CARD_OPTION_UNKNOWN"
    card = await v2_interview.get("/operator/card")
    assert path not in card.json()["values"]


async def test_a_hidden_field_is_accepted(v2_interview: OperatorFlow) -> None:
    """`q.fire.offence` is hidden until a street fire has a burning object — still accepted."""
    response = await v2_interview.set_field("q.fire.offence", ["offence"])
    assert response.status_code == 200, response.text
    assert response.json()["revision"]["field_path"] == "q.fire.offence"


async def test_a_description_over_1999_characters_is_refused(v2_interview: OperatorFlow) -> None:
    """I7 E55: «Описание со слов заявителя» takes at most 1999 characters (the «0 / 1999»
    counter, `max_length`); a longer value is `422 CARD_VALUE_TYPE_MISMATCH` and writes nothing."""
    accepted = await v2_interview.set_field("description.text", "ы" * 1999)
    assert accepted.status_code == 200, accepted.text
    refused = await v2_interview.set_field("description.text", "ы" * 2000)
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "CARD_VALUE_TYPE_MISMATCH"
    card = await v2_interview.get("/operator/card")
    assert card.json()["values"]["description.text"] == "ы" * 1999
    spec = next(
        item for item in card.json()["field_specs"] if item["field_path"] == "description.text"
    )
    assert spec["max_length"] == 1999


async def _example_version_id(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork], demo_version_id: ScenarioVersionId
) -> ScenarioVersionId:
    """The committed schema-2 example — imported together with the demo by `demo_version_id`."""
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(EXAMPLE_SLUG)
        assert stored is not None
        version = await uow.scenarios.find_version(stored.scenario_id, 1)
        assert version is not None
        await uow.commit()
    return version.scenario_version_id


async def test_the_generated_card_reaches_the_dds_in_the_v2_layout(
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

    item = await client.get(
        f"/api/v1/sessions/{session_id}/dds/work-item", headers=auth(tokens["trainee2"])
    )
    assert item.status_code == 200, item.text
    body = item.json()
    assert body["card_schema"] == "v2"
    assert body["card_values"]["q.fire.street_object"] == ["мусор"]
    assert body["card_values"]["address.district"] == "Щукино"
    # I3 E2b′ (HLD 70 §70.6.4): the prefab's recipients are the manual part; the snapshot holds
    # auto ∪ manual — image 19's bar plus the district and prefecture ДДС of the card's address.
    assert body["recipient_services"] == [
        "FIRE_RESCUE",
        "TSODD",
        "OATI",
        "DDS_DISTRICT_SHCHUKINO",
        "DDS_PREFECTURE_SZAO",
    ]
    specs = {spec["field_path"]: spec for spec in body["field_specs"]}
    assert specs["q.fire.street_object"]["label_ru"] == "Улица (пламя, дым)"
    # v2's `required_for_handoff` fields the generated card leaves empty
    assert body["missing_field_paths"] == ["address.locality"]

    snapshot = await client.get(
        f"/api/v1/sessions/{session_id}/snapshot", headers=auth(tokens["trainee2"])
    )
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["work_item"]["card_schema"] == "v2"

    async with unit_of_work() as uow:
        events = await uow.events.read(session_id)  # type: ignore[arg-type]
        await uow.commit()
    created_event = next(e for e in events if e.event_type is EventType.SESSION_CREATED)
    assert created_event.payload["reference_pack"]["card_schema"] == "v2"
    written = [e for e in events if e.event_type is EventType.CARD_FIELD_CHANGED]
    assert {e.payload["field_path"] for e in written} >= {"incident.types", "q.fire.access"}
    assert all(e.actor_type is ActorType.INSTRUCTOR for e in written)


async def test_get_card_schema_serves_v1_and_v2(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    for schema_id, count in (("v1", 38), ("v2", 61)):
        response = await client.get(
            f"/api/v1/reference/card-schema/{schema_id}", headers=auth(tokens["trainee1"])
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["schema_id"] == schema_id
        assert len(body["field_specs"]) == count
        assert len(body["sha256"]) == 64
    missing = await client.get("/api/v1/reference/card-schema/v9", headers=auth(tokens["trainee1"]))
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"

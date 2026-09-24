"""The reference pack over HTTP (I3 E2a; HLD `70-i3-alignment.md` §70.6.1-§70.6.3, D18).

* `getReferenceManifest` answers `reference/manifest.json` verbatim;
* `listReferenceServices` serves the «СЛУЖБЫ 112» catalog of a pack — hidden/deprecated entries
  only with `include_hidden`, `q` filters, an unknown pack is `404`;
* `searchClassifier` / `getClassifierRow` read the classifier of a pack that has one — tested
  against a fixture pack that names the real `v046_24` files, because the product's only pack,
  `legacy-r1`, has none (and answers `404`);
* every read needs a bearer token;
* `createSession` records `SESSION_CREATED.reference_pack` with the files' sha256;
* a scenario whose `reference_pack` the manifest lacks cannot start a session (`409
  REFERENCE_PACK_UNKNOWN`).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from app.api.container import Container
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.scenario.version import ScenarioVersion
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.reference.file_catalog import DEFAULT_REFERENCE_DIR, FileReferenceCatalog

from tests.api.conftest import auth, create_demo_session, participant
from tests.fixtures.scenarios import demo_document

pytestmark = pytest.mark.integration

MANIFEST = json.loads((DEFAULT_REFERENCE_DIR / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def classifier_pack(tmp_path: Path, container: Container) -> Container:
    """The container, reading a copy of `reference/` whose manifest adds a pack `test-r1` that
    names the real classifier files (the resolver fixture shape E2b uses)."""
    for name in MANIFEST["files"]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DEFAULT_REFERENCE_DIR / name, target)
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["packs"]["test-r1"] = {"card_schema": "v1", "services": "v1", "classifier": "v046_24"}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    container.reference = FileReferenceCatalog(tmp_path)
    return container


async def test_the_manifest_is_served_verbatim(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.get("/api/v1/reference/manifest", headers=auth(tokens["trainee1"]))
    assert response.status_code == 200, response.text
    assert response.json() == MANIFEST


async def test_every_reference_read_needs_a_token(client: httpx.AsyncClient) -> None:
    for path in (
        "/api/v1/reference/manifest",
        "/api/v1/reference/services",
        "/api/v1/reference/classifier",
        "/api/v1/reference/classifier/1010101",
    ):
        response = await client.get(path)
        assert response.status_code == 401, path


async def test_the_service_catalog_of_the_default_pack(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    headers = auth(tokens["instructor1"])
    visible = (await client.get("/api/v1/reference/services", headers=headers)).json()
    everything = (
        await client.get("/api/v1/reference/services?include_hidden=true", headers=headers)
    ).json()
    visible_ids = [entry["id"] for entry in visible]
    all_ids = [entry["id"] for entry in everything]

    assert all_ids[:6] == [
        "FIRE_RESCUE",
        "POLICE",
        "AMBULANCE",
        "GAS_SERVICE",
        "UTILITY_EMERGENCY",
        "EDDS",
    ]
    assert "UTILITY_EMERGENCY" not in visible_ids  # deprecated (C8)
    # deprecated (C8) + the classifier-only orgs, hidden (`display: false`, I3 E3a, REQ-5280)
    hidden = {entry["id"] for entry in everything if not entry["display"]}
    assert len(hidden) == 18
    assert set(all_ids) - set(visible_ids) == {"UTILITY_EMERGENCY"} | hidden
    fire = everything[0]
    assert fire["name_ru"] == "Пожарно-спасательная служба"
    assert fire["code"] == "101"
    assert set(fire) == {
        "id",
        "name_ru",
        "full_name_ru",
        "kind",
        "code",
        "okrug",
        "district",
        "classifier_org_id",
        "classifier_org_ids",
        "status_policy",
        "display",
        "deprecated",
        "phone",
    }

    found = await client.get("/api/v1/reference/services?q=мосводоканал", headers=headers)
    assert [entry["id"] for entry in found.json()] == ["MOSVODOKANAL"]
    explicit = await client.get("/api/v1/reference/services?pack=legacy-r1", headers=headers)
    assert [entry["id"] for entry in explicit.json()] == visible_ids


async def test_an_unknown_pack_is_404(client: httpx.AsyncClient, tokens: dict[str, str]) -> None:
    response = await client.get(
        "/api/v1/reference/services?pack=no-such-pack", headers=auth(tokens["trainee1"])
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_the_legacy_pack_has_no_classifier(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    headers = auth(tokens["instructor1"])
    for path in ("/api/v1/reference/classifier", "/api/v1/reference/classifier/1010101"):
        response = await client.get(f"{path}?pack=legacy-r1", headers=headers)
        assert response.status_code == 404, path
        assert response.json()["code"] == "NOT_FOUND"
        # The default pack is the manifest's newest, `v046_24-r1` since I3 E3a — it has one.
        assert (await client.get(path, headers=headers)).status_code == 200, path


async def test_classifier_search_and_row_on_a_pack_that_has_one(
    classifier_pack: Container, client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    headers = auth(tokens["instructor1"])
    everything = await client.get(
        "/api/v1/reference/classifier?pack=test-r1&limit=200", headers=headers
    )
    assert everything.status_code == 200, everything.text
    assert everything.json()["total"] == 1283  # REQ-5707
    assert len(everything.json()["items"]) == 200

    page = await client.get(
        "/api/v1/reference/classifier?pack=test-r1&q=мусор&limit=2&offset=1", headers=headers
    )
    body = page.json()
    assert body["total"] > 2
    assert len(body["items"]) == 2
    assert all("routing" not in item for item in body["items"])
    assert set(body["items"][0]) == {
        "code",
        "group_no",
        "group_ru",
        "features",
        "final_type_ru",
        "main_service",
    }

    row = await client.get("/api/v1/reference/classifier/1010101?pack=test-r1", headers=headers)
    assert row.status_code == 200, row.text
    data = row.json()
    assert data["final_type_ru"] == "пожар: мусор"
    assert data["group_ru"] == "Пожары и задымления"
    assert data["routing"]["MCHS_SLUZHBA_101"][0] == {
        "when": {"no_access": False},
        "value": "пожар: мусор",
    }

    missing = await client.get("/api/v1/reference/classifier/42?pack=test-r1", headers=headers)
    assert missing.status_code == 404


async def test_session_created_records_the_reference_pack(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    created = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee1"], "OPERATOR_112"), participant(users["trainee2"], "DDS")],
    )
    async with unit_of_work() as uow:
        events = await uow.events.read(SessionId(UUID(created["id"])))
        await uow.commit()
    assert events[0].event_type.value == "SESSION_CREATED"
    assert events[0].payload["reference_pack"] == {
        "pack_id": "legacy-r1",
        "card_schema": "v1",
        "card_schema_sha256": MANIFEST["files"]["card-schema/v1.yaml"],
        "classifier": None,
        "classifier_sha256": None,
        "services": "v1",
        "services_sha256": MANIFEST["files"]["services/v1.yaml"],
    }


async def test_a_version_naming_an_unknown_pack_cannot_start_a_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    isolated_scenario_catalog: None,
) -> None:
    """The version is stored directly (import would refuse it: R38); session creation then has
    no pack to record and answers `409 REFERENCE_PACK_UNKNOWN`. `isolated_scenario_catalog`
    removes the extra scenario afterwards, so `listScenarios` tests keep seeing only the demo."""
    from tests.api.test_session_variants import _import

    document = demo_document()
    document["schema_version"] = 2
    document["reference_pack"] = "gone-r1"
    document["id"] = "7f0b8a52-5c1e-4c55-9d7e-2a61c3c0e2a1"
    document["scenario_id"] = "0c2d8a3e-6a6f-4f7e-8d42-8b8a9f3e2b10"
    ScenarioVersion.model_validate(document)
    version_id = await _import(unit_of_work, "reference-pack-gone", document)

    response = await client.post(
        "/api/v1/sessions",
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(version_id),
            "session_mode": "MULTI_TRAINEE",
            "participants": [
                participant(users["trainee1"], "OPERATOR_112"),
                participant(users["trainee2"], "DDS"),
            ],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "REFERENCE_PACK_UNKNOWN"

"""Every ticket scenario, imported and run under GENERATED_CARD + MEMO_STATUSES through the handoff
(I3 E8; HLD 70 §70.2, §70.4, §70.6.4; HLD 30 §30.13).

`scenarios/tickets` is imported through the real `ImportScenarios` (validation included). Then,
for each of the 96 base scenarios, the instructor creates and starts a `SINGLE_ROLE` session with
one ДДС trainee and **no variant request**: the scenario's defaults resolve `card_source:
GENERATED_CARD` and `dds_mode: MEMO_STATUSES`, the prefab card is materialised at start, the final
`RECIPIENTS_RESOLVED` names the resolver's automatic services, one leg per notified service
(auto ∪ manual) arrives `ADDED`, and the trainee takes the main service's primary decision
(«Принята»). Nothing is patched; the real API, database and reference pack are used.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.application.scenarios.import_scenarios import ImportScenarios
from app.domain.common.ids import UserId
from app.domain.routing.resolve import notification_list, pack_routing
from app.infrastructure.reference.file_catalog import FileReferenceCatalog
from app.infrastructure.scenarios.yaml_loader import load_scenario_version
from app.tools.import_scenarios import YamlScenarioSource

from tests.api.conftest import REPO_ROOT, auth, participant

pytestmark = pytest.mark.integration

API = "/api/v1/sessions"
TICKETS_DIR = REPO_ROOT / "scenarios" / "tickets"
BASE_SLUG = re.compile(r"^ticket-\d{2}-call-\d$")
ROUTING = pack_routing(FileReferenceCatalog().catalog(), "v046_24-r1")


async def _run_one(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    version_id: UUID,
    slug: str,
) -> None:
    version = load_scenario_version(TICKETS_DIR / slug / "v1.yaml")
    prefab = version.expected_response.prefab_handoff
    assert prefab is not None
    resolution = ROUTING.resolve(prefab.card_values)
    expected_legs = set(notification_list(resolution.auto_services, prefab.recipient_services))
    main = version.expected_response.required_services[0]

    created = await client.post(
        API,
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(version_id),
            "session_mode": "SINGLE_ROLE",
            "participants": [participant(users["trainee2"], "DDS")],
        },
    )
    assert created.status_code == 201, f"{slug}: {created.text}"
    detail = created.json()
    assert detail["variants"]["card_source"] == "GENERATED_CARD", slug
    assert detail["variants"]["dds_mode"] == "MEMO_STATUSES", slug
    # D28 (owner 2026-09-25): no override ⇒ the ДДС phone.
    assert detail["variants"]["dds_brigade_call"] == "ON", slug
    session_id = detail["id"]
    started = await client.post(f"{API}/{session_id}/start", headers=auth(tokens["instructor1"]))
    assert started.status_code == 200, f"{slug}: {started.text}"

    log = await client.get(
        f"{API}/{session_id}/events", headers=auth(tokens["instructor1"]), params={"limit": 1000}
    )
    assert log.status_code == 200, log.text
    items: list[dict[str, Any]] = log.json()["items"]
    resolved = [i["payload"] for i in items if i["event_type"] == "RECIPIENTS_RESOLVED"]
    assert resolved and resolved[-1]["final"] is True, slug
    assert resolved[-1]["auto_services"] == list(resolution.auto_services), slug
    received = {
        i["payload"]["service_type"] for i in items if i["event_type"] == "HANDOFF_RECEIVED"
    }
    assert received == expected_legs, slug

    legs_response = await client.get(
        f"{API}/{session_id}/dds/legs", headers=auth(tokens["trainee2"])
    )
    assert legs_response.status_code == 200, legs_response.text
    legs = {leg["service_type"]: leg for leg in legs_response.json()}
    assert set(legs) == expected_legs, slug
    assert {leg["response_status"] for leg in legs.values()} == {"ADDED"}, slug
    accepted = await client.post(
        f"{API}/{session_id}/dds/legs/{legs[main]['assignment_id']}/status",
        headers=auth(tokens["trainee2"]),
        json={"status": "ACCEPTED"},
    )
    assert accepted.status_code == 200, f"{slug}: {accepted.text}"
    assert accepted.json()["response_status"] == "ACCEPTED", slug


async def test_every_ticket_scenario_runs_generated_card_memo_through_the_handoff(
    isolated_scenario_catalog: None,
    unit_of_work: Any,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
) -> None:
    report = await ImportScenarios(unit_of_work, YamlScenarioSource())(TICKETS_DIR)
    assert report.files == report.versions_created >= 96

    slugs = sorted(path.name for path in TICKETS_DIR.iterdir() if BASE_SLUG.match(path.name))
    assert len(slugs) == 96
    version_ids: dict[str, UUID] = {}
    async with unit_of_work() as uow:
        for slug in slugs:
            stored = await uow.scenarios.find_scenario_by_slug(slug)
            assert stored is not None, slug
            row = await uow.scenarios.find_version(stored.scenario_id, 1)
            assert row is not None, slug
            version_ids[slug] = UUID(str(row.scenario_version_id))
        await uow.commit()

    for slug in slugs:
        await _run_one(client, tokens, users, version_ids[slug], slug)

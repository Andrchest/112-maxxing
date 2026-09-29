"""«в службу 03 передаются только первые 100 символов» over HTTP (I7 E55, card instruction ¶257).

The committed memo example `street-rubbish-fire` with `AMBULANCE` added to its prefab's recipients
and a description longer than 100 characters. A ДДС trainee bound to the 03 service reads the
first 100 characters of «Описание со слов заявителя» — on `getDdsWorkItem` and on the restore
snapshot alike; the instructor, and a ДДС trainee bound to another service, read it whole. The
handoff snapshot itself (and its hash) is untouched.
"""

from __future__ import annotations

import copy
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import yaml
from app.application.scenarios.import_scenarios import canonical_content, content_digest
from app.domain.common.ids import ScenarioId, ScenarioVersionId, UserId
from app.domain.scenario.version import ScenarioVersion

from tests.api.conftest import auth
from tests.api.dds.test_memo_mode import API, EXAMPLE_PATH, start_session

pytestmark = pytest.mark.integration

LONG_DESCRIPTION = (
    "Горит мусор на контейнерной площадке, подъехать нельзя — площадку заставили машины. "
    "Рядом стоит мужчина, у него ожог руки, просит скорую."
)


@pytest.fixture
async def long_description_version_id(unit_of_work: Any) -> ScenarioVersionId:
    """The example with a 103 leg and a description longer than 100 characters."""
    slug = "street-rubbish-fire-long-description-103"
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug(slug)
        row = await uow.scenarios.find_version(stored.scenario_id, 1) if stored else None
        await uow.commit()
    if row is not None:
        return ScenarioVersionId(row.scenario_version_id)
    document: dict[str, Any] = copy.deepcopy(yaml.safe_load(EXAMPLE_PATH.read_text("utf-8")))
    document["id"] = str(uuid4())
    document["scenario_id"] = str(uuid4())
    prefab = document["expected_response"]["prefab_handoff"]
    prefab["recipient_services"].append("AMBULANCE")
    prefab["card_values"]["description.text"] = LONG_DESCRIPTION
    version = ScenarioVersion(**document)
    content = canonical_content(version)
    async with unit_of_work() as uow:
        await uow.scenarios.add_scenario(
            ScenarioId(UUID(document["scenario_id"])), slug, version.title
        )
        await uow.scenarios.add_version(version, content, content_digest(content))
        await uow.scenarios.add_scoring_rules(version.id, version.scoring_rules)
        await uow.commit()
    return version.id


async def _description(client: httpx.AsyncClient, token: str, session_id: UUID) -> tuple[str, str]:
    """The description on `getDdsWorkItem` and on `getSessionSnapshot.work_item`."""
    item = await client.get(f"{API}/{session_id}/dds/work-item", headers=auth(token))
    assert item.status_code == 200, item.text
    snapshot = await client.get(f"{API}/{session_id}/snapshot", headers=auth(token))
    assert snapshot.status_code == 200, snapshot.text
    return (
        item.json()["card_values"]["description.text"],
        snapshot.json()["work_item"]["card_values"]["description.text"],
    )


async def test_the_03_service_reads_the_first_100_characters(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    long_description_version_id: ScenarioVersionId,
) -> None:
    assert len(LONG_DESCRIPTION) > 100
    session_id = await start_session(
        client, tokens, users, long_description_version_id, assigned_service_id="AMBULANCE"
    )
    assert await _description(client, tokens["trainee2"], session_id) == (
        LONG_DESCRIPTION[:100],
        LONG_DESCRIPTION[:100],
    )
    # The instructor reads the whole card.
    item = await client.get(
        f"{API}/{session_id}/dds/work-item", headers=auth(tokens["instructor1"])
    )
    assert item.status_code == 200, item.text
    assert item.json()["card_values"]["description.text"] == LONG_DESCRIPTION


async def test_another_service_reads_the_whole_description(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    long_description_version_id: ScenarioVersionId,
) -> None:
    session_id = await start_session(
        client, tokens, users, long_description_version_id, assigned_service_id="FIRE_RESCUE"
    )
    assert await _description(client, tokens["trainee2"], session_id) == (
        LONG_DESCRIPTION,
        LONG_DESCRIPTION,
    )

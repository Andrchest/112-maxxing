"""«было → стало» on the scenario rows (I7 E43, Q-E15-3): `importScenarioVersion` reports a new
scenario and version (an idempotent re-import reports nothing); `archiveScenario` /
`unarchiveScenario` report the flag.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api._audit_changes import audit_ids, changes_by_field, new_row
from tests.api.conftest import auth
from tests.fixtures.scenarios import demo_document

pytestmark = pytest.mark.integration


async def _import(client: httpx.AsyncClient, token: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/api/v1/scenarios/import", headers=auth(token), json=body)
    assert response.status_code == 201, response.text
    imported: dict[str, Any] = response.json()
    return imported


async def test_import_then_archive_and_unarchive_record_their_changes(
    client: httpx.AsyncClient, tokens: dict[str, str], migrated_engine: AsyncEngine
) -> None:
    document = demo_document()
    document["id"] = str(uuid4())
    document["scenario_id"] = str(uuid4())
    slug = f"e43-{uuid4().hex[:8]}"
    body = {
        "format": "JSON",
        "content": json.dumps(document, ensure_ascii=False),
        "source_path": f"x/{slug}/v1.yaml",
    }
    token = tokens["instructor1"]

    before = await audit_ids(migrated_engine)
    await _import(client, token, body)
    changes = changes_by_field(await new_row(migrated_engine, before, "importScenarioVersion"))
    digest = changes.pop("scenario_version.content_sha256")
    assert digest[0] is None and len(digest[1]) == 64
    assert changes == {
        "scenario.slug": (None, slug),
        "scenario_version.title": (None, document["title"]),
        "scenario_version.version": (None, document["version"]),
    }

    before = await audit_ids(migrated_engine)
    await _import(client, token, body)
    again = await new_row(migrated_engine, before, "importScenarioVersion")
    assert again["changes"] is None, "an idempotent re-import changes nothing"

    url = f"/api/v1/scenarios/{document['scenario_id']}"
    before = await audit_ids(migrated_engine)
    archived = await client.post(f"{url}/archive", headers=auth(token))
    assert archived.status_code == 200, archived.text
    assert changes_by_field(await new_row(migrated_engine, before, "archiveScenario")) == {
        "scenario.archived": (False, True)
    }

    before = await audit_ids(migrated_engine)
    unarchived = await client.post(f"{url}/unarchive", headers=auth(token))
    assert unarchived.status_code == 200, unarchived.text
    assert changes_by_field(await new_row(migrated_engine, before, "unarchiveScenario")) == {
        "scenario.archived": (True, False)
    }

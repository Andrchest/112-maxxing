"""`getScenarioVersionDocument` — «Скачать» a scenario version (I7 E53, G14a; ТЗ ¶222, ¶229).

* YAML (the default) and JSON both parse back to the stored document, and uploading the file
  unchanged is the idempotent re-import (same version id);
* the edit path the ТЗ asks for: download → change `version` → upload → the next version;
* instructor-only (the document carries `world_truth`, D3), `404` for an unknown version;
* the download is audited under its own operationId (E25's middleware).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
import pytest
import yaml
from app.domain.common.ids import ScenarioVersionId
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth

pytestmark = pytest.mark.integration


def _url(version_id: ScenarioVersionId, format: str | None = None) -> str:
    query = "" if format is None else f"?format={format}"
    return f"/api/v1/scenarios/versions/{version_id}/document{query}"


async def _import(
    client: httpx.AsyncClient, token: str, document_format: str, content: str
) -> httpx.Response:
    return await client.post(
        "/api/v1/scenarios/import",
        headers=auth(token),
        json={"format": document_format, "content": content},
    )


async def test_yaml_is_the_default_and_re_imports_as_the_same_version(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    isolated_scenario_catalog: None,
    demo_version_id: ScenarioVersionId,
) -> None:
    response = await client.get(_url(demo_version_id), headers=auth(tokens["instructor1"]))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/yaml")
    assert 'filename="apartment-fire-v1.yaml"' in response.headers["content-disposition"]
    document: dict[str, Any] = yaml.safe_load(response.text)
    assert document["id"] == str(demo_version_id)
    assert document["version"] == 1
    assert "world_truth" in document
    # Cyrillic stays readable in the file (no `\u` escapes).
    assert "\\u04" not in response.text

    again = await _import(client, tokens["instructor1"], "YAML", response.text)
    assert again.status_code == 201, again.text
    assert again.json()["id"] == str(demo_version_id)


async def test_json_download_re_imports_as_the_same_version(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    isolated_scenario_catalog: None,
    demo_version_id: ScenarioVersionId,
) -> None:
    response = await client.get(_url(demo_version_id, "json"), headers=auth(tokens["instructor1"]))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert 'filename="apartment-fire-v1.json"' in response.headers["content-disposition"]
    assert json.loads(response.text)["version"] == 1

    again = await _import(client, tokens["instructor1"], "JSON", response.text)
    assert again.status_code == 201, again.text
    assert again.json()["id"] == str(demo_version_id)


async def test_download_edit_upload_makes_the_next_version(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    isolated_scenario_catalog: None,
    demo_version_id: ScenarioVersionId,
) -> None:
    """ТЗ ¶222 «редактировать»: versions are immutable (D4), so an edit is the next version."""
    response = await client.get(_url(demo_version_id), headers=auth(tokens["instructor1"]))
    document = yaml.safe_load(response.text)
    document["id"] = "7d1c1f4e-53e5-4c53-9b53-000000000053"
    document["version"] = 2
    document["difficulty"] = 4

    imported = await _import(
        client, tokens["instructor1"], "YAML", yaml.safe_dump(document, allow_unicode=True)
    )

    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert body["version"] == 2
    assert body["difficulty"] == 4
    assert body["scenario_id"] == document["scenario_id"]


async def test_a_trainee_may_not_download(
    client: httpx.AsyncClient, tokens: dict[str, str], demo_version_id: ScenarioVersionId
) -> None:
    response = await client.get(_url(demo_version_id), headers=auth(tokens["trainee1"]))

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_an_unknown_version_is_404(client: httpx.AsyncClient, tokens: dict[str, str]) -> None:
    response = await client.get(
        _url(ScenarioVersionId(UUID("00000000-0000-4000-8000-000000000053"))),
        headers=auth(tokens["instructor1"]),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_the_download_is_audited(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    migrated_engine: AsyncEngine,
    demo_version_id: ScenarioVersionId,
) -> None:
    query = text(
        "SELECT count(*) FROM audit_log WHERE operation_id = 'getScenarioVersionDocument'"
        " AND status = 200 AND target_ids ->> 'scenario_version_id' = :version_id"
    )

    async def count() -> int:
        async with migrated_engine.connect() as connection:
            result = await connection.execute(query, {"version_id": str(demo_version_id)})
            return int(result.scalar_one())

    before = await count()
    response = await client.get(_url(demo_version_id), headers=auth(tokens["instructor1"]))
    assert response.status_code == 200

    assert await count() == before + 1

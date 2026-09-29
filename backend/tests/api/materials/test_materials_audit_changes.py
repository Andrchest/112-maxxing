"""«было → стало» on the materials rows (I7 E43, Q-E15-3): `uploadMaterial` reports the new
material's metadata, `archiveMaterial` the flag (once — a repeat changes nothing).
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api._audit_changes import audit_ids, changes_by_field, new_row
from tests.api.conftest import auth
from tests.api.materials.test_materials import (  # noqa: F401 - fixtures, used by name
    _api_settings_base,
    _upload,
    api_settings,
)

pytestmark = pytest.mark.integration


async def test_upload_and_archive_record_their_changes(
    client: httpx.AsyncClient, tokens: dict[str, str], migrated_engine: AsyncEngine
) -> None:
    instructor = auth(tokens["instructor1"])
    content = b"%PDF-1.4 e43 audit body"

    before = await audit_ids(migrated_engine)
    uploaded = await _upload(client, instructor, title_ru="Памятка E43", content=content)
    assert uploaded.status_code == 201, uploaded.text
    assert changes_by_field(await new_row(migrated_engine, before, "uploadMaterial")) == {
        "material.title_ru": (None, "Памятка E43"),
        "material.file_name": (None, "manual.pdf"),
        "material.content_type": (None, "application/pdf"),
        "material.size_bytes": (None, len(content)),
    }

    url = f"/api/v1/materials/{uploaded.json()['material_id']}/archive"
    before = await audit_ids(migrated_engine)
    assert (await client.post(url, headers=instructor)).status_code == 200
    assert changes_by_field(await new_row(migrated_engine, before, "archiveMaterial")) == {
        "material.archived": (False, True)
    }

    before = await audit_ids(migrated_engine)
    assert (await client.post(url, headers=instructor)).status_code == 200
    assert (await new_row(migrated_engine, before, "archiveMaterial"))["changes"] is None

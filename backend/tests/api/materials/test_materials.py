"""`materials` over HTTP (I4 E34, HLD 71 §71.11).

`api_settings` is overridden (same reasoning as `tests.api.admin.test_purge_recordings`) so
`data_dir` lives under this test's own `tmp_path` — a real file is written here and must never
touch the repository's own `data/` directory.

Acceptance (`docs/hld/90-tbd-epics.md` "### E34"):
* the role gates — `test_upload_and_archive_are_instructor_or_admin_only`,
  `test_every_authenticated_role_may_list_and_download`;
* the allow-list refusal — `test_upload_refuses_a_disallowed_extension`;
* the sha dedupe: the same bytes are stored once —
  `test_identical_bytes_are_stored_once_on_disk`;
* the download content type — `test_get_material_file_content_type_and_disposition`.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from app.api.container import Container
from app.config.settings import Settings

from tests.api import conftest as _api_fixtures
from tests.api.conftest import auth

#: The unmodified fixture, bound under a private name (same pattern as `test_purge_recordings.py`).
_api_settings_base = _api_fixtures.api_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def api_settings(_api_settings_base: Settings, tmp_path: Path) -> Settings:
    """`_api_settings_base` with `data_dir` under this test's own `tmp_path`."""
    return _api_settings_base.model_copy(update={"data_dir": str(tmp_path / "data")})


async def _upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    title_ru: str = "Инструкция",
    file_name: str = "manual.pdf",
    content: bytes = b"%PDF-1.4 fake pdf body",
    content_type: str = "application/pdf",
) -> httpx.Response:
    return await client.post(
        "/api/v1/materials",
        headers=headers,
        data={"title_ru": title_ru},
        files={"file": (file_name, content, content_type)},
    )


async def test_upload_and_archive_are_instructor_or_admin_only(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    trainee = auth(tokens["trainee1"])
    refused = await _upload(client, trainee)
    assert refused.status_code == 403 and refused.json()["code"] == "FORBIDDEN_FOR_ROLE"

    created = await _upload(client, auth(tokens["instructor1"]))
    assert created.status_code == 201, created.text
    material_id = created.json()["material_id"]

    archive_refused = await client.post(f"/api/v1/materials/{material_id}/archive", headers=trainee)
    assert archive_refused.status_code == 403

    archived_by_admin = await client.post(
        f"/api/v1/materials/{material_id}/archive", headers=auth(tokens["admin1"])
    )
    assert archived_by_admin.status_code == 200
    assert archived_by_admin.json()["archived_at"] is not None


async def test_every_authenticated_role_may_list_and_download(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    created = await _upload(client, auth(tokens["instructor1"]), title_ru="Памятка")
    assert created.status_code == 201, created.text
    material_id = created.json()["material_id"]

    for username in ("trainee1", "trainee2", "instructor1", "admin1"):
        listed = await client.get("/api/v1/materials", headers=auth(tokens[username]))
        assert listed.status_code == 200, (username, listed.text)
        assert "total" not in listed.json()
        assert material_id in [item["material_id"] for item in listed.json()["items"]]

        downloaded = await client.get(
            f"/api/v1/materials/{material_id}/file", headers=auth(tokens[username])
        )
        assert downloaded.status_code == 200, (username, downloaded.text)
        assert downloaded.content == b"%PDF-1.4 fake pdf body"

    unauthenticated = await client.get("/api/v1/materials")
    assert unauthenticated.status_code == 401


async def test_upload_refuses_a_disallowed_extension(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    refused = await _upload(
        client,
        auth(tokens["instructor1"]),
        file_name="virus.exe",
        content=b"not a real document",
        content_type="application/octet-stream",
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "MATERIAL_TYPE_NOT_ALLOWED"


async def test_upload_refuses_a_body_over_the_configured_limit(
    client: httpx.AsyncClient, tokens: dict[str, str], container: Container
) -> None:
    container.settings.material_max_mb = 0  # any non-empty body now exceeds the limit
    try:
        refused = await _upload(client, auth(tokens["instructor1"]), content=b"x")
    finally:
        container.settings.material_max_mb = 20
    assert refused.status_code == 422
    assert refused.json()["code"] == "MATERIAL_TOO_LARGE"


async def test_identical_bytes_are_stored_once_on_disk(
    client: httpx.AsyncClient, tokens: dict[str, str], api_settings: Settings
) -> None:
    instructor = auth(tokens["instructor1"])
    content = b"%PDF-1.4 the same bytes twice"
    first = await _upload(client, instructor, title_ru="Копия 1", content=content)
    second = await _upload(client, instructor, title_ru="Копия 2", content=content)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["material_id"] != second.json()["material_id"]
    assert first.json()["sha256"] == second.json()["sha256"]

    materials_dir = Path(api_settings.data_dir) / "materials"
    stored_files = list(materials_dir.iterdir())
    assert stored_files == [materials_dir / first.json()["sha256"]]

    listed = await client.get("/api/v1/materials", headers=instructor)
    ids = [item["material_id"] for item in listed.json()["items"]]
    assert first.json()["material_id"] in ids
    assert second.json()["material_id"] in ids


async def test_get_material_file_content_type_and_disposition(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    instructor = auth(tokens["instructor1"])
    pdf = await _upload(
        client,
        instructor,
        file_name="памятка.pdf",
        content=b"%PDF-1.4 x",
        content_type="application/pdf",
    )
    docx = await _upload(
        client,
        instructor,
        file_name="report.docx",
        content=b"docx bytes",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert pdf.status_code == 201 and docx.status_code == 201

    pdf_file = await client.get(
        f"/api/v1/materials/{pdf.json()['material_id']}/file", headers=instructor
    )
    assert pdf_file.headers["content-type"] == "application/pdf"
    assert pdf_file.headers["content-disposition"].startswith("inline")

    docx_file = await client.get(
        f"/api/v1/materials/{docx.json()['material_id']}/file", headers=instructor
    )
    assert docx_file.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert docx_file.headers["content-disposition"].startswith("attachment")


async def test_archive_is_idempotent_and_hides_the_file_from_a_trainee(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    instructor = auth(tokens["instructor1"])
    trainee = auth(tokens["trainee1"])
    created = await _upload(client, instructor, title_ru="Скрыть после архивации")
    material_id = created.json()["material_id"]

    visible = await client.get(f"/api/v1/materials/{material_id}/file", headers=trainee)
    assert visible.status_code == 200

    first_archive = await client.post(
        f"/api/v1/materials/{material_id}/archive", headers=instructor
    )
    second_archive = await client.post(
        f"/api/v1/materials/{material_id}/archive", headers=instructor
    )
    assert first_archive.status_code == 200 and second_archive.status_code == 200
    assert first_archive.json()["archived_at"] == second_archive.json()["archived_at"]

    hidden_from_list = await client.get("/api/v1/materials", headers=trainee)
    assert material_id not in [item["material_id"] for item in hidden_from_list.json()["items"]]

    hidden_from_download = await client.get(
        f"/api/v1/materials/{material_id}/file", headers=trainee
    )
    assert hidden_from_download.status_code == 404

    still_visible_to_instructor = await client.get(
        "/api/v1/materials?include_archived=true", headers=instructor
    )
    assert material_id in [
        item["material_id"] for item in still_visible_to_instructor.json()["items"]
    ]
    still_downloadable_by_instructor = await client.get(
        f"/api/v1/materials/{material_id}/file", headers=instructor
    )
    assert still_downloadable_by_instructor.status_code == 200


async def test_archive_unknown_material_is_404(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.post(
        f"/api/v1/materials/{uuid4()}/archive", headers=auth(tokens["instructor1"])
    )
    assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"

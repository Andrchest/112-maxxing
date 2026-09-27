"""`app.tools.seed_materials` against real PostgreSQL (I5 E41 CHANGE B).

The seed run twice against a scratch database yields each material once (the brief's own
acceptance check) — `UploadMaterial`'s own sha256 dedupe only prevents writing the *file* twice,
not a second `training_materials` row, so `seed_materials` must do its own idempotency check
before calling it. `conftest.py`'s autouse `clean_database` truncates `users` (and, by `CASCADE`,
`training_materials`) before and after every test in this package, so no manual cleanup is needed
here.
"""

from __future__ import annotations

from hashlib import sha256 as sha256_of
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from app.application.ports.user_repository import UserRole
from app.config.settings import Settings
from app.tools.seed_materials import (
    UPLOADER_USERNAME,
    OrganizerMaterial,
    UploaderNotFoundError,
    seed_materials,
)
from app.tools.seed_users import SeedAccount, seed_users
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def _material_rows(engine: AsyncEngine) -> list[sa.Row[tuple[object, ...]]]:
    async with engine.connect() as connection:
        result = await connection.execute(
            sa.text(
                "SELECT title_ru, sha256, uploaded_by FROM training_materials ORDER BY title_ru"
            )
        )
        return result.all()


async def _user_id(engine: AsyncEngine, username: str) -> UUID:
    async with engine.connect() as connection:
        result = await connection.execute(
            sa.text("SELECT id FROM users WHERE username = :u"), {"u": username}
        )
        return UUID(str(result.scalar_one()))


def _organizer_materials(tmp_path: Path) -> list[OrganizerMaterial]:
    one = tmp_path / "one.pdf"
    one.write_bytes(b"organizer material one")
    two = tmp_path / "two.pdf"
    two.write_bytes(b"organizer material two")
    return [
        OrganizerMaterial(
            id="one",
            title_ru="Один",
            path="one.pdf",
            sha256=sha256_of(one.read_bytes()).hexdigest(),
        ),
        OrganizerMaterial(
            id="two",
            title_ru="Два",
            path="two.pdf",
            sha256=sha256_of(two.read_bytes()).hexdigest(),
        ),
    ]


async def test_a_second_seed_run_yields_each_material_once_and_uploads_as_admin(
    migrated_engine: AsyncEngine,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    username = UPLOADER_USERNAME
    admin_account = SeedAccount(
        username=username,
        display_name_ru="Администратор",
        user_role=UserRole.ADMIN,
        password_env="SIM_SEED_MATERIALS_TEST_ADMIN_PASSWORD",
    )
    monkeypatch.setenv(admin_account.password_env, "test-password")
    settings = test_settings.model_copy(
        update={
            "database_url": migrated_engine.url.render_as_string(hide_password=False),
            "data_dir": str(tmp_path / "data"),
        }
    )
    await seed_users(settings, accounts=(admin_account,))
    admin_id = await _user_id(migrated_engine, username)

    materials = _organizer_materials(tmp_path)

    first = await seed_materials(settings, materials, repo_root=tmp_path)
    assert sorted(first) == [("one", "uploaded"), ("two", "uploaded")]
    rows_after_first = await _material_rows(migrated_engine)
    assert {row.title_ru for row in rows_after_first} == {"Один", "Два"}
    assert {UUID(str(row.uploaded_by)) for row in rows_after_first} == {admin_id}

    second = await seed_materials(settings, materials, repo_root=tmp_path)
    assert sorted(second) == [("one", "already present"), ("two", "already present")]
    rows_after_second = await _material_rows(migrated_engine)
    assert len(rows_after_second) == 2, "each material must appear exactly once"


async def test_a_missing_admin_account_refuses_the_run(
    migrated_engine: AsyncEngine, test_settings: Settings, tmp_path: Path
) -> None:
    settings = test_settings.model_copy(
        update={
            "database_url": migrated_engine.url.render_as_string(hide_password=False),
            "data_dir": str(tmp_path / "data"),
        }
    )
    with pytest.raises(UploaderNotFoundError):
        await seed_materials(settings, _organizer_materials(tmp_path), repo_root=tmp_path)

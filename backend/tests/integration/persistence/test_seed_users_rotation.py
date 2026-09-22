"""Re-running `seed_users` rotates an existing account's password and keeps its id (E20).

The E20-G re-walk reported a re-seed leaving the old hash in place; the upsert does rewrite
`password_hash` on conflict, and this test pins that against real PostgreSQL.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.application.ports.user_repository import UserRole
from app.config.settings import Settings
from app.infrastructure.auth.argon2_hasher import Argon2PasswordHasher
from app.tools.seed_users import SeedAccount, seed_users
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def _row(engine: AsyncEngine, username: str) -> sa.Row[tuple[object, ...]]:
    async with engine.connect() as connection:
        result = await connection.execute(
            sa.text("SELECT id, password_hash FROM users WHERE username = :u"), {"u": username}
        )
        return result.one()


async def test_a_second_seed_rotates_the_password_and_keeps_the_id(
    migrated_engine: AsyncEngine, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    username = f"seed-rotation-{uuid4().hex[:8]}"
    account = SeedAccount(
        username=username,
        display_name_ru="Проверка",
        user_role=UserRole.TRAINEE,
        password_env="SIM_SEED_ROTATION_TEST_PASSWORD",
    )
    settings = test_settings.model_copy(
        update={"database_url": migrated_engine.url.render_as_string(hide_password=False)}
    )
    hasher = Argon2PasswordHasher()
    try:
        monkeypatch.setenv(account.password_env, "first-password")
        await seed_users(settings, accounts=(account,))
        first_id, first_hash = await _row(migrated_engine, username)
        assert hasher.verify(str(first_hash), "first-password")

        monkeypatch.setenv(account.password_env, "second-password")
        await seed_users(settings, accounts=(account,))
        second_id, second_hash = await _row(migrated_engine, username)

        assert second_id == first_id
        assert hasher.verify(str(second_hash), "second-password")
        assert not hasher.verify(str(second_hash), "first-password")
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                sa.text("DELETE FROM users WHERE username = :u"), {"u": username}
            )

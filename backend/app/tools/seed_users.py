"""`python -m app.tools.seed_users` — the three local accounts a demo box needs (D8, SPEC §41).

One `TRAINEE`, one `INSTRUCTOR`, one `ADMIN`, upserted by username, so re-running it rotates the
passwords without changing an account's `id` and therefore without orphaning any session that
references it.

**No password is ever a literal in this source file.** Each one is read from the environment —
`SIM_SEED_TRAINEE_PASSWORD`, `SIM_SEED_INSTRUCTOR_PASSWORD`, `SIM_SEED_ADMIN_PASSWORD` — and a
missing variable is a refusal, not a default: a default would be a credential committed to the
repository, which is exactly what SPEC §41 forbids ("Secrets/configuration belong in
environment/config files, not source code"). `.env.example` documents the three names with
obviously-fake values.

The passwords are hashed with the real `Argon2PasswordHasher`; nothing is printed but the username
and the role of each account. The plaintext is never logged, echoed or written anywhere.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from app.application.ports.user_repository import UserRole
from app.config.settings import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.domain.common.ids import UserId
from app.infrastructure.auth.argon2_hasher import Argon2PasswordHasher
from app.infrastructure.clock import SystemClock
from app.infrastructure.persistence.unit_of_work import unit_of_work_factory

__all__ = ["SEED_ACCOUNTS", "SeedAccount", "main", "seed_users"]


@dataclass(frozen=True)
class SeedAccount:
    """One account to upsert. The password lives in `password_env`, never here."""

    username: str
    display_name_ru: str
    user_role: UserRole
    password_env: str


SEED_ACCOUNTS: tuple[SeedAccount, ...] = (
    SeedAccount(
        username="trainee",
        display_name_ru="Стажёр",
        user_role=UserRole.TRAINEE,
        password_env="SIM_SEED_TRAINEE_PASSWORD",
    ),
    SeedAccount(
        username="instructor",
        display_name_ru="Инструктор",
        user_role=UserRole.INSTRUCTOR,
        password_env="SIM_SEED_INSTRUCTOR_PASSWORD",
    ),
    SeedAccount(
        username="admin",
        display_name_ru="Администратор",
        user_role=UserRole.ADMIN,
        password_env="SIM_SEED_ADMIN_PASSWORD",
    ),
)
"""`display_name_ru` is Russian; the username, the role and every identifier are English (D0)."""


class MissingSeedPasswordError(RuntimeError):
    """A seed password environment variable is unset or empty (SPEC §41)."""


def _password(account: SeedAccount) -> str:
    """The account's password from the environment; a missing one refuses the whole run."""
    password = os.environ.get(account.password_env, "")
    if not password:
        raise MissingSeedPasswordError(
            f"{account.password_env} is unset or empty. Seed passwords are never defaulted in "
            f"source (SPEC §41) — export the three SIM_SEED_*_PASSWORD variables, or put them in "
            f".env (see .env.example)."
        )
    return password


async def seed_users(
    settings: Settings, accounts: Sequence[SeedAccount] = SEED_ACCOUNTS
) -> list[tuple[str, UserRole]]:
    """Upsert `accounts` in one transaction; returns `(username, role)` per account.

    The passwords are read *before* the transaction opens, so a missing variable is refused
    without touching the database at all.
    """
    hasher = Argon2PasswordHasher()
    digests = [(account, hasher.hash(_password(account))) for account in accounts]

    engine = create_engine(settings)
    try:
        unit_of_work = unit_of_work_factory(
            create_session_factory(engine), SystemClock(), _NullPublisher()
        )
        async with unit_of_work() as uow:
            for account, digest in digests:
                await uow.users.upsert(
                    # Used only if the row is inserted: `upsert` keys on `username`, so an
                    # existing account keeps its id (and everything that references it).
                    user_id=UserId(uuid4()),
                    username=account.username,
                    display_name_ru=account.display_name_ru,
                    user_role=account.user_role,
                    password_hash=digest,
                    is_active=True,
                )
            await uow.commit()
    finally:
        await engine.dispose()
    return [(account.username, account.user_role) for account, _ in digests]


class _NullPublisher:
    """An `EventPublisher` that publishes nothing: seeding appends no session event."""

    async def publish(self, session_id: object, envelopes: object) -> None:
        """A no-op — there is nothing to fan out."""
        return None


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Prints one line per account; never prints a password."""
    del argv  # no options: the accounts and their env var names are fixed
    try:
        seeded = asyncio.run(seed_users(get_settings()))
    except MissingSeedPasswordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for username, role in seeded:
        print(f"seeded {username} ({role.value})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

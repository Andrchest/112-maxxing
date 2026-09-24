"""`UserRepository` port — the `users` table (HLD `20-db-schema.md` §20.2, D8).

D8 gives the backend local accounts only: "local username/password → JWT (HS256, secret from env).
Roles `TRAINEE`, `INSTRUCTOR`, `ADMIN`". Those three values have no counterpart in
`app.domain.enums` — `20-db-schema.md` §20.2 spells them out in prose and
`app.db.models.reference.USER_ROLES` repeats them for the CHECK constraint — because an *account*
role is not a simulation concept: `RoleType` (`OPERATOR_112`, `DDS`, `EDDS`) is what the domain
reasons about. `UserRole` therefore lives here, in the application layer, next to the port that
reads it, and is copied literally from `openapi.yaml`'s `UserRole` schema.

`StoredUser.password_hash` never leaves this layer: `Login` hands it straight to the
`PasswordHasher` port and nothing else reads it. It carries `repr=False` so that a stray log line,
traceback or `repr()` of a user value can never print a credential (SPEC §41).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.ids import UserId

__all__ = ["StoredUser", "UserRepository", "UserRole"]


class UserRole(str, Enum):
    """`users.role` (§20.2, D8) — `openapi.yaml`'s `UserRole`, member names are wire values."""

    TRAINEE = "TRAINEE"
    INSTRUCTOR = "INSTRUCTOR"
    ADMIN = "ADMIN"


class StoredUser(BaseModel):
    """One persisted `users` row (§20.2)."""

    model_config = ConfigDict(frozen=True)

    user_id: UserId
    username: str
    display_name_ru: str
    user_role: UserRole
    is_active: bool
    #: The argon2 digest. Never rendered, never logged, never returned by the API (SPEC §41).
    password_hash: str = Field(repr=False)
    created_at: datetime
    #: I3 E6e (HLD 80 §80.7): the optional per-user SIP Digest HA1 — `None` ⇒ the deployment SIP
    #: password applies. A credential digest: never rendered by a user view, never logged; only
    #: the SIP gateway's `getSipCredential` returns it (SPEC §41).
    sip_ha1: str | None = Field(default=None, repr=False)


@runtime_checkable
class UserRepository(Protocol):
    """Read and upsert local accounts (§20.2, D8)."""

    async def get(self, user_id: UserId) -> StoredUser | None:
        """The account with this id, or `None`."""
        ...

    async def get_by_username(self, username: str) -> StoredUser | None:
        """The account with this username, or `None`. `users.username` is unique (§20.2)."""
        ...

    async def get_many(self, user_ids: Sequence[UserId]) -> list[StoredUser]:
        """Every account among `user_ids` that exists, in `username` order.

        The session views name their participants (`SessionParticipantView.username`,
        `display_name_ru`), and reading them one by one would be a query per participant.
        """
        ...

    async def list_users(
        self, *, role: UserRole | None = None, limit: int, offset: int
    ) -> tuple[list[StoredUser], int]:
        """One page of **active** accounts in `username` order, and the unpaged total.

        `openapi.yaml`'s `listUsers` answers `UserAccount`, which has no `is_active` property —
        there is no way to render a retired account honestly, so a retired account is not
        returned at all. That is also the only reading that keeps the endpoint useful for what it
        exists for: picking the participants of a new session (`createSession`), which a
        deactivated account cannot be.

        `role` filters on `users.role` when it is given; `None` means every role. `total` counts
        the accounts the same filter matches, not the page.
        """
        ...

    async def upsert(
        self,
        *,
        user_id: UserId,
        username: str,
        display_name_ru: str,
        user_role: UserRole,
        password_hash: str,
        is_active: bool = True,
    ) -> StoredUser:
        """Insert the account, or update the existing row with this `username`.

        `user_id` is used only when the row is inserted: an existing account keeps its id, so a
        re-run of `app.tools.seed_users` never orphans the sessions that reference it.
        """
        ...

    async def set_sip_ha1(self, username: str, sip_ha1: str | None) -> bool:
        """Set (or, with `None`, clear) the account's per-user SIP HA1 (I3 E6e, HLD 80 §80.7).

        `False` when no account has this username. `upsert` never touches the column, so a
        re-run of `app.tools.seed_users` keeps a SIP credential set by `app.tools.set_sip_password`.
        """
        ...

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
        self,
        *,
        role: UserRole | None = None,
        limit: int,
        offset: int,
        include_inactive: bool = False,
    ) -> tuple[list[StoredUser], int]:
        """One page of accounts in `username` order, and the unpaged total.

        Active accounts only unless `include_inactive` (I4 E28, ADMIN only at the router):
        `openapi.yaml`'s `listUsers` used to answer plain `UserAccount`, which has no `is_active`
        property, so a retired account could not be rendered honestly and was excluded outright.
        `UserAccountI4` (I4 E28) can render one, so an ADMIN may now ask for the whole roster —
        e.g. to block/unblock — while the default stays "active only", which is what the endpoint
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

    # --- I4 E28 accounts (`71-i4-wave4.md` §71.5) ----------------------------------------------
    #
    # `upsert` above is `seed_users`'s idempotent-by-username tool; these four are the ADMIN
    # surface's own primitives, keyed by `user_id` (the account already exists by the time any of
    # them is called, `createUser` excepted).

    async def create(
        self,
        *,
        user_id: UserId,
        username: str,
        display_name_ru: str,
        user_role: UserRole,
        password_hash: str,
    ) -> StoredUser:
        """Insert a brand-new account (`createUser`, ТЗ ¶195).

        The caller has already checked `get_by_username` is `None`; a concurrent duplicate still
        surfaces through `uq_users_username` rather than silently overwriting the other row (the
        difference from `upsert`, which is intentionally `ON CONFLICT DO UPDATE`).
        """
        ...

    async def update(
        self,
        user_id: UserId,
        *,
        display_name_ru: str | None = None,
        user_role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> StoredUser | None:
        """Patch the fields given (`None` = leave unchanged); `None` back = no such account.

        Shared by `UpdateUser` (role / display name) and `SetActive` (`is_active`) — one column
        set, one place that writes it.
        """
        ...

    async def set_password_hash(self, user_id: UserId, password_hash: str) -> bool:
        """Replace the digest (`resetUserPassword`). `False` when no such account."""
        ...

    async def count_active(self, user_role: UserRole) -> int:
        """How many **active** accounts hold this role — the last-active-ADMIN guard's count."""
        ...

    # --- end I4 E28 -----------------------------------------------------------------------------

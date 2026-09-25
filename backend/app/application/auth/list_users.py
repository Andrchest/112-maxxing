"""`ListUsers` — one page of local accounts (`openapi.yaml` `listUsers`, additive E7, D8).

The endpoint exists for one reason: `createSession` takes a list of `user_id`s, and an instructor
building a session has to be able to pick them. It is therefore restricted to `INSTRUCTOR` /
`ADMIN` (`403 FORBIDDEN_FOR_ROLE` for a trainee — the gate is
`app.api.security.require_roles`, D8's *account* gate) and it answers the same `UserAccount`
schema `getCurrentUser` does.

What it never carries is the digest: `UserAccount` has no `password_hash` property,
`app.api.schemas.auth.user_account_schema` builds the response by naming each field, and
`StoredUser.password_hash` carries `repr=False` so it cannot leak through a traceback either
(SPEC §41).

Retired accounts are not returned at all by default — see `UserRepository.list_users` for why the
schema leaves no honest way to render one, and how I4 E28's `include_inactive` (ADMIN only, gated
by the router, not here) changes that.
"""

from __future__ import annotations

from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.user_repository import StoredUser, UserRole

__all__ = ["ListUsers"]


class ListUsers:
    """`listUsers` — the page and the unpaged total, filtered by account role."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        *,
        role: UserRole | None = None,
        limit: int,
        offset: int,
        include_inactive: bool = False,
    ) -> tuple[list[StoredUser], int]:
        """One page of accounts in `username` order, and how many match the filter."""
        async with self._unit_of_work() as uow:
            page = await uow.users.list_users(
                role=role, limit=limit, offset=offset, include_inactive=include_inactive
            )
            await uow.commit()
        return page

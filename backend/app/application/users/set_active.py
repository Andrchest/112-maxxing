"""`SetActive` — the `is_active` half of `updateUser` (ADMIN, ТЗ ¶197, I4 E28).

Blocking takes effect immediately: `authenticate_token` re-reads `is_active` on every request
(`app/application/auth/get_current_user.py:59`), so a blocked user's live token is refused on its
very next call — this use case does not need to touch anything beyond the row.

The guards apply only to *blocking* (`is_active=False`) an active ADMIN; unblocking, and touching
any non-ADMIN account, never needs them.
"""

from __future__ import annotations

from app.application.ports.audit_changes import NO_AUDIT_CHANGES, AuditChangeCollector
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.user_repository import StoredUser, UserRole
from app.application.users.errors import (
    LastAdminRequiredError,
    SelfModificationForbiddenError,
    UserNotFoundError,
)
from app.domain.common.ids import UserId

__all__ = ["SetActive"]


class SetActive:
    """Block or unblock an account."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, changes: AuditChangeCollector = NO_AUDIT_CHANGES
    ) -> None:
        self._unit_of_work = unit_of_work
        self._changes = changes  # I7 E43

    async def __call__(self, user_id: UserId, *, actor_id: UserId, is_active: bool) -> StoredUser:
        async with self._unit_of_work() as uow:
            target = await uow.users.get(user_id)
            if target is None:
                raise UserNotFoundError(user_id)

            blocks_an_active_admin = (
                not is_active and target.is_active and target.user_role is UserRole.ADMIN
            )
            if blocks_an_active_admin:
                if target.user_id == actor_id:
                    raise SelfModificationForbiddenError(
                        "an ADMIN cannot block its own account (§71.5)"
                    )
                if await uow.users.count_active(UserRole.ADMIN) <= 1:
                    raise LastAdminRequiredError(
                        "the last active ADMIN account cannot be blocked (§71.5)"
                    )

            updated = await uow.users.update(user_id, is_active=is_active)
            assert updated is not None, "the `get` above already proved the row exists"
            await uow.commit()
        self._changes.record("user", "is_active", target.is_active, updated.is_active)
        return updated

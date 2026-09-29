"""`UpdateUser` — the role / display-name half of `updateUser` (ADMIN, ТЗ ¶196, I4 E28).

`is_active` is `SetActive`'s job (`app.application.users.set_active`) — the router composes the
two under one PATCH body, so a request that changes both still leaves exactly one `audit_log` row
(E25's middleware records the HTTP request, not the use case calls inside it).

The guard only ever looks at a role change that leaves `ADMIN`: raising or renaming display name
is never "demoting", and a `user_role` equal to the current one is a no-op the guard ignores.
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

__all__ = ["UpdateUser"]


class UpdateUser:
    """Change `display_name_ru` and/or `user_role`; both optional, at least one expected."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, changes: AuditChangeCollector = NO_AUDIT_CHANGES
    ) -> None:
        self._unit_of_work = unit_of_work
        self._changes = changes  # I7 E43

    async def __call__(
        self,
        user_id: UserId,
        *,
        actor_id: UserId,
        display_name_ru: str | None = None,
        user_role: UserRole | None = None,
    ) -> StoredUser:
        async with self._unit_of_work() as uow:
            target = await uow.users.get(user_id)
            if target is None:
                raise UserNotFoundError(user_id)

            demotes_from_admin = (
                user_role is not None
                and user_role != target.user_role
                and target.user_role is UserRole.ADMIN
            )
            if demotes_from_admin:
                if target.user_id == actor_id:
                    raise SelfModificationForbiddenError(
                        "an ADMIN cannot demote its own account (§71.5)"
                    )
                if await uow.users.count_active(UserRole.ADMIN) <= 1:
                    raise LastAdminRequiredError(
                        "the last active ADMIN account cannot be demoted (§71.5)"
                    )

            updated = await uow.users.update(
                user_id, display_name_ru=display_name_ru, user_role=user_role
            )
            assert updated is not None, "the `get` above already proved the row exists"
            await uow.commit()
        for field in ("display_name_ru", "user_role"):
            self._changes.record("user", field, getattr(target, field), getattr(updated, field))
        return updated

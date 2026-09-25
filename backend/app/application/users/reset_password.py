"""`ResetPassword` — `resetUserPassword` (`POST /api/v1/admin/users/{user_id}/password`, ADMIN,
I4 E28).

`openapi.yaml`: "The password is never echoed, logged or audited in clear (E25 records the
operation, not the body)" — nothing here returns the plaintext or the digest, and the response is
`204` with no body (the router never builds a schema that could carry one).

No self/last-admin guard: resetting your own password, or another ADMIN's, is neither blocking
nor demoting an account.
"""

from __future__ import annotations

from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.users.errors import PasswordTooShortError, UserNotFoundError
from app.domain.common.ids import UserId

__all__ = ["ResetPassword"]


class ResetPassword:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, hasher: PasswordHasher, *, min_password_length: int
    ) -> None:
        self._unit_of_work = unit_of_work
        self._hasher = hasher
        self._min_password_length = min_password_length

    async def __call__(self, user_id: UserId, *, password: str) -> None:
        if len(password) < self._min_password_length:
            raise PasswordTooShortError(self._min_password_length)
        async with self._unit_of_work() as uow:
            target = await uow.users.get(user_id)
            if target is None:
                raise UserNotFoundError(user_id)
            await uow.users.set_password_hash(user_id, self._hasher.hash(password))
            await uow.commit()

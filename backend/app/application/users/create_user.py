"""`CreateUser` — `createUser` (`POST /api/v1/admin/users`, ADMIN, ТЗ ¶195, I4 E28).

Passwords are argon2 as `Login` already hashes them (`app.infrastructure.auth.argon2_hasher`),
with a floor from config (`Settings.min_password_length`) rather than a fixed OpenAPI `minLength`
— the contract can only state a static bound, and this one is a deployment setting.

The username-uniqueness check is read-then-write, the same pattern
`app.application.scenarios.import_scenario_version` uses for `SCENARIO_VERSION_EXISTS`: a
concurrent duplicate still surfaces through `uq_users_username` at the database —
`UsernameTakenError` is this use case's own pre-check for the common case.
"""

from __future__ import annotations

from app.application.ports.id_generator import IdGenerator
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.user_repository import StoredUser, UserRole
from app.application.users.errors import PasswordTooShortError, UsernameTakenError
from app.domain.common.ids import UserId

__all__ = ["CreateUser"]


class CreateUser:
    """Create an account of any role. No guard here: a brand-new account cannot be "the last
    ADMIN" being removed, and it is nobody's own account being demoted."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        hasher: PasswordHasher,
        ids: IdGenerator,
        *,
        min_password_length: int,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._hasher = hasher
        self._ids = ids
        self._min_password_length = min_password_length

    async def __call__(
        self, *, username: str, display_name_ru: str, user_role: UserRole, password: str
    ) -> StoredUser:
        if len(password) < self._min_password_length:
            raise PasswordTooShortError(self._min_password_length)
        async with self._unit_of_work() as uow:
            if await uow.users.get_by_username(username) is not None:
                raise UsernameTakenError(username)
            user = await uow.users.create(
                user_id=UserId(self._ids.new()),
                username=username,
                display_name_ru=display_name_ru,
                user_role=user_role,
                password_hash=self._hasher.hash(password),
            )
            await uow.commit()
        return user

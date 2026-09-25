"""`CreateUser` / `UpdateUser` / `SetActive` / `ResetPassword` — the decisions, not PostgreSQL
(I4 E28, `71-i4-wave4.md` §71.5).

`tests/api/admin/test_users.py` proves the same guards through HTTP, where the ADMIN-only role
gate means a caller can only ever be *the* active ADMIN when there is just one — so a third party
demoting or blocking "the last active ADMIN" is not reachable through that surface. The guard is
still an application-layer invariant (`UpdateUser`/`SetActive` do not know or care how their caller
authenticated), and `test_a_third_party_cannot_demote_the_last_active_admin` /
`test_a_third_party_cannot_block_the_last_active_admin` below prove it directly, with an `actor_id`
that is not the target's.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from app.application.ports.user_repository import UserRole
from app.application.testing.fakes import FakePasswordHasher
from app.application.users.create_user import CreateUser
from app.application.users.errors import (
    LastAdminRequiredError,
    PasswordTooShortError,
    SelfModificationForbiddenError,
    UsernameTakenError,
    UserNotFoundError,
)
from app.application.users.reset_password import ResetPassword
from app.application.users.set_active import SetActive
from app.application.users.update_user import UpdateUser
from app.domain.common.ids import UserId

from tests.unit.application.users._fakes import (
    InMemoryUserRepository,
    make_user,
    unit_of_work_factory,
)

MIN_PASSWORD_LENGTH = 8


def _uid(n: int) -> UserId:
    """A deterministic id for an actor no `StoredUser` needs (a not-found target, a bystander)."""
    return UserId(UUID(int=n))


class _SequentialIds:
    """A trivial `IdGenerator`: increasing UUIDs, deterministic enough for assertions."""

    def __init__(self) -> None:
        self._next = 0

    def new(self) -> UUID:
        self._next += 1
        return UUID(int=self._next)


# ---------------------------------------------------------------------------------------------
# `CreateUser`
# ---------------------------------------------------------------------------------------------


def _build_create_user(users: InMemoryUserRepository) -> CreateUser:
    return CreateUser(
        unit_of_work_factory(users),
        FakePasswordHasher(),
        _SequentialIds(),
        min_password_length=MIN_PASSWORD_LENGTH,
    )


async def test_creates_an_account_with_the_hashed_password() -> None:
    create_user = _build_create_user(InMemoryUserRepository())

    created = await create_user(
        username="new1",
        display_name_ru="Новый",
        user_role=UserRole.INSTRUCTOR,
        password="a-long-enough-password",
    )

    assert created.username == "new1"
    assert created.user_role is UserRole.INSTRUCTOR
    assert created.is_active is True
    assert created.password_hash != "a-long-enough-password"


async def test_an_existing_username_is_refused() -> None:
    users = InMemoryUserRepository([make_user(username="taken")])
    create_user = _build_create_user(users)

    with pytest.raises(UsernameTakenError):
        await create_user(
            username="taken",
            display_name_ru="Кто-то",
            user_role=UserRole.TRAINEE,
            password="a-long-enough-password",
        )


async def test_a_short_password_is_refused_on_create() -> None:
    create_user = _build_create_user(InMemoryUserRepository())

    with pytest.raises(PasswordTooShortError):
        await create_user(
            username="new1", display_name_ru="Новый", user_role=UserRole.TRAINEE, password="short"
        )


# ---------------------------------------------------------------------------------------------
# `UpdateUser` — role / display name
# ---------------------------------------------------------------------------------------------


async def test_renames_an_account() -> None:
    admin = make_user(username="admin1", user_role=UserRole.ADMIN)
    users = InMemoryUserRepository([admin])
    update_user = UpdateUser(unit_of_work_factory(users))

    updated = await update_user(admin.user_id, actor_id=_uid(999), display_name_ru="Новое имя")

    assert updated.display_name_ru == "Новое имя"


async def test_an_unknown_account_is_not_found_when_updating() -> None:
    update_user = UpdateUser(unit_of_work_factory(InMemoryUserRepository()))

    with pytest.raises(UserNotFoundError):
        await update_user(_uid(1), actor_id=_uid(1), display_name_ru="x")


async def test_an_admin_cannot_demote_its_own_account() -> None:
    admin = make_user(username="admin1", user_role=UserRole.ADMIN)
    other_admin = make_user(username="admin2", user_role=UserRole.ADMIN)
    users = InMemoryUserRepository([admin, other_admin])
    update_user = UpdateUser(unit_of_work_factory(users))

    with pytest.raises(SelfModificationForbiddenError):
        await update_user(admin.user_id, actor_id=admin.user_id, user_role=UserRole.TRAINEE)


async def test_a_role_change_that_keeps_admin_is_not_a_demotion() -> None:
    admin = make_user(username="admin1", user_role=UserRole.ADMIN)
    users = InMemoryUserRepository([admin])
    update_user = UpdateUser(unit_of_work_factory(users))

    updated = await update_user(admin.user_id, actor_id=admin.user_id, user_role=UserRole.ADMIN)

    assert updated.user_role is UserRole.ADMIN


async def test_a_third_party_cannot_demote_the_last_active_admin() -> None:
    """Not reachable through the ADMIN-gated HTTP surface (the caller would have to be the
    target), but the use case enforces it regardless of how the caller authenticated."""
    sole_admin = make_user(username="admin1", user_role=UserRole.ADMIN)
    other_caller = make_user(username="someone-else", user_role=UserRole.TRAINEE)
    users = InMemoryUserRepository([sole_admin, other_caller])
    update_user = UpdateUser(unit_of_work_factory(users))

    with pytest.raises(LastAdminRequiredError):
        await update_user(
            sole_admin.user_id, actor_id=other_caller.user_id, user_role=UserRole.TRAINEE
        )


async def test_demoting_one_of_two_active_admins_by_someone_else_succeeds() -> None:
    admin_a = make_user(username="admin-a", user_role=UserRole.ADMIN)
    admin_b = make_user(username="admin-b", user_role=UserRole.ADMIN)
    users = InMemoryUserRepository([admin_a, admin_b])
    update_user = UpdateUser(unit_of_work_factory(users))

    updated = await update_user(
        admin_b.user_id, actor_id=admin_a.user_id, user_role=UserRole.INSTRUCTOR
    )

    assert updated.user_role is UserRole.INSTRUCTOR


# ---------------------------------------------------------------------------------------------
# `SetActive`
# ---------------------------------------------------------------------------------------------


async def test_blocks_a_trainee() -> None:
    trainee = make_user(username="trainee1", user_role=UserRole.TRAINEE)
    users = InMemoryUserRepository([trainee])
    set_active = SetActive(unit_of_work_factory(users))

    updated = await set_active(trainee.user_id, actor_id=_uid(999), is_active=False)

    assert updated.is_active is False


async def test_an_admin_cannot_block_its_own_account() -> None:
    admin = make_user(username="admin1", user_role=UserRole.ADMIN)
    users = InMemoryUserRepository([admin])
    set_active = SetActive(unit_of_work_factory(users))

    with pytest.raises(SelfModificationForbiddenError):
        await set_active(admin.user_id, actor_id=admin.user_id, is_active=False)


async def test_a_third_party_cannot_block_the_last_active_admin() -> None:
    sole_admin = make_user(username="admin1", user_role=UserRole.ADMIN)
    other_caller = make_user(username="someone-else", user_role=UserRole.TRAINEE)
    users = InMemoryUserRepository([sole_admin, other_caller])
    set_active = SetActive(unit_of_work_factory(users))

    with pytest.raises(LastAdminRequiredError):
        await set_active(sole_admin.user_id, actor_id=other_caller.user_id, is_active=False)


async def test_unblocking_never_needs_a_guard_even_for_the_sole_admin() -> None:
    admin = make_user(username="admin1", user_role=UserRole.ADMIN, is_active=False)
    users = InMemoryUserRepository([admin])
    set_active = SetActive(unit_of_work_factory(users))

    updated = await set_active(admin.user_id, actor_id=admin.user_id, is_active=True)

    assert updated.is_active is True


# ---------------------------------------------------------------------------------------------
# `ResetPassword`
# ---------------------------------------------------------------------------------------------


async def test_resets_the_password_hash() -> None:
    trainee = make_user(username="trainee1", password_hash="old$hash")
    users = InMemoryUserRepository([trainee])
    reset_password = ResetPassword(
        unit_of_work_factory(users), FakePasswordHasher(), min_password_length=MIN_PASSWORD_LENGTH
    )

    await reset_password(trainee.user_id, password="a-brand-new-password")

    stored = await users.get(trainee.user_id)
    assert stored is not None
    assert stored.password_hash != "old$hash"


async def test_a_short_password_is_refused_when_resetting() -> None:
    trainee = make_user(username="trainee1")
    users = InMemoryUserRepository([trainee])
    reset_password = ResetPassword(
        unit_of_work_factory(users), FakePasswordHasher(), min_password_length=MIN_PASSWORD_LENGTH
    )

    with pytest.raises(PasswordTooShortError):
        await reset_password(trainee.user_id, password="short")


async def test_an_unknown_account_is_not_found_when_resetting_password() -> None:
    reset_password = ResetPassword(
        unit_of_work_factory(InMemoryUserRepository()),
        FakePasswordHasher(),
        min_password_length=MIN_PASSWORD_LENGTH,
    )

    with pytest.raises(UserNotFoundError):
        await reset_password(_uid(1), password="a-brand-new-password")

"""`require_owner_or_admin` — I5 E39 (Q-E9b-4 variant а): see everything, change only your own.

The pure rule under every mutating lesson/session/report/group operation: the owner or an ADMIN
passes, another INSTRUCTOR is `NOT_RESOURCE_OWNER`, a TRAINEE is `FORBIDDEN_FOR_ROLE`, and a row
with no recorded owner (`None`, the legacy/seed rule) is mutable by any instructor.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.auth.ownership import (
    NotResourceOwnerError,
    is_owner_or_admin,
    require_owner_or_admin,
)
from app.application.ports.user_repository import UserRole
from app.application.sessions.queries import ForbiddenForRoleError
from app.domain.common.ids import UserId


def _user(role: UserRole) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=UserId(uuid4()), username="u", display_name_ru="Пользователь", user_role=role
    )


OWNER = _user(UserRole.INSTRUCTOR)
OTHER = _user(UserRole.INSTRUCTOR)
ADMIN = _user(UserRole.ADMIN)
TRAINEE = _user(UserRole.TRAINEE)


@pytest.mark.parametrize("user", [OWNER, ADMIN], ids=["owner", "admin"])
def test_the_owner_and_an_admin_may_change_it(user: AuthenticatedUser) -> None:
    assert is_owner_or_admin(OWNER.user_id, user)
    require_owner_or_admin(OWNER.user_id, user, resource="lesson x")


def test_another_instructor_is_not_the_owner() -> None:
    assert not is_owner_or_admin(OWNER.user_id, OTHER)
    with pytest.raises(NotResourceOwnerError) as refused:
        require_owner_or_admin(OWNER.user_id, OTHER, resource="lesson x")
    assert refused.value.code == "NOT_RESOURCE_OWNER"


@pytest.mark.parametrize("owner", [None, OWNER.user_id], ids=["no-owner", "owned"])
def test_a_trainee_is_refused_on_role(owner: UserId | None) -> None:
    with pytest.raises(ForbiddenForRoleError):
        require_owner_or_admin(owner, TRAINEE, resource="lesson x")


@pytest.mark.parametrize("user", [OWNER, OTHER, ADMIN], ids=["owner", "other", "admin"])
def test_a_row_with_no_recorded_owner_is_mutable_by_any_instructor(
    user: AuthenticatedUser,
) -> None:
    """Legacy/seed rows (`created_by_user_id` NULL): shared, as before I5."""
    assert is_owner_or_admin(None, user)
    require_owner_or_admin(None, user, resource="session x")

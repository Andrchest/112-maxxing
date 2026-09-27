"""Instructor ownership — "видит всё, но менять может только своё" (I5 E39, Q-E9b-4 variant а).

ТЗ ¶245 forbids «вмешательство в работу других преподавателей», while the Q&A (L786–789) lets an
instructor see every trainee's work. The owner's answer keeps both: every READ stays open to every
INSTRUCTOR, and every MUTATING instructor operation on a lesson, a session, its report or a
trainee group is refused to an instructor who is not its owner.

* The owner is the row's `created_by_user_id` — the instructor who created it.
* `ADMIN` is not subject to the check (unchanged: an admin may do anything an instructor can).
* A row with no recorded owner (`None`) is mutable by any instructor — the rule for legacy/seed
  rows. Today every such column is `NOT NULL`, so the branch is reached only through the pure
  function; it is kept so a future nullable owner column needs no second rule.
* A `TRAINEE` reaching the check is refused on role (`403 FORBIDDEN_FOR_ROLE`), exactly as the
  creator-or-admin checks this module replaces answered.

An instructor who is not the owner gets `403 NOT_RESOURCE_OWNER` — a code of its own, distinct
from `FORBIDDEN_FOR_ROLE` (the account role *would* permit the operation; the resource is someone
else's), so the UI can say why.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.domain.common.errors import DomainError
from app.domain.common.ids import UserId

__all__ = ["NotResourceOwnerError", "is_owner_or_admin", "require_owner_or_admin"]


class NotResourceOwnerError(DomainError):
    """An INSTRUCTOR changing a resource another instructor created (`403 NOT_RESOURCE_OWNER`)."""

    code = "NOT_RESOURCE_OWNER"


def is_owner_or_admin(owner_user_id: UserId | None, user: AuthenticatedUser) -> bool:
    """May this INSTRUCTOR/ADMIN change a resource owned by `owner_user_id`?"""
    if user.user_role is UserRole.ADMIN:
        return True
    if user.user_role is not UserRole.INSTRUCTOR:
        return False
    return owner_user_id is None or owner_user_id == user.user_id


def require_owner_or_admin(
    owner_user_id: UserId | None, user: AuthenticatedUser, *, resource: str
) -> None:
    """Raise unless `user` may change `resource` (see the module docstring for the rule)."""
    if is_owner_or_admin(owner_user_id, user):
        return
    if user.user_role is not UserRole.INSTRUCTOR:
        # Imported here: `app.application.sessions` imports this module (start/abort), and
        # `sessions.queries` is where `ForbiddenForRoleError` lives.
        from app.application.sessions.queries import ForbiddenForRoleError

        raise ForbiddenForRoleError(f"{resource} may be changed by an INSTRUCTOR or ADMIN only")
    raise NotResourceOwnerError(
        f"{resource} may be changed only by the instructor who created it (or an ADMIN)"
    )

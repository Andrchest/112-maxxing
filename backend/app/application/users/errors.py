"""Errors of the accounts use cases (I4 E28, `71-i4-wave4.md` §71.5, delta `ConflictI4`).

One shared module for `create_user.py` / `update_user.py` / `set_active.py` / `reset_password.py`,
the same pattern `app.application.lessons.errors` and `app.application.reports.explanation.errors`
already use for a multi-module feature area.
"""

from __future__ import annotations

from app.domain.common.errors import DomainError
from app.domain.common.ids import UserId

__all__ = [
    "LastAdminRequiredError",
    "PasswordTooShortError",
    "SelfModificationForbiddenError",
    "UserNotFoundError",
    "UsernameTakenError",
]


class UsernameTakenError(DomainError):
    """`createUser`: `users.username` is unique (§20.2) — `409 USERNAME_TAKEN`."""

    code = "USERNAME_TAKEN"

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"username {username!r} is already taken")


class SelfModificationForbiddenError(DomainError):
    """An ADMIN cannot block or demote its own account (§71.5) — `409
    SELF_MODIFICATION_FORBIDDEN`."""

    code = "SELF_MODIFICATION_FORBIDDEN"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class LastAdminRequiredError(DomainError):
    """The last active ADMIN account cannot be blocked or demoted (§71.5) — `409
    LAST_ADMIN_REQUIRED`."""

    code = "LAST_ADMIN_REQUIRED"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PasswordTooShortError(DomainError):
    """Shorter than `Settings.min_password_length` — `422 VALIDATION_ERROR` (openapi.yaml: "Minimum
    length from config")."""

    code = "VALIDATION_ERROR"

    def __init__(self, minimum: int) -> None:
        self.minimum = minimum
        super().__init__(f"password must be at least {minimum} character(s)")


class UserNotFoundError(DomainError):
    """No `users` row with this id (`404 NOT_FOUND`)."""

    code = "NOT_FOUND"

    def __init__(self, user_id: UserId) -> None:
        self.user_id = user_id
        super().__init__(f"no account {user_id}")

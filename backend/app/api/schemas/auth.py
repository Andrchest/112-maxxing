"""`auth` schemas — `LoginRequest`, `TokenResponse`, `UserAccount` (`openapi.yaml`, D8)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.auth.login import LoginResult
from app.application.ports.user_repository import StoredUser, UserRole

__all__ = [
    "LoginRequestSchema",
    "TokenResponseSchema",
    "UserAccountSchema",
    "token_response_schema",
    "user_account_schema",
]


class LoginRequestSchema(ApiModel):
    """`openapi.yaml`'s `LoginRequest`.

    The bounds are the schema's: a username of 1-128 characters, a password of 1-256. They are
    input validation, not a password policy — a policy belongs to whoever seeds the accounts.
    """

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256, repr=False)
    """`format: password`. `repr=False` keeps it out of tracebacks and logs (SPEC §41)."""


class UserAccountSchema(ApiModel):
    """`openapi.yaml`'s `UserAccount` — never the digest, never `is_active`."""

    id: UUID
    username: str
    display_name_ru: str
    user_role: UserRole
    created_at: datetime


class TokenResponseSchema(ApiModel):
    """`openapi.yaml`'s `TokenResponse`."""

    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(ge=1)
    user: UserAccountSchema


def user_account_schema(user: StoredUser) -> UserAccountSchema:
    """`StoredUser` → `UserAccount`. The digest and `is_active` are dropped here, deliberately."""
    return UserAccountSchema(
        id=UUID(str(user.user_id)),
        username=user.username,
        display_name_ru=user.display_name_ru,
        user_role=user.user_role,
        created_at=user.created_at,
    )


def authenticated_user_schema(user: AuthenticatedUser, created_at: datetime) -> UserAccountSchema:
    """`AuthenticatedUser` → `UserAccount` for `getCurrentUser`.

    `AuthenticatedUser` deliberately carries no `created_at` (it is not an authorisation fact), so
    the endpoint re-reads the account and passes it in.
    """
    return UserAccountSchema(
        id=UUID(str(user.user_id)),
        username=user.username,
        display_name_ru=user.display_name_ru,
        user_role=user.user_role,
        created_at=created_at,
    )


def token_response_schema(result: LoginResult) -> TokenResponseSchema:
    """`LoginResult` → `TokenResponse`."""
    return TokenResponseSchema(
        access_token=result.token.access_token,
        token_type="bearer",
        expires_in=result.token.expires_in,
        user=user_account_schema(result.user),
    )

"""`auth` schemas — `LoginRequest`, `TokenResponse`, `UserAccount` (`openapi.yaml`, D8)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.api.schemas.common import ApiModel
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.auth.login import LoginResult
from app.application.ports.user_repository import StoredUser, UserRole

__all__ = [
    "LoginRequestSchema",
    "PasswordResetRequestSchema",
    "TokenResponseSchema",
    "UserAccountI4Schema",
    "UserAccountSchema",
    "UserCreateRequestSchema",
    "UserUpdateRequestSchema",
    "token_response_schema",
    "user_account_i4_schema",
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


# --- I4 E28 accounts (`71-i4-wave4.md` §71.5, delta `UserAccountI4`) ---------------------------
#
# `UserAccountI4` is additive to `UserAccount` (it adds `is_active`), but it is its own contract
# schema and its own pydantic model: `getCurrentUser`/`loginUser` keep answering the plain
# `UserAccount` (never `is_active`, SPEC §41 does not apply here — the flag is not a credential,
# but the contract for those two operations was never changed), while `listUsers`, `createUser`
# and `updateUser` answer this one.


class UserAccountI4Schema(ApiModel):
    """`openapi.yaml`'s `UserAccountI4` — `UserAccount` plus `is_active`."""

    id: UUID
    username: str
    display_name_ru: str
    user_role: UserRole
    created_at: datetime
    is_active: bool


class UserCreateRequestSchema(ApiModel):
    """`openapi.yaml`'s `UserCreateRequest` (`createUser`, ТЗ ¶195)."""

    username: str = Field(min_length=1)
    display_name_ru: str = Field(min_length=1)
    user_role: UserRole
    password: str = Field(repr=False)


class UserUpdateRequestSchema(ApiModel):
    """`openapi.yaml`'s `UserUpdateRequest` (`updateUser`, ТЗ ¶196, ¶197). Every field optional,
    but at least one is required — `minProperties: 1` of the contract."""

    display_name_ru: str | None = Field(default=None, min_length=1)
    user_role: UserRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> UserUpdateRequestSchema:
        """`minProperties: 1` of the contract — an empty body is `422 VALIDATION_ERROR`."""
        if self.display_name_ru is None and self.user_role is None and self.is_active is None:
            raise ValueError("at least one of display_name_ru, user_role, is_active is required")
        return self


class PasswordResetRequestSchema(ApiModel):
    """`openapi.yaml`'s `PasswordResetRequest` (`resetUserPassword`)."""

    password: str = Field(repr=False)


def user_account_i4_schema(user: StoredUser) -> UserAccountI4Schema:
    """`StoredUser` → `UserAccountI4`. The digest never leaves the application layer."""
    return UserAccountI4Schema(
        id=UUID(str(user.user_id)),
        username=user.username,
        display_name_ru=user.display_name_ru,
        user_role=user.user_role,
        created_at=user.created_at,
        is_active=user.is_active,
    )


# --- end I4 E28 ----------------------------------------------------------------------------------

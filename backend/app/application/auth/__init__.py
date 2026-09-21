"""Authentication use cases (E7, D8, SPEC §41).

`Login` verifies a local account's password and mints the HS256 bearer token; `authenticate_token`
reads that token back into an `AuthenticatedUser`; `ListUsers` answers `listUsers`, the account
picker `createSession` needs. All three are pure application code over the
`PasswordHasher`, `TokenService` and `UserRepository` ports — the secret, the KDF and the JWT
library all live in `app.infrastructure.auth`.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser, authenticate_token
from app.application.auth.list_users import ListUsers
from app.application.auth.login import (
    InvalidCredentialsError,
    Login,
    LoginCommand,
    LoginResult,
)

__all__ = [
    "AuthenticatedUser",
    "InvalidCredentialsError",
    "ListUsers",
    "Login",
    "LoginCommand",
    "LoginResult",
    "authenticate_token",
]

"""`TokenService` port — minting and reading the HS256 bearer token (D8, SPEC §41).

D8: "Auth: local username/password → JWT (HS256, secret from env)". The secret, the algorithm and
the clock that decides expiry are all technology, so the whole of it is one port; the production
adapter is `app.infrastructure.auth.jwt_token_service.JwtTokenService`.

`decode` raises `InvalidTokenError` for every unusable token — missing, malformed, wrong
signature, expired, or carrying claims that are not the ones `issue` writes. One exception for all
of them is deliberate: `openapi.yaml`'s `Unauthorized` response is a single `UNAUTHENTICATED`
problem, and telling a caller *which* way their token was unusable is an oracle.

Neither the token nor the secret is ever logged by an implementation (SPEC §41); `IssuedToken`
carries `repr=False` on the token for the same reason `StoredUser` does on the digest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.application.ports.user_repository import UserRole
from app.domain.common.errors import DomainError
from app.domain.common.ids import UserId

__all__ = ["InvalidTokenError", "IssuedToken", "TokenClaims", "TokenService"]


class InvalidTokenError(DomainError):
    """The bearer token is missing, malformed, expired or not ours (`401 UNAUTHENTICATED`)."""

    code = "UNAUTHENTICATED"

    def __init__(self, reason: str = "the bearer token is missing, malformed or expired") -> None:
        super().__init__(reason)


class TokenClaims(BaseModel):
    """What `decode` recovered: D8's `sub`, `role` and `exp`, as application types."""

    model_config = ConfigDict(frozen=True)

    subject: UserId
    user_role: UserRole
    expires_at: datetime


class IssuedToken(BaseModel):
    """A freshly minted token and its lifetime — `openapi.yaml`'s `TokenResponse` halves."""

    model_config = ConfigDict(frozen=True)

    #: The compact JWT. Never rendered, never logged (SPEC §41).
    access_token: str = Field(repr=False)
    expires_in: int = Field(ge=1)
    """Seconds until expiry, exactly as `TokenResponse.expires_in` defines it."""


@runtime_checkable
class TokenService(Protocol):
    """Mint and read the bearer token of D8."""

    def issue(self, user_id: UserId, user_role: UserRole) -> IssuedToken:
        """Mint a token for this account: `sub`, `role` and `exp` (D8)."""
        ...

    def decode(self, token: str) -> TokenClaims:
        """The claims of a valid token; raises `InvalidTokenError` for every unusable one."""
        ...

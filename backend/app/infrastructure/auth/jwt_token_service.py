"""`JwtTokenService` — the production `TokenService` adapter (D8, SPEC §41).

HS256, the secret from `Settings.jwt_secret` (env `SIM_JWT_SECRET`, never a literal in source —
SPEC §41), with exactly the three claims D8 names: `sub` (the user id), `role` (the account role)
and `exp`. `iat` is written too because PyJWT needs no help to produce it and it is what makes two
tokens minted in the same second distinguishable in an audit.

Every decode failure — a bad signature, an expired token, a missing or unknown claim, a token that
is not a JWT at all — becomes one `InvalidTokenError`. The reason is deliberately not propagated:
`openapi.yaml`'s `Unauthorized` is a single `UNAUTHENTICATED` problem and telling a caller which
way their token was unusable is an oracle.

The token and the secret are never logged (SPEC §41): nothing in this module writes a log line.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

from app.application.ports.token_service import (
    InvalidTokenError,
    IssuedToken,
    TokenClaims,
)
from app.application.ports.user_repository import UserRole
from app.domain.common.ids import UserId

__all__ = ["ALGORITHM", "JwtTokenService"]

ALGORITHM = "HS256"
"""D8: "JWT (HS256, secret from env)"."""


class JwtTokenService:
    """`TokenService` over PyJWT."""

    def __init__(self, secret: str, *, ttl_minutes: int, algorithm: str = ALGORITHM) -> None:
        if not secret:
            raise ValueError("SIM_JWT_SECRET is empty; a token signed with no secret is not one")
        self._secret = secret
        self._ttl = timedelta(minutes=ttl_minutes)
        self._algorithm = algorithm

    def issue(self, user_id: UserId, user_role: UserRole) -> IssuedToken:
        """Mint `{sub, role, iat, exp}` for this account."""
        issued_at = datetime.now(UTC)
        expires_at = issued_at + self._ttl
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "role": user_role.value,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return IssuedToken(
            access_token=token,
            # Computed from the two integer claims, so it can never disagree with `exp`.
            expires_in=max(1, payload["exp"] - payload["iat"]),
        )

    def decode(self, token: str) -> TokenClaims:
        """The claims of a valid token; one `InvalidTokenError` for every unusable one."""
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["sub", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError() from exc
        return self._claims_of(payload)

    def _claims_of(self, payload: dict[str, Any]) -> TokenClaims:
        try:
            subject = UserId(UUID(str(payload["sub"])))
            user_role = UserRole(str(payload["role"]))
            expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidTokenError() from exc
        return TokenClaims(subject=subject, user_role=user_role, expires_at=expires_at)

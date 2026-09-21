"""Authentication adapters (D8, SPEC §41).

`Argon2PasswordHasher` implements `PasswordHasher`; `JwtTokenService` implements `TokenService`.
These two modules are the only place in the backend that knows the KDF, the signing algorithm or
the secret — every caller above them sees the two ports and nothing else.
"""

from __future__ import annotations

from app.infrastructure.auth.argon2_hasher import Argon2PasswordHasher
from app.infrastructure.auth.jwt_token_service import ALGORITHM, JwtTokenService

__all__ = ["ALGORITHM", "Argon2PasswordHasher", "JwtTokenService"]

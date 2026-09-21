"""`PasswordHasher` port (D8, SPEC §41).

Hashing a password is technology — a KDF with a cost parameter — so it is a port, and the
production adapter is `app.infrastructure.auth.argon2_hasher.Argon2PasswordHasher`.

`verify` returns a boolean rather than raising: "wrong password" is an ordinary outcome of a login
attempt, not an exception, and the use case must answer it with exactly the same problem document
as "no such user" so that the endpoint cannot be used to enumerate accounts.

Neither the plaintext nor the digest is ever logged by an implementation (SPEC §41).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["PasswordHasher"]


@runtime_checkable
class PasswordHasher(Protocol):
    """Hash and verify a local account's password."""

    def hash(self, password: str) -> str:
        """The digest to store in `users.password_hash`."""
        ...

    def verify(self, password_hash: str, password: str) -> bool:
        """`True` when `password` matches `password_hash`; a malformed digest is `False`."""
        ...

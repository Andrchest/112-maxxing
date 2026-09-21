"""`Argon2PasswordHasher` — the production `PasswordHasher` adapter (D8, SPEC §41).

argon2id through `argon2-cffi`, at the library's own defaults. The defaults are deliberate rather
than lazy: they are the maintained, memory-hard parameter set, and pinning our own numbers here
would freeze a cost decision in source that the library revises as hardware moves. The digest is
self-describing (`$argon2id$v=19$m=…,t=…,p=…$salt$hash`), so a rotation of those parameters keeps
verifying the digests written under the old ones.

`verify` answers `False` for every unusable digest — wrong password, malformed digest, a digest
produced by another algorithm — rather than raising, because `openapi.yaml` gives `loginUser` one
`401` and the use case must not be able to tell the two apart.

Neither the plaintext nor the digest is logged, and neither appears in an exception this module
raises (SPEC §41).
"""

from __future__ import annotations

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import Argon2Error, InvalidHashError

__all__ = ["Argon2PasswordHasher"]


class Argon2PasswordHasher:
    """`PasswordHasher` over argon2id."""

    def __init__(self) -> None:
        self._hasher = _Argon2()

    def hash(self, password: str) -> str:
        """The argon2id digest to store in `users.password_hash`."""
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """`True` only for a matching password; every failure mode is `False`."""
        try:
            return bool(self._hasher.verify(password_hash, password))
        except (Argon2Error, InvalidHashError, TypeError, ValueError):
            # Deliberately broad and deliberately silent: the reason a digest did not verify is
            # never reported to the caller and never logged (SPEC §41).
            return False

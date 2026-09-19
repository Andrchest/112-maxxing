"""`Uuid4Generator` — the production `IdGenerator` adapter (D2, D7).

The domain never calls `uuid4`: every id a factory needs is passed in. This is the one module
that produces them for the session slice, so a test can make id allocation deterministic by
injecting `app.application.testing.fakes.SequentialIdGenerator` instead.
"""

from __future__ import annotations

from uuid import UUID, uuid4

__all__ = ["Uuid4Generator"]


class Uuid4Generator:
    """A random `IdGenerator` (`uuid.uuid4`)."""

    def new(self) -> UUID:
        """A fresh random UUID."""
        return uuid4()

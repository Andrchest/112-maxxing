"""`IdGenerator` port (D2, D7).

The domain calls neither `uuid4` nor a clock: every id a factory needs is passed in
(`app.domain.session.session.create_session`). Randomness is therefore a capability of the
application layer, and a capability the application layer owns is a port — which is also what
makes a use-case test deterministic (`app.application.testing.fakes.SequentialIdGenerator`).

The production adapter is `app.infrastructure.ids.Uuid4Generator`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

__all__ = ["IdGenerator"]


@runtime_checkable
class IdGenerator(Protocol):
    """Allocates fresh identifiers for newly created aggregates."""

    def new(self) -> UUID:
        """A fresh, never-before-returned UUID."""
        ...

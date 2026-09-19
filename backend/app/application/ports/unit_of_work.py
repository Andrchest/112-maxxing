"""`UnitOfWork` port (D5: "Every use case runs in one Unit of Work").

One transaction covers the materialized state changes *and* the event append of a use case; the
event envelopes are published to Redis only after that transaction commits (§20.8), so a subscriber
never sees an event a later PostgreSQL read would not return (§40.6).

Usage::

    async with uow_factory() as uow:
        ...                                   # materialized writes through uow's repositories
        await uow.events.append(session_id, domain_events)
        await uow.commit()                    # publish happens here, after the commit

Leaving the block without `commit()` rolls back and publishes nothing.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, runtime_checkable

from app.application.ports.event_store import EventStore
from app.application.ports.scenario_repository import ScenarioRepository

__all__ = ["UnitOfWork", "UnitOfWorkFactory"]


@runtime_checkable
class UnitOfWork(Protocol):
    """One transaction plus the after-commit fan-out (D5)."""

    @property
    def events(self) -> EventStore:
        """The event store bound to this transaction."""
        ...

    @property
    def scenarios(self) -> ScenarioRepository:
        """The scenario reference-data repository bound to this transaction."""
        ...

    async def __aenter__(self) -> UnitOfWork:
        """Begin the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Roll back unless `commit()` already succeeded."""
        ...

    async def commit(self) -> None:
        """Commit, then publish the envelopes of every event appended in this transaction.

        A publisher failure is logged and swallowed: the events are committed and authoritative
        (§40.6), so losing the fan-out costs liveness only, never correctness.
        """
        ...

    async def rollback(self) -> None:
        """Roll back and discard the pending envelopes; nothing is published."""
        ...


@runtime_checkable
class UnitOfWorkFactory(Protocol):
    """Creates a fresh, not-yet-entered `UnitOfWork` per use-case invocation."""

    def __call__(self) -> UnitOfWork:
        """Return a new Unit of Work."""
        ...

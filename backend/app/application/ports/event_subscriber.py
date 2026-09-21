"""`EventSubscriber` port — the live half of the realtime read path (HLD §40.3, §40.6, D5).

§40.3 step 2: "The server subscribes to the Redis channel `session:{session_id}:events` **first**
and buffers incoming messages in memory." That ordering is the whole losslessness argument, so it
is a property of the port, not of one adapter: entering the subscription context *is* the
subscribe, and every envelope published after that moment is buffered until somebody reads it.

The envelopes are the unredacted `EventEnvelope`s of §40.6; each connection applies its own role
filter (`app.application.realtime.redaction`) downstream.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from app.application.ports.event_publisher import EventEnvelope
from app.domain.common.ids import SessionId

__all__ = ["EventSubscriber", "EventSubscription"]


@runtime_checkable
class EventSubscription(Protocol):
    """One live subscription to a session's channel, already subscribed and buffering."""

    async def get(self) -> EventEnvelope:
        """The next buffered or live envelope; waits when the buffer is empty.

        Envelopes arrive in publish order, which is `seq_no` order per session (§40.3).
        """
        ...

    def drain(self) -> list[EventEnvelope]:
        """Every envelope buffered *so far*, removed from the buffer, without waiting.

        §40.3 step 4 drains what accumulated during the PostgreSQL replay and discards whatever
        the replay already covered.
        """
        ...


@runtime_checkable
class EventSubscriber(Protocol):
    """Opens subscriptions to `session:{session_id}:events`."""

    def subscribe(self, session_id: SessionId) -> AbstractAsyncContextManager[EventSubscription]:
        """An async context manager whose entry has completed the subscribe.

        Leaving the context releases every resource the subscription holds — the Redis pub/sub
        connection and its reader task — which is what keeps `PUBSUB NUMSUB` at zero once the
        last socket for a session has gone (§40.6, resource hygiene).
        """
        ...

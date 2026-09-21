"""`LastSeqNoCache` port — the `session:{session_id}:last_seq_no` read cache (HLD §40.6).

§40.6: "A read cache so a heartbeat does not hit PostgreSQL. Loss ⇒ the handler reads
`MAX(seq_no)` from PostgreSQL instead." That fallback is the contract: `get` answers `None` for a
missing key and the caller is expected to ask the `EventStore`, never to treat `None` as zero.

Nothing here is a source of truth (§40.6, SPEC §31): a complete Redis flush costs one round trip
to PostgreSQL per heartbeat and nothing else.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import SessionId

__all__ = ["LastSeqNoCache"]


@runtime_checkable
class LastSeqNoCache(Protocol):
    """The highest published `seq_no` per session, cached with a TTL."""

    async def get(self, session_id: SessionId) -> int | None:
        """The cached value, or `None` when the key is missing, unreadable or malformed."""
        ...

    async def set(self, session_id: SessionId, seq_no: int) -> None:
        """Write (and refresh the TTL of) the cached value; never raises."""
        ...

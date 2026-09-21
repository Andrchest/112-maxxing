"""`CallStateCache` port — §40.6's `session:{id}:call_state`, and nothing more (D5, SPEC §31).

§40.6 lists the key as "Transient realtime state for the phone widget (SPEC §31). Loss ⇒ rebuilt
from `CALL_RINGING` / `CALL_ANSWERED` / `CALL_ENDED` / `CALLER_TTS_*` in `session_events`."

That sentence is the whole contract, and it is why this port exists as a *cache* rather than as a
store: `app.application.operator.views.project_call_state` — the pure fold over the session's
event log — stays the authority, this key only saves a reader the fold. Every read therefore goes
through `app.application.operator.views.read_call_state`, which falls back to the fold whenever the
key is missing, expired, flushed or unparseable, so a `FLUSHALL` against a running simulation costs
nothing but one PostgreSQL read (§40.6's stated invariant).

An implementation never raises: an unreachable Redis is a cache miss, which is a documented,
harmless state. Making a call command fail because a cache is down would trade correctness for
nothing.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import SessionId

__all__ = ["CallStateCache"]


@runtime_checkable
class CallStateCache(Protocol):
    """Reads and writes the `session:{id}:call_state` JSON string of §40.6."""

    async def get(self, session_id: SessionId) -> str | None:
        """The cached JSON document, or `None` for a miss (including any failure)."""
        ...

    async def put(self, session_id: SessionId, document: str) -> None:
        """Store `document` under this session's key with the configured TTL. Never raises."""
        ...

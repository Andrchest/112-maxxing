"""`VoiceSignalPublisher` port — the two voice control signals of §40.6 (D9).

Redis carries two backend→voice-agent signals, and neither is a source of truth (§40.6):

* `voice:join` — payload `{session_id, room, call_id}`, published at `CALL_RINGING`. "Loss ⇒ the
  agent never joins; the backend re-publishes every `VOICE_JOIN_RETRY_MS` (default 2000) while the
  stage is `RINGING`, so the signal is self-healing."
* `voice:cancel:{session_id}` — payload `{call_id, reason, at_offset_ms}` with
  `reason ∈ {HANGUP, ABORT, TRANSPORT_LOST}`, published on `endCall`, `abortSession` or a transport
  grace timeout. "Loss ⇒ the caller finishes one utterance into a closed call; no state is
  corrupted."

Both are published **after** the Unit of Work commits, exactly as §40.6 requires of the event
channel: a signal that escaped before its transaction could tell the agent to join a room whose
`CALL_RINGING` a rollback then erased.

An implementation never raises. Redis being down degrades liveness and never correctness, so a
failed publish is logged and swallowed rather than turned into a failed command — the alternative
would make a hang-up fail because a cache is unreachable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.common.ids import SessionId

__all__ = ["CANCEL_REASONS", "VoiceSignalPublisher"]

CANCEL_REASONS: tuple[str, ...] = ("HANGUP", "ABORT", "TRANSPORT_LOST")
"""§40.6's `voice:cancel:{session_id}` `reason` enum, exact."""


@runtime_checkable
class VoiceSignalPublisher(Protocol):
    """Publishes `voice:join` and `voice:cancel:{session_id}` (§40.6, D9)."""

    async def publish_join(self, session_id: SessionId, *, room: str, call_id: UUID) -> None:
        """`voice:join` — `{session_id, room, call_id}`. Never raises."""
        ...

    async def publish_cancel(
        self, session_id: SessionId, *, call_id: UUID, reason: str, at_offset_ms: int
    ) -> None:
        """`voice:cancel:{session_id}` — `{call_id, reason, at_offset_ms}`. Never raises."""
        ...

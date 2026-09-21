"""`SipCallTransport` — the documented stub that makes the second transport a file (§2.1, D9).

SPEC §15 requires a `CallTransport` abstraction "so a future SIP/PSTN transport can be added
without rewriting the dialogue engine", and explicitly does **not** require PSTN for the demo. A
port with exactly one implementation is an untested abstraction, so the second one exists here as
a class that satisfies the Protocol and refuses to run — the shape is checked by the type system
and by `test_sip_transport.py`, and the day SIP is wanted the work is filling these methods in,
not discovering what the seam should have been.

TODO(SIP, out of I1 scope — SPEC §15): this stub stays a stub for the whole of this project's
scope. It becomes real only if the owner adds PSTN to the specification; nothing downstream may
treat it as available.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from app.application.ports.call_transport import AudioFrame, PlaybackHandle, TransportEvent

__all__ = ["SIP_STUB_MESSAGE", "SipCallTransport"]

SIP_STUB_MESSAGE = "SIP transport is a documented stub; see SPEC §15"


class SipCallTransport:
    """A `CallTransport` for SIP/PSTN. Every method refuses (§2.1)."""

    async def connect(self, call_id: uuid.UUID) -> None:
        """Refuse: there is no SIP stack."""
        raise NotImplementedError(SIP_STUB_MESSAGE)

    def inbound_audio(self) -> AsyncIterator[AudioFrame]:
        """Refuse: there is no SIP stack."""
        raise NotImplementedError(SIP_STUB_MESSAGE)

    async def play(self, frames: AsyncIterator[AudioFrame]) -> PlaybackHandle:
        """Refuse: there is no SIP stack."""
        raise NotImplementedError(SIP_STUB_MESSAGE)

    async def clear_outbound(self) -> None:
        """Refuse: there is no SIP stack."""
        raise NotImplementedError(SIP_STUB_MESSAGE)

    def events(self) -> AsyncIterator[TransportEvent]:
        """Refuse: there is no SIP stack."""
        raise NotImplementedError(SIP_STUB_MESSAGE)

    async def disconnect(self) -> None:
        """Refuse: there is no SIP stack."""
        raise NotImplementedError(SIP_STUB_MESSAGE)

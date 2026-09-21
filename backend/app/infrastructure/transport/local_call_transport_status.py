"""`LocalCallTransportStatus` — the `SIM_CALL_TRANSPORT=fake` readiness adapter (D9, §10.8).

A development box and the gate run with no SFU and no voice-agent: there is no media plane to be
unready, and the caller agent is the backend's own simulation. "Can the transport take a call?"
therefore has exactly one honest answer here — yes — and answering it is what lets `ring` fire and
a session run end to end without LiveKit.

This is production wiring, not a test double. The scriptable fake a test drives lives in
`app.application.testing.fakes.FakeCallTransportStatus`, and `app.application.testing` is never
imported from a composition root (D13) — which is precisely why this module exists rather than the
container reaching into the testing package.

`SIM_CALL_TRANSPORT=livekit` is answered by
`app.infrastructure.transport.livekit_transport_status.LiveKitTransportStatus`, which reads the
real LiveKit server and the voice-agent heartbeat instead of assuming both.
"""

from __future__ import annotations

from app.domain.common.ids import SessionId

__all__ = ["LocalCallTransportStatus"]


class LocalCallTransportStatus:
    """`CallTransportStatus` for the transport-less local profile: always ready."""

    async def transport_ready(self, session_id: SessionId) -> bool:
        """Always `True` — see this module's docstring."""
        return True

"""`LocalCallTransportStatus` — the `SIM_CALL_TRANSPORT=fake` readiness adapter (D9, §10.8).

A development box and the gate run with no SFU: there is no room for a caller to join, and the
caller agent is the backend's own simulation. "Has the caller joined?" therefore has exactly one
honest answer here — yes — and answering it is what lets `ring` fire and a session run end to end
without LiveKit.

This is production wiring, not a test double. The scriptable fake a test drives lives in
`app.application.testing.fakes.FakeCallTransportStatus`, and `app.application.testing` is never
imported from a composition root (D13) — which is precisely why this module exists rather than the
container reaching into the testing package.

TODO(E11): `SIM_CALL_TRANSPORT=livekit` has no adapter yet; `app.api.container` raises a
`NotImplementedError` naming E11 rather than silently degrading to this one, because a demo that
believed the caller had joined a room nobody is in would fail as a mystery rather than as a
configuration error.
"""

from __future__ import annotations

from app.domain.common.ids import SessionId

__all__ = ["LocalCallTransportStatus"]


class LocalCallTransportStatus:
    """`CallTransportStatus` for the transport-less local profile: the caller is always present."""

    async def caller_joined(self, session_id: SessionId) -> bool:
        """Always `True` — see this module's docstring."""
        return True

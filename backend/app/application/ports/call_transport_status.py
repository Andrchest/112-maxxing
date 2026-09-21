"""`CallTransportStatus` port — "has the caller joined the room?" (D9, §10.8 `ring` guard).

`app.application.sessions.guard_context.build_guard_runtime` documents why `transport_ready`
cannot be derived from the event log: §10.13's catalog has no event that states the caller joined.
`TRANSPORT_DISCONNECTED` / `TRANSPORT_RECONNECTED` describe losing and regaining an *established*
transport, and `CALL_RINGING` is the result of the guarded transition, so reading either would
make the guard vacuous. The missing fact is therefore a reading of the transport itself, which is
technology — so it is this port, and the log-only projection keeps its honest `False` default.

Two adapters exist today:

* `app.infrastructure.transport.local_call_transport_status.LocalCallTransportStatus` —
  `SIM_CALL_TRANSPORT=fake`: the dev/gate wiring, where the caller is always considered joined
  because there is no SFU to join;
* `SIM_CALL_TRANSPORT=livekit` — TODO(E11): the real reading over the LiveKit room. The container
  raises `NotImplementedError` naming E11 rather than silently degrading to the local adapter.

The scriptable fake a test drives (`caller_joined` returning what the test set) lives in
`app.application.testing.fakes.FakeCallTransportStatus`; `app.application.testing` is a test
fixture package and is never imported by production wiring (D13).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import SessionId

__all__ = ["CallTransportStatus"]


@runtime_checkable
class CallTransportStatus(Protocol):
    """Whether this session's call transport has the caller present (D9)."""

    async def caller_joined(self, session_id: SessionId) -> bool:
        """`True` when the caller agent is present on this session's call transport.

        An implementation never raises: an unreachable transport is `False`, which denies `ring`,
        which is the conservative answer (§10.8).
        """
        ...

"""`CallTransportStatus` port — "can the media plane take a call?" (D9, §10.8 `ring` guard).

`app.application.sessions.guard_context.build_guard_runtime` documents why `transport_ready`
cannot be derived from the event log: §10.13's catalog has no event that states it.
`TRANSPORT_DISCONNECTED` / `TRANSPORT_RECONNECTED` describe losing and regaining an *established*
transport, and `CALL_RINGING` is the result of the guarded transition, so reading either would
make the guard vacuous. The missing fact is therefore a reading of the transport itself, which is
technology — so it is this port, and the log-only projection keeps its honest `False` default.

**What the guard means (E11 ruling).** D9 has the voice-agent join the room on the `voice:join`
message the backend publishes *at* `CALL_RINGING`, while §10.8's guard cell used to read "the
`CallTransport` reports the caller joined" — which is circular: nobody can be in a room that the
`CALL_RINGING` this guard permits has not yet named. The guard means what its name says:
`transport_ready` is "the media plane can take a call", i.e. the LiveKit server is reachable **and**
the voice-agent is alive (§40.6's `voice:health:vad` heartbeat key exists with state `READY`;
`60-inference-ops.md` §4.3 — "a missing key is `NOT_READY`, never `READY`"). Ringing a trainee's
phone into a room nobody can join is the failure this denies.

Two production adapters exist:

* `app.infrastructure.transport.local_call_transport_status.LocalCallTransportStatus` —
  `SIM_CALL_TRANSPORT=fake`: the dev/gate wiring, where there is no SFU and no agent, so the
  media plane is "ready" by construction;
* `app.infrastructure.transport.livekit_transport_status.LiveKitTransportStatus` —
  `SIM_CALL_TRANSPORT=livekit`: HTTP reachability of the LiveKit server AND the `voice:health:vad`
  key, both of which must hold.

The scriptable fake a test drives (`transport_ready` returning what the test set) lives in
`app.application.testing.fakes.FakeCallTransportStatus`; `app.application.testing` is a test
fixture package and is never imported by production wiring (D13).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import SessionId

__all__ = ["CallTransportStatus"]


@runtime_checkable
class CallTransportStatus(Protocol):
    """Whether this session's call transport can carry a call (D9)."""

    async def transport_ready(self, session_id: SessionId) -> bool:
        """`True` when the media plane can take this session's call.

        An implementation never raises: an unreachable transport is `False`, which denies `ring`,
        which is the conservative answer (§10.8).
        """
        ...

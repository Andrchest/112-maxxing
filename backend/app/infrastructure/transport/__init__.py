"""Call-transport adapters (D9).

E7-A ships the readiness half only: `LocalCallTransportStatus` answers the `CallTransportStatus`
port for `SIM_CALL_TRANSPORT=fake`. TODO(E11): the LiveKit `CallTransport` itself — `connect`,
`inbound_audio`, `play`, `clear_outbound`, `events`, `disconnect` — lives in
`workers/voice_agent/transport/` (D9) and the LiveKit readiness adapter belongs beside it.
"""

from __future__ import annotations

from app.infrastructure.transport.local_call_transport_status import LocalCallTransportStatus

__all__ = ["LocalCallTransportStatus"]

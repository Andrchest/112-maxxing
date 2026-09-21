"""`LiveKitHealthProbe` — the `livekit` component of `/api/v1/health/ready` (D8, SPEC §37).

One HTTP `GET` against the LiveKit origin under the same one-second timeout the PostgreSQL and
Redis probes use. LiveKit signals over WebSocket, but the same process answers HTTP on the same
port, so "answered anything within a second" is the reading — see
`app.infrastructure.transport.livekit_transport_status`, which asks the same question for the
`ring` guard and which this probe deliberately does not duplicate the *heartbeat* half of: the
`llm`/`asr`/`tts`/`vad` components report the voice-agent, and `livekit` reports the SFU.

Like every probe it never raises: an unreachable SFU is a `NOT_READY` reading with the reason in
`detail`, which is what keeps `/health/ready` answerable while the media plane is down.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.application.ports.health_probe import ComponentReading
from app.domain.enums import HealthStatus
from app.infrastructure.health.postgres_probe import PROBE_TIMEOUT_S
from app.infrastructure.transport.livekit_transport_status import http_origin_of

__all__ = ["LiveKitHealthProbe"]


class LiveKitHealthProbe:
    """`HealthProbe` for `livekit`."""

    def __init__(self, livekit_url: str, *, timeout_s: float = PROBE_TIMEOUT_S) -> None:
        self._origin = http_origin_of(livekit_url)
        self._timeout_s = timeout_s

    @property
    def component(self) -> str:
        """`ComponentHealth.component` — `livekit`."""
        return "livekit"

    async def check(self) -> ComponentReading:
        """A `GET` on the origin within the timeout; never raises."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                await client.get(self._origin)
        except Exception as exc:
            return self._reading(HealthStatus.NOT_READY, _reason(exc))
        return self._reading(HealthStatus.READY, None)

    def _reading(self, status: HealthStatus, detail: str | None) -> ComponentReading:
        return ComponentReading(
            component=self.component,
            status=status,
            detail=detail,
            checked_at=datetime.now(UTC),
            provider="livekit",
        )


def _reason(exc: Exception) -> str:
    """A short, credential-free reason for a failed probe."""
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return text[:200]

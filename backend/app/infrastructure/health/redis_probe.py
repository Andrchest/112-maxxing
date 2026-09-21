"""`RedisHealthProbe` — the `redis` component of `/api/v1/health/ready` (D8, SPEC §37, §40.6).

`PING`, under a one-second timeout, and nothing else. Redis is never a source of truth (§40.6), so
this reading does not make the simulator correct or incorrect; what it tells the operator is that
live fan-out, the runner lock and the inference heartbeats are working, which is exactly what the
start button should be disabled on (SPEC §37).

Like the PostgreSQL probe it never raises: an unreachable Redis is a `NOT_READY` reading with the
reason in `detail`. That is what makes the "Redis probe pointed at a closed port" test of this
epic return a documented degraded answer instead of a 500.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.application.ports.health_probe import ComponentReading
from app.domain.enums import HealthStatus
from app.infrastructure.health.postgres_probe import PROBE_TIMEOUT_S

__all__ = ["RedisHealthProbe"]


class RedisHealthProbe:
    """`HealthProbe` for `redis`."""

    def __init__(self, client: Redis, *, timeout_s: float = PROBE_TIMEOUT_S) -> None:
        self._client = client
        self._timeout_s = timeout_s

    @property
    def component(self) -> str:
        """`ComponentHealth.component` — `redis`."""
        return "redis"

    async def check(self) -> ComponentReading:
        """`PING` within the timeout; never raises."""
        try:
            async with asyncio.timeout(self._timeout_s):
                await self._client.ping()
        except TimeoutError:
            return self._reading(HealthStatus.NOT_READY, f"no PONG within {self._timeout_s:.0f} s")
        except Exception as exc:  # an unreachable Redis is a reading, never a 500
            return self._reading(HealthStatus.NOT_READY, _reason(exc))
        return self._reading(HealthStatus.READY, None)

    def _reading(self, status: HealthStatus, detail: str | None) -> ComponentReading:
        return ComponentReading(
            component=self.component,
            status=status,
            detail=detail,
            checked_at=datetime.now(UTC),
            provider="redis",
        )


def _reason(exc: Exception) -> str:
    """A short, credential-free reason for a failed probe."""
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return text[:200]

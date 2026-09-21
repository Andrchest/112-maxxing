"""`PostgresHealthProbe` — the `postgres` component of `/api/v1/health/ready` (D8, SPEC §37).

`SELECT 1` on a connection from the engine, under a one-second timeout. That is the whole check,
and it is the right one: readiness asks whether a session could be started right now, and a
database that cannot answer `SELECT 1` within a second cannot serve a command either.

It never raises. A connection failure, an authentication failure or a timeout all become a
`NOT_READY` reading with the reason in `detail`, because `/health/ready` must answer while the
database is down — that is the one moment the endpoint earns its keep. The exception's text is put
in `detail` rather than swallowed, but it is the driver's own message and carries no credential:
the DSN, which does, is never rendered.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.application.ports.health_probe import ComponentReading
from app.domain.enums import HealthStatus

__all__ = ["PROBE_TIMEOUT_S", "PostgresHealthProbe"]

PROBE_TIMEOUT_S = 1.0
"""One second per probe: `/health/ready` is polled by the UI and must never hang on it."""


class PostgresHealthProbe:
    """`HealthProbe` for `postgres`."""

    def __init__(self, engine: AsyncEngine, *, timeout_s: float = PROBE_TIMEOUT_S) -> None:
        self._engine = engine
        self._timeout_s = timeout_s

    @property
    def component(self) -> str:
        """`ComponentHealth.component` — `postgres`."""
        return "postgres"

    async def check(self) -> ComponentReading:
        """`SELECT 1` within the timeout; never raises."""
        try:
            async with asyncio.timeout(self._timeout_s):
                async with self._engine.connect() as connection:
                    await connection.execute(sa.text("SELECT 1"))
        except TimeoutError:
            return self._reading(
                HealthStatus.NOT_READY, f"no answer within {self._timeout_s:.0f} s"
            )
        except Exception as exc:  # every driver failure is a reading, never a 500
            return self._reading(HealthStatus.NOT_READY, _reason(exc))
        return self._reading(HealthStatus.READY, None)

    def _reading(self, status: HealthStatus, detail: str | None) -> ComponentReading:
        return ComponentReading(
            component=self.component,
            status=status,
            detail=detail,
            checked_at=datetime.now(UTC),
            provider="postgresql",
        )


def _reason(exc: Exception) -> str:
    """A short, credential-free reason for a failed probe."""
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return text[:200]

"""`HealthProbe` port — one component's readiness reading (D8, SPEC §37).

SPEC §37: "Expose readiness separately from process liveness." `openapi.yaml`'s
`getHealthReady` aggregates seven named components — `postgres`, `redis`, `livekit`, `llm`, `asr`,
`tts`, `vad` — each answering `READY | WARMING | NOT_READY | FATAL`. One probe per component, all
behind this one port, so the aggregation in `app.application.health` is a pure fold over
`ComponentProbe.check()` results and knows nothing about PostgreSQL, Redis or Redis health keys.

A probe **never raises**: a component that cannot be reached is a `NOT_READY` reading with the
reason in `detail`. That is what makes `/health/ready` answerable while the database is down,
which is the one moment it matters. Each probe is given a timeout by its adapter (1 s for the
PostgreSQL and Redis probes) so a hung component cannot hang the endpoint either.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.domain.enums import HealthStatus

__all__ = ["ComponentReading", "HealthProbe"]


class ComponentReading(BaseModel):
    """One component's reading — `openapi.yaml`'s `ComponentHealth`, property names literal."""

    model_config = ConfigDict(frozen=True)

    component: str
    status: HealthStatus
    detail: str | None = None
    checked_at: datetime
    provider: str | None = None
    model_version: str | None = None
    warmup_ms: int | None = None


@runtime_checkable
class HealthProbe(Protocol):
    """Reads one named component's readiness (SPEC §37, D8)."""

    @property
    def component(self) -> str:
        """The `ComponentHealth.component` member this probe answers for."""
        ...

    async def check(self) -> ComponentReading:
        """This component's reading; never raises, never blocks past its own timeout."""
        ...

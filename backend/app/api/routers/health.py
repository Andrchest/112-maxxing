"""`health` router — `getHealthLive`, `getHealthReady` (SPEC §37, D8).

SPEC §37: "Expose readiness separately from process liveness." The two endpoints are therefore
genuinely different operations, not one with a flag:

* `/health/live` touches nothing. No database, no Redis, no probe. If this coroutine runs, the
  process is alive — that is the whole claim, and it is why an orchestrator restarting on a
  liveness failure never restarts a backend whose database merely went away;
* `/health/ready` probes every component of `ComponentHealth` and folds the readings. `200` when
  `overall` is `READY`, `503` otherwise, "so a plain HTTP health probe works" (`openapi.yaml`).

Both carry `security: []` in `openapi.yaml`: a health endpoint that needs a token is useless to
the thing that needs to check it.

The fold is deliberately small and lives here rather than in the application layer: it is nothing
but a precedence rule over `ComponentReading`s the port already produced, and `HealthStatus`
itself is a domain enum.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from fastapi import APIRouter, Response

from app.api.container import HEALTH_COMPONENTS, REQUIRED_HEALTH_COMPONENTS
from app.api.deps import ContainerDep
from app.api.schemas.health import (
    ComponentHealthSchema,
    HealthLiveResponseSchema,
    HealthReadyResponseSchema,
    component_health_schema,
)
from app.application.ports.health_probe import ComponentReading
from app.domain.enums import HealthStatus

router = APIRouter(prefix="/api/v1/health", tags=["health"])

API_VERSION = "1.0.0"
"""`HealthLiveResponse.version` — `openapi.yaml`'s `info.version`, kept in step with it by test."""

_PROCESS_STARTED_MONOTONIC = time.monotonic()
"""Drawn at import. `uptime_seconds` is a *process* duration, which is exactly what
`Clock.monotonic_ms` is for and exactly what an event offset is not (D7)."""


@router.get(
    "/live",
    operation_id="getHealthLive",
    summary="Process liveness.",
    response_model=HealthLiveResponseSchema,
    status_code=200,
)
async def get_health_live() -> HealthLiveResponseSchema:
    """Liveness only — this endpoint reads nothing and can never be made to fail by a dependency."""
    return HealthLiveResponseSchema(
        status="LIVE",
        version=API_VERSION,
        uptime_seconds=int(time.monotonic() - _PROCESS_STARTED_MONOTONIC),
    )


@router.get(
    "/ready",
    operation_id="getHealthReady",
    summary="Per-service readiness.",
    response_model=HealthReadyResponseSchema,
    status_code=200,
    responses={503: {"model": HealthReadyResponseSchema}},
)
async def get_health_ready(
    container: ContainerDep, response: Response
) -> HealthReadyResponseSchema:
    """Probe every component and fold the readings; `200` on `READY`, `503` otherwise.

    The probes run concurrently and each one has its own timeout and never raises
    (`app.application.ports.health_probe`), so a component that is down makes this endpoint report
    it — it never makes this endpoint fail.
    """
    readings = await asyncio.gather(*(probe.check() for probe in container.health_probes))
    overall = overall_status(readings, required=REQUIRED_HEALTH_COMPONENTS)
    if overall is not HealthStatus.READY:
        response.status_code = 503
    return HealthReadyResponseSchema(
        overall=overall,
        components=_ordered(readings),
        required_components=list(REQUIRED_HEALTH_COMPONENTS),
        require_inference_ready=container.settings.require_inference_ready,
        model_profile=container.settings.model_profile,  # type: ignore[arg-type]
    )


def overall_status(
    readings: Sequence[ComponentReading], *, required: Sequence[str]
) -> HealthStatus:
    """`HealthReadyResponse.overall` (`openapi.yaml`).

    "`overall` is `READY` only when every component in `required_components` is `READY`; `FATAL`
    anywhere makes `overall` `FATAL`." `FATAL` wins over everything — including over a component
    nobody required — because a latched fatal condition is the one state a restart loop must not
    be able to hide (§40.6, `voice:health:fatal`). Then `NOT_READY`, then `WARMING`.
    """
    by_component = {reading.component: reading.status for reading in readings}
    if HealthStatus.FATAL in by_component.values():
        return HealthStatus.FATAL
    required_statuses = [by_component.get(name, HealthStatus.NOT_READY) for name in required]
    if HealthStatus.NOT_READY in required_statuses:
        return HealthStatus.NOT_READY
    if HealthStatus.WARMING in required_statuses:
        return HealthStatus.WARMING
    return HealthStatus.READY


def _ordered(readings: Sequence[ComponentReading]) -> list[ComponentHealthSchema]:
    """The readings in `HEALTH_COMPONENTS` order, so the UI's rows never reshuffle."""
    by_component = {reading.component: reading for reading in readings}
    ordered = [by_component[name] for name in HEALTH_COMPONENTS if name in by_component]
    ordered.extend(reading for reading in readings if reading.component not in HEALTH_COMPONENTS)
    return [component_health_schema(reading) for reading in ordered]

"""`health` schemas — `HealthLiveResponse`, `ComponentHealth`, `HealthReadyResponse` (SPEC §37)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.ports.health_probe import ComponentReading
from app.domain.enums import HealthStatus

__all__ = [
    "ComponentHealthSchema",
    "HealthLiveResponseSchema",
    "HealthReadyResponseSchema",
    "component_health_schema",
]


class HealthLiveResponseSchema(ApiModel):
    """`openapi.yaml`'s `HealthLiveResponse` — "Liveness only, deliberately separate from
    readiness (SPEC §37)".

    It touches nothing: no database, no Redis, no probe. If this process can serialise this
    object, it is alive, and that is the entire claim.
    """

    status: Literal["LIVE"] = "LIVE"
    version: str
    uptime_seconds: int = Field(ge=0)


class ComponentHealthSchema(ApiModel):
    """`openapi.yaml`'s `ComponentHealth`."""

    component: Literal["postgres", "redis", "livekit", "llm", "asr", "tts", "vad"]
    status: HealthStatus
    detail: str | None = None
    checked_at: datetime
    provider: str | None = None
    model_version: str | None = None
    warmup_ms: int | None = None


class HealthReadyResponseSchema(ApiModel):
    """`openapi.yaml`'s `HealthReadyResponse`.

    "`overall` is `READY` only when every component in `required_components` is `READY`; `FATAL`
    anywhere makes `overall` `FATAL`." The endpoint answers `200` when `overall` is `READY` and
    `503` otherwise, "so a plain HTTP health probe works".
    """

    overall: HealthStatus
    components: list[ComponentHealthSchema]
    required_components: list[str]
    require_inference_ready: bool
    model_profile: Literal[
        "DEV_3060TI",
        "DEV_3060TI_SHARED",
        "DEV_3060TI_VOICE",
        "CPU",
        "FINAL_3080TI_12GB",
        "FINAL_3080TI_16GB",
    ]


def component_health_schema(reading: ComponentReading) -> ComponentHealthSchema:
    """`ComponentReading` → `ComponentHealth`."""
    return ComponentHealthSchema(
        component=reading.component,  # type: ignore[arg-type]  # probes answer only these seven
        status=reading.status,
        detail=reading.detail,
        checked_at=reading.checked_at,
        provider=reading.provider,
        model_version=reading.model_version,
        warmup_ms=reading.warmup_ms,
    )

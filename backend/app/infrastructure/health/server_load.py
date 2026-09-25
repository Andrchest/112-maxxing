"""`RedisServerHeartbeat` — `ServerHeartbeatReader` over `voice:health:*` (I4 E29,
`docs/hld/71-i4-wave4.md` §71.6, `docs/hld/60-inference-ops.md` §4.3).

Reads the same two Redis shapes `app.infrastructure.health.voice_health` already reads for
`/health/ready` — the per-service heartbeat frame and the `voice:health:fatal` latch — but for a
different purpose: `getServerLoad`'s GPU pair (F-23: no heartbeat carries it today, so this always
answers `GpuLoad(None, None)`, never a guess) and `listAdminAlerts`' `INFERENCE_FATAL` alert. It
imports only `app.infrastructure.health`'s public names, never `voice_health`'s own private
helpers, so E18's module stays untouched.

Never raises (matches `HealthProbe`'s own rule): an unreachable Redis reads as "no reading",
because a monitoring endpoint must not 500 when the bus it reports on is briefly down.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app.application.ports.admin_monitoring import FatalLatch, GpuLoad
from app.infrastructure.health import INFERENCE_SERVICES, VOICE_HEALTH_FATAL_KEY, voice_health_key

__all__ = ["RedisServerHeartbeat"]

#: `listAdminAlerts`' `INFERENCE_FATAL.detail_ru` when the latch cannot be parsed at all — the
#: same "a latch that cannot be read is exactly the condition that must not be hidden" rule
#: `docs/hld/60-inference-ops.md` §4.3 states for the probes, reused for the alert's wording.
_UNPARSEABLE_DETAIL_RU = "Голосовой сервис в состоянии FATAL (подробности недоступны)."


class RedisServerHeartbeat:
    """`ServerHeartbeatReader` — `voice:health:{service}` for the GPU pair, `voice:health:fatal`
    for the alert."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def gpu_load(self) -> GpuLoad:
        for service in INFERENCE_SERVICES:
            frame = await self._frame_of(service)
            if frame is None:
                continue
            used, total = frame.get("gpu_memory_used_mb"), frame.get("gpu_memory_total_mb")
            if isinstance(used, int | float) and isinstance(total, int | float):
                return GpuLoad(used_mb=float(used), total_mb=float(total))
        return GpuLoad(used_mb=None, total_mb=None)

    async def fatal_latch(self) -> FatalLatch:
        try:
            raw = await self._client.get(VOICE_HEALTH_FATAL_KEY)
        except Exception:  # an unreachable Redis is "not latched", never a 500
            return FatalLatch(latched=False, detail_ru="")
        if raw is None:
            return FatalLatch(latched=False, detail_ru="")
        return FatalLatch(latched=True, detail_ru=_detail_ru_of(raw))

    async def _frame_of(self, service: str) -> dict[str, Any] | None:
        try:
            raw = await self._client.get(voice_health_key(service))
        except Exception:
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None


def _detail_ru_of(raw: str | bytes) -> str:
    """A Russian sentence naming the latched service and its `detail`, if the latch parses."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return _UNPARSEABLE_DETAIL_RU
    if not isinstance(payload, dict):
        return _UNPARSEABLE_DETAIL_RU
    service = payload.get("service")
    detail = payload.get("detail")
    if not isinstance(service, str) or not service:
        return _UNPARSEABLE_DETAIL_RU
    sentence = f"Голосовой сервис «{service}» в состоянии FATAL."
    if isinstance(detail, str) and detail:
        sentence += f" {detail}"
    return sentence

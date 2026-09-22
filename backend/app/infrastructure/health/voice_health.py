"""The backend half of the inference heartbeat (HLD `60-inference-ops.md` §4.3, D8, SPEC §37).

The voice-agent process is the **writer**: it warms `vad`, `asr`, `llm` and `tts` in that order
and publishes each transition as `SET voice:health:{service} <json> EX 15`, refreshed every five
seconds. This module is the **reader**, and it is deliberately the only one:

* `VoiceHealthProbe(client, service)` is the `HealthProbe` for one inference service. A **missing
  key is `NOT_READY`**, never `READY` — §4.3's own sentence, and the reason a crashed voice-agent
  is visible without a second liveness protocol;
* `RedisInferenceReadiness` is the `InferenceReadiness` adapter `startSession` consults: ready iff
  every one of the four services reports `READY`;
* `RedisInferenceFatalLatch` clears `voice:health:fatal`, the un-expiring mirror of a FATAL state
  that exists so "a restart loop cannot make a fatal condition look transient". Only
  `clearInferenceFatal` deletes it, and deleting it publishes a transition on `voice:health` so the
  instructor's log records that a human cleared it.

Nothing here writes a `voice:health:*` key: the backend never invents a readiness it cannot
observe, which is the precise failure SPEC §37 exists to prevent.

**The `voice:health:fatal` payload.** §4.3 fixes the per-service frame literally but says only
that FATAL is "additionally mirrored to `voice:health:fatal`". This module reads that key
tolerantly and errs towards FATAL, because a latch that cannot be read is exactly the condition
that must not be hidden: a JSON object naming a `service` latches that service; a JSON object
without one, a bare service name, and an unparsable value latch **every** service. See §4.3's
"read by the backend" paragraph, extended by E18-B.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from redis.asyncio import Redis

from app.application.ports.health_probe import ComponentReading
from app.domain.enums import HealthStatus
from app.infrastructure.health.postgres_probe import PROBE_TIMEOUT_S

__all__ = [
    "INFERENCE_SERVICES",
    "VOICE_HEALTH_CHANNEL",
    "VOICE_HEALTH_FATAL_KEY",
    "VOICE_HEALTH_PREFIX",
    "RedisInferenceFatalLatch",
    "RedisInferenceReadiness",
    "VoiceHealthFrame",
    "VoiceHealthProbe",
    "voice_health_key",
]

logger = logging.getLogger(__name__)

VOICE_HEALTH_PREFIX = "voice:health:"
"""§4.3: `voice:health:{service}`, written by the voice-agent with `EX 15`."""

VOICE_HEALTH_FATAL_KEY = "voice:health:fatal"
"""§4.3: the un-expiring FATAL mirror, deleted only by `clearInferenceFatal`."""

VOICE_HEALTH_CHANNEL = "voice:health"
"""§4.3: the pub/sub channel every transition is announced on (`40-realtime-protocol.md` §40.6)."""

INFERENCE_SERVICES: tuple[str, ...] = ("llm", "asr", "tts", "vad")
"""The four services of §4.1, in `ComponentHealth.component` order."""

MISSING_HEARTBEAT_DETAIL = "no heartbeat from voice-agent"
"""§4.3, and `openapi.yaml`'s `ComponentHealth.detail`, literally: what a missing key reads as."""


def voice_health_key(service: str) -> str:
    """`voice:health:{service}` — the one place this key is spelled."""
    return f"{VOICE_HEALTH_PREFIX}{service}"


class VoiceHealthFrame(BaseModel):
    """The JSON value of `voice:health:{service}` (§4.3, property names literal).

    `extra="ignore"`: the writer is another process on its own release cadence, and a frame that
    grew a field must still be readable here. An unknown `state` is `NOT_READY` — the same
    direction as a missing key, never `READY`.
    """

    model_config = ConfigDict(extra="ignore")

    state: str
    profile: str | None = None
    provider: str | None = None
    model_version: str | None = None
    updated_at: str | None = None
    detail: str | None = None
    warmup_ms: int | None = None

    def status(self) -> HealthStatus:
        """`state` as a `HealthStatus`; anything unrecognised is `NOT_READY`."""
        try:
            return HealthStatus(self.state)
        except ValueError:
            return HealthStatus.NOT_READY


class VoiceHealthProbe:
    """`HealthProbe` for one of `llm`, `asr`, `tts`, `vad` — reads `voice:health:{service}`.

    Like every probe it **never raises** (`app.application.ports.health_probe`): an unreachable
    Redis is a `NOT_READY` reading with the reason in `detail`, so `/health/ready` still answers
    while the bus is down.
    """

    def __init__(self, client: Redis, service: str, *, timeout_s: float = PROBE_TIMEOUT_S) -> None:
        self._client = client
        self._service = service
        self._timeout_s = timeout_s

    @property
    def component(self) -> str:
        """`ComponentHealth.component` — the service this probe answers for."""
        return self._service

    async def check(self) -> ComponentReading:
        """The service's reading: FATAL if latched, else the heartbeat frame, else `NOT_READY`."""
        try:
            async with asyncio.timeout(self._timeout_s):
                fatal_raw = await self._client.get(VOICE_HEALTH_FATAL_KEY)
                raw = await self._client.get(voice_health_key(self._service))
        except TimeoutError:
            return self._reading(
                HealthStatus.NOT_READY, f"no answer from redis within {self._timeout_s:.0f} s"
            )
        except Exception as exc:  # an unreachable Redis is a reading, never a 500
            return self._reading(HealthStatus.NOT_READY, _reason(exc))

        if fatal_raw is not None and _fatal_covers(fatal_raw, self._service):
            return self._reading(HealthStatus.FATAL, _fatal_detail(fatal_raw), frame=None)

        if raw is None:
            return self._reading(HealthStatus.NOT_READY, MISSING_HEARTBEAT_DETAIL)
        try:
            frame = VoiceHealthFrame.model_validate_json(raw)
        except ValidationError:
            logger.warning(
                "unreadable %s frame; reporting NOT_READY", voice_health_key(self._service)
            )
            return self._reading(
                HealthStatus.NOT_READY, f"{MISSING_HEARTBEAT_DETAIL}: unreadable frame"
            )
        return self._reading(frame.status(), frame.detail, frame=frame)

    def _reading(
        self,
        status: HealthStatus,
        detail: str | None,
        *,
        frame: VoiceHealthFrame | None = None,
    ) -> ComponentReading:
        return ComponentReading(
            component=self._service,
            status=status,
            detail=detail,
            checked_at=datetime.now(UTC),
            provider=frame.provider if frame is not None else None,
            model_version=frame.model_version if frame is not None else None,
            warmup_ms=frame.warmup_ms if frame is not None else None,
        )


class RedisInferenceReadiness:
    """`InferenceReadiness` over the four heartbeats (D8) — ready iff all four say `READY`.

    The same readings `/health/ready` folds, asked for the one boolean `startSession`'s
    `guard_inference_ready` needs. `False` on any failure, which is what makes an unreachable
    Redis refuse a demo start rather than wave it through.
    """

    def __init__(
        self,
        client: Redis,
        *,
        services: tuple[str, ...] = INFERENCE_SERVICES,
        timeout_s: float = PROBE_TIMEOUT_S,
    ) -> None:
        self._probes = tuple(
            VoiceHealthProbe(client, service, timeout_s=timeout_s) for service in services
        )

    async def is_ready(self) -> bool:
        """`True` when every inference service reports `READY` (D8)."""
        readings = await asyncio.gather(*(probe.check() for probe in self._probes))
        return all(reading.status is HealthStatus.READY for reading in readings)


class RedisInferenceFatalLatch:
    """`InferenceFatalLatch` — deletes `voice:health:fatal` and announces it on `voice:health`.

    The announcement is what turns an admin's click into an `INFERENCE_HEALTH_CHANGED` on every
    ACTIVE session (`openapi.yaml`'s `x-emits` for `clearInferenceFatal`): this adapter publishes
    the transition, the subscriber of `app.application.inference_health` appends it. Clearing the
    latch does **not** make anything READY — the next heartbeat decides that.
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def clear(self) -> bool:
        """Delete the latch; `True` when one was actually latched."""
        raw = await self._client.get(VOICE_HEALTH_FATAL_KEY)
        deleted = await self._client.delete(VOICE_HEALTH_FATAL_KEY)
        if not deleted:
            return False
        service = _fatal_service(raw) if raw is not None else None
        await self._client.publish(
            VOICE_HEALTH_CHANNEL,
            _transition_json(
                service=service or "llm",
                previous="FATAL",
                new="NOT_READY",
                detail="fatal state cleared by an administrator",
            ),
        )
        return True


def _transition_json(*, service: str, previous: str, new: str, detail: str) -> str:
    """§4.3's pub/sub message: `{service, from, to, detail, at}`."""
    return json.dumps(
        {
            "service": service,
            "from": previous,
            "to": new,
            "detail": detail,
            "at": datetime.now(UTC).isoformat(),
        }
    )


def _fatal_payload(raw: str | bytes) -> dict[str, Any] | None:
    """`voice:health:fatal` as a mapping, or `None` when it is not a JSON object."""
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _fatal_service(raw: str | bytes) -> str | None:
    """Which service the latch names, if it names one (see this module's docstring)."""
    payload = _fatal_payload(raw)
    if payload is not None:
        service = payload.get("service")
        return service if isinstance(service, str) else None
    text = raw.decode() if isinstance(raw, bytes) else raw
    return text.strip() if text.strip() in INFERENCE_SERVICES else None


def _fatal_covers(raw: str | bytes, service: str) -> bool:
    """Does the latch apply to `service`? An unreadable latch applies to all of them."""
    named = _fatal_service(raw)
    return named is None or named == service


def _fatal_detail(raw: str | bytes) -> str:
    """The latch's own `detail`, or a documented default."""
    payload = _fatal_payload(raw)
    detail = payload.get("detail") if payload is not None else None
    if isinstance(detail, str) and detail:
        return detail
    return "fatal inference state latched in voice:health:fatal"


def _reason(exc: Exception) -> str:
    """A short, credential-free reason for a failed probe (as in `redis_probe`)."""
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return text[:200]

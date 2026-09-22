"""Readiness probes (D8, SPEC §37, `openapi.yaml` `getHealthReady`).

`openapi.yaml` names seven components and all seven are now probed for real:

* `postgres`, `redis` and `livekit` (E11) answer from their own adapters here;
* `llm`, `asr`, `tts` and `vad` answer from `voice:health:{service}`, the heartbeat the
  voice-agent process writes (`60-inference-ops.md` §4.3) — `voice_health.py`. A **missing key is
  `NOT_READY`**, never `READY`: a probe that invented `READY` would let a demo session start
  against an inference stack that is not there, the precise failure SPEC §37 exists to prevent.

The same four readings answer `InferenceReadiness` for `startSession`
(`RedisInferenceReadiness`), and `voice:health:fatal` — the latch a restart loop must not be able
to hide — is read by every probe and cleared only through `RedisInferenceFatalLatch`.
"""

from __future__ import annotations

from app.infrastructure.health.livekit_probe import LiveKitHealthProbe
from app.infrastructure.health.postgres_probe import PROBE_TIMEOUT_S, PostgresHealthProbe
from app.infrastructure.health.redis_probe import RedisHealthProbe
from app.infrastructure.health.voice_health import (
    INFERENCE_SERVICES,
    VOICE_HEALTH_CHANNEL,
    VOICE_HEALTH_FATAL_KEY,
    VOICE_HEALTH_PREFIX,
    RedisInferenceFatalLatch,
    RedisInferenceReadiness,
    VoiceHealthFrame,
    VoiceHealthProbe,
    voice_health_key,
)
from app.infrastructure.health.voice_health_subscriber import VoiceHealthSubscriber

__all__ = [
    "INFERENCE_SERVICES",
    "PROBE_TIMEOUT_S",
    "VOICE_HEALTH_CHANNEL",
    "VOICE_HEALTH_FATAL_KEY",
    "VOICE_HEALTH_PREFIX",
    "LiveKitHealthProbe",
    "PostgresHealthProbe",
    "RedisHealthProbe",
    "RedisInferenceFatalLatch",
    "RedisInferenceReadiness",
    "VoiceHealthFrame",
    "VoiceHealthProbe",
    "VoiceHealthSubscriber",
    "voice_health_key",
]

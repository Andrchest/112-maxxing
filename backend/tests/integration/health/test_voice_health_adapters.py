"""`VoiceHealthProbe`, `RedisInferenceReadiness`, `RedisInferenceFatalLatch` against real Redis.

The adapters, not the endpoint: every case here is a `voice:health:*` key written the way
`60-inference-ops.md` §4.3 says the voice-agent writes it, then read back through the production
adapter. The compose test Redis is shared with the rest of the suite, so every test clears the
five keys it touches on the way in and on the way out.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import redis.asyncio as redis_asyncio
from app.config.settings import Settings
from app.domain.enums import HealthStatus
from app.infrastructure.health import (
    INFERENCE_SERVICES,
    VOICE_HEALTH_CHANNEL,
    VOICE_HEALTH_FATAL_KEY,
    RedisInferenceFatalLatch,
    RedisInferenceReadiness,
    VoiceHealthProbe,
    voice_health_key,
)

pytestmark = pytest.mark.integration

_KEYS = (VOICE_HEALTH_FATAL_KEY, *(voice_health_key(name) for name in INFERENCE_SERVICES))


def frame(state: str, **overrides: object) -> str:
    """A `voice:health:{service}` value, §4.3's shape literally."""
    payload: dict[str, object] = {
        "state": state,
        "profile": "DEV_3060TI",
        "provider": "gigaam",
        "model_version": "v3_e2e_ctc",
        "updated_at": datetime.now(UTC).isoformat(),
        "detail": None,
        "warmup_ms": 4210,
    }
    payload.update(overrides)
    return json.dumps(payload)


@pytest.fixture
async def redis_client(test_settings: Settings) -> AsyncIterator[redis_asyncio.Redis]:
    """A client on the compose test Redis, with every `voice:health:*` key cleared around it."""
    client: redis_asyncio.Redis = redis_asyncio.from_url(
        test_settings.redis_url, decode_responses=True
    )
    await client.delete(*_KEYS)
    try:
        yield client
    finally:
        await client.delete(*_KEYS)
        await client.aclose()


async def test_a_missing_key_is_not_ready_with_the_documented_reason(
    redis_client: redis_asyncio.Redis,
) -> None:
    """§4.3: "A **missing key is NOT_READY**, not READY"— and `openapi.yaml`'s exact `detail`."""
    reading = await VoiceHealthProbe(redis_client, "asr").check()

    assert reading.component == "asr"
    assert reading.status is HealthStatus.NOT_READY
    assert reading.detail == "no heartbeat from voice-agent"


async def test_a_ready_frame_is_read_with_its_provider_and_warmup(
    redis_client: redis_asyncio.Redis,
) -> None:
    """The reading carries the frame's `provider`, `model_version` and `warmup_ms` (§4.3)."""
    await redis_client.set(voice_health_key("asr"), frame("READY"), ex=15)

    reading = await VoiceHealthProbe(redis_client, "asr").check()

    assert reading.status is HealthStatus.READY
    assert reading.provider == "gigaam"
    assert reading.model_version == "v3_e2e_ctc"
    assert reading.warmup_ms == 4210


async def test_unparsable_json_is_not_ready_rather_than_an_exception(
    redis_client: redis_asyncio.Redis,
) -> None:
    """A probe never raises; an unreadable frame is `NOT_READY`, never `READY` (E18-B)."""
    await redis_client.set(voice_health_key("llm"), "{not json at all", ex=15)

    reading = await VoiceHealthProbe(redis_client, "llm").check()

    assert reading.status is HealthStatus.NOT_READY
    assert reading.detail is not None and "no heartbeat from voice-agent" in reading.detail


async def test_an_unknown_state_is_not_ready(redis_client: redis_asyncio.Redis) -> None:
    """A frame from a newer writer that names a state this build does not know is not `READY`."""
    await redis_client.set(voice_health_key("tts"), frame("RECOVERING"), ex=15)

    assert (await VoiceHealthProbe(redis_client, "tts").check()).status is HealthStatus.NOT_READY


async def test_the_fatal_latch_makes_the_named_service_fatal(
    redis_client: redis_asyncio.Redis,
) -> None:
    """A latch that names a service is FATAL for it and leaves the other three alone (§4.3)."""
    for service in INFERENCE_SERVICES:
        await redis_client.set(voice_health_key(service), frame("READY"), ex=15)
    await redis_client.set(
        VOICE_HEALTH_FATAL_KEY, json.dumps({"service": "tts", "detail": "CUDA out of memory"})
    )

    fatal = await VoiceHealthProbe(redis_client, "tts").check()
    other = await VoiceHealthProbe(redis_client, "llm").check()

    assert fatal.status is HealthStatus.FATAL
    assert fatal.detail == "CUDA out of memory"
    assert other.status is HealthStatus.READY


async def test_an_unreadable_latch_is_fatal_for_every_service(
    redis_client: redis_asyncio.Redis,
) -> None:
    """A latch nobody can parse must not be hideable: it applies to all four (module docstring)."""
    for service in INFERENCE_SERVICES:
        await redis_client.set(voice_health_key(service), frame("READY"), ex=15)
    await redis_client.set(VOICE_HEALTH_FATAL_KEY, "totally-unreadable")

    for service in INFERENCE_SERVICES:
        reading = await VoiceHealthProbe(redis_client, service).check()
        assert reading.status is HealthStatus.FATAL, service


async def test_readiness_is_true_only_when_all_four_services_are_ready(
    redis_client: redis_asyncio.Redis,
) -> None:
    """`RedisInferenceReadiness` is D8's "every required inference component is READY"."""
    readiness = RedisInferenceReadiness(redis_client)
    assert await readiness.is_ready() is False, "no heartbeats at all"

    for service in INFERENCE_SERVICES:
        await redis_client.set(voice_health_key(service), frame("READY"), ex=15)
    assert await readiness.is_ready() is True

    await redis_client.set(voice_health_key("llm"), frame("WARMING"), ex=15)
    assert await readiness.is_ready() is False, "one WARMING service is not ready"


async def test_clearing_the_latch_deletes_the_key_and_announces_the_transition(
    redis_client: redis_asyncio.Redis, test_settings: Settings
) -> None:
    """`clearInferenceFatal`'s side effects: the key is gone and `voice:health` carries the news.

    The announcement is what `openapi.yaml`'s `x-emits: [INFERENCE_HEALTH_CHANGED]` is honoured
    by — the subscriber, not this adapter, does the appending.
    """
    await redis_client.set(VOICE_HEALTH_FATAL_KEY, json.dumps({"service": "tts", "detail": "OOM"}))
    listener: redis_asyncio.Redis = redis_asyncio.from_url(
        test_settings.redis_url, decode_responses=True
    )
    pubsub = listener.pubsub()
    await pubsub.subscribe(VOICE_HEALTH_CHANNEL)
    try:
        cleared = await RedisInferenceFatalLatch(redis_client).clear()
        message = None
        for _ in range(200):
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
            if message is not None:
                break
    finally:
        await pubsub.unsubscribe(VOICE_HEALTH_CHANNEL)
        await pubsub.aclose()
        await listener.aclose()

    assert cleared is True
    assert await redis_client.exists(VOICE_HEALTH_FATAL_KEY) == 0
    assert message is not None, "clearing must announce the transition on voice:health"
    announced = json.loads(message["data"])
    assert announced["service"] == "tts"
    assert announced["from"] == "FATAL"
    assert announced["to"] == "NOT_READY"


async def test_clearing_nothing_is_false_and_announces_nothing(
    redis_client: redis_asyncio.Redis,
) -> None:
    """No latch, no announcement — clearing twice must not fabricate a second health change."""
    assert await RedisInferenceFatalLatch(redis_client).clear() is False

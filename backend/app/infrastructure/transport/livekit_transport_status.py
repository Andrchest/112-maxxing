"""`LiveKitTransportStatus` — the `SIM_CALL_TRANSPORT=livekit` readiness adapter (D9, §10.8).

Two facts, both required, because `ring` means "start a real call" (see
`app.application.ports.call_transport_status` for why the guard is not "the caller joined"):

1. **the LiveKit server answers.** A plain HTTP `GET` against the server's origin under a
   one-second timeout. LiveKit's signalling is WebSocket, but the same process serves HTTP on the
   same port and answers *something* to a bare `GET` — and "something, in under a second" is
   exactly the fact wanted here. Any status code counts: an SFU that replies `404` is an SFU that
   is up, while a connection refusal, a DNS failure or a timeout is not. Nothing about the room is
   inspected, so this adapter needs no API call and no SDK;
2. **the voice-agent is alive.** §40.6's `voice:health:vad` key exists and its `state` is `READY`
   (`60-inference-ops.md` §4.3: the key is written with `EX 15` and heartbeated every 5 s, and "a
   missing key is `NOT_READY`, never `READY`"). `vad` is the right service of the four to ask
   about: it is the first stage of the turn pipeline and the one the agent warms up first, so a
   `READY` VAD means the agent process is running and past warm-up.

It never raises. Every failure — an unreachable server, an unreachable Redis, a key holding
something that is not JSON — is `False`, which denies `ring`, which is the conservative answer.
The `ws://` / `wss://` URL of `SIM_LIVEKIT_URL` is mapped to `http://` / `https://` for the probe;
no credential is ever sent, so nothing here can leak the API secret.
"""

from __future__ import annotations

import json
import logging

import httpx
from redis.asyncio import Redis

from app.domain.common.ids import SessionId
from app.domain.enums import HealthStatus

__all__ = ["HEALTH_KEY", "PROBE_TIMEOUT_S", "LiveKitTransportStatus", "http_origin_of"]

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 1.0
"""One second, like the PostgreSQL and Redis probes: a hung SFU must not hang a tick."""

HEALTH_KEY = "voice:health:vad"
"""§40.6's voice-agent heartbeat key this adapter reads."""

_SCHEME_MAP = {"ws": "http", "wss": "https"}


def http_origin_of(livekit_url: str) -> str:
    """`ws://host:7880` -> `http://host:7880`; an already-HTTP URL passes through unchanged."""
    scheme, separator, rest = livekit_url.partition("://")
    if not separator:
        return livekit_url
    return f"{_SCHEME_MAP.get(scheme.lower(), scheme)}://{rest}"


class LiveKitTransportStatus:
    """`CallTransportStatus` for `SIM_CALL_TRANSPORT=livekit`."""

    def __init__(
        self,
        livekit_url: str,
        redis: Redis,
        *,
        timeout_s: float = PROBE_TIMEOUT_S,
        health_key: str = HEALTH_KEY,
    ) -> None:
        self._origin = http_origin_of(livekit_url)
        self._redis = redis
        self._timeout_s = timeout_s
        self._health_key = health_key

    async def transport_ready(self, session_id: SessionId) -> bool:
        """`True` only when the SFU answers *and* the voice-agent heartbeat says `READY`."""
        return await self._server_reachable() and await self._agent_ready()

    async def _server_reachable(self) -> bool:
        """Any HTTP answer from the LiveKit origin within the timeout. Never raises."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                await client.get(self._origin)
        except Exception:  # unreachable, refused, timed out — all one answer (§10.8)
            logger.debug("LiveKit server at %s did not answer", self._origin)
            return False
        return True

    async def _agent_ready(self) -> bool:
        """`voice:health:vad` exists and holds `state == "READY"`. Never raises."""
        try:
            raw = await self._redis.get(self._health_key)
        except Exception:  # an unreachable Redis is a missing heartbeat (§40.6)
            return False
        if raw is None:
            return False
        if isinstance(raw, bytes):  # a client built without `decode_responses=True`
            raw = raw.decode("utf-8", errors="replace")
        try:
            document = json.loads(raw)
        except ValueError:
            return False
        return isinstance(document, dict) and document.get("state") == HealthStatus.READY.value

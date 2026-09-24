"""The SIP gateway's two links to the rest of the simulator (I3 E6e, HLD 80 §80.2.3, §80.3.7).

* **The backend** (`TelephonyBackend`): the four `/api/v1/telephony/*` operations, called with the
  gateway's service credential `SIM_SIP_GATEWAY_SECRET` (header `X-Sip-Gateway-Secret`,
  [credential redacted] in every document): `dial` (a softphone dialled — `dialFromSip`),
  `report_leg` (`reportSipLeg`: `UP` / `FAILED` / `DOWN`), `get_call` (`getTelephonyCall`, the
  self-healing re-read) and `credential` (`getSipCredential`, the per-user HA1 of migration
  `0015`). `HttpTelephonyBackend` is the real one (httpx); the gate uses an in-process fake.
* **Redis** (`RedisTelephonySignals`): `voice:join` (acted on only for `endpoint: SIP` — the gateway
  rings that user's softphone), `voice:cancel:{session_id}` and `session:{session_id}:events` (a
  `DDS_CALL_ANSWERED` sends the softphone its `200 OK`, a `DDS_CALL_ENDED` its `BYE`). The two
  per-session channels are pattern-subscribed (`voice:cancel:*`, `session:*:events`) and every
  message not about a call this gateway bridges is dropped at once; Redis loss is covered by the
  gateway's periodic `get_call` re-read while it waits (HLD 40 §40.6: a signal is liveness only).
  `RedisBindingMirror` writes `sip:binding:{username}` on every REGISTER (HLD 40 §40.6 row).

Nothing here logs the service credential, an HA1 or a token.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from voice_agent.transport.sip.registrar import (
    Binding,
    Credential,
    CredentialUnavailableError,
)

__all__ = [
    "SIP_GATEWAY_SECRET_HEADER",
    "BackendCredentials",
    "BackendUnavailableError",
    "DialRefused",
    "DialedCall",
    "HttpTelephonyBackend",
    "RedisBindingMirror",
    "RedisTelephonySignals",
    "TelephonyBackend",
    "TelephonyListener",
    "sip_status_for_problem",
]

logger = logging.getLogger(__name__)

SIP_GATEWAY_SECRET_HEADER = "X-Sip-Gateway-Secret"
_JOIN_CHANNEL = "voice:join"
_CANCEL_PATTERN = "voice:cancel:*"
_EVENTS_PATTERN = "session:*:events"


@dataclass(frozen=True)
class DialedCall:
    """`SipDialResponse`: the call a softphone's number became."""

    call_id: str
    session_id: str
    room_name: str
    kind: str
    persona_id: str | None = None


class DialRefused(Exception):
    """The backend refused the dial; `sip_status` is what the softphone is answered."""

    def __init__(self, sip_status: int, code: str | None = None) -> None:
        super().__init__(f"dial refused: SIP {sip_status} ({code})")
        self.sip_status = sip_status
        self.code = code


class BackendUnavailableError(RuntimeError):
    """The backend could not be reached or answered 5xx / 401."""


def sip_status_for_problem(http_status: int, code: str | None) -> int:
    """The SIP final response for a refused `dialFromSip` (HLD 80 §80.2.3 step 2).

    `404 DIAL_NUMBER_UNKNOWN` ⇒ `404`; `409 NO_ACTIVE_DDS_SESSION` ⇒ `480`; `409 DDS_LINE_BUSY` ⇒
    `486 Busy Here`; any other `409` (the phone not offered right now) ⇒ `480`; `403` (unknown or
    retired user, another trainee's leg) ⇒ `403`; everything else ⇒ `503`.
    """
    if http_status == 404:
        return 404
    if http_status == 409:
        return 486 if code == "DDS_LINE_BUSY" else 480
    if http_status == 403:
        return 403
    return 503


class TelephonyBackend(Protocol):
    """The backend's `telephony` operations, as the gateway uses them."""

    async def dial(self, sip_user: str, dialed: str, sip_call_id: str) -> DialedCall:
        """`dialFromSip`; raises `DialRefused` or `BackendUnavailableError`."""
        ...

    async def report_leg(self, call_id: str, state: str, sip_status: int | None = None) -> str:
        """`reportSipLeg`; returns the call's `state` after the report."""
        ...

    async def get_call(self, call_id: str) -> dict[str, Any]:
        """`getTelephonyCall` — the `DdsCallView`."""
        ...

    async def credential(self, username: str) -> Credential | None:
        """`getSipCredential`: `None` for an unknown user; raises `CredentialUnavailableError`."""
        ...


class HttpTelephonyBackend:
    """`TelephonyBackend` over httpx (`SIM_SIP_BACKEND_URL`, `SIM_SIP_GATEWAY_SECRET`)."""

    def __init__(self, base_url: str, secret: str, *, timeout_s: float = 5.0) -> None:
        import httpx

        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={SIP_GATEWAY_SECRET_HEADER: secret},
            timeout=timeout_s,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        import httpx

        try:
            return await self._client.request(method, f"/api/v1/telephony{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise BackendUnavailableError(f"{method} {path}: {type(exc).__name__}") from exc

    async def dial(self, sip_user: str, dialed: str, sip_call_id: str) -> DialedCall:
        response = await self._request(
            "POST",
            "/dial",
            json={"sip_user": sip_user, "dialed": dialed, "sip_call_id": sip_call_id},
        )
        if response.status_code == 201:
            body = response.json()
            return DialedCall(
                call_id=str(body["call_id"]),
                session_id=str(body["session_id"]),
                room_name=str(body["room_name"]),
                kind=str(body["kind"]),
                persona_id=body.get("persona_id"),
            )
        code = _problem_code(response)
        if response.status_code == 401 or response.status_code >= 500:
            raise BackendUnavailableError(f"dialFromSip answered {response.status_code}")
        raise DialRefused(sip_status_for_problem(response.status_code, code), code)

    async def report_leg(self, call_id: str, state: str, sip_status: int | None = None) -> str:
        body: dict[str, Any] = {"state": state}
        if sip_status is not None:
            body["sip_status"] = sip_status
        response = await self._request("POST", f"/calls/{call_id}/leg", json=body)
        if response.status_code != 200:
            raise BackendUnavailableError(f"reportSipLeg answered {response.status_code}")
        return str(response.json()["state"])

    async def get_call(self, call_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/calls/{call_id}")
        if response.status_code != 200:
            raise BackendUnavailableError(f"getTelephonyCall answered {response.status_code}")
        view: dict[str, Any] = response.json()
        return view

    async def credential(self, username: str) -> Credential | None:
        try:
            response = await self._request("GET", f"/sip-credentials/{username}")
        except BackendUnavailableError as exc:
            raise CredentialUnavailableError(str(exc)) from exc
        if response.status_code == 200:
            return Credential(ha1=str(response.json()["ha1"]))
        if response.status_code == 404:
            return Credential()
        if response.status_code == 403:
            return None
        raise CredentialUnavailableError(f"getSipCredential answered {response.status_code}")


def _problem_code(response: Any) -> str | None:
    with contextlib.suppress(Exception):
        code = response.json().get("code")
        return None if code is None else str(code)
    return None


class BackendCredentials:
    """The registrar's `CredentialSource` over the backend (E6e decision 3 + migration `0015`).

    A short in-process cache (`ttl_s`) keeps a softphone's REGISTER refresh and the INVITE right
    after it from asking twice; it is never persisted and never logged.
    """

    def __init__(self, backend: TelephonyBackend, *, ttl_s: float = 10.0) -> None:
        self._backend = backend
        self._ttl_s = ttl_s
        self._cache: dict[str, tuple[float, Credential | None]] = {}

    async def lookup(self, username: str) -> Credential | None:
        now = time.monotonic()
        cached = self._cache.get(username)
        if cached is not None and now - cached[0] < self._ttl_s:
            return cached[1]
        credential = await self._backend.credential(username)
        self._cache[username] = (now, credential)
        return credential


class RedisBindingMirror:
    """`sip:binding:{username}` over Redis — the registrar's `on_bind` / `on_unbind` hooks."""

    def __init__(self, writer: Any, now: Callable[[], float] = time.monotonic) -> None:
        self._writer = writer  # `app.infrastructure.transport.redis_sip_bindings.RedisSipBindings`
        self._now = now

    async def on_bind(self, binding: Binding) -> None:
        ttl = max(1, round(binding.expires_at - self._now()))
        await self._writer.bind(
            binding.username,
            contact=binding.contact,
            expires_at=time.time() + ttl,
            ttl_s=ttl,
        )

    async def on_unbind(self, username: str) -> None:
        await self._writer.unbind(username)


class TelephonyListener(Protocol):
    """What the gateway does with a Redis signal (implemented by `SipGateway`)."""

    def on_join(self, payload: dict[str, Any]) -> None: ...

    def on_call_answered(self, call_id: str) -> None: ...

    def on_call_ended(self, call_id: str, reason: str) -> None: ...

    def bridges(self, call_id: str) -> bool: ...


@dataclass
class RedisTelephonySignals:
    """Subscribes the gateway to `voice:join`, `voice:cancel:*` and `session:*:events`."""

    redis: Any
    listener: TelephonyListener
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="sip-telephony-signals")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task

    async def _run(self) -> None:
        while True:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe(_JOIN_CHANNEL)
                await pubsub.psubscribe(_CANCEL_PATTERN, _EVENTS_PATTERN)
                async for message in pubsub.listen():
                    if message.get("type") not in ("message", "pmessage"):
                        continue
                    self.dispatch(_text(message.get("channel")), message.get("data"))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("SIP gateway: Redis subscription lost; retrying in 2 s")
                await asyncio.sleep(2.0)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()

    def dispatch(self, channel: str, raw: Any) -> None:
        """Route one message to the listener (public so the gate can drive it without Redis)."""
        try:
            data = json.loads(_text(raw))
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        if channel == _JOIN_CHANNEL:
            if data.get("endpoint") == "SIP" and data.get("sip_user"):
                self.listener.on_join(data)
            return
        if channel.startswith("voice:cancel:"):
            call_id = str(data.get("call_id", "")).lower()
            if call_id and self.listener.bridges(call_id):
                self.listener.on_call_ended(call_id, str(data.get("reason", "ABORT")))
            return
        if channel.startswith("session:") and channel.endswith(":events"):
            payload = data.get("payload") or {}
            call_id = str(payload.get("call_id", "")).lower() if isinstance(payload, dict) else ""
            if not call_id or not self.listener.bridges(call_id):
                return
            event_type = data.get("event_type")
            if event_type == "DDS_CALL_ANSWERED":
                self.listener.on_call_answered(call_id)
            elif event_type == "DDS_CALL_ENDED":
                self.listener.on_call_ended(call_id, str(payload.get("reason", "ABORT")))


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "" if value is None else str(value)

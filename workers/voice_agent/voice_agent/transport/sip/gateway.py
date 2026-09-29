"""The SIP gateway process core (HLD 80 §80.2.1 `gateway.py`, §80.2.3, D22, D27).

UDP + TCP listeners on `SIM_SIP_PORT`; the registrar; the UAS side of every call (INVITE →
100/180/200, ACK, BYE, CANCEL, re-INVITE answered with the same SDP, OPTIONS); dial handling
through a `Router`; health `GET /health` on `127.0.0.1:SIM_SIP_GATEWAY_HTTP_PORT`; a `BYE` to
every live call on `stop()` (SIGTERM, `voice_agent.sip_gateway`).

Dial handling in E6a (`default_router`): `999` is the gateway-local **echo** — no backend, no
room; every RTP payload is sent straight back re-stamped with the gateway's own SSRC/sequence/
timestamp, so it is the interop and latency probe (80 §80.2.3 step 6). A `Route` of kind `BRIDGE`
connects the call to a `RoomPort` (`FakeRoomBridge` in the gate, `LiveKitRoomBridge` for real):
inbound RTP goes through the jitter buffer on a 20 ms playout clock into the room; the room's audio
goes out as RTP.

**The ДДС phone (I3 E6e, §80.2.3 steps 2–5).** With a `TelephonyBackend` (`SIM_SIP_BACKEND_URL`),
every number but `999` is the backend's (`dialFromSip`): the gateway answers `100 Trying`, asks
the backend, maps a refusal to the SIP final (`404` unknown number, `480` no eligible session,
`486` line busy, `403`, `503`), else sends `180 Ringing`, joins the call's room as `sip-{call_id}`
and reports `leg UP` (repeated while the transport is not ready) — the backend rings the call and
the agent joins — then sends `200 OK` on `DDS_CALL_ANSWERED` (a Redis event, or the periodic
`getTelephonyCall` re-read that covers a lost one). A `DDS_CALL_ENDED` before that is the final
response (`486` busy, `480` no answer / abort, `487` hung up); after it, a `BYE`. `BYE` / `CANCEL`
from the softphone is `leg DOWN`. The other direction — the browser button with a live softphone
registration, or a brigade's `CALL_IN` — arrives as `voice:join {endpoint: SIP, sip_user}`: the
gateway (UAC) INVITEs that user's registered contact, reports `leg UP` on its `200` (the ring of an
OUTBOUND call, the trainee's answer of an INBOUND one), and `leg FAILED {sip_status}` when the
softphone rejects or does not answer within `ring_timeout_s` (30 s).

**INVITE authentication (E6e decision 1, `SIM_SIP_INVITE_AUTH`).** An INVITE is accepted only from
a user with a live registration (`403` otherwise) in both modes. `challenge` (the default)
additionally answers every INVITE and in-dialog re-INVITE `407 Proxy Authentication Required` with
a fresh nonce; the retried request must carry a valid `Proxy-Authorization` Digest **for the From
user** (the dial plan trusts that username to pick the trainee's session, and a UDP source address
is spoofable), else `403`. `registered_only` is E6a's behaviour: the registration's Digest check is
the only one. A malformed request is answered `400` when enough of it survived to address an
answer, and never raises out of the listener. The gateway logs no credential, no HA1, no token and
no `Authorization` / `Proxy-Authorization` header.

**Encryption (I7 E44, Q-E15-2, ТЗ ¶293).** `SIM_SIP_TRANSPORTS` (default `tls,udp,tcp`) picks the
listeners: SIP over **TLS** on `SIM_SIP_TLS_PORT` (5061) with the `make certs` certificate
(`SIM_SIP_TLS_CERT` / `SIM_SIP_TLS_KEY`), beside plain UDP/TCP on `SIM_SIP_PORT` for phones that
cannot do TLS (turning plain off is the owner's Q-I7-E44-1). A call whose INVITE arrived over TLS
must negotiate **SRTP** (SDES, `AES_CM_128_HMAC_SHA1_80`, `srtp.py`): an `RTP/AVP` offer, or one
with no usable `a=crypto`, is `488`. A call over plain SIP stays RTP (an `RTP/SAVP` offer there is
`488`: the key would travel in clear). The gateway's own INVITE to a softphone registered over TLS
offers SRTP and hangs up (`leg FAILED 488`) on an answer without it. No key is ever logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import inspect
import json
import logging
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from voice_agent.transport.sip.bridge import FakeRoomBridge, RoomPort
from voice_agent.transport.sip.dialog import (
    Channel,
    ClientTransactions,
    Dialog,
    DialogState,
    ServerTransactionCache,
    SipEndpoint,
    TransactionTimeout,
    server_tls_context,
    stamp_received,
)
from voice_agent.transport.sip.message import (
    PT_PCMA,
    PT_PCMU,
    SdpMedia,
    SipMessage,
    SipParseError,
    build_response,
    build_sdp,
    choose_codec,
    new_branch,
    new_call_id,
    new_tag,
    parse_auth_header,
    parse_message,
    parse_name_addr,
    parse_sdp,
    parse_uri,
    user_of,
)
from voice_agent.transport.sip.registrar import (
    Binding,
    CredentialSource,
    DigestCheck,
    Registrar,
)
from voice_agent.transport.sip.rtp import (
    FRAME_BYTES,
    PTIME_MS,
    JitterBuffer,
    PortAllocator,
    RtpPacket,
    RtpSession,
    decode,
)
from voice_agent.transport.sip.srtp import (
    PROTO_AVP,
    PROTO_SAVP,
    CryptoAttribute,
    MediaRejected,
    SrtpContext,
    SrtpError,
    accept_answer,
    negotiate_answer,
    new_crypto,
)
from voice_agent.transport.sip.telephony import (
    BackendCredentials,
    BackendUnavailableError,
    DialedCall,
    DialRefused,
    TelephonyBackend,
)

__all__ = [
    "ECHO_EXTENSION",
    "INVITE_AUTH_MODES",
    "RoomFactory",
    "Route",
    "RouteKind",
    "SipGateway",
    "SipGatewayConfig",
    "default_router",
    "parse_transports",
    "sip_status_for_end_reason",
]

logger = logging.getLogger(__name__)

ECHO_EXTENSION = "999"
ALLOW = "INVITE, ACK, BYE, CANCEL, OPTIONS, REGISTER"
SERVER_NAME = "sim112-sip-gateway"
_STOP_BYE_TIMEOUT_S = 2.0
_UNACKED_2XX_TIMEOUT_S = 32.0
INVITE_AUTH_MODES = ("challenge", "registered_only")
#: I7 E44: the listeners `SIM_SIP_TRANSPORTS` may name, and its default (TLS beside plain SIP).
SIP_TRANSPORTS = ("tls", "udp", "tcp")
DEFAULT_SIP_TRANSPORTS = "tls,udp,tcp"
_END_REASON_SIP_STATUS = {"BUSY": 486, "NO_ANSWER": 480, "HANGUP": 487}


def sip_status_for_end_reason(reason: str | None) -> int:
    """The final response to a softphone INVITE whose ДДС call ended before it was answered:
    `BUSY` ⇒ `486`, `NO_ANSWER` ⇒ `480`, the trainee's `HANGUP` (from the browser) ⇒ `487`,
    `ABORT` / `TRANSPORT_LOST` ⇒ `480`."""
    return _END_REASON_SIP_STATUS.get(reason or "", 480)


def parse_transports(text: str | None) -> frozenset[str]:
    """`SIM_SIP_TRANSPORTS` (`"tls,udp,tcp"`) → the set of listeners; `ValueError` on an unknown
    name or an empty list."""
    names = {part.strip().lower() for part in (text or DEFAULT_SIP_TRANSPORTS).split(",")}
    names.discard("")
    unknown = names - set(SIP_TRANSPORTS)
    if unknown:
        raise ValueError(f"SIM_SIP_TRANSPORTS: unknown transport(s) {sorted(unknown)}")
    if not names:
        raise ValueError("SIM_SIP_TRANSPORTS names no transport")
    return frozenset(names)


@dataclass(frozen=True)
class SipGatewayConfig:
    """The gateway's settings (80 §80.2.1's `SIM_SIP_*` keys).

    Read from the environment by `from_env()` (process env first, then the `.env` file `Settings`
    reads). They are declared on `app.config.settings.Settings` too (I3 E6e) — same names, same
    defaults — but read here directly: the gateway needs none of the backend's required settings
    (database, JWT secret), so it never instantiates `Settings`.
    """

    password: str = field(repr=False)
    realm: str = "sim112"
    bind_host: str = "0.0.0.0"
    sip_port: int = 5060
    rtp_port_range: str | None = "20000-20199"
    http_port: int | None = 8114
    media_ip: str | None = None
    jitter_ms: int = 40
    udp: bool = True
    tcp: bool = True
    #: I3 E6e (`SIM_SIP_INVITE_AUTH`): `challenge` (407 on every INVITE) or `registered_only`.
    invite_auth: str = "challenge"
    #: I3 E6e (`SIM_SIP_BACKEND_URL`): empty ⇒ standalone (echo `999` only, E6a).
    backend_url: str | None = None
    #: I3 E6e (`SIM_SIP_GATEWAY_SECRET`): the service credential towards the backend.
    gateway_secret: str = field(default="", repr=False)
    #: How long a softphone may ring (click-to-call / `CALL_IN`) before `leg FAILED` (§80.2.3).
    ring_timeout_s: float = 30.0
    #: How often `leg UP` is re-reported while the backend cannot ring yet (transport not ready).
    leg_retry_s: float = 1.0
    #: How often a waiting call is re-read (`getTelephonyCall`) — covers a lost Redis event.
    answer_poll_s: float = 2.0
    #: I7 E44 (`SIM_SIP_TRANSPORTS` names `tls`): SIP over TLS on `tls_port`; calls over it
    #: require SRTP. `from_env` turns it on by default; the dataclass default is off (tests).
    tls: bool = False
    #: `SIM_SIP_TLS_PORT` (5061, RFC 3261 §26.2). `0` = ephemeral (tests).
    tls_port: int = 5061
    #: `SIM_SIP_TLS_CERT` / `SIM_SIP_TLS_KEY`: the server certificate chain and key (`make certs`:
    #: `infra/certs/server.crt` / `server.key`; compose mounts them at `/certs/`).
    tls_cert: str | None = None
    tls_key: str | None = None

    def __post_init__(self) -> None:
        if self.invite_auth not in INVITE_AUTH_MODES:
            raise ValueError(f"SIM_SIP_INVITE_AUTH must be one of {INVITE_AUTH_MODES}")
        if not (self.udp or self.tcp or self.tls):
            raise ValueError("SIM_SIP_TRANSPORTS: at least one of tls, udp, tcp")

    @property
    def transports(self) -> tuple[str, ...]:
        on = {"tls": self.tls, "udp": self.udp, "tcp": self.tcp}
        return tuple(name for name in SIP_TRANSPORTS if on[name])

    @classmethod
    def from_env(cls, read: Callable[[str], str | None] | None = None) -> SipGatewayConfig:
        if read is None:
            from app.config.settings import read_env_value

            read = read_env_value

        def _int(name: str, default: int) -> int:
            value = read(name)
            return int(value) if value else default

        transports = parse_transports(read("SIM_SIP_TRANSPORTS"))
        return cls(
            password=read("SIM_SIP_PASSWORD") or "",
            realm=read("SIM_SIP_REALM") or "sim112",
            bind_host=read("SIM_SIP_BIND_HOST") or "0.0.0.0",
            sip_port=_int("SIM_SIP_PORT", 5060),
            rtp_port_range=read("SIM_SIP_RTP_PORT_RANGE") or "20000-20199",
            http_port=_int("SIM_SIP_GATEWAY_HTTP_PORT", 8114),
            media_ip=read("SIM_SIP_MEDIA_IP") or None,
            jitter_ms=_int("SIM_SIP_JITTER_MS", 40),
            invite_auth=read("SIM_SIP_INVITE_AUTH") or "challenge",
            backend_url=read("SIM_SIP_BACKEND_URL") or None,
            gateway_secret=read("SIM_SIP_GATEWAY_SECRET") or "",
            udp="udp" in transports,
            tcp="tcp" in transports,
            tls="tls" in transports,
            tls_port=_int("SIM_SIP_TLS_PORT", 5061),
            tls_cert=read("SIM_SIP_TLS_CERT") or None,
            tls_key=read("SIM_SIP_TLS_KEY") or None,
        )


class RouteKind(enum.Enum):
    ECHO = "ECHO"
    BRIDGE = "BRIDGE"
    REJECT = "REJECT"


@dataclass(frozen=True)
class Route:
    """What to do with a dialled number."""

    kind: RouteKind
    status: int = 404
    bridge_factory: Callable[[str], RoomPort] | None = None
    #: Ring this long before answering (a CANCEL in between is honoured).
    answer_after_ms: int = 0


Router = Callable[[str, str | None], Route | Awaitable[Route]]
RoomFactory = Callable[[DialedCall], RoomPort]


def default_router(dialed: str, from_user: str | None) -> Route:
    """E6a's dial plan: `999` echoes, everything else is `404` (E6e: the backend's dial plan)."""
    if dialed == ECHO_EXTENSION:
        return Route(RouteKind.ECHO)
    return Route(RouteKind.REJECT, status=404)


@dataclass
class _Call:
    """One inbound call (UAS side)."""

    dialog: Dialog
    invite: SipMessage
    route: Route
    dialed: str
    from_user: str | None
    started_at: float
    rtp: RtpSession | None = None
    bridge: RoomPort | None = None
    jitter: JitterBuffer | None = None
    answer_sdp: bytes = b""
    ok_response: SipMessage | None = None
    final_sent: bool = False
    answered: bool = False
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    #: I3 E6e: the ДДС call this dialog carries (`DdsCall.call_id`), and whether we placed it (UAC).
    dds_call_id: str | None = None
    uac: bool = False
    #: Set when the backend's call was answered / ended, or the softphone cancelled: wakes a waiter.
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    dds_answered: bool = False
    dds_ended: str | None = None
    #: I7 E44: our SDES crypto line on an SRTP call (the key we send with), and the `build_sdp`
    #: arguments of our answer (rebuilt when a re-INVITE picks another crypto tag).
    local_crypto: CryptoAttribute | None = None
    answer_args: dict[str, Any] = field(default_factory=dict)


def _record_room(_dialed: DialedCall) -> RoomPort:
    """The standalone / gate default room of a ДДС call: records what the softphone says."""
    return FakeRoomBridge(mode="record")


class SipGateway:
    """Registrar + UAS + echo + bridge, over one UDP socket and one TCP listener."""

    def __init__(
        self,
        config: SipGatewayConfig,
        *,
        router: Router = default_router,
        clock: Callable[[], float] = time.monotonic,
        backend: TelephonyBackend | None = None,
        room_factory: RoomFactory | None = None,
        credentials: CredentialSource | None = None,
        on_bind: Callable[[Binding], Awaitable[None] | None] | None = None,
        on_unbind: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> None:
        self.config = config
        self._router = router
        self._clock = clock
        self._backend = backend
        self._room_factory: RoomFactory = room_factory or _record_room
        self.registrar = Registrar(
            realm=config.realm,
            password=config.password,
            now=clock,
            credentials=credentials
            if credentials is not None
            else (BackendCredentials(backend) if backend is not None else None),
            on_bind=on_bind,
            on_unbind=on_unbind,
        )
        self._endpoint = SipEndpoint(self._on_datagram)
        self._transactions = ClientTransactions()
        self._transactions.on_stray_response = self._on_stray_response
        #: `DdsCall.call_id` → its dialog (I3 E6e), for the Redis signals and the backend's reads.
        self._dds: dict[str, _Call] = {}
        self._server_cache = ServerTransactionCache(now=clock)
        self._allocator = PortAllocator(config.rtp_port_range)
        self._calls: dict[str, _Call] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._http: asyncio.Server | None = None
        self.http_port: int | None = None
        self._stopping = False

    # -- lifecycle ------------------------------------------------------------------------------

    @property
    def udp_port(self) -> int | None:
        return self._endpoint.udp_port

    @property
    def tcp_port(self) -> int | None:
        return self._endpoint.tcp_port

    @property
    def tls_port(self) -> int | None:
        return self._endpoint.tls_port

    @property
    def live_calls(self) -> int:
        return len(self._calls)

    async def start(self) -> None:
        host, port = self.config.bind_host, self.config.sip_port
        if self.config.udp:
            port = await self._endpoint.listen_udp(host, port)
        if self.config.tcp:
            await self._endpoint.listen_tcp(host, port)
        if self.config.tls:
            if not (self.config.tls_cert and self.config.tls_key):
                raise ValueError("SIP over TLS needs SIM_SIP_TLS_CERT and SIM_SIP_TLS_KEY")
            context = server_tls_context(self.config.tls_cert, self.config.tls_key)
            await self._endpoint.listen_tls(host, self.config.tls_port, context)
        if self.config.http_port is not None:
            self._http = await asyncio.start_server(
                self._serve_http, "127.0.0.1", self.config.http_port
            )
            sockets = self._http.sockets or ()
            self.http_port = int(sockets[0].getsockname()[1]) if sockets else None
        logger.info(
            "SIP gateway listening udp=%s tcp=%s tls=%s host=%s realm=%s rtp=%s "
            "health=127.0.0.1:%s",
            self.udp_port,
            self.tcp_port,
            self.tls_port,
            host,
            self.config.realm,
            self.config.rtp_port_range or "ephemeral",
            self.http_port,
        )

    async def stop(self) -> None:
        """BYE every answered call, refuse every ringing one, then close every socket.

        A ДДС call this gateway carries is reported `leg FAILED {503}` (best effort): the backend
        ends it by SYSTEM `ABORT` rather than leaving it live with no softphone behind it."""
        self._stopping = True
        if self._backend is not None:
            for call in list(self._dds.values()):
                if call.dds_call_id is not None and call.dds_ended is None:
                    call.dds_ended = "ABORT"
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(
                            self._backend.report_leg(call.dds_call_id, "FAILED", 503), 2.0
                        )
        byes = []
        for call in list(self._calls.values()):
            if call.final_sent and call.answered:
                byes.append(self._send_bye(call))
            elif not call.final_sent and not call.uac:
                self._final(call, 480, "Gateway shutting down")
        if byes:
            await asyncio.gather(*byes, return_exceptions=True)
        for call in list(self._calls.values()):
            await self._terminate(call, "gateway stop")
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(BaseException):
                await task
        await self._endpoint.close()
        if self._http is not None:
            self._http.close()
            with contextlib.suppress(Exception):
                await self._http.wait_closed()
            self._http = None
        logger.info("SIP gateway stopped")

    def health(self) -> dict[str, object]:
        return {
            "status": "stopping" if self._stopping else "ok",
            "realm": self.config.realm,
            "sip_udp_port": self.udp_port,
            "sip_tcp_port": self.tcp_port,
            "sip_tls_port": self.tls_port,
            "transports": list(self.config.transports),
            "srtp": "required over TLS" if self.config.tls else "off",
            "registrations": len(self.registrar.bindings()),
            "calls": self.live_calls,
            "dds_calls": len(self._dds),
            "backend": self._backend is not None,
            "invite_auth": self.config.invite_auth,
        }

    async def _serve_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = (await asyncio.wait_for(reader.readline(), 5)).decode("latin-1")
            while (await asyncio.wait_for(reader.readline(), 5)).strip():
                pass
            parts = request_line.split()
            if len(parts) >= 2 and parts[0] == "GET" and parts[1] == "/health":
                status, body = "200 OK", json.dumps(self.health())
            else:
                status, body = "404 Not Found", json.dumps({"detail": "not found"})
            payload = body.encode("utf-8")
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                + payload
            )
            await writer.drain()
        except (TimeoutError, ConnectionError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    def _spawn(self, coro: object, name: str) -> asyncio.Task[None]:
        task: asyncio.Task[None] = asyncio.create_task(coro, name=name)  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("gateway task %s failed", task.get_name(), exc_info=task.exception())

    # -- inbound --------------------------------------------------------------------------------

    def _on_datagram(self, data: bytes, channel: Channel) -> None:
        if not data.strip():  # CRLF keep-alive
            return
        try:
            message = parse_message(data)
        except SipParseError as exc:
            self._answer_malformed(exc, channel)
            return
        if not message.is_request:
            self._transactions.on_response(message, channel)
            return
        stamp_received(message, channel.peer)
        method = message.method or ""
        if method != "ACK" and not self._server_cache.begin(message):
            cached = self._server_cache.cached(message)
            if cached is not None:
                channel.send(cached)
            return
        if method in ("REGISTER", "INVITE"):
            # Both are answered after an await (credentials, the backend): mark the transaction
            # in flight so a retransmission is dropped instead of executed twice.
            self._server_cache.remember(message, None)
        handler = {
            "REGISTER": self._on_register,
            "INVITE": self._on_invite,
            "ACK": self._on_ack,
            "BYE": self._on_bye,
            "CANCEL": self._on_cancel,
            "OPTIONS": self._on_options,
        }.get(method)
        if handler is None:
            self._respond(message, channel, build_response(message, 501, to_tag=new_tag()))
            return
        handler(message, channel)

    def _answer_malformed(self, exc: SipParseError, channel: Channel) -> None:
        partial = exc.partial
        logger.info("malformed SIP message from %s:%d: %s", *channel.peer, exc)
        if partial is None or not partial.is_request or partial.method == "ACK":
            return
        if not partial.get("Via"):
            return  # nowhere to address an answer (RFC 3261 §18.1.1)
        response = build_response(partial, 400, _reason_text(str(exc)), to_tag=new_tag())
        channel.send_message(response)

    def _respond(self, request: SipMessage, channel: Channel, response: SipMessage) -> None:
        response.add("Server", SERVER_NAME)
        self._server_cache.remember(request, response)
        channel.send_message(response)

    def _on_register(self, request: SipMessage, channel: Channel) -> None:
        self._spawn(self._register(request, channel), "register")

    async def _register(self, request: SipMessage, channel: Channel) -> None:
        response = await self.registrar.handle_register(
            request, source=channel.peer, transport=channel.kind, channel=channel
        )
        self._respond(request, channel, response)

    async def _authorise_invite(
        self, request: SipMessage, channel: Channel, from_user: str | None
    ) -> bool:
        """E6e decision 1: under `challenge`, a valid `Proxy-Authorization` for the From user.

        Answers the request itself (`407` / `403` / `503`) and returns `False` when it is not.
        """
        if self.config.invite_auth != "challenge":
            return True
        to_tag = None if parse_name_addr(request.get("To") or "").tag else new_tag()
        header = request.get("Proxy-Authorization")
        verdict = DigestCheck.CHALLENGE
        if header is not None:
            scheme, params = parse_auth_header(header)
            if scheme.lower() == "digest":
                verdict, _ = await self.registrar.verify_digest(
                    params, method="INVITE", expected_user=from_user
                )
        if verdict is DigestCheck.OK:
            return True
        if verdict in (DigestCheck.CHALLENGE, DigestCheck.STALE):
            challenge = self.registrar.challenge_value(stale=verdict is DigestCheck.STALE)
            response = build_response(
                request, 407, to_tag=to_tag, headers=[("Proxy-Authenticate", challenge)]
            )
        elif verdict is DigestCheck.UNAVAILABLE:
            response = build_response(request, 503, to_tag=to_tag)
        else:
            logger.info("INVITE from %s refused: bad Proxy-Authorization", from_user)
            response = build_response(request, 403, to_tag=to_tag)
        self._respond(request, channel, response)
        return False

    def _on_options(self, request: SipMessage, channel: Channel) -> None:
        response = build_response(
            request,
            200,
            to_tag=new_tag(),
            headers=[("Allow", ALLOW), ("Accept", "application/sdp"), ("Supported", "")],
        )
        self._respond(request, channel, response)

    def _on_invite(self, request: SipMessage, channel: Channel) -> None:
        to = parse_name_addr(request.get("To") or "")
        if to.tag:
            call = self._calls.get(request.call_id)
            if call is None or call.dialog.local_tag != to.tag:
                self._respond(request, channel, build_response(request, 481))
                return
            self._spawn(self._reinvite(call, request, channel), "reinvite")
            return
        if request.call_id in self._calls:  # a retransmission after its cache entry expired
            return
        if self._stopping:
            self._respond(request, channel, build_response(request, 503, to_tag=new_tag()))
            return
        self._spawn(self._handle_invite(request, channel), f"invite-{request.call_id}")

    async def _handle_invite(self, request: SipMessage, channel: Channel) -> None:
        from_header = parse_name_addr(request.get("From") or "")
        from_user = user_of(request.get("From") or "")
        dialed = parse_uri(request.uri or "").user or ""
        if not self.registrar.is_registered(from_user):
            logger.info("INVITE %s from unregistered user %s refused", dialed, from_user)
            self._respond(request, channel, build_response(request, 403, to_tag=new_tag()))
            return
        if not await self._authorise_invite(request, channel, from_user):
            return
        try:
            offer = parse_sdp(request.body)
        except ValueError as exc:
            logger.info("INVITE %s from %s: no usable SDP offer (%s)", dialed, from_user, exc)
            self._respond(request, channel, build_response(request, 488, to_tag=new_tag()))
            return
        codec = choose_codec(offer)
        if codec is None:
            logger.info("INVITE %s: no PCMA/PCMU in offer %s", dialed, offer.payload_types)
            self._respond(request, channel, build_response(request, 488, to_tag=new_tag()))
            return
        try:  # I7 E44: over TLS the media must be SRTP; over plain SIP it stays RTP
            sdes = negotiate_answer(offer, secure_signalling=channel.secure)
        except MediaRejected as exc:
            logger.info("INVITE %s from %s over %s: 488 (%s)", dialed, from_user, channel.kind, exc)
            self._respond(request, channel, build_response(request, 488, to_tag=new_tag()))
            return
        dds: DialedCall | None = None
        if self._backend is not None and dialed != ECHO_EXTENSION and from_user is not None:
            # I3 E6e: the backend's dial plan (§80.2.3 step 2). `100 Trying` first — the
            # backend's answer is a network round trip away.
            self._respond(request, channel, build_response(request, 100))
            try:
                dds = await self._backend.dial(from_user, dialed, request.call_id)
            except DialRefused as exc:
                logger.info("INVITE %s from %s: dial refused %s", dialed, from_user, exc.code)
                self._respond(
                    request, channel, build_response(request, exc.sip_status, to_tag=new_tag())
                )
                return
            except BackendUnavailableError as exc:
                logger.warning("INVITE %s from %s: backend unavailable: %s", dialed, from_user, exc)
                self._respond(request, channel, build_response(request, 503, to_tag=new_tag()))
                return
            route = Route(RouteKind.BRIDGE)
        else:
            routed = self._router(dialed, from_user)
            route = await routed if inspect.isawaitable(routed) else routed
            if route.kind is RouteKind.REJECT:
                logger.info("INVITE %s from %s rejected %d", dialed, from_user, route.status)
                self._respond(
                    request, channel, build_response(request, route.status, to_tag=new_tag())
                )
                return
            self._respond(request, channel, build_response(request, 100))
        contact = request.get("Contact")
        remote_target = parse_name_addr(contact).uri if contact else from_header.uri
        dialog = Dialog(
            call_id=request.call_id,
            local_tag=new_tag(),
            remote_tag=from_header.tag,
            local_uri=to_uri(request),
            remote_uri=from_header.uri,
            remote_target=remote_target,
            channel=channel,
            remote_cseq=request.cseq[0],
        )
        call = _Call(
            dialog=dialog,
            invite=request,
            route=route,
            dialed=dialed,
            from_user=from_user,
            started_at=self._clock(),
        )
        if dds is not None:
            call.dds_call_id = dds.call_id.lower()
            self._dds[call.dds_call_id] = call
        self._calls[request.call_id] = call
        logger.info(
            "INVITE %s from %s (%r) codec=%s media=%s call-id=%s",
            dialed,
            from_user,
            channel,
            "PCMA" if codec == 8 else "PCMU",
            "SRTP" if sdes is not None else "RTP",
            request.call_id,
        )
        try:
            rtp = RtpSession(
                bind_host=self.config.bind_host,
                allocator=self._allocator,
                payload_type=codec,
                on_packet=lambda packet, arrival: self._on_rtp(call, packet, arrival),
                clock=self._clock,
            )
            rtp.require_srtp = channel.secure
            if sdes is not None:
                rtp.srtp = SrtpContext(local_key=sdes.local.key, remote_key=sdes.remote.key)
                call.local_crypto = sdes.local
            await rtp.open()
            call.rtp = rtp
            rtp.set_remote((offer.address, offer.port))
            advertised = self._advertised_ip(channel.peer[0])
            call.answer_args = {
                "address": advertised,
                "port": rtp.local_port,
                "payload_types": (codec,),
                "session_id": int(self._clock() * 1000) % 1_000_000_000,
                "protocol": PROTO_SAVP if sdes is not None else PROTO_AVP,
            }
            call.answer_sdp = build_sdp(
                **call.answer_args,
                crypto=() if sdes is None else (sdes.local.sdp_value(),),
            )
            ringing = build_response(
                request, 180, to_tag=dialog.local_tag, headers=[self._contact(call, channel)]
            )
            self._respond(request, channel, ringing)
            if dds is not None:
                if await self._await_dds_answer(call, dds):
                    self._send_ok(call, request, channel)
                return
            if route.answer_after_ms > 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(call.cancelled.wait(), route.answer_after_ms / 1000)
            if call.cancelled.is_set() or call.final_sent:
                return
            if route.kind is RouteKind.BRIDGE and route.bridge_factory is not None:
                call.jitter = JitterBuffer(self.config.jitter_ms)
                bridge = route.bridge_factory(request.call_id)
                await bridge.open(lambda pcm: self._from_room(call, pcm))
                call.bridge = bridge
            if call.cancelled.is_set():
                return
            self._send_ok(call, request, channel)
        except Exception:
            logger.exception("INVITE %s failed", request.call_id)
            if not call.final_sent:
                self._final(call, 500)
            await self._terminate(call, "setup failed")

    def _send_ok(self, call: _Call, request: SipMessage, channel: Channel) -> None:
        """The `200 OK` with our SDP answer (retransmitted over UDP until the ACK)."""
        ok = build_response(
            request,
            200,
            to_tag=call.dialog.local_tag,
            headers=[
                self._contact(call, channel),
                ("Allow", ALLOW),
                ("Content-Type", "application/sdp"),
            ],
            body=call.answer_sdp,
        )
        call.ok_response = ok
        call.final_sent = True
        call.answered = True
        self._respond(request, channel, ok)
        port = call.rtp.local_port if call.rtp is not None else 0
        logger.info("200 OK %s call-id=%s rtp=%d", call.dialed, request.call_id, port)
        if not channel.reliable:
            call.tasks.append(self._spawn(self._retransmit_2xx(call), "2xx-retransmit"))

    async def _reinvite(self, call: _Call, request: SipMessage, channel: Channel) -> None:
        """A re-INVITE, challenged like an INVITE under `challenge` (E6e decision 1)."""
        if not await self._authorise_invite(request, channel, user_of(request.get("From") or "")):
            return
        self._on_reinvite(call, request, channel)

    def _on_reinvite(self, call: _Call, request: SipMessage, channel: Channel) -> None:
        """A re-INVITE (hold, refresh): answered with the same SDP; the far RTP address updates.

        I7 E44: on an SRTP call the new offer must again carry an acceptable crypto line (else
        `488`, the call keeps its current keys); a changed far key re-keys the inbound side."""
        call.dialog.remote_cseq = request.cseq[0]
        try:
            offer: SdpMedia | None = parse_sdp(request.body)
        except ValueError:
            offer = None
        srtp_call = call.local_crypto is not None and call.rtp is not None
        if offer is not None and srtp_call and not self._rekey(call, offer):
            response = build_response(request, 488, to_tag=call.dialog.local_tag)
            self._respond(request, channel, response)
            return
        if offer is not None and call.rtp is not None:
            call.rtp.set_remote((offer.address, offer.port))
        response = build_response(
            request,
            200,
            to_tag=call.dialog.local_tag,
            headers=[self._contact(call, channel), ("Content-Type", "application/sdp")],
            body=call.answer_sdp,
        )
        self._respond(request, channel, response)

    def _rekey(self, call: _Call, offer: SdpMedia) -> bool:
        """An SRTP call's re-offer: accept its crypto line (re-keying inbound if the far key
        changed; answering under the offer's tag); `False` ⇒ `488`, the current keys stay."""
        assert call.local_crypto is not None and call.rtp is not None
        try:
            sdes = negotiate_answer(offer, secure_signalling=True)
            assert sdes is not None and call.rtp.srtp is not None
            if call.rtp.srtp.rekey_inbound(sdes.remote.key):
                logger.info("re-INVITE call-id=%s: SRTP re-keyed", call.dialog.call_id)
        except (MediaRejected, SrtpError) as exc:
            logger.info("re-INVITE call-id=%s: 488 (%s)", call.dialog.call_id, exc)
            return False
        if sdes.remote.tag != call.local_crypto.tag and call.answer_args:
            local = call.local_crypto
            call.local_crypto = CryptoAttribute(sdes.remote.tag, local.suite, local.key)
            call.answer_args["version"] = int(call.answer_args.get("version", 1)) + 1
            call.answer_sdp = build_sdp(**call.answer_args, crypto=(call.local_crypto.sdp_value(),))
        return True

    def _on_ack(self, request: SipMessage, channel: Channel) -> None:
        call = self._calls.get(request.call_id)
        if call is None or not call.answered:
            return  # the ACK of a non-2xx final (hop-by-hop), or a stray
        if call.dialog.state is DialogState.EARLY:
            call.dialog.state = DialogState.CONFIRMED
            logger.info("ACK call-id=%s: call up", request.call_id)

    def _on_bye(self, request: SipMessage, channel: Channel) -> None:
        call = self._calls.get(request.call_id)
        if call is None:
            self._respond(request, channel, build_response(request, 481))
            return
        self._respond(request, channel, build_response(request, 200))
        self._spawn(self._terminate(call, "BYE from the far end"), "bye")
        self._report_down(call)

    def _on_cancel(self, request: SipMessage, channel: Channel) -> None:
        call = self._calls.get(request.call_id)
        branch = request.top_via.branch if request.top_via else None
        invite_via = call.invite.top_via if call is not None else None
        if call is None or invite_via is None or invite_via.branch != branch:
            self._respond(request, channel, build_response(request, 481))
            return
        self._respond(request, channel, build_response(request, 200))
        if call.final_sent:
            return  # too late: CANCEL has no effect once a final response went out
        call.cancelled.set()
        call.wake.set()
        self._final(call, 487)
        logger.info("CANCEL call-id=%s: 487 Request Terminated", request.call_id)
        self._spawn(self._terminate(call, "CANCEL"), "cancel")
        self._report_down(call)

    def _final(self, call: _Call, status: int, reason: str | None = None) -> None:
        response = build_response(call.invite, status, reason, to_tag=call.dialog.local_tag)
        call.final_sent = True
        self._respond(call.invite, call.dialog.channel, response)

    # -- the ДДС phone: the backend's calls (I3 E6e, §80.2.3) -------------------------------------

    def bridges(self, call_id: str) -> bool:
        """This gateway carries the ДДС call `call_id` (the Redis signals' filter)."""
        return call_id.lower() in self._dds

    def on_call_answered(self, call_id: str) -> None:
        """`DDS_CALL_ANSWERED`: a softphone-dialled call waiting for its `200 OK` gets it."""
        call = self._dds.get(call_id.lower())
        if call is not None:
            call.dds_answered = True
            call.wake.set()

    def on_call_ended(self, call_id: str, reason: str) -> None:
        """`DDS_CALL_ENDED` or `voice:cancel`: a final response, a `CANCEL` or a `BYE`."""
        call = self._dds.get(call_id.lower())
        if call is None or call.dds_ended is not None:
            return
        call.dds_ended = reason or "ABORT"
        call.wake.set()
        if call.uac and not call.answered:
            call.cancelled.set()  # the softphone is still ringing: `_invite_softphone` CANCELs
        elif call.answered and call.final_sent:
            self._spawn(self._bye_and_terminate(call, f"ДДС call ended ({reason})"), "dds-bye")

    def on_join(self, payload: dict[str, Any]) -> None:
        """`voice:join {endpoint: SIP, sip_user}`: ring that user's softphone (UAC INVITE)."""
        call_id = str(payload.get("call_id", "")).lower()
        sip_user = payload.get("sip_user")
        if not call_id or not sip_user or call_id in self._dds or self._stopping:
            return
        if self._backend is None:
            return
        self._spawn(self._ring_softphone(call_id, str(sip_user), payload), f"ring-{call_id}")

    async def _bye_and_terminate(self, call: _Call, why: str) -> None:
        await self._send_bye(call)
        await self._terminate(call, why)

    def _report_down(self, call: _Call) -> None:
        """`BYE` / `CANCEL` from the softphone ⇒ `leg DOWN` (unless the backend ended it first)."""
        if call.dds_call_id is None or call.dds_ended is not None or self._backend is None:
            return
        call.dds_ended = "HANGUP"
        self._spawn(self._report(call.dds_call_id, "DOWN"), "leg-down")

    async def _report(self, call_id: str, state: str, sip_status: int | None = None) -> str | None:
        """One `reportSipLeg`; `None` when the backend is unreachable (logged, never raised)."""
        assert self._backend is not None
        try:
            return await self._backend.report_leg(call_id, state, sip_status)
        except BackendUnavailableError as exc:
            logger.warning("leg %s of ДДС call %s not reported: %s", state, call_id, exc)
            return None

    async def _wait_wake(self, call: _Call, timeout_s: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(call.wake.wait(), timeout_s)
        call.wake.clear()

    async def _refresh(self, call: _Call) -> None:
        """The periodic re-read (`getTelephonyCall`) that covers a lost Redis event."""
        assert self._backend is not None and call.dds_call_id is not None
        try:
            view = await self._backend.get_call(call.dds_call_id)
        except BackendUnavailableError:
            return
        if view.get("state") == "CONNECTED":
            call.dds_answered = True
        elif view.get("state") == "ENDED" and call.dds_ended is None:
            call.dds_ended = str(view.get("end_reason") or "ABORT")

    async def _join_room(self, call: _Call, dialed: DialedCall) -> None:
        call.jitter = JitterBuffer(self.config.jitter_ms)
        bridge = self._room_factory(dialed)
        await bridge.open(lambda pcm: self._from_room(call, pcm))
        call.bridge = bridge

    async def _await_dds_answer(self, call: _Call, dialed: DialedCall) -> bool:
        """A softphone-dialled call (UAS): join the room, `leg UP` until rung, then wait for
        `DDS_CALL_ANSWERED`. `True` ⇒ send the `200 OK`; `False` ⇒ a final response went out (or
        the softphone cancelled) and the call is torn down."""
        assert self._backend is not None and call.dds_call_id is not None
        await self._join_room(call, dialed)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.ring_timeout_s
        while not call.cancelled.is_set() and call.dds_ended is None:
            state = await self._report(call.dds_call_id, "UP")
            if state == "ENDED":
                await self._refresh(call)
                call.dds_ended = call.dds_ended or "ABORT"
            elif state == "CONNECTED":
                call.dds_answered = True
            if state not in (None, "DIALING"):
                break
            if loop.time() >= deadline:  # the transport never came up: give the phone back
                await self._report(call.dds_call_id, "FAILED", 480)
                call.dds_ended = "ABORT"
                break
            await self._wait_wake(call, self.config.leg_retry_s)
        while not (call.cancelled.is_set() or call.dds_answered or call.dds_ended is not None):
            await self._wait_wake(call, self.config.answer_poll_s)
            if not (call.cancelled.is_set() or call.dds_answered or call.dds_ended is not None):
                await self._refresh(call)
        if call.cancelled.is_set():
            return False  # `_on_cancel` answered 487, reported DOWN and terminates the call
        if call.dds_ended is not None and not call.dds_answered:
            status = sip_status_for_end_reason(call.dds_ended)
            logger.info("ДДС call %s ended (%s) before it was answered", call.dds_call_id, status)
            self._final(call, status)
            await self._terminate(call, f"ДДС call ended {call.dds_ended}")
            return False
        return True

    async def _ring_softphone(self, call_id: str, sip_user: str, payload: dict[str, Any]) -> None:
        """UAC: INVITE `sip_user`'s registered contact for the ДДС call `call_id` (§80.2.3 step 3,
        step 5); `leg UP` on its `200`, `leg FAILED {status}` on a refusal or no answer."""
        binding = self.registrar.lookup(sip_user)
        if binding is None:
            logger.info("ДДС call %s: %s has no live registration", call_id, sip_user)
            await self._report(call_id, "FAILED", 480)
            return
        channel = binding.channel
        if not isinstance(channel, Channel) or channel.closed or not channel.reliable:
            if binding.transport == "TLS" or not self.config.udp:
                # I7 E44: a TLS registration is never rung in clear; its connection is gone.
                logger.info("ДДС call %s: %s's connection is closed", call_id, sip_user)
                await self._report(call_id, "FAILED", 480)
                return
            channel = self._endpoint.udp_channel(binding.source)
        host = self._advertised_ip(binding.source[0])
        port = self._listen_port(channel)
        kind = str(payload.get("call_kind") or "dds").lower()
        local_uri = f"sip:{kind}@{self.config.realm}"
        sip_call_id = new_call_id(host)
        invite = SipMessage(method="INVITE", uri=binding.contact)
        invite.add("Via", f"SIP/2.0/{channel.kind} {host}:{port};branch={new_branch()};rport")
        invite.add("Max-Forwards", "70")
        local_tag = new_tag()
        invite.add("From", f"<{local_uri}>;tag={local_tag}")
        invite.add("To", f"<{binding.aor}>")
        invite.add("Call-ID", sip_call_id)
        invite.add("CSeq", "1 INVITE")
        invite.add("Contact", f"<sip:{kind}@{host}:{port}{channel.transport_param}>")
        invite.add("User-Agent", SERVER_NAME)
        invite.add("Content-Type", "application/sdp")
        dialog = Dialog(
            call_id=sip_call_id,
            local_tag=local_tag,
            remote_tag=None,
            local_uri=local_uri,
            remote_uri=binding.aor,
            remote_target=binding.contact,
            channel=channel,
        )
        call = _Call(
            dialog=dialog,
            invite=invite,
            route=Route(RouteKind.BRIDGE),
            dialed=sip_user,
            from_user=sip_user,
            started_at=self._clock(),
            dds_call_id=call_id,
            uac=True,
            local_crypto=new_crypto() if channel.secure else None,
        )
        self._dds[call_id] = call
        self._calls[sip_call_id] = call
        try:
            rtp = RtpSession(
                bind_host=self.config.bind_host,
                allocator=self._allocator,
                payload_type=PT_PCMA,
                on_packet=lambda packet, arrival: self._on_rtp(call, packet, arrival),
                clock=self._clock,
            )
            rtp.require_srtp = channel.secure
            await rtp.open()
            call.rtp = rtp
            invite.body = build_sdp(
                address=host,
                port=rtp.local_port,
                payload_types=(PT_PCMA, PT_PCMU),
                session_id=int(self._clock() * 1000) % 1_000_000_000,
                protocol=PROTO_SAVP if call.local_crypto is not None else PROTO_AVP,
                crypto=() if call.local_crypto is None else (call.local_crypto.sdp_value(),),
            )
            logger.info("ДДС call %s: INVITE %s at %s", call_id, sip_user, binding.contact)
            response = await self._invite_softphone(call, channel)
        except Exception:
            logger.exception("ДДС call %s: ringing %s failed", call_id, sip_user)
            await self._report(call_id, "FAILED", 500)
            await self._terminate(call, "UAC setup failed")
            return
        status = 0 if response is None else (response.status or 0)
        if response is None or not 200 <= status < 300:
            if call.dds_ended is None:
                await self._report(call_id, "FAILED", status or 408)
            await self._terminate(call, f"softphone answered {status or 'nothing'}")
            return
        await self._on_softphone_answered(call, response, dialed=payload)

    async def _invite_softphone(self, call: _Call, channel: Channel) -> SipMessage | None:
        """Send the INVITE; the final response, or `None` after a `CANCEL` (ring timeout, or the
        ДДС call ended while the softphone rang)."""
        request = asyncio.ensure_future(
            self._transactions.request(
                call.invite, channel, timeout_s=self.config.ring_timeout_s + 5.0
            )
        )
        waker = asyncio.ensure_future(call.cancelled.wait())
        try:
            done, _ = await asyncio.wait(
                {request, waker},
                timeout=self.config.ring_timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if request in done:
                with contextlib.suppress(TransactionTimeout):
                    response = request.result()
                    if not 200 <= (response.status or 0) < 300:
                        channel.send_message(_ack_non_2xx(call.invite, response))
                    return response
                return None
            # Timed out, or the backend ended the call: CANCEL the ringing INVITE.
            if call.dds_ended is None:
                call.dds_ended = "NO_ANSWER"
                await self._report(call.dds_call_id or "", "FAILED", 408)
            await self._send_cancel(call, channel)
            with contextlib.suppress(Exception):
                response = await asyncio.wait_for(request, 5.0)
                if 200 <= (response.status or 0) < 300:  # answered as we cancelled: hang up
                    await self._on_softphone_answered(call, response, dialed={}, report=False)
                    await self._send_bye(call)
                else:
                    channel.send_message(_ack_non_2xx(call.invite, response))
            return None
        finally:
            waker.cancel()
            if not request.done():
                request.cancel()

    async def _send_cancel(self, call: _Call, channel: Channel) -> None:
        cancel = SipMessage(method="CANCEL", uri=call.invite.uri)
        cancel.add("Via", call.invite.get("Via") or "")
        cancel.add("Max-Forwards", "70")
        cancel.add("From", call.invite.get("From") or "")
        cancel.add("To", call.invite.get("To") or "")
        cancel.add("Call-ID", call.dialog.call_id)
        cancel.add("CSeq", "1 CANCEL")
        with contextlib.suppress(TransactionTimeout):
            await self._transactions.request(cancel, channel, timeout_s=_STOP_BYE_TIMEOUT_S)

    async def _on_softphone_answered(
        self,
        call: _Call,
        response: SipMessage,
        *,
        dialed: dict[str, Any],
        report: bool = True,
    ) -> None:
        """The softphone took the call: ACK, RTP towards its answer, join the room, `leg UP`."""
        to = parse_name_addr(response.get("To") or "")
        contact = response.get("Contact")
        call.dialog.remote_tag = to.tag
        if contact:
            call.dialog.remote_target = parse_name_addr(contact).uri
        call.dialog.state = DialogState.CONFIRMED
        call.answered = True
        call.final_sent = True
        self._send_uac_ack(call)
        with contextlib.suppress(ValueError, IndexError):
            answer = parse_sdp(response.body)
            if call.rtp is not None:
                call.rtp.payload_type = answer.payload_types[0]
                call.rtp.set_remote((answer.address, answer.port))
                if call.local_crypto is not None:  # I7 E44: our SRTP offer needs an SRTP answer
                    self._accept_srtp_answer(call, answer)
        if call.local_crypto is not None and (call.rtp is None or call.rtp.srtp is None):
            if not report:
                return  # the cancel race: the caller hangs up anyway
            if call.dds_call_id is not None and call.dds_ended is None:
                call.dds_ended = "ABORT"
                await self._report(call.dds_call_id, "FAILED", 488)
            await self._bye_and_terminate(call, "answer without SRTP on a TLS call")
            return
        if not report or call.dds_call_id is None:
            return
        await self._join_room(
            call,
            DialedCall(
                call_id=call.dds_call_id,
                session_id=str(dialed.get("session_id", "")),
                room_name=str(dialed.get("room", "")),
                kind=str(dialed.get("call_kind", "")),
                persona_id=dialed.get("persona_id"),
            ),
        )
        state = await self._report(call.dds_call_id, "UP")
        logger.info("ДДС call %s: softphone answered, leg UP -> %s", call.dds_call_id, state)
        if state == "ENDED" or call.dds_ended is not None:
            await self._bye_and_terminate(call, "ДДС call ended while the softphone answered")

    def _accept_srtp_answer(self, call: _Call, answer: SdpMedia) -> None:
        assert call.local_crypto is not None and call.rtp is not None
        try:
            remote = accept_answer(answer, call.local_crypto)
            call.rtp.srtp = SrtpContext(local_key=call.local_crypto.key, remote_key=remote.key)
        except (MediaRejected, SrtpError) as exc:
            logger.info("ДДС call %s: softphone answer refused (%s)", call.dds_call_id, exc)

    def _send_uac_ack(self, call: _Call) -> None:
        channel = call.dialog.channel
        port = self._listen_port(channel)
        ack = call.dialog.ack_for_2xx(
            call.invite.cseq[0], via_host=self._advertised_ip(channel.peer[0]), via_port=port
        )
        channel.send_message(ack)

    def _on_stray_response(self, response: SipMessage, channel: Channel) -> None:
        """A retransmitted `200` to our own INVITE (our ACK was lost): ACK it again."""
        call = self._calls.get(response.call_id)
        try:
            method = response.cseq[1]
        except ValueError:
            return
        if call is None or not call.uac or method != "INVITE":
            return
        if 200 <= (response.status or 0) < 300 and call.dialog.state is DialogState.CONFIRMED:
            self._send_uac_ack(call)

    # -- media ----------------------------------------------------------------------------------

    def _on_rtp(self, call: _Call, packet: RtpPacket, arrival: float) -> None:
        if not call.answered or call.rtp is None:
            return
        if call.route.kind is RouteKind.ECHO:
            call.rtp.send_payload(packet.payload, marker=packet.marker)
            return
        if call.jitter is None:
            return
        call.jitter.push(packet)
        if call.jitter.primed and not any(t.get_name() == "playout" for t in call.tasks):
            call.tasks.append(self._spawn(self._playout(call), "playout"))

    async def _playout(self, call: _Call) -> None:
        """The jitter buffer's clock: one frame into the room every 20 ms (silence on a gap)."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        frame = 0
        silence = b"\x00" * FRAME_BYTES
        while call.bridge is not None and call.rtp is not None and call.jitter is not None:
            packet = call.jitter.pop()
            pcm = decode(packet.payload, call.rtp.payload_type) if packet is not None else silence
            await call.bridge.push(pcm)
            frame += 1
            delay = started + frame * PTIME_MS / 1000 - loop.time()
            await asyncio.sleep(max(0.0, delay))

    def _from_room(self, call: _Call, pcm: bytes) -> None:
        if call.rtp is not None and call.answered:
            call.rtp.send_pcm(pcm)

    # -- teardown -------------------------------------------------------------------------------

    async def _retransmit_2xx(self, call: _Call) -> None:
        """RFC 3261 §13.3.1.4: re-send the 200 until the ACK; no ACK within 32 s ⇒ BYE."""
        interval = 0.5
        waited = 0.0
        while call.dialog.state is DialogState.EARLY and self._alive(call):
            await asyncio.sleep(interval)
            waited += interval
            if call.dialog.state is not DialogState.EARLY or not self._alive(call):
                return
            if waited >= _UNACKED_2XX_TIMEOUT_S:
                logger.info("no ACK for call-id=%s: hanging up", call.dialog.call_id)
                await self._send_bye(call)
                await self._terminate(call, "no ACK")
                return
            if call.ok_response is not None:
                call.dialog.channel.send_message(call.ok_response)
            interval = min(interval * 2, 4.0)

    def _alive(self, call: _Call) -> bool:
        return self._calls.get(call.dialog.call_id) is call

    async def _send_bye(self, call: _Call) -> None:
        channel = call.dialog.channel
        bye = call.dialog.in_dialog_request(
            "BYE",
            via_host=self._advertised_ip(channel.peer[0]),
            via_port=self._listen_port(channel),
        )
        bye.add("User-Agent", SERVER_NAME)
        try:
            response = await self._transactions.request(bye, channel, timeout_s=_STOP_BYE_TIMEOUT_S)
            logger.info("BYE call-id=%s answered %s", call.dialog.call_id, response.status)
        except TransactionTimeout:
            logger.info("BYE call-id=%s: no answer", call.dialog.call_id)

    async def _terminate(self, call: _Call, why: str) -> None:
        if call.dds_call_id is not None and self._dds.get(call.dds_call_id) is call:
            del self._dds[call.dds_call_id]
        if self._calls.get(call.dialog.call_id) is not call:
            return
        del self._calls[call.dialog.call_id]
        call.dialog.state = DialogState.TERMINATED
        call.cancelled.set()
        current = asyncio.current_task()
        for task in call.tasks:
            if task is not current:
                task.cancel()
        if call.bridge is not None:
            with contextlib.suppress(Exception):
                await call.bridge.close()
        rtp = call.rtp
        if rtp is not None:
            rtp.close()
            duration = self._clock() - call.started_at
            logger.info(
                "call %s ended (%s) after %.1fs: rtp sent=%d received=%d lost=%d jitter=%.1fms",
                call.dialog.call_id,
                why,
                duration,
                rtp.sent,
                rtp.stats.received,
                rtp.stats.lost,
                rtp.stats.jitter_ms,
            )

    # -- addressing -----------------------------------------------------------------------------

    def _advertised_ip(self, peer_host: str) -> str:
        """What we put in SDP / Contact / Via: `SIM_SIP_MEDIA_IP`, else our route to the peer."""
        if self.config.media_ip:
            return self.config.media_ip
        if self.config.bind_host not in ("0.0.0.0", ""):
            return self.config.bind_host
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            try:
                probe.connect((peer_host, 9))
                return str(probe.getsockname()[0])
            except OSError:
                return "127.0.0.1"

    def _listen_port(self, channel: Channel) -> int:
        """Our listening port for the channel's transport (Via sent-by, Contact)."""
        port = {"TLS": self.tls_port, "TCP": self.tcp_port}.get(channel.kind, self.udp_port)
        return port or 0

    def _contact(self, call: _Call, channel: Channel) -> tuple[str, str]:
        port = self._listen_port(channel)
        host = self._advertised_ip(channel.peer[0])
        target = f"sip:{call.dialed or 'gateway'}@{host}:{port}{channel.transport_param}"
        return ("Contact", f"<{target}>")


def _ack_non_2xx(invite: SipMessage, response: SipMessage) -> SipMessage:
    """RFC 3261 §17.1.1.3: the ACK of a non-2xx final belongs to the INVITE transaction."""
    ack = SipMessage(method="ACK", uri=invite.uri)
    ack.add("Via", invite.get("Via") or "")
    ack.add("Max-Forwards", "70")
    ack.add("From", invite.get("From") or "")
    ack.add("To", response.get("To") or invite.get("To") or "")
    ack.add("Call-ID", invite.call_id)
    ack.add("CSeq", f"{invite.cseq[0]} ACK")
    return ack


def to_uri(request: SipMessage) -> str:
    return parse_name_addr(request.get("To") or "").uri


def _reason_text(text: str) -> str:
    """A reason phrase from an error message: printable ASCII, no CR/LF, bounded."""
    cleaned = "".join(ch for ch in text if 32 <= ord(ch) < 127)
    return ("Bad Request - " + cleaned)[:80]

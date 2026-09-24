"""The SIP gateway process core (HLD 80 §80.2.1 `gateway.py`, §80.2.3, D22).

UDP + TCP listeners on `SIM_SIP_PORT`; the registrar; the UAS side of every call (INVITE →
100/180/200, ACK, BYE, CANCEL, re-INVITE answered with the same SDP, OPTIONS); dial handling
through a `Router`; health `GET /health` on `127.0.0.1:SIM_SIP_GATEWAY_HTTP_PORT`; a `BYE` to
every live call on `stop()` (SIGTERM, `voice_agent.sip_gateway`).

Dial handling in E6a (`default_router`): `999` is the gateway-local **echo** — no backend, no
room; every RTP payload is sent straight back re-stamped with the gateway's own SSRC/sequence/
timestamp, so it is the interop and latency probe (80 §80.2.3 step 6). Every other number is
`404 Not Found` until E6e routes it through `POST /api/v1/telephony/dial`. A `Route` of kind
`BRIDGE` connects the call to a `RoomPort` (`FakeRoomBridge` in the gate, `LiveKitRoomBridge`
for real, used today by `benchmarks/benchmark_voip.py --path sip-livekit`): inbound RTP goes
through the jitter buffer on a 20 ms playout clock into the room; the room's audio goes out as RTP.

An INVITE is accepted only from a user with a live registration (`403` otherwise): in E6a the
registration's Digest check is the only credential check there is. A malformed request is
answered `400` when enough of it survived to address an answer, and never raises out of the
listener. The gateway logs no credential and no `Authorization` header.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import json
import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from voice_agent.transport.sip.bridge import RoomPort
from voice_agent.transport.sip.dialog import (
    Channel,
    ClientTransactions,
    Dialog,
    DialogState,
    ServerTransactionCache,
    SipEndpoint,
    TransactionTimeout,
    stamp_received,
)
from voice_agent.transport.sip.message import (
    SipMessage,
    SipParseError,
    build_response,
    build_sdp,
    choose_codec,
    new_tag,
    parse_message,
    parse_name_addr,
    parse_sdp,
    parse_uri,
    user_of,
)
from voice_agent.transport.sip.registrar import Registrar
from voice_agent.transport.sip.rtp import (
    FRAME_BYTES,
    PTIME_MS,
    JitterBuffer,
    PortAllocator,
    RtpPacket,
    RtpSession,
    decode,
)

__all__ = [
    "ECHO_EXTENSION",
    "Route",
    "RouteKind",
    "SipGateway",
    "SipGatewayConfig",
    "default_router",
]

logger = logging.getLogger(__name__)

ECHO_EXTENSION = "999"
ALLOW = "INVITE, ACK, BYE, CANCEL, OPTIONS, REGISTER"
SERVER_NAME = "sim112-sip-gateway"
_STOP_BYE_TIMEOUT_S = 2.0
_UNACKED_2XX_TIMEOUT_S = 32.0


@dataclass(frozen=True)
class SipGatewayConfig:
    """The gateway's settings (80 §80.2.1's `SIM_SIP_*` keys).

    Read from the environment by `from_env()` (process env first, then the `.env` file `Settings`
    reads). They are not `app.config.settings.Settings` fields in E6a: the gateway needs none of
    the backend's required settings (database, Redis, JWT secret), and moving them into `Settings`
    is left to the epic that first needs both (E6e) — the key names are identical either way.
    """

    password: str
    realm: str = "sim112"
    bind_host: str = "0.0.0.0"
    sip_port: int = 5060
    rtp_port_range: str | None = "20000-20199"
    http_port: int | None = 8114
    media_ip: str | None = None
    jitter_ms: int = 40
    udp: bool = True
    tcp: bool = True

    @classmethod
    def from_env(cls, read: Callable[[str], str | None] | None = None) -> SipGatewayConfig:
        if read is None:
            from app.config.settings import read_env_value

            read = read_env_value

        def _int(name: str, default: int) -> int:
            value = read(name)
            return int(value) if value else default

        return cls(
            password=read("SIM_SIP_PASSWORD") or "",
            realm=read("SIM_SIP_REALM") or "sim112",
            bind_host=read("SIM_SIP_BIND_HOST") or "0.0.0.0",
            sip_port=_int("SIM_SIP_PORT", 5060),
            rtp_port_range=read("SIM_SIP_RTP_PORT_RANGE") or "20000-20199",
            http_port=_int("SIM_SIP_GATEWAY_HTTP_PORT", 8114),
            media_ip=read("SIM_SIP_MEDIA_IP") or None,
            jitter_ms=_int("SIM_SIP_JITTER_MS", 40),
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


Router = Callable[[str, str | None], Route]


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


class SipGateway:
    """Registrar + UAS + echo + bridge, over one UDP socket and one TCP listener."""

    def __init__(
        self,
        config: SipGatewayConfig,
        *,
        router: Router = default_router,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._router = router
        self._clock = clock
        self.registrar = Registrar(realm=config.realm, password=config.password, now=clock)
        self._endpoint = SipEndpoint(self._on_datagram)
        self._transactions = ClientTransactions()
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
    def live_calls(self) -> int:
        return len(self._calls)

    async def start(self) -> None:
        host, port = self.config.bind_host, self.config.sip_port
        if self.config.udp:
            port = await self._endpoint.listen_udp(host, port)
        if self.config.tcp:
            await self._endpoint.listen_tcp(host, port)
        if self.config.http_port is not None:
            self._http = await asyncio.start_server(
                self._serve_http, "127.0.0.1", self.config.http_port
            )
            sockets = self._http.sockets or ()
            self.http_port = int(sockets[0].getsockname()[1]) if sockets else None
        logger.info(
            "SIP gateway listening udp=%s tcp=%s host=%s realm=%s rtp=%s health=127.0.0.1:%s",
            self.udp_port,
            self.tcp_port,
            host,
            self.config.realm,
            self.config.rtp_port_range or "ephemeral",
            self.http_port,
        )

    async def stop(self) -> None:
        """BYE every answered call, refuse every ringing one, then close every socket."""
        self._stopping = True
        byes = []
        for call in list(self._calls.values()):
            if call.final_sent and call.answered:
                byes.append(self._send_bye(call))
            elif not call.final_sent:
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
            "registrations": len(self.registrar.bindings()),
            "calls": self.live_calls,
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
        response = self.registrar.handle_register(
            request, source=channel.peer, transport=channel.kind
        )
        self._respond(request, channel, response)

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
            self._on_reinvite(call, request, channel)
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
        route = self._router(dialed, from_user)
        if route.kind is RouteKind.REJECT:
            logger.info("INVITE %s from %s rejected %d", dialed, from_user, route.status)
            self._respond(request, channel, build_response(request, route.status, to_tag=new_tag()))
            return

        trying = build_response(request, 100)
        self._respond(request, channel, trying)
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
        self._calls[request.call_id] = call
        logger.info(
            "INVITE %s from %s (%r) codec=%s call-id=%s",
            dialed,
            from_user,
            channel,
            "PCMA" if codec == 8 else "PCMU",
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
            await rtp.open()
            call.rtp = rtp
            rtp.set_remote((offer.address, offer.port))
            advertised = self._advertised_ip(channel.peer[0])
            call.answer_sdp = build_sdp(
                address=advertised,
                port=rtp.local_port,
                payload_types=(codec,),
                session_id=int(self._clock() * 1000) % 1_000_000_000,
            )
            ringing = build_response(
                request, 180, to_tag=dialog.local_tag, headers=[self._contact(call, channel)]
            )
            self._respond(request, channel, ringing)
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
            ok = build_response(
                request,
                200,
                to_tag=dialog.local_tag,
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
            logger.info("200 OK %s call-id=%s rtp=%d", dialed, request.call_id, rtp.local_port)
            if not channel.reliable:
                call.tasks.append(self._spawn(self._retransmit_2xx(call), "2xx-retransmit"))
        except Exception:
            logger.exception("INVITE %s failed", request.call_id)
            if not call.final_sent:
                self._final(call, 500)
            await self._terminate(call, "setup failed")

    def _on_reinvite(self, call: _Call, request: SipMessage, channel: Channel) -> None:
        """A re-INVITE (hold, refresh): answered with the same SDP; the far RTP address updates."""
        with contextlib.suppress(ValueError):
            offer = parse_sdp(request.body)
            if call.rtp is not None:
                call.rtp.set_remote((offer.address, offer.port))
        call.dialog.remote_cseq = request.cseq[0]
        response = build_response(
            request,
            200,
            to_tag=call.dialog.local_tag,
            headers=[self._contact(call, channel), ("Content-Type", "application/sdp")],
            body=call.answer_sdp,
        )
        self._respond(request, channel, response)

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
        self._final(call, 487)
        logger.info("CANCEL call-id=%s: 487 Request Terminated", request.call_id)
        self._spawn(self._terminate(call, "CANCEL"), "cancel")

    def _final(self, call: _Call, status: int, reason: str | None = None) -> None:
        response = build_response(call.invite, status, reason, to_tag=call.dialog.local_tag)
        call.final_sent = True
        self._respond(call.invite, call.dialog.channel, response)

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
        port = self.tcp_port if channel.reliable else self.udp_port
        bye = call.dialog.in_dialog_request(
            "BYE", via_host=self._advertised_ip(channel.peer[0]), via_port=port or 0
        )
        bye.add("User-Agent", SERVER_NAME)
        try:
            response = await self._transactions.request(bye, channel, timeout_s=_STOP_BYE_TIMEOUT_S)
            logger.info("BYE call-id=%s answered %s", call.dialog.call_id, response.status)
        except TransactionTimeout:
            logger.info("BYE call-id=%s: no answer", call.dialog.call_id)

    async def _terminate(self, call: _Call, why: str) -> None:
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

    def _contact(self, call: _Call, channel: Channel) -> tuple[str, str]:
        port = self.tcp_port if channel.reliable else self.udp_port
        transport = ";transport=tcp" if channel.reliable else ""
        host = self._advertised_ip(channel.peer[0])
        return ("Contact", f"<sip:{call.dialed or 'gateway'}@{host}:{port}{transport}>")


def to_uri(request: SipMessage) -> str:
    return parse_name_addr(request.get("To") or "").uri


def _reason_text(text: str) -> str:
    """A reason phrase from an error message: printable ASCII, no CR/LF, bounded."""
    cleaned = "".join(ch for ch in text if 32 <= ord(ch) < 127)
    return ("Bad Request - " + cleaned)[:80]

"""SIP sockets, transactions and dialog state (HLD 80 §80.2.1 `dialog.py`).

Shared by both ends of a call — the gateway (UAS; UAC for its own `BYE`) and the headless
softphone (UAC):

* `SipEndpoint` — the UDP socket and/or TCP listener/connections, turning bytes into
  `(SipMessage-bytes, Channel)` for a handler; a `Channel` is "where to answer": the datagram's
  source address, or the TCP connection it came on (RFC 3581 symmetric response);
* `ClientTransactions` — requests we send: matched to responses by `Via` branch, retransmitted
  over UDP (RFC 3261 §17.1 timers A/E, T1 = 500 ms, T2 = 4 s) until a final response or 32 s;
* `ServerTransactionCache` — a retransmitted request gets the last response again, never a
  second execution;
* `Dialog` — `Call-ID` + tags, remote target, CSeq counters, and the in-dialog requests (`BYE`,
  `ACK`) built from them. A dialog maps to at most one `DdsCall.call_id` from E6e on.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from voice_agent.transport.sip.message import (
    SipMessage,
    SipParseError,
    StreamFramer,
    new_branch,
    parse_via,
)

__all__ = [
    "Address",
    "Channel",
    "ClientTransactions",
    "Dialog",
    "DialogState",
    "ServerTransactionCache",
    "SipEndpoint",
    "TransactionTimeout",
]

logger = logging.getLogger(__name__)

Address = tuple[str, int]
T1_S = 0.5
T2_S = 4.0
TIMER_B_S = 64 * T1_S


class Channel:
    """Where a message came from and where its answer goes."""

    def __init__(self, kind: str, peer: Address, sender: Callable[[bytes], None]) -> None:
        self.kind = kind  # "UDP" | "TCP"
        self.peer = peer
        self._sender = sender
        self.closed = False

    @property
    def reliable(self) -> bool:
        return self.kind == "TCP"

    def send(self, data: bytes) -> None:
        if self.closed:
            return
        try:
            self._sender(data)
        except Exception as exc:  # a vanished peer must never take the listener down
            logger.debug("send to %s:%d failed: %s", self.peer[0], self.peer[1], exc)

    def send_message(self, message: SipMessage) -> None:
        self.send(message.to_bytes())

    def __repr__(self) -> str:
        return f"Channel({self.kind} {self.peer[0]}:{self.peer[1]})"


Handler = Callable[[bytes, Channel], None]


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, endpoint: SipEndpoint) -> None:
        self._endpoint = endpoint
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.DatagramTransport)
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[Any, ...]) -> None:
        peer = (str(addr[0]), int(addr[1]))
        transport = self.transport
        assert transport is not None
        channel = Channel("UDP", peer, lambda payload: transport.sendto(payload, peer))
        self._endpoint.dispatch(data, channel)

    def error_received(self, exc: Exception) -> None:
        logger.debug("SIP UDP socket error: %s", exc)


class SipEndpoint:
    """UDP and TCP transports for SIP. Every inbound frame goes to `handler(data, channel)`."""

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self._udp: asyncio.DatagramTransport | None = None
        self._tcp_server: asyncio.Server | None = None
        self._tcp_tasks: set[asyncio.Task[None]] = set()
        self._tcp_writers: set[asyncio.StreamWriter] = set()
        self.udp_port: int | None = None
        self.tcp_port: int | None = None

    def dispatch(self, data: bytes, channel: Channel) -> None:
        try:
            self._handler(data, channel)
        except Exception:  # the listener never dies of one message
            logger.exception("SIP handler failed on a message from %r", channel)

    async def listen_udp(self, host: str, port: int) -> int:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self), local_addr=(host, port)
        )
        self._udp = transport
        self.udp_port = int(transport.get_extra_info("sockname")[1])
        return self.udp_port

    def udp_channel(self, peer: Address) -> Channel:
        """A channel that sends datagrams from our UDP socket to `peer` (UA side)."""
        transport = self._udp
        if transport is None:
            raise RuntimeError("listen_udp() first")
        return Channel("UDP", peer, lambda payload: transport.sendto(payload, peer))

    async def listen_tcp(self, host: str, port: int) -> int:
        self._tcp_server = await asyncio.start_server(self._serve_tcp, host, port)
        sockets = self._tcp_server.sockets or ()
        self.tcp_port = int(sockets[0].getsockname()[1]) if sockets else port
        return self.tcp_port

    async def connect_tcp(self, peer: Address) -> Channel:
        """An outbound TCP connection (UA side); its inbound frames go to the handler too."""
        reader, writer = await asyncio.open_connection(peer[0], peer[1])
        channel = self._tcp_channel(writer, peer)
        sockname = writer.get_extra_info("sockname")
        self.tcp_port = int(sockname[1]) if sockname else None
        task = asyncio.create_task(self._read_tcp(reader, writer, channel))
        self._tcp_tasks.add(task)
        task.add_done_callback(self._tcp_tasks.discard)
        return channel

    def _tcp_channel(self, writer: asyncio.StreamWriter, peer: Address) -> Channel:
        self._tcp_writers.add(writer)
        return Channel("TCP", peer, writer.write)

    async def _serve_tcp(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peername = writer.get_extra_info("peername") or ("?", 0)
        channel = self._tcp_channel(writer, (str(peername[0]), int(peername[1])))
        task = asyncio.current_task()
        if task is not None:
            self._tcp_tasks.add(task)
            task.add_done_callback(self._tcp_tasks.discard)
        await self._read_tcp(reader, writer, channel)

    async def _read_tcp(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, channel: Channel
    ) -> None:
        framer = StreamFramer()
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                try:
                    frames = framer.feed(data)
                except SipParseError as exc:
                    logger.info("dropping TCP connection %r: %s", channel, exc)
                    break
                for frame in frames:
                    self.dispatch(frame, channel)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            channel.closed = True
            self._tcp_writers.discard(writer)
            with contextlib.suppress(Exception):
                writer.close()

    async def close(self) -> None:
        if self._udp is not None:
            self._udp.close()
            self._udp = None
        if self._tcp_server is not None:
            self._tcp_server.close()
        for writer in list(self._tcp_writers):
            with contextlib.suppress(Exception):
                writer.close()
        for task in list(self._tcp_tasks):
            task.cancel()
        for task in list(self._tcp_tasks):
            with contextlib.suppress(BaseException):
                await task
        if self._tcp_server is not None:
            with contextlib.suppress(Exception):
                await self._tcp_server.wait_closed()
            self._tcp_server = None


class TransactionTimeout(TimeoutError):
    """No final response within timer B/F (32 s by default)."""


@dataclass
class _ClientTransaction:
    request: SipMessage
    channel: Channel
    future: asyncio.Future[SipMessage]
    on_provisional: Callable[[SipMessage], None] | None
    provisional_seen: bool = False


class ClientTransactions:
    """Requests we send, matched to their responses by top-`Via` branch + CSeq method."""

    def __init__(self, *, t1_s: float = T1_S, timeout_s: float = TIMER_B_S) -> None:
        self._t1 = t1_s
        self._timeout = timeout_s
        self._pending: dict[tuple[str, str], _ClientTransaction] = {}
        #: A 2xx for an INVITE that already completed (our ACK was lost): the UA re-ACKs it.
        self.on_stray_response: Callable[[SipMessage, Channel], None] | None = None

    async def request(
        self,
        request: SipMessage,
        channel: Channel,
        *,
        on_provisional: Callable[[SipMessage], None] | None = None,
        timeout_s: float | None = None,
    ) -> SipMessage:
        """Send `request` and return its final response (raises `TransactionTimeout`)."""
        via = request.top_via
        if via is None or not via.branch:
            raise ValueError("a client request needs a top Via with a branch")
        key = (via.branch, request.cseq[1])
        loop = asyncio.get_running_loop()
        txn = _ClientTransaction(request, channel, loop.create_future(), on_provisional)
        self._pending[key] = txn
        data = request.to_bytes()
        channel.send(data)
        retransmit: asyncio.Task[None] | None = None
        if not channel.reliable:
            retransmit = asyncio.create_task(self._retransmit(txn, data))
        try:
            return await asyncio.wait_for(txn.future, timeout_s or self._timeout)
        except TimeoutError as exc:
            raise TransactionTimeout(f"no final response to {request.summary()}") from exc
        finally:
            self._pending.pop(key, None)
            if retransmit is not None:
                retransmit.cancel()

    async def _retransmit(self, txn: _ClientTransaction, data: bytes) -> None:
        interval = self._t1
        is_invite = txn.request.method == "INVITE"
        while not txn.future.done():
            await asyncio.sleep(interval)
            if txn.future.done() or (is_invite and txn.provisional_seen):
                return
            txn.channel.send(data)
            interval = interval * 2 if is_invite else min(interval * 2, T2_S)

    def on_response(self, response: SipMessage, channel: Channel) -> bool:
        """Route one response; `True` when a pending transaction took it."""
        via = response.top_via
        try:
            method = response.cseq[1]
        except ValueError:
            return False
        if via is None or not via.branch:
            return False
        txn = self._pending.get((via.branch, method))
        if txn is None:
            if self.on_stray_response is not None:
                self.on_stray_response(response, channel)
            return False
        status = response.status or 0
        if status < 200:
            txn.provisional_seen = True
            if txn.on_provisional is not None:
                txn.on_provisional(response)
        elif not txn.future.done():
            txn.future.set_result(response)
        return True


class ServerTransactionCache:
    """The last response per server transaction, re-sent when the request is retransmitted."""

    def __init__(self, *, ttl_s: float = TIMER_B_S, now: Callable[[], float] = time.monotonic):
        self._ttl = ttl_s
        self._now = now
        self._entries: dict[tuple[str, str, str], tuple[bytes | None, float]] = {}

    @staticmethod
    def key(request: SipMessage) -> tuple[str, str, str] | None:
        via = request.top_via
        if via is None or not via.branch:
            return None
        method = request.method or ""
        return (via.branch, method, request.call_id)

    def begin(self, request: SipMessage) -> bool:
        """`True` for a new transaction; `False` for a retransmission of a known one."""
        self._expire()
        key = self.key(request)
        if key is None:
            return True
        return key not in self._entries

    def cached(self, request: SipMessage) -> bytes | None:
        key = self.key(request)
        entry = self._entries.get(key) if key else None
        return entry[0] if entry else None

    def remember(self, request: SipMessage, response: SipMessage | None) -> None:
        key = self.key(request)
        if key is not None:
            data = response.to_bytes() if response is not None else None
            self._entries[key] = (data, self._now() + self._ttl)

    def _expire(self) -> None:
        now = self._now()
        for key in [k for k, (_, until) in self._entries.items() if until <= now]:
            del self._entries[key]


class DialogState(enum.Enum):
    EARLY = "EARLY"
    CONFIRMED = "CONFIRMED"
    TERMINATED = "TERMINATED"


@dataclass
class Dialog:
    """One SIP dialog, from our side (RFC 3261 §12)."""

    call_id: str
    local_tag: str
    remote_tag: str | None
    local_uri: str  # our From (UAC) / To (UAS) URI
    remote_uri: str  # their From (UAS side) / To (UAC side) URI
    remote_target: str  # their Contact URI: the Request-URI of in-dialog requests
    channel: Channel
    local_cseq: int = 1
    remote_cseq: int = 0
    state: DialogState = DialogState.EARLY
    extra: dict[str, Any] = field(default_factory=dict)

    def in_dialog_request(self, method: str, *, via_host: str, via_port: int) -> SipMessage:
        """A new in-dialog request (`BYE`, re-`INVITE`): next CSeq, fresh branch."""
        self.local_cseq += 1
        return self._request(method, self.local_cseq, via_host=via_host, via_port=via_port)

    def ack_for_2xx(self, invite_cseq: int, *, via_host: str, via_port: int) -> SipMessage:
        """The ACK to a 2xx: its own transaction, the INVITE's CSeq number (RFC 3261 §13.2.2.4)."""
        return self._request("ACK", invite_cseq, via_host=via_host, via_port=via_port)

    def _request(self, method: str, cseq: int, *, via_host: str, via_port: int) -> SipMessage:
        request = SipMessage(method=method, uri=self.remote_target)
        request.add(
            "Via", f"SIP/2.0/{self.channel.kind} {via_host}:{via_port};branch={new_branch()};rport"
        )
        request.add("Max-Forwards", "70")
        request.add("From", f"<{self.local_uri}>;tag={self.local_tag}")
        to = f"<{self.remote_uri}>" + (f";tag={self.remote_tag}" if self.remote_tag else "")
        request.add("To", to)
        request.add("Call-ID", self.call_id)
        request.add("CSeq", f"{cseq} {method}")
        return request


def stamp_received(request: SipMessage, source: Address) -> None:
    """RFC 3581 / RFC 3261 §18.2.1: record where the top `Via` actually came from."""
    vias = request.get_all("Via")
    if not vias:
        return
    try:
        via = parse_via(vias[0])
    except ValueError:
        return
    if via.host != source[0]:
        via.params["received"] = source[0]
    if "rport" in via.params:
        via.params["rport"] = str(source[1])
        via.params["received"] = source[0]
    others = [(k, v) for k, v in request.headers if k != "Via"]
    first_via_index = next(i for i, (k, _) in enumerate(request.headers) if k == "Via")
    rebuilt = [("Via", str(via))] + [("Via", v) for v in vias[1:]]
    request.headers = others[:first_via_index] + rebuilt + others[first_via_index:]

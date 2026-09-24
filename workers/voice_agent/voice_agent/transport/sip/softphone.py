"""The headless SIP user agent (HLD 80 §80.2.1 `softphone.py`, §80.8).

One class, three uses: the gate's UA against the in-process gateway, the load generator and the
latency probe of `benchmarks/benchmark_voip.py`, and — wrapped by `voice_agent.tools.softphone`
with `--headset` (sox) — the software IP phone of ТЗ ¶175 for manual runs.

UAC: REGISTER (answering the 401 Digest challenge), INVITE with a PCMA/PCMU offer → ACK — a
`407 Proxy Authentication Required` is answered once with `Proxy-Authorization` (I3 E6e,
`SIM_SIP_INVITE_AUTH=challenge`), so is a re-INVITE's (`SoftCall.reinvite`) — CANCEL, BYE. UAS
(I3 E6e, being called: the ДДС click-to-call and a brigade's `CALL_IN`): `answer_mode` decides —
`busy` (the E6a default, `486 Busy Here`), `auto` (`180`, then `200` with an SDP answer after
`answer_delay_s`) or `ring` (`180` forever: the gateway's ring timeout); every incoming call is put
on `SoftPhone.incoming`. BYE and OPTIONS are answered in every mode. Audio is 8 kHz s16le mono in
20 ms frames on the caller's side of `SoftCall.send_pcm` / `SoftCall.received`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from voice_agent.transport.sip.dialog import (
    Channel,
    ClientTransactions,
    Dialog,
    DialogState,
    SipEndpoint,
)
from voice_agent.transport.sip.message import (
    PT_PCMA,
    PT_PCMU,
    SipMessage,
    SipParseError,
    build_authorization,
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
    user_of,
)
from voice_agent.transport.sip.rtp import PortAllocator, RtpPacket, RtpSession, decode

__all__ = ["CallFailed", "SoftCall", "SoftPhone", "ToneBurstProbe"]

logger = logging.getLogger(__name__)

USER_AGENT = "sim112-softphone"


class CallFailed(RuntimeError):
    """The INVITE ended in a non-2xx final response."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(f"{status} {reason}")
        self.status = status
        self.reason = reason


@dataclass
class SoftCall:
    """One outgoing call."""

    number: str
    call_id: str
    invite: SipMessage
    phone: SoftPhone
    provisional: list[int] = field(default_factory=list)
    final_status: int | None = None
    dialog: Dialog | None = None
    rtp: RtpSession | None = None
    codec: int | None = None
    #: `(arrival_s, packet)` for every RTP packet received, in arrival order.
    received: list[tuple[float, RtpPacket]] = field(default_factory=list)
    on_audio: Callable[[bytes, float], None] | None = None
    final_reason: str = ""
    _ended: asyncio.Event = field(default_factory=asyncio.Event)
    _answered: asyncio.Future[SipMessage] | None = None
    ended_by_remote: bool = False
    #: I3 E6e: `True` for a call the gateway placed to us (click-to-call / `CALL_IN`).
    incoming: bool = False
    #: The INVITE was challenged `407` and retried with `Proxy-Authorization`.
    challenged: bool = False
    _confirmed: asyncio.Event = field(default_factory=asyncio.Event)
    #: An incoming call: our To tag and our `200 OK` (re-sent for a retransmitted INVITE).
    local_tag: str = ""
    ok: SipMessage | None = None

    @property
    def is_up(self) -> bool:
        return self.dialog is not None and self.dialog.state is DialogState.CONFIRMED

    async def wait_final(self, timeout_s: float = 10.0) -> int:
        """The INVITE's final status (200 once answered)."""
        assert self._answered is not None
        response = await asyncio.wait_for(asyncio.shield(self._answered), timeout_s)
        return response.status or 0

    async def wait_ended(self, timeout_s: float) -> bool:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._ended.wait(), timeout_s)
        return self._ended.is_set()

    def send_pcm(self, pcm: bytes) -> RtpPacket | None:
        if self.rtp is None or self.dialog is None:
            return None
        return self.rtp.send_pcm(pcm)

    def received_pcm(self) -> bytes:
        if self.codec is None:
            return b""
        return b"".join(decode(packet.payload, self.codec) for _, packet in self.received)

    async def wait_confirmed(self, timeout_s: float = 10.0) -> bool:
        """An incoming call: our `200` was ACKed (the dialog is up)."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._confirmed.wait(), timeout_s)
        return self._confirmed.is_set()

    async def cancel(self) -> int:
        """CANCEL the pending INVITE; returns the CANCEL's own final status."""
        return await self.phone._cancel(self)

    async def reinvite(self) -> int:
        """An in-dialog re-INVITE with the same offer (a session refresh); its final status."""
        return await self.phone._reinvite(self)

    async def hangup(self) -> int:
        """BYE; returns its final status (0 if the call was not up)."""
        return await self.phone._hangup(self)

    def _on_rtp(self, packet: RtpPacket, arrival: float) -> None:
        self.received.append((arrival, packet))
        if self.on_audio is not None and self.codec is not None:
            self.on_audio(decode(packet.payload, self.codec), arrival)


class SoftPhone:
    """A SIP UA bound to one local UDP port (or one TCP connection) towards one registrar."""

    def __init__(
        self,
        *,
        server: tuple[str, int],
        username: str,
        password: str,
        transport: str = "udp",
        local_host: str = "127.0.0.1",
        domain: str | None = None,
        rtp_port_range: str | None = None,
        codecs: tuple[int, ...] = (PT_PCMA, PT_PCMU),
        clock: Callable[[], float] = time.monotonic,
        answer_mode: str = "busy",
        answer_delay_s: float = 0.2,
    ) -> None:
        if answer_mode not in ("busy", "auto", "ring"):
            raise ValueError(f"unknown answer_mode {answer_mode!r}")
        self.server = server
        self.username = username
        self._password = password
        self.transport = transport.upper()
        self.local_host = local_host
        self.domain = domain or server[0]
        self.codecs = codecs
        self._clock = clock
        self._endpoint = SipEndpoint(self._on_frame)
        self._transactions = ClientTransactions()
        self._transactions.on_stray_response = self._on_stray_response
        self._allocator = PortAllocator(rtp_port_range)
        self._channel: Channel | None = None
        self._calls: dict[str, SoftCall] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._register_call_id = new_call_id(local_host)
        self._register_cseq = 0
        self._local_tag = new_tag()
        self.local_port = 0
        self.answer_mode = answer_mode
        self.answer_delay_s = answer_delay_s
        #: Every call the gateway placed to us, in arrival order (I3 E6e).
        self.incoming: asyncio.Queue[SoftCall] = asyncio.Queue()

    # -- lifecycle ------------------------------------------------------------------------------

    async def start(self) -> None:
        if self.transport == "TCP":
            self._channel = await self._endpoint.connect_tcp(self.server)
            self.local_port = self._endpoint.tcp_port or 0
        else:
            self.local_port = await self._endpoint.listen_udp(self.local_host, 0)
            self._channel = self._endpoint.udp_channel(self.server)

    async def close(self) -> None:
        for call in list(self._calls.values()):
            if call.rtp is not None:
                call.rtp.close()
        self._calls.clear()
        for task in list(self._tasks):
            task.cancel()
        await self._endpoint.close()

    async def __aenter__(self) -> SoftPhone:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    @property
    def aor(self) -> str:
        return f"sip:{self.username}@{self.domain}"

    def _contact(self) -> str:
        suffix = ";transport=tcp" if self.transport == "TCP" else ""
        return f"<sip:{self.username}@{self.local_host}:{self.local_port or 5060}{suffix}>"

    def _via(self) -> str:
        return (
            f"SIP/2.0/{self.transport} {self.local_host}:{self.local_port or 5060}"
            f";branch={new_branch()};rport"
        )

    def _channel_or_raise(self) -> Channel:
        if self._channel is None:
            raise RuntimeError("start() the phone first")
        return self._channel

    # -- REGISTER -------------------------------------------------------------------------------

    async def register(self, expires: int = 300) -> SipMessage:
        """REGISTER, answering one 401 challenge; returns the final response."""
        response = await self._register_once(expires, challenge=None)
        if response.status == 401:
            challenge = response.get("WWW-Authenticate") or ""
            _, params = parse_auth_header(challenge)
            response = await self._register_once(expires, challenge=params)
        logger.info("REGISTER %s -> %s %s", self.username, response.status, response.reason)
        return response

    async def unregister(self) -> SipMessage:
        return await self.register(expires=0)

    async def _register_once(self, expires: int, challenge: dict[str, str] | None) -> SipMessage:
        self._register_cseq += 1
        uri = f"sip:{self.domain}"
        request = SipMessage(method="REGISTER", uri=uri)
        request.add("Via", self._via())
        request.add("Max-Forwards", "70")
        request.add("From", f"<{self.aor}>;tag={self._local_tag}")
        request.add("To", f"<{self.aor}>")
        request.add("Call-ID", self._register_call_id)
        request.add("CSeq", f"{self._register_cseq} REGISTER")
        request.add("Contact", self._contact())
        request.add("Expires", str(expires))
        request.add("User-Agent", USER_AGENT)
        if challenge is not None:
            request.add(
                "Authorization",
                build_authorization(
                    username=self.username,
                    password=self._password,
                    method="REGISTER",
                    uri=uri,
                    challenge=challenge,
                ),
            )
        return await self._transactions.request(request, self._channel_or_raise())

    # -- INVITE ---------------------------------------------------------------------------------

    async def begin_call(self, number: str, *, codecs: tuple[int, ...] | None = None) -> SoftCall:
        """Send the INVITE and return at once; `await call.wait_final()` for the answer."""
        offered = codecs or self.codecs
        call_id = new_call_id(self.local_host)
        rtp = RtpSession(
            bind_host=self.local_host,
            allocator=self._allocator,
            payload_type=offered[0],
            clock=self._clock,
        )
        await rtp.open()
        target = f"sip:{number}@{self.domain}"
        invite = SipMessage(method="INVITE", uri=target)
        invite.add("Via", self._via())
        invite.add("Max-Forwards", "70")
        invite.add("From", f"<{self.aor}>;tag={new_tag()}")
        invite.add("To", f"<{target}>")
        invite.add("Call-ID", call_id)
        invite.add("CSeq", "1 INVITE")
        invite.add("Contact", self._contact())
        invite.add("User-Agent", USER_AGENT)
        invite.add("Content-Type", "application/sdp")
        invite.body = build_sdp(
            address=self.local_host,
            port=rtp.local_port,
            payload_types=offered,
            session_id=int(self._clock() * 1000) % 1_000_000_000,
            telephone_event=101,
        )
        call = SoftCall(number=number, call_id=call_id, invite=invite, phone=self, rtp=rtp)
        rtp.on_packet = call._on_rtp
        self._calls[call_id] = call
        loop = asyncio.get_running_loop()
        call._answered = loop.create_future()
        task = asyncio.create_task(self._run_invite(call))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return call

    async def call(self, number: str, *, timeout_s: float = 10.0, **kwargs: object) -> SoftCall:
        """INVITE → ACK; raises `CallFailed` on a non-2xx final."""
        call = await self.begin_call(number, **kwargs)  # type: ignore[arg-type]
        status = await call.wait_final(timeout_s)
        if status != 200:
            raise CallFailed(status, call.final_reason)
        return call

    async def _run_invite(self, call: SoftCall) -> None:
        assert call._answered is not None
        try:
            response = await self._transactions.request(
                call.invite,
                self._channel_or_raise(),
                on_provisional=lambda r: call.provisional.append(r.status or 0),
            )
        except Exception as exc:
            if not call._answered.done():
                call._answered.set_exception(exc)
            return
        if response.status == 407 and not call.challenged:
            # I3 E6e: the gateway challenges every INVITE; answer once for the same user.
            self._ack_non_2xx(call, response)
            call.challenged = True
            call.invite = self._authorised_retry(call.invite, response)
            try:
                response = await self._transactions.request(
                    call.invite,
                    self._channel_or_raise(),
                    on_provisional=lambda r: call.provisional.append(r.status or 0),
                )
            except Exception as exc:
                if not call._answered.done():
                    call._answered.set_exception(exc)
                return
        call.final_status = response.status
        call.final_reason = response.reason
        status = response.status or 0
        if 200 <= status < 300:
            self._on_invite_2xx(call, response)
        else:
            self._ack_non_2xx(call, response)
            if call.rtp is not None:
                call.rtp.close()
            call._ended.set()
            self._calls.pop(call.call_id, None)
        if not call._answered.done():
            call._answered.set_result(response)

    def _authorised_retry(self, request: SipMessage, challenge: SipMessage) -> SipMessage:
        """The same request, next CSeq, fresh branch, with `Proxy-Authorization` (RFC 3261
        §22.3) answering `challenge`'s `Proxy-Authenticate`."""
        _, params = parse_auth_header(challenge.get("Proxy-Authenticate") or "")
        number, method = request.cseq
        retry = SipMessage(method=request.method, uri=request.uri, body=request.body)
        for name, value in request.headers:
            if name in ("Via", "CSeq", "Proxy-Authorization"):
                continue
            retry.add(name, value)
        retry.headers.insert(0, ("Via", self._via()))
        retry.set("CSeq", f"{number + 1} {method}")
        retry.add(
            "Proxy-Authorization",
            build_authorization(
                username=self.username,
                password=self._password,
                method=method,
                uri=request.uri or "",
                challenge=params,
            ),
        )
        return retry

    def _on_invite_2xx(self, call: SoftCall, response: SipMessage) -> None:
        to = parse_name_addr(response.get("To") or "")
        contact = response.get("Contact")
        dialog = Dialog(
            call_id=call.call_id,
            local_tag=parse_name_addr(call.invite.get("From") or "").tag or "",
            remote_tag=to.tag,
            local_uri=self.aor,
            remote_uri=to.uri,
            remote_target=parse_name_addr(contact).uri if contact else call.invite.uri or "",
            channel=self._channel_or_raise(),
            local_cseq=call.invite.cseq[0],
        )
        call.dialog = dialog
        try:
            answer = parse_sdp(response.body)
            call.codec = answer.payload_types[0]
        except (ValueError, IndexError):
            call.codec = None
        if call.rtp is not None and call.codec is not None:
            call.rtp.payload_type = call.codec
            call.rtp.set_remote((answer.address, answer.port))
        self._send_ack(call)
        dialog.state = DialogState.CONFIRMED

    def _send_ack(self, call: SoftCall) -> None:
        assert call.dialog is not None
        ack = call.dialog.ack_for_2xx(
            call.invite.cseq[0], via_host=self.local_host, via_port=self.local_port or 5060
        )
        self._channel_or_raise().send_message(ack)

    def _ack_non_2xx(self, call: SoftCall, response: SipMessage) -> None:
        """RFC 3261 §17.1.1.3: the ACK of a non-2xx final is part of the INVITE transaction."""
        ack = SipMessage(method="ACK", uri=call.invite.uri)
        ack.add("Via", call.invite.get("Via") or "")
        ack.add("Max-Forwards", "70")
        ack.add("From", call.invite.get("From") or "")
        ack.add("To", response.get("To") or call.invite.get("To") or "")
        ack.add("Call-ID", call.call_id)
        ack.add("CSeq", f"{call.invite.cseq[0]} ACK")
        self._channel_or_raise().send_message(ack)

    async def _cancel(self, call: SoftCall) -> int:
        cancel = SipMessage(method="CANCEL", uri=call.invite.uri)
        cancel.add("Via", call.invite.get("Via") or "")
        cancel.add("Max-Forwards", "70")
        cancel.add("From", call.invite.get("From") or "")
        cancel.add("To", call.invite.get("To") or "")
        cancel.add("Call-ID", call.call_id)
        cancel.add("CSeq", f"{call.invite.cseq[0]} CANCEL")
        response = await self._transactions.request(cancel, self._channel_or_raise())
        return response.status or 0

    async def _hangup(self, call: SoftCall) -> int:
        if call.dialog is None or call.dialog.state is not DialogState.CONFIRMED:
            return 0
        bye = call.dialog.in_dialog_request(
            "BYE", via_host=self.local_host, via_port=self.local_port or 5060
        )
        bye.add("User-Agent", USER_AGENT)
        call.dialog.state = DialogState.TERMINATED
        response = await self._transactions.request(bye, self._channel_or_raise())
        self._end(call)
        return response.status or 0

    async def _reinvite(self, call: SoftCall) -> int:
        if call.dialog is None or call.dialog.state is not DialogState.CONFIRMED:
            return 0
        request = call.dialog.in_dialog_request(
            "INVITE", via_host=self.local_host, via_port=self.local_port or 5060
        )
        request.add("Contact", self._contact())
        request.add("User-Agent", USER_AGENT)
        request.add("Content-Type", "application/sdp")
        request.body = (call.invite.body if not call.incoming else b"") or build_sdp(
            address=self.local_host,
            port=call.rtp.local_port if call.rtp is not None else 0,
            payload_types=self.codecs,
            session_id=int(self._clock() * 1000) % 1_000_000_000,
        )
        channel = self._channel_or_raise()
        response = await self._transactions.request(request, channel)
        if response.status == 407:
            channel.send_message(self._ack_for(request, response))
            request = self._authorised_retry(request, response)
            call.dialog.local_cseq = request.cseq[0]
            response = await self._transactions.request(request, channel)
        if 200 <= (response.status or 0) < 300:
            channel.send_message(
                call.dialog.ack_for_2xx(
                    request.cseq[0], via_host=self.local_host, via_port=self.local_port or 5060
                )
            )
        else:
            channel.send_message(self._ack_for(request, response))
        return response.status or 0

    def _ack_for(self, request: SipMessage, response: SipMessage) -> SipMessage:
        ack = SipMessage(method="ACK", uri=request.uri)
        ack.add("Via", request.get("Via") or "")
        ack.add("Max-Forwards", "70")
        ack.add("From", request.get("From") or "")
        ack.add("To", response.get("To") or request.get("To") or "")
        ack.add("Call-ID", request.call_id)
        ack.add("CSeq", f"{request.cseq[0]} ACK")
        return ack

    def _end(self, call: SoftCall) -> None:
        if call.rtp is not None:
            call.rtp.close()
        call._ended.set()
        self._calls.pop(call.call_id, None)

    # -- inbound --------------------------------------------------------------------------------

    def _on_frame(self, data: bytes, channel: Channel) -> None:
        if not data.strip():
            return
        try:
            message = parse_message(data)
        except SipParseError as exc:
            logger.info("softphone: malformed message from %s:%d: %s", *channel.peer, exc)
            return
        if not message.is_request:
            self._transactions.on_response(message, channel)
            return
        method = message.method
        if method == "BYE":
            call = self._calls.get(message.call_id)
            channel.send_message(build_response(message, 200 if call else 481))
            if call is not None:
                if call.dialog is not None:
                    call.dialog.state = DialogState.TERMINATED
                call.ended_by_remote = True
                self._end(call)
        elif method == "OPTIONS":
            channel.send_message(build_response(message, 200, to_tag=new_tag()))
        elif method == "INVITE":
            self._on_incoming_invite(message, channel)
        elif method == "ACK":
            call = self._calls.get(message.call_id)
            if call is not None and call.incoming and call.dialog is not None:
                call.dialog.state = DialogState.CONFIRMED
                call._confirmed.set()
        elif method == "CANCEL":
            call = self._calls.get(message.call_id)
            channel.send_message(build_response(message, 200 if call else 481))
            if call is not None and call.incoming and not call._confirmed.is_set():
                if call.final_status is None:
                    call.final_status = 487
                    channel.send_message(build_response(call.invite, 487, to_tag=call.local_tag))
                call.ended_by_remote = True
                self._end(call)
        else:
            channel.send_message(build_response(message, 501, to_tag=new_tag()))

    # -- being called (I3 E6e) ---------------------------------------------------------------

    def _on_incoming_invite(self, invite: SipMessage, channel: Channel) -> None:
        existing = self._calls.get(invite.call_id)
        if existing is not None:
            if existing.incoming and existing.final_status == 200 and existing.ok is not None:
                channel.send_message(existing.ok)  # a retransmitted INVITE: our 200 again
            elif existing.incoming and parse_name_addr(invite.get("To") or "").tag:
                self._answer_reinvite(existing, invite, channel)
            return
        if self.answer_mode == "busy":
            channel.send_message(build_response(invite, 486, to_tag=new_tag()))
            return
        task = asyncio.create_task(self._take_call(invite, channel))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _take_call(self, invite: SipMessage, channel: Channel) -> None:
        try:
            offer = parse_sdp(invite.body)
        except ValueError:
            channel.send_message(build_response(invite, 488, to_tag=new_tag()))
            return
        codec = choose_codec(offer, self.codecs)
        if codec is None:
            channel.send_message(build_response(invite, 488, to_tag=new_tag()))
            return
        rtp = RtpSession(
            bind_host=self.local_host,
            allocator=self._allocator,
            payload_type=codec,
            clock=self._clock,
        )
        await rtp.open()
        rtp.set_remote((offer.address, offer.port))
        sender = parse_name_addr(invite.get("From") or "")
        contact = invite.get("Contact")
        call = SoftCall(
            number=user_of(invite.get("From") or "") or "",
            call_id=invite.call_id,
            invite=invite,
            phone=self,
            rtp=rtp,
            codec=codec,
            incoming=True,
        )
        call.local_tag = new_tag()
        rtp.on_packet = call._on_rtp
        call.dialog = Dialog(
            call_id=invite.call_id,
            local_tag=call.local_tag,
            remote_tag=sender.tag,
            local_uri=parse_name_addr(invite.get("To") or "").uri,
            remote_uri=sender.uri,
            remote_target=parse_name_addr(contact).uri if contact else sender.uri,
            channel=channel,
            remote_cseq=invite.cseq[0],
        )
        self._calls[invite.call_id] = call
        channel.send_message(build_response(invite, 180, to_tag=call.local_tag))
        self.incoming.put_nowait(call)
        if self.answer_mode == "ring":
            return
        await asyncio.sleep(self.answer_delay_s)
        if call._ended.is_set():
            return
        call.ok = build_response(
            invite,
            200,
            to_tag=call.local_tag,
            headers=[("Contact", self._contact()), ("Content-Type", "application/sdp")],
            body=build_sdp(
                address=self.local_host,
                port=rtp.local_port,
                payload_types=(codec,),
                session_id=int(self._clock() * 1000) % 1_000_000_000,
            ),
        )
        call.final_status = 200
        for _ in range(8):  # RFC 3261 §13.3.1.4, loosely: re-send the 200 until the ACK
            channel.send_message(call.ok)
            if await call.wait_confirmed(0.5) or call._ended.is_set():
                return

    def _answer_reinvite(self, call: SoftCall, invite: SipMessage, channel: Channel) -> None:
        body = call.ok.body if call.ok is not None else b""
        channel.send_message(
            build_response(
                invite,
                200,
                to_tag=call.local_tag,
                headers=[("Contact", self._contact()), ("Content-Type", "application/sdp")],
                body=body,
            )
        )

    def _on_stray_response(self, response: SipMessage, channel: Channel) -> None:
        """A retransmitted 2xx to an INVITE (our ACK was lost): ACK it again."""
        try:
            method = response.cseq[1]
        except ValueError:
            return
        call = self._calls.get(response.call_id)
        is_2xx = 200 <= (response.status or 0) < 300
        if method == "INVITE" and is_2xx and call is not None and call.dialog is not None:
            self._send_ack(call)


class ToneBurstProbe:
    """The latency probe of 80 §80.8.3: 1 kHz bursts at known send offsets, detected by energy.

    The sender asks `frame(index)` for each 20 ms frame and calls `mark_sent(index, t)` right
    after sending it; the far end (or the echo, back at the sender) feeds every received frame to
    `observe(pcm, t)`. Times are one host clock (`time.monotonic` / the event loop's), so no
    clock sync is involved. The instant a burst *began* is taken on both sides at sample
    resolution: the first sample of a sent frame was captured one frame before it was sent, and
    the first loud sample of a received frame came `(frame_len - index) / rate` before the frame
    was delivered. Both corrections are the same model, so a zero-latency path measures 0.
    """

    def __init__(
        self,
        *,
        interval_ms: int = 2000,
        burst_ms: int = 100,
        tone_hz: int = 1000,
        amplitude: int = 8000,
        sample_rate: int = 8000,
        frame_ms: int = 20,
    ) -> None:
        if interval_ms % frame_ms or burst_ms % frame_ms or burst_ms >= interval_ms:
            raise ValueError("interval and burst must be whole frames, burst < interval")
        self.interval_frames = interval_ms // frame_ms
        self.burst_frames = burst_ms // frame_ms
        self.sample_rate = sample_rate
        self.frame_samples = sample_rate * frame_ms // 1000
        self.threshold = amplitude // 4
        self._frame_s = frame_ms / 1000.0
        samples = self.frame_samples * self.burst_frames
        tone = [
            int(amplitude * math.sin(2 * math.pi * tone_hz * n / sample_rate))
            for n in range(samples)
        ]
        self._burst = struct.pack(f"<{samples}h", *tone)
        self._silence = b"\x00" * (self.frame_samples * 2)
        #: Capture instant of each burst's first sample, in send order.
        self.sent: list[float] = []
        #: Delivery instant of each detected burst onset, in arrival order.
        self.arrived: list[float] = []
        self._quiet_frames = 1_000

    def frame(self, index: int) -> bytes:
        position = index % self.interval_frames
        if position < self.burst_frames:
            start = position * self.frame_samples * 2
            return self._burst[start : start + self.frame_samples * 2]
        return self._silence

    def is_onset(self, index: int) -> bool:
        return index % self.interval_frames == 0

    def mark_sent(self, index: int, sent_at: float) -> None:
        if self.is_onset(index):
            self.sent.append(sent_at - self._frame_s)

    def observe(self, pcm: bytes, delivered_at: float) -> None:
        count = len(pcm) // 2
        if count == 0:
            return
        samples = struct.unpack(f"<{count}h", pcm[: count * 2])
        loud_at = next((i for i, s in enumerate(samples) if abs(s) > self.threshold), None)
        if loud_at is None:
            self._quiet_frames += 1
            return
        if self._quiet_frames >= 3:
            self.arrived.append(delivered_at - (count - loud_at) / self.sample_rate)
        self._quiet_frames = 0

    def delays_ms(self) -> list[float]:
        """One delay per detected burst: arrival − the latest burst sent before it."""
        delays: list[float] = []
        window = self.interval_frames * self._frame_s
        for arrival in self.arrived:
            earlier = [sent for sent in self.sent if sent <= arrival]
            if earlier and arrival - earlier[-1] < window:
                delays.append((arrival - earlier[-1]) * 1000.0)
        return delays

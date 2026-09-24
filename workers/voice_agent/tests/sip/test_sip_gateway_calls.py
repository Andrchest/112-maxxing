"""The headless UA against the in-process gateway on loopback (HLD 80 §80.8.1 row (1), E6a).

REGISTER 401 → 200 (UDP and TCP), wrong password 403, expiry; INVITE 100/180/200/ACK with the SDP
answer selecting PCMA or PCMU; 2 s of RTP both ways with sequence/timestamp continuity; BYE,
CANCEL, OPTIONS, re-INVITE; the echo extension `999`; a `BRIDGE` route through `FakeRoomBridge`
(jitter buffer → room, room → RTP); malformed messages answered `400` with the listener still
alive; `stop()` sends BYE; the health endpoint. Ephemeral loopback ports only.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import struct
from collections.abc import Callable
from typing import Any

import pytest
from sip_testkit import TEST_REALM, FakeClock, RawUdp
from voice_agent.tools.softphone import continuity
from voice_agent.transport.sip.bridge import FakeRoomBridge
from voice_agent.transport.sip.gateway import Route, RouteKind, SipGateway, default_router
from voice_agent.transport.sip.message import PT_PCMA, PT_PCMU, parse_sdp
from voice_agent.transport.sip.rtp import FRAME_BYTES, seq_diff
from voice_agent.transport.sip.softphone import CallFailed, SoftCall, SoftPhone, ToneBurstProbe

MakeGateway = Callable[..., Any]
MakePhone = Callable[..., Any]

TONE = struct.pack(
    "<160h", *[int(8000 * math.sin(2 * math.pi * 1000 * n / 8000)) for n in range(160)]
)


async def _registered(make_phone: MakePhone, gateway: SipGateway, **kwargs: Any) -> SoftPhone:
    phone: SoftPhone = await make_phone(gateway, **kwargs)
    response = await phone.register()
    assert response.status == 200, response.summary()
    return phone


async def _send_frames(call: SoftCall, frames: int, pcm: bytes = TONE) -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()
    for index in range(frames):
        call.send_pcm(pcm)
        await asyncio.sleep(max(0.0, started + (index + 1) * 0.02 - loop.time()))


async def _eventually(predicate: Callable[[], bool], timeout_s: float = 2.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


# -- REGISTER ------------------------------------------------------------------------------------


@pytest.mark.parametrize("transport", ["udp", "tcp"])
async def test_register_is_challenged_then_accepted(
    gateway: SipGateway, make_phone: MakePhone, transport: str
) -> None:
    phone: SoftPhone = await make_phone(gateway, transport=transport)
    first = await phone._register_once(300, challenge=None)
    assert first.status == 401
    assert (first.get("WWW-Authenticate") or "").startswith("Digest ")
    final = await phone.register()
    assert final.status == 200
    binding = gateway.registrar.lookup("trainee")
    assert binding is not None and binding.transport == transport.upper()


async def test_a_wrong_password_is_403(gateway: SipGateway, make_phone: MakePhone) -> None:
    phone: SoftPhone = await make_phone(gateway, password="wrong-test-password")
    assert (await phone.register()).status == 403
    assert gateway.registrar.lookup("trainee") is None


async def test_an_expired_registration_can_no_longer_call(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    clock = FakeClock()
    gateway: SipGateway = await make_gateway(clock=clock)
    phone: SoftPhone = await make_phone(gateway)
    assert (await phone.register(expires=60)).status == 200
    clock.advance(61)
    assert gateway.registrar.lookup("trainee") is None
    with pytest.raises(CallFailed) as excinfo:
        await phone.call("999")
    assert excinfo.value.status == 403


async def test_unregister_removes_the_binding(gateway: SipGateway, make_phone: MakePhone) -> None:
    phone = await _registered(make_phone, gateway)
    assert (await phone.unregister()).status == 200
    assert gateway.registrar.lookup("trainee") is None


# -- INVITE / echo / RTP -------------------------------------------------------------------------


async def test_echo_999_invite_100_180_200_ack_and_two_seconds_of_rtp_both_ways(
    gateway: SipGateway, make_phone: MakePhone
) -> None:
    phone = await _registered(make_phone, gateway)
    call = await phone.call("999")
    assert call.provisional == [100, 180]
    assert call.final_status == 200
    assert call.codec == PT_PCMA
    assert call.is_up
    assert await _eventually(lambda: gateway.live_calls == 1)

    await _send_frames(call, 100)  # 2 s at 20 ms
    assert await _eventually(lambda: len(call.received) >= 100)
    rtp = call.rtp
    assert rtp is not None
    assert rtp.sent == 100
    assert rtp.stats.received == 100 and rtp.stats.lost == 0
    report = continuity(call)
    assert report == {"seq_breaks": 0, "ts_breaks": 0, "ssrc_count": 1}
    # The echo re-stamps with its own SSRC (continuity is the gateway's, not a reflection).
    assert call.received[0][1].ssrc != rtp.ssrc
    # The audio itself came back: the same PCMA payload bytes we sent.
    assert call.received[10][1].payload == call.received[50][1].payload
    assert (await call.hangup()) == 200
    assert await _eventually(lambda: gateway.live_calls == 0)


async def test_a_pcmu_only_offer_is_answered_with_pcmu(
    gateway: SipGateway, make_phone: MakePhone
) -> None:
    phone = await _registered(make_phone, gateway, codecs=(PT_PCMU,))
    call = await phone.call("999")
    assert call.codec == PT_PCMU
    await _send_frames(call, 10)
    assert await _eventually(lambda: len(call.received) == 10)
    assert {packet.payload_type for _, packet in call.received} == {PT_PCMU}
    await call.hangup()


async def test_the_echo_round_trip_on_loopback_is_small(
    gateway: SipGateway, make_phone: MakePhone
) -> None:
    phone = await _registered(make_phone, gateway)
    call = await phone.call("999")
    probe = ToneBurstProbe(interval_ms=200, burst_ms=60)
    call.on_audio = probe.observe
    loop = asyncio.get_running_loop()
    started = loop.time()
    for index in range(50):
        call.send_pcm(probe.frame(index))
        probe.mark_sent(index, loop.time())
        await asyncio.sleep(max(0.0, started + (index + 1) * 0.02 - loop.time()))
    await asyncio.sleep(0.1)
    delays = probe.delays_ms()
    assert len(delays) == 5
    assert all(0 <= delay < 60 for delay in delays), delays
    await call.hangup()


async def test_an_unknown_number_is_404_and_an_unregistered_caller_403(
    gateway: SipGateway, make_phone: MakePhone
) -> None:
    phone = await _registered(make_phone, gateway)
    with pytest.raises(CallFailed) as excinfo:
        await phone.call("101")
    assert excinfo.value.status == 404
    stranger: SoftPhone = await make_phone(gateway, username="stranger")
    with pytest.raises(CallFailed) as excinfo:
        await stranger.call("999")
    assert excinfo.value.status == 403
    assert gateway.live_calls == 0


async def test_an_offer_without_g711_is_488(
    make_gateway: MakeGateway, make_phone: MakePhone, raw_udp: RawUdp
) -> None:
    # A hand-built INVITE carries no `Proxy-Authorization`: E6a's `registered_only` mode.
    gateway = await make_gateway(invite_auth="registered_only")
    await _registered(make_phone, gateway)
    sdp = b"v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio 4000 RTP/AVP 9\r\na=rtpmap:9 G722/8000\r\n"
    raw_udp.send(_invite(raw_udp.port, sdp), gateway.udp_port or 0)
    final = await raw_udp.recv_final()
    assert final is not None and final.status == 488


def _invite(port: int, sdp: bytes, *, call_id: str = "raw-1") -> bytes:
    head = (
        f"INVITE sip:999@{TEST_REALM} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP 127.0.0.1:{port};branch=z9hG4bK{call_id};rport\r\n"
        "Max-Forwards: 70\r\n"
        f"From: <sip:trainee@{TEST_REALM}>;tag=raw\r\n"
        f"To: <sip:999@{TEST_REALM}>\r\n"
        f"Call-ID: {call_id}\r\n"
        "CSeq: 1 INVITE\r\n"
        f"Contact: <sip:trainee@127.0.0.1:{port}>\r\n"
        "Content-Type: application/sdp\r\n"
        f"Content-Length: {len(sdp)}\r\n\r\n"
    )
    return head.encode() + sdp


async def test_a_reinvite_is_answered_with_the_same_sdp(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    # A hand-built re-INVITE carries no `Proxy-Authorization`: E6a's `registered_only` mode (the
    # challenged re-INVITE is `test_sip_dds_calls.py`'s).
    gateway = await make_gateway(invite_auth="registered_only")
    phone = await _registered(make_phone, gateway)
    call = await phone.call("999")
    assert call.dialog is not None and call.rtp is not None
    reinvite = call.dialog.in_dialog_request(
        "INVITE", via_host="127.0.0.1", via_port=phone.local_port
    )
    reinvite.add("Contact", f"<sip:trainee@127.0.0.1:{phone.local_port}>")
    reinvite.add("Content-Type", "application/sdp")
    reinvite.body = call.invite.body
    response = await phone._transactions.request(reinvite, phone._channel_or_raise())
    assert response.status == 200
    first = parse_sdp(response.body)
    assert first.payload_types == (PT_PCMA,)
    await call.hangup()


# -- CANCEL / BYE / OPTIONS ----------------------------------------------------------------------


def _slow_echo(dialed: str, from_user: str | None) -> Route:
    if dialed == "555":
        return Route(RouteKind.ECHO, answer_after_ms=10_000)
    return default_router(dialed, from_user)


async def test_cancel_before_the_answer_gets_200_and_the_invite_487(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    gateway: SipGateway = await make_gateway(router=_slow_echo)
    phone = await _registered(make_phone, gateway)
    call = await phone.begin_call("555")
    assert await _eventually(lambda: 180 in call.provisional)
    assert await call.cancel() == 200
    assert await call.wait_final(5) == 487
    assert await _eventually(lambda: gateway.live_calls == 0)


async def test_a_bye_from_the_gateway_on_stop_ends_the_call(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    gateway: SipGateway = await make_gateway()
    phone = await _registered(make_phone, gateway)
    call = await phone.call("999")
    await gateway.stop()
    assert await call.wait_ended(3)
    assert call.ended_by_remote


async def test_a_bye_for_an_unknown_call_is_481_and_options_is_200(
    gateway: SipGateway, raw_udp: RawUdp
) -> None:
    port = gateway.udp_port or 0
    common = (
        f"Via: SIP/2.0/UDP 127.0.0.1:{raw_udp.port};branch=z9hG4bKopt1\r\n"
        f"From: <sip:x@{TEST_REALM}>;tag=a\r\nTo: <sip:y@{TEST_REALM}>\r\nCall-ID: opt-1\r\n"
    )
    raw_udp.send(
        f"OPTIONS sip:{TEST_REALM} SIP/2.0\r\n{common}CSeq: 1 OPTIONS\r\n\r\n".encode(), port
    )
    options = await raw_udp.recv()
    assert options is not None and options.status == 200
    assert "INVITE" in (options.get("Allow") or "")
    raw_udp.send(
        f"BYE sip:{TEST_REALM} SIP/2.0\r\n"
        f"{common.replace('opt1', 'bye1')}CSeq: 2 BYE\r\n\r\n".encode(),
        port,
    )
    bye = await raw_udp.recv()
    assert bye is not None and bye.status == 481


# -- malformed input -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        b"OPTIONS sip:x SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:{port};branch=z9hG4bKm1\r\n\r\n",
        b"OPTIONS sip:x SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:{port};branch=z9hG4bKm2\r\n"
        b"From: <sip:a@x>;tag=1\r\nTo: <sip:b@x>\r\nCall-ID: m\r\nCSeq: one OPTIONS\r\n\r\n",
        b"INVITE sip:999@x SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:{port};branch=z9hG4bKm3\r\n"
        b"From: <sip:a@x>;tag=1\r\nTo: <sip:b@x>\r\nCall-ID: m3\r\nCSeq: 1 INVITE\r\n"
        b"Content-Length: 900\r\n\r\nv=0",
        b"REGISTER sip:x SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:{port};branch=z9hG4bKm4\r\n"
        b"From: <sip:a@x>;tag=1\r\nTo: not a uri\r\nCall-ID: m4\r\nCSeq: 1 REGISTER\r\n\r\n",
    ],
)
async def test_malformed_requests_get_400_and_the_listener_survives(
    gateway: SipGateway, raw_udp: RawUdp, payload: bytes
) -> None:
    port = gateway.udp_port or 0
    raw_udp.send(payload.replace(b"{port}", str(raw_udp.port).encode()), port)
    answer = await raw_udp.recv()
    assert answer is not None and answer.status == 400
    raw_udp.send(b"\x00\x01garbage that is not SIP at all\xff", port)
    raw_udp.send(b"", port)
    assert await raw_udp.recv(0.3) is None  # nothing addressable: dropped, no answer
    raw_udp.send(
        (
            f"OPTIONS sip:{TEST_REALM} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{raw_udp.port};branch=z9hG4bKalive\r\n"
            f"From: <sip:x@{TEST_REALM}>;tag=a\r\nTo: <sip:y@{TEST_REALM}>\r\n"
            "Call-ID: alive\r\nCSeq: 1 OPTIONS\r\n\r\n"
        ).encode(),
        port,
    )
    alive = await raw_udp.recv()
    assert alive is not None and alive.status == 200


async def test_malformed_tcp_input_drops_that_connection_only(
    gateway: SipGateway, make_phone: MakePhone
) -> None:
    reader, writer = await asyncio.open_connection("127.0.0.1", gateway.tcp_port)
    writer.write(b"OPTIONS sip:x SIP/2.0\r\nContent-Length: nope\r\n\r\n")
    await writer.drain()
    assert await asyncio.wait_for(reader.read(), 2) == b""  # closed by the gateway
    writer.close()
    phone = await _registered(make_phone, gateway, transport="tcp")
    assert phone is not None


async def test_an_unsupported_method_is_501(gateway: SipGateway, raw_udp: RawUdp) -> None:
    raw_udp.send(
        (
            f"MESSAGE sip:{TEST_REALM} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{raw_udp.port};branch=z9hG4bKmsg\r\n"
            f"From: <sip:x@{TEST_REALM}>;tag=a\r\nTo: <sip:y@{TEST_REALM}>\r\n"
            "Call-ID: msg\r\nCSeq: 1 MESSAGE\r\n\r\n"
        ).encode(),
        gateway.udp_port or 0,
    )
    answer = await raw_udp.recv()
    assert answer is not None and answer.status == 501


async def test_a_retransmitted_request_gets_the_cached_answer_not_a_second_execution(
    gateway: SipGateway, raw_udp: RawUdp
) -> None:
    request = (
        f"REGISTER sip:{TEST_REALM} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP 127.0.0.1:{raw_udp.port};branch=z9hG4bKretx\r\n"
        f"From: <sip:trainee@{TEST_REALM}>;tag=a\r\nTo: <sip:trainee@{TEST_REALM}>\r\n"
        f"Call-ID: retx\r\nCSeq: 1 REGISTER\r\nContact: <sip:trainee@127.0.0.1:{raw_udp.port}>\r\n"
        "\r\n"
    ).encode()
    raw_udp.send(request, gateway.udp_port or 0)
    first = await raw_udp.recv()
    raw_udp.send(request, gateway.udp_port or 0)
    second = await raw_udp.recv()
    assert first is not None and second is not None and first.status == 401
    assert first.get("WWW-Authenticate") == second.get("WWW-Authenticate")  # same nonce


# -- the bridge route ----------------------------------------------------------------------------


async def test_a_bridge_route_carries_audio_through_the_jitter_buffer_into_the_room_and_back(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    bridges: list[FakeRoomBridge] = []

    def router(dialed: str, from_user: str | None) -> Route:
        def factory(call_id: str) -> FakeRoomBridge:
            bridge = FakeRoomBridge(mode="loopback")
            bridges.append(bridge)
            return bridge

        return Route(RouteKind.BRIDGE, bridge_factory=factory)

    gateway: SipGateway = await make_gateway(router=router)
    phone = await _registered(make_phone, gateway)
    call = await phone.call("7001")
    assert len(bridges) == 1 and bridges[0].opened
    await _send_frames(call, 50)
    assert await _eventually(lambda: len(call.received) >= 45)
    bridge = bridges[0]
    # Into the room: decoded 8 kHz PCM frames, in order, what we sent (G.711 round trip).
    voiced = [frame for frame in bridge.frames if frame != b"\x00" * FRAME_BYTES]
    assert len(voiced) >= 45 and all(len(frame) == FRAME_BYTES for frame in voiced)
    sent = struct.unpack("<160h", TONE)
    got = struct.unpack("<160h", voiced[10])
    assert max(abs(a - b) for a, b in zip(sent, got, strict=True)) < 300
    # Back out of the room as RTP with the gateway's own continuous numbering.
    packets = [packet for _, packet in call.received]
    assert all(seq_diff(b.sequence, a.sequence) == 1 for a, b in itertools.pairwise(packets))
    assert await call.hangup() == 200
    assert await _eventually(lambda: bridge.closed)


# -- health --------------------------------------------------------------------------------------


async def test_health_answers_on_loopback(gateway: SipGateway, make_phone: MakePhone) -> None:
    await _registered(make_phone, gateway)
    reader, writer = await asyncio.open_connection("127.0.0.1", gateway.http_port)
    writer.write(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(), 2)
    writer.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200")
    payload = json.loads(body)
    assert payload["status"] == "ok" and payload["registrations"] == 1
    assert payload["sip_udp_port"] == gateway.udp_port

"""SIP over TLS + SRTP against the in-process gateway (I7 E44; Q-E15-2, ТЗ ¶293).

The certificate is the real one: `infra/scripts/make-certs.sh` (what `make certs` runs) issues a
local CA and a server certificate for `127.0.0.1` into a temporary directory. The client is the
headless softphone over a verified TLS socket, keyed with SDES; the media on the wire is checked
with an independent `pylibsrtp` session (bytes differ from the plaintext RTP, decrypt back to it).
Everything is on ephemeral loopback ports; no GPU, no network.
"""

from __future__ import annotations

import asyncio
import math
import shutil
import ssl
import struct
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pylibsrtp
import pytest
from sip_testkit import TEST_REALM, TEST_SIP_PASSWORD, FakeTelephonyBackend, gateway_config
from voice_agent import sip_gateway
from voice_agent.transport.sip.bridge import FakeRoomBridge
from voice_agent.transport.sip.gateway import SipGateway, SipGatewayConfig, parse_transports
from voice_agent.transport.sip.message import PT_PCMA, parse_sdp
from voice_agent.transport.sip.rtp import RtpPacket, encode
from voice_agent.transport.sip.softphone import CallFailed, SoftCall, SoftPhone
from voice_agent.transport.sip.srtp import PROTO_AVP, PROTO_SAVP
from voice_agent.transport.sip.telephony import DialedCall, RedisTelephonySignals

MakeGateway = Callable[..., Any]
MakePhone = Callable[..., Any]

REPO_ROOT = Path(__file__).resolve().parents[4]
MAKE_CERTS = REPO_ROOT / "infra" / "scripts" / "make-certs.sh"
TONE = struct.pack(
    "<160h", *[int(8000 * math.sin(2 * math.pi * 1000 * n / 8000)) for n in range(160)]
)


@pytest.fixture(scope="module")
def certs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`make certs` output for 127.0.0.1 in a temporary directory (never `infra/certs/`)."""
    if shutil.which("openssl") is None:
        pytest.skip("openssl is not on PATH (make-certs.sh needs it)")
    out = tmp_path_factory.mktemp("sip-certs")
    subprocess.run(
        ["bash", str(MAKE_CERTS), "--out", str(out), "--ip", "127.0.0.1", "--host", "localhost"],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return out


async def _tls_gateway(make_gateway: MakeGateway, certs: Path, **config: Any) -> SipGateway:
    gateway: SipGateway = await make_gateway(
        tls=True,
        tls_port=0,
        tls_cert=str(certs / "server.crt"),
        tls_key=str(certs / "server.key"),
        **config,
    )
    assert gateway.tls_port
    return gateway


async def _tls_phone(
    make_phone: MakePhone, gateway: SipGateway, certs: Path, **kwargs: Any
) -> SoftPhone:
    phone: SoftPhone = await make_phone(
        gateway, transport="tls", tls_ca=str(certs / "ca.crt"), **kwargs
    )
    response = await phone.register()
    assert response.status == 200, response.summary()
    return phone


async def _eventually(predicate: Callable[[], bool], timeout_s: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


def _tap(call: SoftCall) -> tuple[list[bytes], list[bytes]]:
    """Record the call's RTP datagrams exactly as they cross the wire, both directions."""
    rtp = call.rtp
    assert rtp is not None and rtp._transport is not None
    sent: list[bytes] = []
    received: list[bytes] = []
    transport = rtp._transport
    original_sendto = transport.sendto
    original_receive = rtp._on_datagram

    def sendto(data: bytes, addr: Any = None) -> None:
        sent.append(bytes(data))
        original_sendto(data, addr)

    def on_datagram(data: bytes, addr: tuple[str, int]) -> None:
        received.append(bytes(data))
        original_receive(data, addr)

    transport.sendto = sendto  # type: ignore[method-assign]
    rtp._on_datagram = on_datagram  # type: ignore[method-assign]
    return sent, received


def _inbound(key: bytes) -> pylibsrtp.Session:
    """An independent libsrtp receiver keyed from an SDES line (not the gateway's wrapper)."""
    return pylibsrtp.Session(pylibsrtp.Policy(key=key, ssrc_type=pylibsrtp.Policy.SSRC_ANY_INBOUND))


# -- the TLS listener -----------------------------------------------------------------------------


async def test_a_tls_register_and_an_sdes_invite_complete_and_the_media_is_encrypted(
    make_gateway: MakeGateway, make_phone: MakePhone, certs: Path
) -> None:
    gateway = await _tls_gateway(make_gateway, certs)
    health = gateway.health()
    assert health["sip_tls_port"] == gateway.tls_port
    assert health["transports"] == ["tls", "udp", "tcp"]
    assert health["srtp"] == "required over TLS"
    phone = await _tls_phone(make_phone, gateway, certs)
    binding = gateway.registrar.lookup("trainee")
    assert binding is not None and binding.transport == "TLS"

    call = await phone.call("999")  # the echo; the INVITE is 407-challenged and retried
    assert call.final_status == 200 and call.challenged
    offer = parse_sdp(call.invite.body)
    assert offer.protocol == PROTO_SAVP and len(offer.crypto) == 1
    assert call.srtp and call.local_crypto is not None and call.remote_crypto is not None
    assert call.remote_crypto.key != call.local_crypto.key

    sent_wire, received_wire = _tap(call)
    plain_sent: list[bytes] = []
    for _ in range(10):
        packet = call.send_pcm(TONE)
        assert packet is not None
        plain_sent.append(packet.to_bytes())
        await asyncio.sleep(0.02)
    assert await _eventually(lambda: len(call.received) >= 10)

    # Our side of the wire: every datagram is SRTP, not the RTP it carries.
    assert len(sent_wire) == 10
    payload = encode(TONE, PT_PCMA)
    ours = _inbound(call.local_crypto.key)
    for wire, plain in zip(sent_wire, plain_sent, strict=True):
        assert wire != plain and len(wire) == len(plain) + 10
        assert payload not in wire
        assert ours.unprotect(wire) == plain
    # The gateway's side: its echo is SRTP under ITS key, and decrypts back to our payload.
    theirs = _inbound(call.remote_crypto.key)
    assert len(received_wire) >= 10
    for wire in received_wire[:10]:
        assert payload not in wire
        echoed = RtpPacket.parse(theirs.unprotect(wire))
        assert echoed.payload == payload
    assert all(packet.payload == payload for _, packet in call.received[:10])
    assert call.rtp is not None and call.rtp.srtp_dropped == 0
    # A re-INVITE (session refresh) with the same keys is challenged, then answered 200; the
    # SRTP media keeps flowing on the same keys.
    assert await call.reinvite() == 200
    call.send_pcm(TONE)
    assert await _eventually(lambda: len(call.received) >= 11)
    assert call.rtp.srtp_dropped == 0
    assert await call.hangup() == 200
    assert await _eventually(lambda: gateway.live_calls == 0)


async def test_an_rtp_avp_offer_over_tls_is_refused_488(
    make_gateway: MakeGateway, make_phone: MakePhone, certs: Path
) -> None:
    gateway = await _tls_gateway(make_gateway, certs)
    phone = await _tls_phone(make_phone, gateway, certs, srtp=False)
    with pytest.raises(CallFailed) as refused:
        await phone.call("999")
    assert refused.value.status == 488
    assert gateway.live_calls == 0


async def test_plain_udp_beside_tls_keeps_plain_rtp_and_refuses_an_savp_offer(
    make_gateway: MakeGateway, make_phone: MakePhone, certs: Path
) -> None:
    gateway = await _tls_gateway(make_gateway, certs)
    phone: SoftPhone = await make_phone(gateway, transport="udp")
    assert (await phone.register()).status == 200
    call = await phone.call("999")
    assert parse_sdp(call.invite.body).protocol == PROTO_AVP and not call.srtp
    sent_wire, _ = _tap(call)
    packet = call.send_pcm(TONE)
    assert packet is not None and sent_wire == [packet.to_bytes()]  # plaintext RTP
    assert await _eventually(lambda: len(call.received) >= 1)
    assert await call.hangup() == 200
    # SRTP keys offered in clear SIP: refused, the phone is told to use TLS.
    keyed: SoftPhone = await make_phone(gateway, transport="udp", srtp=True)
    assert (await keyed.register()).status == 200
    with pytest.raises(CallFailed) as refused:
        await keyed.call("999")
    assert refused.value.status == 488


async def test_a_client_that_does_not_trust_the_local_ca_cannot_connect(
    make_gateway: MakeGateway, certs: Path
) -> None:
    gateway = await _tls_gateway(make_gateway, certs)
    assert gateway.tls_port is not None
    stranger = SoftPhone(
        server=("127.0.0.1", gateway.tls_port),
        username="trainee",
        password=TEST_SIP_PASSWORD,
        transport="tls",
        domain=TEST_REALM,
        tls_context=ssl.create_default_context(),  # the system store: no sim112 CA
    )
    with pytest.raises(ssl.SSLCertVerificationError):
        await stranger.start()
    await stranger.close()


async def test_the_gateway_rings_a_tls_registered_softphone_with_srtp(
    make_gateway: MakeGateway, make_phone: MakePhone, certs: Path
) -> None:
    """UAC (click-to-call / `CALL_IN`): the INVITE goes down the TLS connection and offers SRTP;
    the softphone answers SRTP and the room hears it."""
    backend = FakeTelephonyBackend()
    rooms: dict[str, FakeRoomBridge] = {}

    def room_factory(dialed: DialedCall) -> FakeRoomBridge:
        rooms[dialed.call_id] = FakeRoomBridge(mode="record")
        return rooms[dialed.call_id]

    gateway = await _tls_gateway(
        make_gateway, certs, backend=backend, room_factory=room_factory, answer_poll_s=5.0
    )
    phone = await _tls_phone(make_phone, gateway, certs, answer_mode="auto")
    call_id = backend.add_call()
    RedisTelephonySignals(redis=None, listener=gateway).dispatch(
        "voice:join",
        (
            '{"session_id": "00000000-0000-4000-8000-00000000aaaa", "room": "dds-test", '
            f'"call_id": "{call_id}", "call_kind": "SERVICE_HEAD", "endpoint": "SIP", '
            '"sip_user": "trainee", "direction": "OUTBOUND"}'
        ),
    )
    incoming: SoftCall = await asyncio.wait_for(phone.incoming.get(), 3.0)
    assert await incoming.wait_confirmed(3.0)
    offer = parse_sdp(incoming.invite.body)
    assert offer.protocol == PROTO_SAVP and incoming.srtp
    assert await _eventually(lambda: (call_id, "UP", None) in backend.legs)
    for _ in range(10):
        incoming.send_pcm(TONE)
        await asyncio.sleep(0.02)
    assert await _eventually(lambda: len(rooms[call_id].frames) >= 5)
    assert await incoming.hangup() == 200


# -- configuration and the entry point ------------------------------------------------------------


def test_sim_sip_transports_defaults_to_tls_beside_plain_and_refuses_unknown_names() -> None:
    assert parse_transports(None) == {"tls", "udp", "tcp"}
    assert parse_transports(" UDP , tcp ") == {"udp", "tcp"}
    with pytest.raises(ValueError, match="unknown"):
        parse_transports("tls,sctp")
    env = {"SIM_SIP_PASSWORD": TEST_SIP_PASSWORD, "SIM_SIP_TLS_CERT": "/certs/server.crt"}
    config = SipGatewayConfig.from_env(env.get)
    assert (config.tls, config.udp, config.tcp, config.tls_port) == (True, True, True, 5061)
    assert config.tls_cert == "/certs/server.crt" and config.tls_key is None
    env["SIM_SIP_TRANSPORTS"] = "tls"
    assert SipGatewayConfig.from_env(env.get).transports == ("tls",)


def test_tls_without_a_certificate_is_switched_off_or_refused(tmp_path: Path) -> None:
    config = gateway_config(tls=True, tls_cert=str(tmp_path / "missing.crt"), tls_key=None)
    resolved, note = sip_gateway.resolve_tls(config)
    assert resolved is not None and not resolved.tls and resolved.udp
    assert note is not None and "TLS is OFF" in note and "SIM_SIP_TLS_KEY=(unset)" in note
    tls_only = gateway_config(tls=True, udp=False, tcp=False)
    resolved, note = sip_gateway.resolve_tls(tls_only)
    assert resolved is None and note is not None and "no other transport" in note


def test_the_entry_point_refuses_tls_only_without_a_certificate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SIM_ENV_FILE", "")
    monkeypatch.setenv("SIM_SIP_PASSWORD", TEST_SIP_PASSWORD)
    monkeypatch.setenv("SIM_SIP_TRANSPORTS", "tls")
    monkeypatch.delenv("SIM_SIP_TLS_CERT", raising=False)
    monkeypatch.delenv("SIM_SIP_TLS_KEY", raising=False)
    assert sip_gateway.main([]) == 2
    assert "no other transport" in capsys.readouterr().err
    monkeypatch.setenv("SIM_SIP_TRANSPORTS", "tls,quic")
    assert sip_gateway.main([]) == 2
    assert "unknown transport" in capsys.readouterr().err

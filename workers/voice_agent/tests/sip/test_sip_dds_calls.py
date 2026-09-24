"""The SIP endpoint wired to the domain — the gateway half (I3 E6e, HLD 80 §80.2.3, D27).

The headless UA against the in-process gateway and a fake backend dial endpoint
(`FakeTelephonyBackend`, the backend's refusal → SIP mapping included), on ephemeral loopback
ports; the room is a `FakeRoomBridge`. The backend half — the real use cases on fake transport — is
`backend/tests/api/dds/test_sip_telephony.py`.

* the softphone dials `101` / `7xxx` / `112` / the claimant's digits: `100/180`, `leg UP`, the
  `200 OK` on `DDS_CALL_ANSWERED` (a Redis event, or the periodic re-read), RTP both ways through
  the room, `BYE` ⇒ `leg DOWN`, `CANCEL` ⇒ `leg DOWN`;
* the backend's refusals: `404 DIAL_NUMBER_UNKNOWN` ⇒ SIP `404`, `409 NO_ACTIVE_DDS_SESSION` ⇒
  `480`, `409 DDS_LINE_BUSY` ⇒ `486`, `403` ⇒ `403`, the backend down ⇒ `503`;
* a call ended by the backend: before the answer ⇒ the final response, after it ⇒ `BYE`;
* click-to-call / `CALL_IN` (UAC): `voice:join {endpoint: SIP, sip_user}` rings the registered
  softphone; its `200` ⇒ `leg UP`; `486` / no answer in the ring timeout ⇒ `leg FAILED {status}`;
  no registration ⇒ `leg FAILED 480`;
* INVITE authentication: `challenge` answers `407`, a valid `Proxy-Authorization` for the From user
  passes, a wrong password or another user's Digest is `403`, a re-INVITE is challenged too;
  `registered_only` accepts a registered user's INVITE with no challenge;
* REGISTER: an unknown username is `403` (E6e decision 3); a per-user HA1 replaces the deployment
  password; every binding is mirrored to `sip:binding:{username}`.
"""

from __future__ import annotations

import asyncio
import json
import math
import struct
from collections.abc import Callable
from typing import Any

import pytest
from app.application.testing.fakes import InMemorySipBindings
from sip_testkit import (
    TEST_REALM,
    TEST_SIP_PASSWORD,
    FakeTelephonyBackend,
    RawUdp,
)
from voice_agent.transport.sip.bridge import FakeRoomBridge
from voice_agent.transport.sip.gateway import SipGateway
from voice_agent.transport.sip.message import (
    SipMessage,
    build_authorization,
    digest_ha1,
    parse_auth_header,
)
from voice_agent.transport.sip.registrar import Credential
from voice_agent.transport.sip.softphone import CallFailed, SoftCall, SoftPhone
from voice_agent.transport.sip.telephony import (
    DialedCall,
    RedisBindingMirror,
    RedisTelephonySignals,
    sip_status_for_problem,
)

MakeGateway = Callable[..., Any]
MakePhone = Callable[..., Any]

TONE = struct.pack(
    "<160h", *[int(8000 * math.sin(2 * math.pi * 1000 * n / 8000)) for n in range(160)]
)


class Rooms:
    """The rooms the gateway joined, by ДДС call id (a recording `FakeRoomBridge` each)."""

    def __init__(self) -> None:
        self.by_call: dict[str, FakeRoomBridge] = {}
        self.joined: list[DialedCall] = []

    def __call__(self, dialed: DialedCall) -> FakeRoomBridge:
        room = FakeRoomBridge(mode="record")
        self.by_call[dialed.call_id] = room
        self.joined.append(dialed)
        return room


async def _eventually(predicate: Callable[[], bool], timeout_s: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


async def _dds_gateway(
    make_gateway: MakeGateway, backend: FakeTelephonyBackend, rooms: Rooms, **config: Any
) -> SipGateway:
    config.setdefault("answer_poll_s", 5.0)  # the Redis event path, unless a test says otherwise
    config.setdefault("leg_retry_s", 0.05)
    gateway: SipGateway = await make_gateway(backend=backend, room_factory=rooms, **config)
    return gateway


async def _registered(make_phone: MakePhone, gateway: SipGateway, **kwargs: Any) -> SoftPhone:
    phone: SoftPhone = await make_phone(gateway, **kwargs)
    response = await phone.register()
    assert response.status == 200, response.summary()
    return phone


def _signals(gateway: SipGateway) -> RedisTelephonySignals:
    """The Redis dispatcher, driven without Redis (`dispatch` is what `listen()` feeds)."""
    return RedisTelephonySignals(redis=None, listener=gateway)


def _event(event_type: str, call_id: str, **payload: Any) -> str:
    return json.dumps({"event_type": event_type, "payload": {"call_id": call_id, **payload}})


def _last_call(backend: FakeTelephonyBackend) -> str:
    return list(backend.calls)[-1]


async def _ringing_dds_call(
    phone: SoftPhone, backend: FakeTelephonyBackend, number: str
) -> tuple[SoftCall, str]:
    call = await phone.begin_call(number)
    assert await _eventually(lambda: bool(backend.calls) and bool(backend.legs))
    call_id = _last_call(backend)
    assert await _eventually(lambda: backend.calls[call_id]["state"] == "RINGING")
    return call, call_id


# ---------------------------------------------------------------------------------------------
# The softphone dials: 101 / 7xxx / 112 / the claimant's digits
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("number", ["101", "7003", "112", "79161234567"])
async def test_the_softphone_dials_a_dds_number_and_is_answered_on_dds_call_answered(
    make_gateway: MakeGateway, make_phone: MakePhone, number: str
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    gateway = await _dds_gateway(make_gateway, backend, rooms)
    phone = await _registered(make_phone, gateway)
    call, call_id = await _ringing_dds_call(phone, backend, number)
    assert backend.dials == [("trainee", number)]
    assert backend.legs[0] == (call_id, "UP", None)
    assert rooms.joined[0].call_id == call_id and gateway.bridges(call_id)
    assert call.challenged  # `SIM_SIP_INVITE_AUTH=challenge` is the default
    assert 180 in call.provisional and call.final_status is None

    backend.calls[call_id]["state"] = "CONNECTED"
    _signals(gateway).dispatch("session:x:events", _event("DDS_CALL_ANSWERED", call_id))
    assert await call.wait_final(3.0) == 200
    for _ in range(25):  # half a second of the trainee's voice into the room
        call.send_pcm(TONE)
        await asyncio.sleep(0.02)
    room = rooms.by_call[call_id]
    assert await _eventually(lambda: len(room.frames) >= 10)
    for _ in range(10):  # the AI party speaks back
        room.play(TONE)
    assert await _eventually(lambda: len(call.received) >= 10)

    assert await call.hangup() == 200
    assert await _eventually(lambda: (call_id, "DOWN", None) in backend.legs)
    assert await _eventually(lambda: not gateway.bridges(call_id))
    assert room.closed


async def test_the_answer_arrives_by_the_periodic_re_read_when_the_event_is_lost(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    gateway = await _dds_gateway(make_gateway, backend, rooms, answer_poll_s=0.1)
    phone = await _registered(make_phone, gateway)
    call, call_id = await _ringing_dds_call(phone, backend, "101")
    backend.calls[call_id]["state"] = "CONNECTED"  # no Redis event at all
    assert await call.wait_final(3.0) == 200


async def test_leg_up_is_repeated_until_the_transport_is_ready(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    backend.transport_ready = False
    gateway = await _dds_gateway(make_gateway, backend, rooms)
    phone = await _registered(make_phone, gateway)
    await phone.begin_call("112")
    assert await _eventually(lambda: len(backend.legs) >= 3)
    call_id = _last_call(backend)
    assert backend.calls[call_id]["state"] == "DIALING"
    backend.transport_ready = True
    assert await _eventually(lambda: backend.calls[call_id]["state"] == "RINGING")


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("unknown_number", 404),
        ("no_session", 480),
        ("line_busy", 486),
        ("backend_down", 503),
    ],
)
async def test_the_backend_s_refusals_map_to_sip_statuses(
    make_gateway: MakeGateway, make_phone: MakePhone, setup: str, expected: int
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    backend.has_session = setup != "no_session"
    backend.line_busy = setup == "line_busy"
    gateway = await _dds_gateway(make_gateway, backend, rooms)
    phone = await _registered(make_phone, gateway)
    backend.unavailable = setup == "backend_down"
    with pytest.raises(CallFailed) as refused:
        await phone.call("555" if setup == "unknown_number" else "101")
    assert refused.value.status == expected
    assert backend.legs == [] and rooms.joined == []


def test_the_problem_to_sip_mapping_is_the_hld_s() -> None:
    assert sip_status_for_problem(404, "DIAL_NUMBER_UNKNOWN") == 404
    assert sip_status_for_problem(409, "NO_ACTIVE_DDS_SESSION") == 480
    assert sip_status_for_problem(409, "DDS_LINE_BUSY") == 486
    assert sip_status_for_problem(409, "ACTION_NOT_AVAILABLE") == 480
    assert sip_status_for_problem(403, "FORBIDDEN_FOR_ROLE") == 403
    assert sip_status_for_problem(500, None) == 503


async def test_the_echo_never_reaches_the_backend(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    gateway = await _dds_gateway(make_gateway, backend, rooms)
    phone = await _registered(make_phone, gateway)
    call = await phone.call("999")
    assert call.final_status == 200 and backend.dials == []
    await call.hangup()


@pytest.mark.parametrize(("reason", "expected"), [("BUSY", 486), ("NO_ANSWER", 480)])
async def test_a_call_the_backend_ends_before_the_answer_is_the_final_response(
    make_gateway: MakeGateway, make_phone: MakePhone, reason: str, expected: int
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    gateway = await _dds_gateway(make_gateway, backend, rooms)
    phone = await _registered(make_phone, gateway)
    call, call_id = await _ringing_dds_call(phone, backend, "101")
    backend.end(call_id, reason)
    _signals(gateway).dispatch("session:x:events", _event("DDS_CALL_ENDED", call_id, reason=reason))
    assert await call.wait_final(3.0) == expected
    assert await _eventually(lambda: not gateway.bridges(call_id))
    assert all(state != "DOWN" for _, state, _ in backend.legs)


async def test_a_hang_up_from_the_browser_sends_the_softphone_a_bye(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    gateway = await _dds_gateway(make_gateway, backend, rooms)
    phone = await _registered(make_phone, gateway)
    call, call_id = await _ringing_dds_call(phone, backend, "112")
    gateway.on_call_answered(call_id)
    assert await call.wait_final(3.0) == 200
    backend.end(call_id, "HANGUP")
    _signals(gateway).dispatch(
        "voice:cancel:x", json.dumps({"call_id": call_id, "reason": "HANGUP"})
    )
    assert await call.wait_ended(3.0) and call.ended_by_remote
    assert all(state != "DOWN" for _, state, _ in backend.legs)


async def test_a_cancel_from_the_softphone_is_leg_down(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    gateway = await _dds_gateway(make_gateway, backend, rooms)
    phone = await _registered(make_phone, gateway)
    call, call_id = await _ringing_dds_call(phone, backend, "101")
    assert await call.cancel() == 200
    assert await call.wait_final(3.0) == 487
    assert await _eventually(lambda: (call_id, "DOWN", None) in backend.legs)
    assert backend.calls[call_id]["end_reason"] == "HANGUP"


# ---------------------------------------------------------------------------------------------
# The gateway rings the softphone (UAC): click-to-call and CALL_IN
# ---------------------------------------------------------------------------------------------


def _join(call_id: str, *, direction: str = "OUTBOUND", sip_user: str = "trainee") -> str:
    return json.dumps(
        {
            "session_id": "00000000-0000-4000-8000-00000000aaaa",
            "room": f"dds-test-{call_id}",
            "call_id": call_id,
            "call_kind": "SERVICE_HEAD",
            "endpoint": "SIP",
            "sip_user": sip_user,
            "direction": direction,
        }
    )


@pytest.mark.parametrize(("transport", "direction"), [("udp", "OUTBOUND"), ("tcp", "INBOUND")])
async def test_voice_join_rings_the_registered_softphone_and_its_answer_is_leg_up(
    make_gateway: MakeGateway, make_phone: MakePhone, transport: str, direction: str
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    gateway = await _dds_gateway(make_gateway, backend, rooms)
    phone = await _registered(make_phone, gateway, transport=transport, answer_mode="auto")
    call_id = backend.add_call(
        direction=direction, state="DIALING" if direction == "OUTBOUND" else "RINGING"
    )
    _signals(gateway).dispatch("voice:join", _join(call_id, direction=direction))
    incoming: SoftCall = await asyncio.wait_for(phone.incoming.get(), 3.0)
    assert await incoming.wait_confirmed(3.0)
    assert await _eventually(lambda: (call_id, "UP", None) in backend.legs)
    expected = "RINGING" if direction == "OUTBOUND" else "CONNECTED"
    assert backend.calls[call_id]["state"] == expected
    room = rooms.by_call[call_id]
    for _ in range(10):
        room.play(TONE)
    assert await _eventually(lambda: len(incoming.received) >= 10)
    for _ in range(20):
        incoming.send_pcm(TONE)
        await asyncio.sleep(0.02)
    assert await _eventually(lambda: len(room.frames) >= 5)
    # A repeated `voice:join` (the backend's retry) rings nothing new.
    _signals(gateway).dispatch("voice:join", _join(call_id, direction=direction))
    await asyncio.sleep(0.2)
    assert phone.incoming.empty()
    assert await incoming.hangup() == 200
    assert await _eventually(lambda: (call_id, "DOWN", None) in backend.legs)


@pytest.mark.parametrize(("mode", "status"), [("busy", 486), ("ring", 408)])
async def test_a_softphone_that_refuses_or_does_not_answer_is_leg_failed(
    make_gateway: MakeGateway, make_phone: MakePhone, mode: str, status: int
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    gateway = await _dds_gateway(make_gateway, backend, rooms, ring_timeout_s=0.5)
    phone = await _registered(make_phone, gateway, answer_mode=mode)
    call_id = backend.add_call()
    _signals(gateway).dispatch("voice:join", _join(call_id))
    assert await _eventually(lambda: (call_id, "FAILED", status) in backend.legs)
    assert backend.calls[call_id]["end_reason"] == "ABORT"
    if mode == "ring":
        rung: SoftCall = await asyncio.wait_for(phone.incoming.get(), 1.0)
        assert await rung.wait_ended(3.0)  # the gateway CANCELled the ringing INVITE
    assert rooms.joined == []


async def test_no_registration_is_leg_failed_480_and_a_browser_join_is_ignored(
    make_gateway: MakeGateway,
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    gateway = await _dds_gateway(make_gateway, backend, rooms)
    call_id = backend.add_call()
    browser = json.loads(_join(call_id))
    browser["endpoint"] = "BROWSER"
    _signals(gateway).dispatch("voice:join", json.dumps(browser))
    await asyncio.sleep(0.1)
    assert backend.legs == []
    _signals(gateway).dispatch("voice:join", _join(call_id, sip_user="nobody-registered"))
    assert await _eventually(lambda: (call_id, "FAILED", 480) in backend.legs)


async def test_a_call_ended_while_the_softphone_rings_is_cancelled(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    backend, rooms = FakeTelephonyBackend(), Rooms()
    gateway = await _dds_gateway(make_gateway, backend, rooms)
    phone = await _registered(make_phone, gateway, answer_mode="ring")
    call_id = backend.add_call()
    _signals(gateway).dispatch("voice:join", _join(call_id))
    rung: SoftCall = await asyncio.wait_for(phone.incoming.get(), 3.0)
    backend.end(call_id, "HANGUP")
    _signals(gateway).dispatch("voice:cancel:x", json.dumps({"call_id": call_id}))
    assert await rung.wait_ended(3.0) and rung.final_status == 487
    assert all(state != "FAILED" for _, state, _ in backend.legs)


# ---------------------------------------------------------------------------------------------
# INVITE authentication (E6e decision 1): challenge / registered_only
# ---------------------------------------------------------------------------------------------


def _raw_invite(port: int, *, call_id: str, cseq: int = 1, extra: str = "") -> bytes:
    sdp = b"v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio 4000 RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\n"
    head = (
        f"INVITE sip:999@{TEST_REALM} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP 127.0.0.1:{port};branch=z9hG4bK{call_id}{cseq};rport\r\n"
        f"Max-Forwards: 70\r\n"
        f"From: <sip:trainee@{TEST_REALM}>;tag=raw\r\n"
        f"To: <sip:999@{TEST_REALM}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: {cseq} INVITE\r\n"
        f"Contact: <sip:trainee@127.0.0.1:{port}>\r\n"
        f"{extra}"
        f"Content-Type: application/sdp\r\n"
        f"Content-Length: {len(sdp)}\r\n\r\n"
    )
    return head.encode() + sdp


def _proxy_authorization(challenge: SipMessage, *, username: str, password: str) -> str:
    _, params = parse_auth_header(challenge.get("Proxy-Authenticate") or "")
    value = build_authorization(
        username=username,
        password=password,
        method="INVITE",
        uri=f"sip:999@{TEST_REALM}",
        challenge=params,
    )
    return f"Proxy-Authorization: {value}\r\n"


async def test_challenge_answers_407_and_only_the_from_user_s_digest_passes(
    gateway: SipGateway, make_phone: MakePhone, raw_udp: RawUdp
) -> None:
    await _registered(make_phone, gateway)
    port = gateway.udp_port or 0
    raw_udp.send(_raw_invite(raw_udp.port, call_id="auth-1"), port)
    challenge = await raw_udp.recv_final()
    assert challenge is not None and challenge.status == 407
    assert (challenge.get("Proxy-Authenticate") or "").startswith("Digest ")
    for username, password, call_id in (
        ("trainee", "wrong-test-password", "auth-2"),
        ("mallory", TEST_SIP_PASSWORD, "auth-3"),
    ):
        raw_udp.send(_raw_invite(raw_udp.port, call_id=call_id), port)
        fresh = await raw_udp.recv_final()
        assert fresh is not None and fresh.status == 407
        header = _proxy_authorization(fresh, username=username, password=password)
        raw_udp.send(_raw_invite(raw_udp.port, call_id=call_id, cseq=2, extra=header), port)
        refused = await raw_udp.recv_final()
        assert refused is not None and refused.status == 403, (username, refused.summary())
    raw_udp.send(_raw_invite(raw_udp.port, call_id="auth-4"), port)
    fresh = await raw_udp.recv_final()
    assert fresh is not None
    header = _proxy_authorization(fresh, username="trainee", password=TEST_SIP_PASSWORD)
    raw_udp.send(_raw_invite(raw_udp.port, call_id="auth-4", cseq=2, extra=header), port)
    accepted = await raw_udp.recv_final()
    assert accepted is not None and accepted.status == 200


async def test_challenge_passes_the_softphone_and_challenges_its_re_invite(
    gateway: SipGateway, make_phone: MakePhone
) -> None:
    assert gateway.config.invite_auth == "challenge"
    phone = await _registered(make_phone, gateway)
    call = await phone.call("999")
    assert call.challenged and call.final_status == 200
    assert await call.reinvite() == 200  # 407 answered with Proxy-Authorization, then 200
    await call.hangup()


async def test_a_wrong_password_on_the_invite_is_403(
    gateway: SipGateway, make_phone: MakePhone
) -> None:
    phone = await _registered(make_phone, gateway)
    phone._password = "wrong-test-password"  # the registration stands; the INVITE's Digest fails
    with pytest.raises(CallFailed) as refused:
        await phone.call("999")
    assert refused.value.status == 403


async def test_registered_only_accepts_a_registered_user_without_a_challenge(
    make_gateway: MakeGateway, make_phone: MakePhone, raw_udp: RawUdp
) -> None:
    gateway = await make_gateway(invite_auth="registered_only")
    phone = await _registered(make_phone, gateway)
    call = await phone.call("999")
    assert not call.challenged and call.final_status == 200
    await call.hangup()
    raw_udp.send(_raw_invite(raw_udp.port, call_id="ro-1"), gateway.udp_port or 0)
    answered = await raw_udp.recv_final()
    assert answered is not None and answered.status == 200
    other = await make_phone(gateway, username="unregistered")
    with pytest.raises(CallFailed) as refused:
        await other.call("999")
    assert refused.value.status == 403


def test_an_unknown_invite_auth_mode_is_refused() -> None:
    from sip_testkit import gateway_config

    with pytest.raises(ValueError, match="SIM_SIP_INVITE_AUTH"):
        gateway_config(invite_auth="none")


# ---------------------------------------------------------------------------------------------
# REGISTER through the backend: unknown user 403, per-user HA1, the Redis mirror
# ---------------------------------------------------------------------------------------------


async def test_an_unknown_sip_username_cannot_register(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    backend = FakeTelephonyBackend(users={"trainee": None})
    gateway = await _dds_gateway(make_gateway, backend, Rooms())
    stranger: SoftPhone = await make_phone(gateway, username="stranger")
    assert (await stranger.register()).status == 403
    assert gateway.registrar.lookup("stranger") is None
    assert (await (await make_phone(gateway)).register()).status == 200


async def test_a_per_user_ha1_replaces_the_deployment_password(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    own = "test-fixture-own-sip-password"
    ha1 = digest_ha1("trainee", TEST_REALM, own)
    backend = FakeTelephonyBackend(users={"trainee": Credential(ha1=ha1)})
    gateway = await _dds_gateway(make_gateway, backend, Rooms())
    deployment: SoftPhone = await make_phone(gateway)
    assert (await deployment.register()).status == 403
    phone: SoftPhone = await make_phone(gateway, password=own)
    assert (await phone.register()).status == 200
    call = await phone.call("999")  # the INVITE's Proxy-Authorization is checked against it too
    assert call.challenged and call.final_status == 200
    await call.hangup()


async def test_every_binding_is_mirrored_to_the_sip_binding_key(
    make_gateway: MakeGateway, make_phone: MakePhone
) -> None:
    bindings = InMemorySipBindings()
    mirror = RedisBindingMirror(bindings)
    gateway = await make_gateway(on_bind=mirror.on_bind, on_unbind=mirror.on_unbind)
    phone = await _registered(make_phone, gateway)
    assert await _eventually(lambda: "trainee" in bindings.bound)
    assert (await phone.unregister()).status == 200
    assert await _eventually(lambda: "trainee" not in bindings.bound)


def test_the_process_refuses_a_backend_without_the_gateway_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from voice_agent import sip_gateway

    monkeypatch.setenv("SIM_ENV_FILE", "")
    monkeypatch.setenv("SIM_SIP_PASSWORD", TEST_SIP_PASSWORD)
    monkeypatch.setenv("SIM_SIP_BACKEND_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("SIM_SIP_GATEWAY_SECRET", raising=False)
    assert sip_gateway.main([]) == 2
    assert "SIM_SIP_GATEWAY_SECRET" in capsys.readouterr().err

"""Helpers for the SIP gate tests (imported by `conftest.py` and the test modules)."""

from __future__ import annotations

import asyncio
import socket

from voice_agent.transport.sip.gateway import SipGatewayConfig
from voice_agent.transport.sip.message import SipMessage, SipParseError, parse_message
from voice_agent.transport.sip.registrar import Credential
from voice_agent.transport.sip.telephony import (
    BackendUnavailableError,
    DialedCall,
    DialRefused,
    sip_status_for_problem,
)

#: TEST FIXTURE ONLY — a throwaway literal for the in-process gateway, never a real password.
TEST_SIP_PASSWORD = "test-fixture-sip-password-not-a-secret"
TEST_REALM = "sim112-test"


class FakeClock:
    """Monotonic seconds that a test advances by hand (expiry without sleeping)."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def gateway_config(**overrides: object) -> SipGatewayConfig:
    values: dict[str, object] = {
        "password": TEST_SIP_PASSWORD,
        "realm": TEST_REALM,
        "bind_host": "127.0.0.1",
        "sip_port": 0,
        "rtp_port_range": None,
        "http_port": 0,
        "media_ip": "127.0.0.1",
        "jitter_ms": 40,
    }
    values.update(overrides)
    return SipGatewayConfig(**values)  # type: ignore[arg-type]


class RawUdp:
    """A bare UDP socket for hand-built (and deliberately broken) messages."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)
        self.port = self.sock.getsockname()[1]

    def send(self, data: bytes, port: int) -> None:
        self.sock.sendto(data, ("127.0.0.1", port))

    async def recv(self, timeout_s: float = 2.0) -> SipMessage | None:
        loop = asyncio.get_running_loop()
        try:
            data = await asyncio.wait_for(loop.sock_recv(self.sock, 65536), timeout_s)
        except TimeoutError:
            return None
        try:
            return parse_message(data)
        except SipParseError as exc:  # a 400 may echo the broken header it complains about
            return exc.partial

    async def recv_final(self, timeout_s: float = 2.0) -> SipMessage | None:
        """Skip provisional responses; the first final one (or `None`)."""
        while True:
            message = await self.recv(timeout_s)
            if message is None or (message.status or 0) >= 200:
                return message

    def close(self) -> None:
        self.sock.close()


# -- I3 E6e: a fake backend dial endpoint ---------------------------------------------------------

#: The dial plan the fake backend answers (HLD 80 §80.3.5's rows, as the real one resolves them on
#: the example card): a catalog code, a `7xxx` extension, 112, the claimant's digits.
FAKE_DIAL_PLAN = {
    "101": "SERVICE_HEAD",
    "7003": "SERVICE_HEAD",
    "112": "OPERATOR_112",
    "79161234567": "CLAIMANT",
}


class FakeTelephonyBackend:
    """An in-process `TelephonyBackend`: the dial plan above and `reportSipLeg`'s state rules
    (DIALING --UP--> RINGING, INBOUND RINGING --UP--> CONNECTED, FAILED / DOWN ⇒ ENDED), with the
    backend's HTTP refusals turned into SIP statuses by the gateway's own mapping."""

    def __init__(self, users: dict[str, Credential | None] | None = None) -> None:
        #: `username → Credential`; a username absent here is unknown (`403`).
        self.users: dict[str, Credential] = {
            name: value if isinstance(value, Credential) else Credential()
            for name, value in (users or {"trainee": None}).items()
        }
        self.has_session = True
        self.line_busy = False
        self.transport_ready = True
        self.unavailable = False
        self.calls: dict[str, dict[str, object]] = {}
        self.dials: list[tuple[str, str]] = []
        self.legs: list[tuple[str, str, int | None]] = []
        self._next = 0

    def _new_id(self) -> str:
        self._next += 1
        return f"00000000-0000-4000-8000-{self._next:012d}"

    async def dial(self, sip_user: str, dialed: str, sip_call_id: str) -> DialedCall:
        if self.unavailable:
            raise BackendUnavailableError("backend down (test)")
        self.dials.append((sip_user, dialed))
        if sip_user not in self.users:
            raise DialRefused(sip_status_for_problem(403, "FORBIDDEN_FOR_ROLE"), "FORBIDDEN")
        if not self.has_session:
            code = "NO_ACTIVE_DDS_SESSION"
            raise DialRefused(sip_status_for_problem(409, code), code)
        kind = FAKE_DIAL_PLAN.get(dialed)
        if kind is None:
            code = "DIAL_NUMBER_UNKNOWN"
            raise DialRefused(sip_status_for_problem(404, code), code)
        if self.line_busy:
            raise DialRefused(sip_status_for_problem(409, "DDS_LINE_BUSY"), "DDS_LINE_BUSY")
        call_id = self._new_id()
        self.calls[call_id] = {"state": "DIALING", "direction": "OUTBOUND", "end_reason": None}
        return DialedCall(
            call_id=call_id,
            session_id="00000000-0000-4000-8000-00000000aaaa",
            room_name=f"dds-test-{call_id}",
            kind=kind,
        )

    def add_call(self, *, direction: str = "OUTBOUND", state: str = "DIALING") -> str:
        """A call the backend started itself (the browser button / a `CALL_IN`)."""
        call_id = self._new_id()
        self.calls[call_id] = {"state": state, "direction": direction, "end_reason": None}
        return call_id

    def end(self, call_id: str, reason: str) -> None:
        self.calls[call_id].update(state="ENDED", end_reason=reason)

    async def report_leg(self, call_id: str, state: str, sip_status: int | None = None) -> str:
        self.legs.append((call_id, state, sip_status))
        call = self.calls[call_id]
        if call["state"] == "ENDED":
            return "ENDED"
        if state == "UP":
            if call["state"] == "DIALING" and call["direction"] == "OUTBOUND":
                if self.transport_ready:
                    call["state"] = "RINGING"
            elif call["state"] == "RINGING" and call["direction"] == "INBOUND":
                call["state"] = "CONNECTED"
        elif state == "FAILED":
            call.update(state="ENDED", end_reason="ABORT")
        else:
            call.update(state="ENDED", end_reason="HANGUP")
        return str(call["state"])

    async def get_call(self, call_id: str) -> dict[str, object]:
        return dict(self.calls[call_id])

    async def credential(self, username: str) -> Credential | None:
        return self.users.get(username)

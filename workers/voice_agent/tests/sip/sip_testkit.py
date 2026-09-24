"""Helpers for the SIP gate tests (imported by `conftest.py` and the test modules)."""

from __future__ import annotations

import asyncio
import socket

from voice_agent.transport.sip.gateway import SipGatewayConfig
from voice_agent.transport.sip.message import SipMessage, SipParseError, parse_message

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

"""Shared fixtures for the SIP gateway gate tests (HLD 80 §80.8.1 row (1), I3 E6a).

Everything runs in-process on **ephemeral loopback ports** (never 5060, never an owner port):
the gateway binds `127.0.0.1:0` for SIP (udp+tcp), RTP and health; the headless UA binds
`127.0.0.1:0`. No GPU, no network, no LiveKit (D13).

`TEST_SIP_PASSWORD` is a throwaway test-fixture literal, not a credential of any deployment: the
real one is `SIM_SIP_PASSWORD` from the environment, never committed ([credential redacted]).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator

import pytest
from sip_testkit import TEST_REALM, TEST_SIP_PASSWORD, RawUdp, gateway_config
from voice_agent.transport.sip.gateway import Route, SipGateway, default_router
from voice_agent.transport.sip.softphone import SoftPhone


@pytest.fixture
async def make_gateway() -> AsyncIterator[Callable[..., object]]:
    """`await make_gateway(router=..., clock=..., **config)` — started, stopped at teardown."""
    started: list[SipGateway] = []

    async def _make(
        *,
        router: Callable[[str, str | None], Route] = default_router,
        clock: Callable[[], float] | None = None,
        **config: object,
    ) -> SipGateway:
        kwargs: dict[str, object] = {"router": router}
        if clock is not None:
            kwargs["clock"] = clock
        # I3 E6e: the gateway's collaborators (a fake backend, the room, the binding hooks).
        for name in ("backend", "room_factory", "credentials", "on_bind", "on_unbind"):
            if name in config:
                kwargs[name] = config.pop(name)
        gateway = SipGateway(gateway_config(**config), **kwargs)  # type: ignore[arg-type]
        await gateway.start()
        started.append(gateway)
        return gateway

    yield _make
    for gateway in started:
        await gateway.stop()


@pytest.fixture
async def gateway(make_gateway: Callable[..., object]) -> SipGateway:
    return await make_gateway()  # type: ignore[misc, no-any-return]


@pytest.fixture
async def make_phone() -> AsyncIterator[Callable[..., object]]:
    """`await make_phone(gateway, username=..., password=..., transport=...)` — started UA."""
    phones: list[SoftPhone] = []

    async def _make(
        gateway: SipGateway,
        *,
        username: str = "trainee",
        password: str = TEST_SIP_PASSWORD,
        transport: str = "udp",
        **kwargs: object,
    ) -> SoftPhone:
        # I7 E44: `transport="tls"` reaches the gateway's TLS listener (pass `tls_ca=`).
        port = {"tcp": gateway.tcp_port, "tls": gateway.tls_port}.get(transport, gateway.udp_port)
        assert port is not None
        phone = SoftPhone(
            server=("127.0.0.1", port),
            username=username,
            password=password,
            transport=transport,
            domain=TEST_REALM,
            **kwargs,  # type: ignore[arg-type]
        )
        await phone.start()
        phones.append(phone)
        return phone

    yield _make
    for phone in phones:
        await phone.close()


@pytest.fixture
def raw_udp() -> Iterator[RawUdp]:
    sock = RawUdp()
    yield sock
    sock.close()

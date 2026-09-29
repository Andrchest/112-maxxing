"""`python -m voice_agent.sip_gateway` — the SIP gateway process (HLD 80 §80.2.1, D22, D27).

Reads the `SIM_SIP_*` keys (`SipGatewayConfig.from_env`: process environment first, then the
`.env` file), binds SIP on `SIM_SIP_PORT` (udp+tcp, default 5060) and SIP over TLS on
`SIM_SIP_TLS_PORT` (default 5061; I7 E44 — `SIM_SIP_TRANSPORTS`, default `tls,udp,tcp`), RTP from
`SIM_SIP_RTP_PORT_RANGE` (default 20000-20199) and health on `127.0.0.1:SIM_SIP_GATEWAY_HTTP_PORT`
(default 8114), and serves until SIGTERM/SIGINT, when it sends a `BYE` to every live call.

**Wired to the domain (I3 E6e).** With `SIM_SIP_BACKEND_URL` set, every number but the echo `999`
goes to the backend (`/api/v1/telephony/*`, service credential `SIM_SIP_GATEWAY_SECRET`); a
REGISTER's username must be an active `users.username` (per-user HA1 when one is set); the gateway
subscribes to `voice:join` / `voice:cancel:*` / `session:*:events` on `SIM_REDIS_URL` and mirrors
each registration to `sip:binding:{username}`; a ДДС call's room is joined as `sip-{call_id}` with
a token minted locally from `SIM_LIVEKIT_URL` / `SIM_LIVEKIT_API_KEY` / `SIM_LIVEKIT_API_SECRET`
(no token travels over Redis, 80 §80.1). Without it the gateway is E6a's standalone echo server.

Refuses to start without `SIM_SIP_PASSWORD`, or with a backend URL but no
`SIM_SIP_GATEWAY_SECRET` — there is no default credential ([credential redacted] in every document;
SPEC §41). Never binds 8000/8001/8011/8012/5000 (owner ports). TLS without a readable
`SIM_SIP_TLS_CERT` / `SIM_SIP_TLS_KEY` (`make certs`) is switched off with a warning while a plain
transport is still configured, and refuses to start when TLS is the only one.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import os
import signal
import sys
from collections.abc import Sequence
from typing import Any

from app.config.settings import read_env_value
from app.infrastructure.logging import configure_logging

from voice_agent.transport.sip.bridge import room_factory_for
from voice_agent.transport.sip.gateway import RoomFactory, SipGateway, SipGatewayConfig
from voice_agent.transport.sip.telephony import (
    HttpTelephonyBackend,
    RedisBindingMirror,
    RedisTelephonySignals,
)

__all__ = ["main", "resolve_tls", "serve"]

logger = logging.getLogger("voice_agent.sip_gateway")

_OWNER_PORTS = {8000, 8001, 8011, 8012, 5000}
_MEDIA_KEYS = ("SIM_LIVEKIT_URL", "SIM_LIVEKIT_API_KEY", "SIM_LIVEKIT_API_SECRET")


async def serve(config: SipGatewayConfig) -> None:
    backend: HttpTelephonyBackend | None = None
    redis: Any = None
    mirror: RedisBindingMirror | None = None
    room_factory: RoomFactory | None = None
    if config.backend_url:
        from app.infrastructure.transport.redis_sip_bindings import RedisSipBindings
        from redis.asyncio import Redis

        backend = HttpTelephonyBackend(config.backend_url, config.gateway_secret)
        redis_url = read_env_value("SIM_REDIS_URL")
        if redis_url:
            redis = Redis.from_url(redis_url)
            mirror = RedisBindingMirror(RedisSipBindings(redis))
        else:
            logger.warning("SIM_REDIS_URL unset: no Redis signals, no sip:binding mirror")
        media = [read_env_value(name) for name in _MEDIA_KEYS]
        if all(media):
            room_factory = room_factory_for(*[str(value) for value in media])
        else:
            logger.warning("SIM_LIVEKIT_* unset: ДДС calls are bridged into a silent test room")
    gateway = SipGateway(
        config,
        backend=backend,
        room_factory=room_factory,
        on_bind=None if mirror is None else mirror.on_bind,
        on_unbind=None if mirror is None else mirror.on_unbind,
    )
    await gateway.start()
    signals = None if redis is None else RedisTelephonySignals(redis, gateway)
    if signals is not None:
        await signals.start()
    logger.info(
        "SIP gateway mode: %s, INVITE auth %s",
        "wired to the backend" if backend is not None else "standalone (echo 999 only)",
        config.invite_auth,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    try:
        await stop.wait()
    finally:
        logger.info("signal received: stopping (BYE to every live call)")
        if signals is not None:
            await signals.stop()
        await gateway.stop()
        if backend is not None:
            await backend.aclose()
        if redis is not None:
            await redis.aclose()


def resolve_tls(config: SipGatewayConfig) -> tuple[SipGatewayConfig | None, str | None]:
    """I7 E44: check the TLS certificate before binding. `(config, warning)` to start with —
    TLS switched off (and a warning) when its files are unset or unreadable but a plain transport
    remains — or `(None, error)` when TLS is the only transport and cannot start."""
    if not config.tls:
        return config, None
    missing = [
        f"{name}={path or '(unset)'}"
        for name, path in (
            ("SIM_SIP_TLS_CERT", config.tls_cert),
            ("SIM_SIP_TLS_KEY", config.tls_key),
        )
        if not path or not os.access(path, os.R_OK)
    ]
    if not missing:
        return config, None
    problem = "SIP over TLS has no readable certificate/key (" + ", ".join(missing) + ")"
    if not (config.udp or config.tcp):
        return None, f"{problem}; SIM_SIP_TRANSPORTS names no other transport"
    fixed = dataclasses.replace(config, tls=False)
    return fixed, f"{problem}: TLS is OFF, serving {','.join(fixed.transports)} only (make certs)"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m voice_agent.sip_gateway", description=__doc__)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(list(argv) if argv is not None else None)
    # I4 E25 (D31): one JSON object per log line under `SIM_LOG_FORMAT=json` (the default);
    # `text` keeps the former `%(asctime)s %(levelname)s %(name)s: %(message)s` line.
    configure_logging(
        read_env_value("SIM_LOG_FORMAT") or "json",
        service="sip-gateway",
        level=args.log_level,
    )
    try:
        config = SipGatewayConfig.from_env()
    except ValueError as exc:
        print(f"sip_gateway: {exc}; refusing to start", file=sys.stderr)
        return 2
    if not config.password:
        print("sip_gateway: SIM_SIP_PASSWORD is not set; refusing to start", file=sys.stderr)
        return 2
    if config.backend_url and not config.gateway_secret:
        print(
            "sip_gateway: SIM_SIP_BACKEND_URL is set but SIM_SIP_GATEWAY_SECRET is not; "
            "refusing to start",
            file=sys.stderr,
        )
        return 2
    resolved, tls_note = resolve_tls(config)
    if resolved is None:
        print(f"sip_gateway: {tls_note}; refusing to start", file=sys.stderr)
        return 2
    if tls_note:
        logger.warning("%s", tls_note)
    config = resolved
    ports = (config.sip_port, config.http_port, config.tls_port if config.tls else None)
    used = {port for port in ports if port is not None}
    if used & _OWNER_PORTS:
        print(f"sip_gateway: refusing owner port(s) {sorted(used & _OWNER_PORTS)}", file=sys.stderr)
        return 2
    asyncio.run(serve(config))
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())

"""`python -m voice_agent.sip_gateway` — the SIP gateway process (HLD 80 §80.2.1, D22).

Reads the `SIM_SIP_*` keys (`SipGatewayConfig.from_env`: process environment first, then the
`.env` file), binds SIP on `SIM_SIP_PORT` (udp+tcp, default 5060), RTP from
`SIM_SIP_RTP_PORT_RANGE` (default 20000-20199) and health on `127.0.0.1:SIM_SIP_GATEWAY_HTTP_PORT`
(default 8114), and serves until SIGTERM/SIGINT, when it sends a `BYE` to every live call.

Refuses to start without `SIM_SIP_PASSWORD` — there is no default credential ([credential
redacted] in every document; SPEC §41). Never binds 8000/8001/8011/8012/5000 (owner ports).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from collections.abc import Sequence

from voice_agent.transport.sip.gateway import SipGateway, SipGatewayConfig

__all__ = ["main"]

logger = logging.getLogger("voice_agent.sip_gateway")

_OWNER_PORTS = {8000, 8001, 8011, 8012, 5000}


async def serve(config: SipGatewayConfig) -> None:
    gateway = SipGateway(config)
    await gateway.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    try:
        await stop.wait()
    finally:
        logger.info("signal received: stopping (BYE to every live call)")
        await gateway.stop()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m voice_agent.sip_gateway", description=__doc__)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = SipGatewayConfig.from_env()
    if not config.password:
        print("sip_gateway: SIM_SIP_PASSWORD is not set; refusing to start", file=sys.stderr)
        return 2
    used = {port for port in (config.sip_port, config.http_port) if port is not None}
    if used & _OWNER_PORTS:
        print(f"sip_gateway: refusing owner port(s) {sorted(used & _OWNER_PORTS)}", file=sys.stderr)
        return 2
    asyncio.run(serve(config))
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())

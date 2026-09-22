"""`python -m tts_qwen3` — launches the worker (`make run-tts-qwen3`, or its compose service).

**The bind host is `127.0.0.1` by default and that default is what a host run gets** (SPEC §41:
this worker is never reachable from outside the machine). `SIM_TTS_QWEN3_HOST` overrides it for the
one case that cannot work otherwise: inside its own container, `tts-qwen3` must accept connections
from the `voice-agent` container at the compose-internal hostname, and a process bound to the
container's loopback is unreachable from any other container. The compose service therefore sets
`SIM_TTS_QWEN3_HOST=0.0.0.0` (E18-E), and it publishes **no host port** — the container network is
the boundary there, exactly as it is for `llama-server` and `voice-agent` (HLD 60 §9, R10).

A non-loopback bind is logged as a warning at start-up, so a host run that picked one up from a
stray `.env` says so in its first line of output rather than silently listening on every interface.
"""

from __future__ import annotations

import ipaddress
import logging
import os

import uvicorn

from tts_qwen3.server import DEFAULT_HOST, DEFAULT_PORT, create_app

log = logging.getLogger("tts_qwen3")

app = create_app()


def _is_loopback(host: str) -> bool:
    candidate = host.strip().strip("[]").lower()
    if candidate == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def main() -> None:
    port = int(os.environ.get("SIM_TTS_QWEN3_PORT", DEFAULT_PORT))
    host = os.environ.get("SIM_TTS_QWEN3_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    if not _is_loopback(host):
        log.warning(
            "SIM_TTS_QWEN3_HOST=%s is not loopback; this is correct only inside a container "
            "whose port is not published (SPEC §41)",
            host,
        )
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

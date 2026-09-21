"""`python -m tts_qwen3` — launches the worker bound to loopback only (`make run-tts-qwen3`).

`--host 127.0.0.1` is passed explicitly here, not left to a default, so "loopback only" is true
regardless of `uvicorn`'s own default and cannot be overridden by an environment variable the way
the port can (SPEC §41: this worker is never reachable from outside the machine).
"""

from __future__ import annotations

import os

import uvicorn

from tts_qwen3.server import DEFAULT_PORT, create_app

app = create_app()


def main() -> None:
    port = int(os.environ.get("SIM_TTS_QWEN3_PORT", DEFAULT_PORT))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()

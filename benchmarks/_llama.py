"""Thin wrapper over the llama-server harness that already exists in `backend/tests/models/`.

`backend/tests/models/conftest.py` (E12/E13) owns every hard-won detail of starting a real
llama-server on this machine: the two candidate binaries, the forbidden-port set, the GGUF block
count, `choose_offload()`'s size-aware GPU/CPU decision, the `/health` wait and a `terminate()`
that only ever signals a `Popen` this process started. HLD §7 and this epic's brief both say to
**reuse** it rather than copy it, so this module does exactly one thing: put `backend/` on
`sys.path` (`_common.ensure_backend_on_path`, the documented dev-tooling allowance) and re-export
those helpers under names a benchmark script can call.

Two small adaptations, and no logic of its own:

* `candidate_binaries()` in the harness is a fixed pair of paths. `SIM_LLAMA_SERVER_BIN` (and
  `--llama-server-bin`) must win on this machine — the owner's newer llama.cpp build is required
  for Qwen3.5 — so `start_server()` temporarily points the harness's first candidate at the
  override and restores it afterwards. Nothing else about the harness is touched.
* The harness signals a failure with `pytest.skip`/`pytest.fail`, which outside a pytest run are
  simply exceptions. `start_server()` lets them propagate as `LlamaServerUnavailable` so a script
  can turn them into an honest `NOT_RUN`/`FAILED` reason instead of a traceback.

**No GPU work happens at import time**, so a gate-side `--provider fake` run never loads anything;
`benchmarks/tests/` imports this module only to assert the wrapper's shape.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from _common import ensure_backend_on_path

__all__ = [
    "LlamaServerUnavailable",
    "choose_offload",
    "free_vram_mb",
    "gguf_block_count",
    "harness",
    "pid_vram_mb",
    "server",
    "start_server",
    "terminate",
]


class LlamaServerUnavailable(RuntimeError):
    """No llama-server binary could load the model — an honest `NOT_RUN`/`FAILED` reason."""


def harness() -> Any:
    """`backend/tests/models/conftest.py` as a module.

    Imported lazily, never at benchmark-module import time, so a fake run loads nothing.
    """
    ensure_backend_on_path()
    import tests.models.conftest as conftest

    return conftest


def choose_offload(model_path: Path, *, vram_free_mb: int | None) -> tuple[str, int]:
    """`(mode, n_gpu_layers)` — the harness's size-aware rule, unchanged."""
    return harness().choose_offload(model_path, vram_free_mb=vram_free_mb)


def gguf_block_count(model_path: Path) -> int | None:
    """Layer count read out of the GGUF header, or `None`."""
    return harness().gguf_block_count(model_path)


def free_vram_mb() -> int | None:
    """`nvidia-smi --query-gpu=memory.free`, or `None`."""
    return harness().free_vram_mb()


def pid_vram_mb(pid: int) -> int | None:
    """VRAM held by one PID, or `None`."""
    return harness().pid_vram_mb(pid)


def terminate(process: Any) -> None:
    """Stop a server this process started. Never called on a PID merely discovered."""
    harness().terminate(process)


def start_server(
    model_path: Path,
    tmp_dir: Path,
    *,
    parallel: int = 1,
    ctx_size: int | None = None,
    binary: str | Path | None = None,
) -> Any:
    """Start llama-server on `model_path`, returning the harness's `ServerHandle`.

    `binary` (else `$SIM_LLAMA_SERVER_BIN`) is tried first; the harness's own two candidates
    follow, exactly as `start_server_trying_binaries` orders them.
    """
    conftest = harness()
    override = binary or os.environ.get("SIM_LLAMA_SERVER_BIN")
    previous = conftest.INSTALLED_BINARY
    if override:
        conftest.INSTALLED_BINARY = Path(override)
    try:
        return conftest.start_server_trying_binaries(
            model_path, tmp_dir, parallel=parallel, ctx_size=ctx_size
        )
    except BaseException as exc:
        raise LlamaServerUnavailable(str(exc)) from exc
    finally:
        conftest.INSTALLED_BINARY = previous


@contextlib.contextmanager
def server(
    model_path: Path,
    tmp_dir: Path,
    *,
    parallel: int = 1,
    ctx_size: int | None = None,
    binary: str | Path | None = None,
) -> Iterator[Any]:
    """`start_server()` with a guaranteed `terminate()` — a benchmark never leaves a server up."""
    handle = start_server(model_path, tmp_dir, parallel=parallel, ctx_size=ctx_size, binary=binary)
    try:
        yield handle
    finally:
        terminate(handle.process)

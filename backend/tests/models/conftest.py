"""Shared llama-server launch helpers for `requires_models` contract tests and
`benchmarks/interpreter_eval/run_eval.py` (this task's brief, CHANGE item 5).

Plain module-level functions, not pytest fixtures — `run_eval.py` (which lives outside the
`backend` package's `sys.path` entry point but shares the same `uv` workspace venv) imports them
directly as `from tests.models.conftest import ...`, the same way `test_llama_cpp_contract.py`
does. Everything here is CPU-cheap (no model load): probing free VRAM, reading one GGUF metadata
key to size a proportional GPU offload, and the subprocess start/health-wait/terminate dance.

**Offload sizing (replaces the old flat "< 3000 MB free -> CPU" rule):**
`choose_offload()` offloads every layer (`--n-gpu-layers 999`) when free VRAM covers the whole
quantised file plus a 20% + 600 MB safety margin, offloads a proportional slice of the model's own
layer count (read from the GGUF header via `gguf_block_count`, no `gguf` package dependency) when
it does not fully fit, and falls back to CPU (`0`) when there is no usable headroom at all or the
layer count could not be determined.
"""

from __future__ import annotations

import socket
import struct
import subprocess
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

__all__ = [
    "ALT_BINARY",
    "FORBIDDEN_PORTS",
    "INSTALLED_BINARY",
    "ServerHandle",
    "candidate_binaries",
    "choose_offload",
    "free_port",
    "free_vram_mb",
    "gguf_block_count",
    "pid_vram_mb",
    "start_server_trying_binaries",
    "terminate",
]

#: Prefer the installed binary, then the owner's newer build (this task's brief, CHANGE item 5:
#: "prefer the first llama-server binary that can load the model"). Both are read-only, never
#: rebuilt.
INSTALLED_BINARY = Path.home() / ".local" / "share" / "llama.cpp" / "bin" / "llama-server"
ALT_BINARY = Path("/home/andreipc/src/llama.cpp/build/bin/llama-server")
#: Never bind these — 8000/8001/8012/8016 belong to the owner's other processes (this machine's
#: MACHINE RULES, E13-B4), 8080 is llama.cpp's own documented default and a plausible collision
#: with something else on a dev box. (8012/8016 were missing from this set before E13-B4 — a gap
#: this task fixed; see its report.)
FORBIDDEN_PORTS: frozenset[int] = frozenset({8000, 8001, 8012, 8016, 8080})

#: CHANGE item 5's formula: full offload once free VRAM covers `file_size * 1.2 + 600 MB`.
_FULL_OFFLOAD_SIZE_FACTOR = 1.2
_FULL_OFFLOAD_MARGIN_MB = 600
_N_GPU_LAYERS_FULL = 999


def candidate_binaries() -> list[Path]:
    return [binary for binary in (INSTALLED_BINARY, ALT_BINARY) if binary.is_file()]


def free_port() -> int:
    for _attempt in range(10):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in FORBIDDEN_PORTS:
            return port
    raise RuntimeError("could not find a free port outside {8000, 8001, 8080}")  # pragma: no cover


def free_vram_mb() -> int | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return int(result.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):  # pragma: no cover - defensive
        return None


def pid_vram_mb(pid: int) -> int | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0] == str(pid):
            try:
                return int(parts[1])
            except ValueError:  # pragma: no cover - defensive
                return None
    return None


# --------------------------------------------------------------------------------------------
# GGUF metadata: just enough to read `<architecture>.block_count` (the model's layer count), no
# `gguf` package dependency — stdlib `struct` only.
# --------------------------------------------------------------------------------------------

_GGUF_MAGIC = b"GGUF"
#: GGUFValueType -> (struct format char, size in bytes), scalar types only.
_SCALAR_STRUCTS: dict[int, tuple[str, int]] = {
    0: ("B", 1),  # UINT8
    1: ("b", 1),  # INT8
    2: ("H", 2),  # UINT16
    3: ("h", 2),  # INT16
    4: ("I", 4),  # UINT32
    5: ("i", 4),  # INT32
    6: ("f", 4),  # FLOAT32
    7: ("?", 1),  # BOOL
    10: ("Q", 8),  # UINT64
    11: ("q", 8),  # INT64
    12: ("d", 8),  # FLOAT64
}
_GGUF_STRING = 8
_GGUF_ARRAY = 9


def _read_u32(handle: Any) -> int:
    return struct.unpack("<I", handle.read(4))[0]


def _read_u64(handle: Any) -> int:
    return struct.unpack("<Q", handle.read(8))[0]


def _read_gguf_string(handle: Any) -> str:
    length = _read_u64(handle)
    return handle.read(length).decode("utf-8", errors="replace")


def _skip_gguf_value(handle: Any, value_type: int) -> None:
    if value_type in _SCALAR_STRUCTS:
        handle.seek(_SCALAR_STRUCTS[value_type][1], 1)
    elif value_type == _GGUF_STRING:
        handle.seek(_read_u64(handle), 1)
    elif value_type == _GGUF_ARRAY:
        item_type = _read_u32(handle)
        count = _read_u64(handle)
        for _ in range(count):
            _skip_gguf_value(handle, item_type)
    else:
        raise ValueError(f"unknown GGUF value type {value_type}")


def gguf_block_count(path: Path) -> int | None:
    """Best-effort read of `<architecture>.block_count` (the model's transformer layer count),
    used to size a proportional GPU offload when the whole model does not fit (CHANGE item 5).

    Stdlib `struct` only, no `gguf` package. Returns `None` on any parse surprise — the caller
    then falls back to CPU rather than guess a layer count.
    """
    try:
        with path.open("rb") as handle:
            if handle.read(4) != _GGUF_MAGIC:
                return None
            handle.read(4)  # version, unused
            _tensor_count = _read_u64(handle)
            kv_count = _read_u64(handle)
            for _ in range(kv_count):
                key = _read_gguf_string(handle)
                value_type = _read_u32(handle)
                if key.endswith(".block_count") and value_type in _SCALAR_STRUCTS:
                    fmt, size = _SCALAR_STRUCTS[value_type]
                    return int(struct.unpack("<" + fmt, handle.read(size))[0])
                _skip_gguf_value(handle, value_type)
    except (OSError, struct.error, UnicodeDecodeError, ValueError):
        return None
    return None


def choose_offload(model_path: Path, *, vram_free_mb: int | None) -> tuple[str, int]:
    """`(mode, n_gpu_layers)` — CHANGE item 5's size-aware rule, replacing the old flat "< 3000 MB
    free -> CPU" check. `mode` is `"GPU_FULL"`, `"GPU_PARTIAL"` or `"CPU"` (printed by callers)."""
    file_size_mb = model_path.stat().st_size / (1024 * 1024)
    full_offload_threshold_mb = file_size_mb * _FULL_OFFLOAD_SIZE_FACTOR + _FULL_OFFLOAD_MARGIN_MB
    if not vram_free_mb or vram_free_mb <= 0:
        return "CPU", 0
    if vram_free_mb >= full_offload_threshold_mb:
        return "GPU_FULL", _N_GPU_LAYERS_FULL
    total_layers = gguf_block_count(model_path)
    if total_layers:
        usable_mb = max(vram_free_mb - _FULL_OFFLOAD_MARGIN_MB, 0)
        ratio = usable_mb / (file_size_mb * _FULL_OFFLOAD_SIZE_FACTOR) if file_size_mb > 0 else 0.0
        layers = max(0, min(total_layers, int(total_layers * ratio)))
        if layers > 0:
            return "GPU_PARTIAL", layers
    return "CPU", 0


# --------------------------------------------------------------------------------------------
# Process lifecycle: start, wait for /health, terminate. Never touches a PID it did not start.
# --------------------------------------------------------------------------------------------


@dataclass
class ServerHandle:
    process: subprocess.Popen[bytes]
    base_url: str
    port: int
    binary: Path
    log_path: Path
    load_seconds: float
    offload_mode: str
    n_gpu_layers: int
    vram_free_mb_at_start: int | None
    peak_vram_mb: int | None = field(default=None)

    def sample_vram(self) -> None:
        sample = pid_vram_mb(self.process.pid)
        if sample is not None:
            self.peak_vram_mb = (
                sample if self.peak_vram_mb is None else max(self.peak_vram_mb, sample)
            )


def _start_server(
    binary: Path,
    model_path: Path,
    *,
    log_path: Path,
    n_gpu_layers: int,
    parallel: int = 1,
    ctx_size: int | None = None,
) -> tuple[subprocess.Popen[bytes], int]:
    """`ctx_size` defaults to `4096 * parallel` when not given — the ledger rule E13-B4 item 3
    documents (`ctx-size = n_ctx * slots`): each of `--parallel N` slots gets the interpreter's
    per-turn `n_ctx` (4096), not a shared budget, so two distinct `id_slot`s (interpreter=0,
    generator=1) never starve each other's context window."""
    port = free_port()
    resolved_ctx_size = ctx_size if ctx_size is not None else 4096 * parallel
    args = [
        str(binary),
        "--model",
        str(model_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        str(resolved_ctx_size),
        "--parallel",
        str(parallel),
        "--jinja",
        "--n-gpu-layers",
        str(n_gpu_layers),
    ]
    log_file = log_path.open("wb")
    process = subprocess.Popen(args, stdout=log_file, stderr=subprocess.STDOUT)  # never a shell
    return process, port


def _wait_for_health(process: subprocess.Popen[bytes], base_url: str, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"llama-server exited early (code {process.returncode})")
            try:
                if client.get(f"{base_url}/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    raise TimeoutError(f"llama-server did not answer /health within {timeout_s}s")


def terminate(process: subprocess.Popen[bytes]) -> None:
    """Only ever called on a `Popen` this same process started (never a PID merely discovered)."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        process.kill()
        process.wait(timeout=15)


def start_server_trying_binaries(
    model_path: Path,
    tmp_dir: Path,
    *,
    parallel: int = 1,
    ctx_size: int | None = None,
) -> ServerHandle:
    """Try each binary `candidate_binaries()` returns, in order, until one loads `model_path`
    (CHANGE item 5: "prefer the first llama-server binary that can load the model"); size the
    offload with `choose_offload()` fresh for each attempt (VRAM may have moved between tries).

    `parallel`/`ctx_size` (E13-B4 item 3): every existing call site keeps the old
    `--parallel 1 --ctx-size 4096` behaviour unchanged (the defaults); `benchmarks/caller_eval/
    run_eval.py` passes `parallel=2` when a run needs the interpreter (`id_slot=0`) and the
    generator (`id_slot=1`) to share one server without contending for the same slot."""
    binaries = candidate_binaries()
    if not binaries:
        pytest.skip(f"no llama-server binary found at {INSTALLED_BINARY} or {ALT_BINARY}")

    last_error: Exception | None = None
    for index, binary in enumerate(binaries):
        vram_free = free_vram_mb()
        offload_mode, n_gpu_layers = choose_offload(model_path, vram_free_mb=vram_free)
        log_path = tmp_dir / f"llama-server.{index}.log"
        started_at = time.monotonic()
        process, port = _start_server(
            binary,
            model_path,
            log_path=log_path,
            n_gpu_layers=n_gpu_layers,
            parallel=parallel,
            ctx_size=ctx_size,
        )
        base_url = f"http://127.0.0.1:{port}"
        print(
            f"binary={binary} offload={offload_mode} n_gpu_layers={n_gpu_layers} "
            f"vram_free_mb_at_start={vram_free}"
        )
        try:
            # Cold CPU-heavy load of a multi-GB gguf can take a while on a shared machine.
            _wait_for_health(process, base_url, timeout_s=180.0)
            return ServerHandle(
                process=process,
                base_url=base_url,
                port=port,
                binary=binary,
                log_path=log_path,
                load_seconds=time.monotonic() - started_at,
                offload_mode=offload_mode,
                n_gpu_layers=n_gpu_layers,
                vram_free_mb_at_start=vram_free,
            )
        except Exception as exc:
            terminate(process)
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            last_error = RuntimeError(f"{binary}: {exc}\n--- log tail ---\n{tail}")
            continue
    assert last_error is not None
    pytest.fail(f"no llama-server binary could load {model_path}:\n{last_error}")

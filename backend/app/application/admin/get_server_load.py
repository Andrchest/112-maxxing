"""`getServerLoad` — CPU / memory / disk (+ GPU when visible) of the server (ADMIN, ТЗ ¶208, ¶289).

`/proc/stat`, `/proc/meminfo` and `shutil.disk_usage` directly (there is no `psutil` — the repo's
own stdlib-only rule), the same way `PurgeRecordings` reads and deletes files directly rather than
behind a port: these are plain OS reads, not a vendor SDK `app.application` may not import (D2).
The GPU pair goes through `ServerHeartbeatReader` instead, because that one *is* a Redis read
(`app.application` may not import `redis` itself).

**Every metric is `None`, never `0`, when it cannot be read** (SPEC §27's rule, reused, and this
epic's own acceptance item): a missing `/proc` file, an unreadable `/proc/meminfo` key or a
zero-length sampling window is a `None`, not an invented number.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.application.ports.admin_monitoring import GpuLoad, ServerHeartbeatReader
from app.application.ports.clock import Clock

__all__ = ["GetServerLoad", "ServerLoadResult"]

#: The gap between the two `/proc/stat` samples `cpu_percent` averages over. Long enough that the
#: two integer snapshots differ, short enough that one request stays fast (technical choice).
DEFAULT_CPU_SAMPLE_INTERVAL_S = 0.1


@dataclass(frozen=True, slots=True)
class ServerLoadResult:
    """`openapi.yaml`'s `ServerLoad`, property names literal."""

    sampled_at: datetime
    cpu_percent: float | None
    memory_used_mb: float | None
    memory_total_mb: float | None
    disk_used_gb: float | None
    disk_total_gb: float | None
    gpu_memory_used_mb: float | None
    gpu_memory_total_mb: float | None


class GetServerLoad:
    """ADMIN only. A point-in-time sample; nothing here is stored."""

    def __init__(
        self,
        heartbeat: ServerHeartbeatReader,
        clock: Clock,
        *,
        disk_path: Path,
        cpu_sample_interval_s: float = DEFAULT_CPU_SAMPLE_INTERVAL_S,
    ) -> None:
        self._heartbeat = heartbeat
        self._clock = clock
        self._disk_path = disk_path
        self._cpu_sample_interval_s = cpu_sample_interval_s

    async def __call__(self) -> ServerLoadResult:
        cpu_percent = await self._cpu_percent()
        memory_used_mb, memory_total_mb = _read_meminfo()
        disk_used_gb, disk_total_gb = _read_disk_usage(self._disk_path)
        gpu: GpuLoad = await self._heartbeat.gpu_load()
        return ServerLoadResult(
            sampled_at=self._clock.now(),
            cpu_percent=cpu_percent,
            memory_used_mb=memory_used_mb,
            memory_total_mb=memory_total_mb,
            disk_used_gb=disk_used_gb,
            disk_total_gb=disk_total_gb,
            gpu_memory_used_mb=gpu.used_mb,
            gpu_memory_total_mb=gpu.total_mb,
        )

    async def _cpu_percent(self) -> float | None:
        """Two `/proc/stat` snapshots `cpu_sample_interval_s` apart, `1 - idle_delta/total_delta`.

        A single snapshot cannot answer "percent busy" — `/proc/stat`'s counters are cumulative
        since boot — so this samples twice, the standard technique for reading it without
        `psutil`.
        """
        first = _read_cpu_snapshot()
        if first is None:
            return None
        await asyncio.sleep(self._cpu_sample_interval_s)
        second = _read_cpu_snapshot()
        if second is None:
            return None
        idle_delta = second[0] - first[0]
        total_delta = second[1] - first[1]
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100))


def _read_cpu_snapshot() -> tuple[int, int] | None:
    """`(idle_ticks, total_ticks)` from `/proc/stat`'s `cpu` line, or `None` if unreadable."""
    try:
        with open("/proc/stat", encoding="ascii") as handle:
            first_line = handle.readline()
    except OSError:
        return None
    parts = first_line.split()
    if len(parts) < 5 or parts[0] != "cpu":
        return None
    try:
        values = [int(part) for part in parts[1:]]
    except ValueError:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    return idle, sum(values)


def _read_meminfo() -> tuple[float | None, float | None]:
    """`(used_mb, total_mb)` from `/proc/meminfo`'s `MemTotal`/`MemAvailable`, or `(None, None)`."""
    try:
        text = Path("/proc/meminfo").read_text(encoding="ascii")
    except OSError:
        return None, None
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if not fields:
            continue
        try:
            values[key.strip()] = int(fields[0])
        except ValueError:
            continue
    total_kb = values.get("MemTotal")
    available_kb = values.get("MemAvailable")
    if total_kb is None or available_kb is None:
        return None, None
    return (total_kb - available_kb) / 1024.0, total_kb / 1024.0


def _read_disk_usage(path: Path) -> tuple[float | None, float | None]:
    """`(used_gb, total_gb)` of the filesystem holding `path` (GiB), or `(None, None)`.

    `Settings.data_dir` may not exist yet (a fresh checkout, before the first recording is
    written) even though the filesystem it will live on already does, so this walks up to the
    nearest existing ancestor — terminating at `/`, which always exists — rather than reporting
    `None` for a directory that is merely not created yet.
    """
    candidate = path.resolve()
    for ancestor in (candidate, *candidate.parents):
        try:
            usage = shutil.disk_usage(ancestor)
        except OSError:
            continue
        gib = 1024**3
        return usage.used / gib, usage.total / gib
    return None, None

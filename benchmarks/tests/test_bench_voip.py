"""`benchmark_voip.py` — the gate-side latency probe (HLD 80 §80.8.1, last row; I3 E6a) and the
`--concurrent` load sweep (HLD 80 §80.8.3; I3 E6f).

`sip-loopback` runs for real in the gate: our UA → the in-process gateway → echo `999` → back, on
ephemeral loopback ports, no GPU, no network. It asserts the envelope's shape and that the
in-process one-way delay is below a **generous structural bound** (60 ms) — a regression guard for
the gateway's own hot path, not the ТЗ ¶161 measurement (that is `sip-livekit`, recorded in
`docs/benchmarks/voip.md`). The two LiveKit paths answer an honest `NOT_RUN` without a server, and
run for real only under `requires_livekit` with a server on `SIM_LIVEKIT_URL`.

`--concurrent N` also runs for real on `sip-loopback` in the gate, with a small N (this launches
the REAL standalone gateway subprocess — no GPU, no network, ports of its own): the shape test
below. Its `sip-livekit` counterpart is `requires_livekit` (a real gateway + SFU + N real rooms).
"""

from __future__ import annotations

import importlib.util
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import benchmark_voip
import pytest
from test_bench_scripts import assert_csv_header_is_the_sample_keys, assert_envelope, read_result

STRUCTURAL_BOUND_MS = 60.0
QUICK = ["--bursts", "5", "--burst-interval-ms", "200", "--burst-ms", "60", "--warmup-ms", "200"]


def test_sip_loopback_measures_every_burst_below_the_structural_bound(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert benchmark_voip.main(["--path", "sip-loopback", *QUICK, "--out", str(out)]) == 0
    payload, rows = read_result(out, "voip")
    assert_envelope(payload, "voip")
    assert_csv_header_is_the_sample_keys(payload, rows)
    assert payload["config"]["path"] == "sip-loopback"
    assert len(payload["samples"]) == 5
    for sample in payload["samples"]:
        assert sample["measure"] == "round_trip/2"
        assert sample["one_way_delay_ms"] == pytest.approx(sample["round_trip_ms"] / 2, abs=1e-3)
    aggregates = payload["aggregates"]
    assert aggregates["bursts_sent"] == 5 and aggregates["bursts_detected"] == 5
    assert aggregates["rtp_lost"] == 0
    assert aggregates["target_one_way_p95_ms"] == 150.0
    one_way = aggregates["one_way_delay_ms"]
    assert one_way["n"] == 5
    assert 0 <= one_way["p50"] <= one_way["p95"] < STRUCTURAL_BOUND_MS
    assert isinstance(aggregates["meets_target"], bool)


@pytest.mark.parametrize("path", ["sip-livekit", "livekit-only"])
def test_the_livekit_paths_without_a_server_are_not_run(tmp_path: Path, path: str) -> None:
    out = tmp_path / "out"
    argv = ["--path", path, *QUICK, "--livekit-url", "ws://127.0.0.1:1", "--out", str(out)]
    assert benchmark_voip.main(argv) == 0
    payload, rows = read_result(out, "voip")
    assert_envelope(payload, "voip", status="NOT_RUN")
    assert rows == []
    assert payload["config"]["path"] == path


def test_the_benchmark_never_imports_the_livekit_sdk_itself() -> None:
    source = Path(benchmark_voip.__file__).read_text(encoding="utf-8")
    assert "import livekit" not in source and "from livekit" not in source


def _livekit_up() -> bool:
    url = os.environ.get("SIM_LIVEKIT_URL", "")
    if not url or importlib.util.find_spec("livekit") is None:
        return False
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), 1.0):
            return True
    except OSError:
        return False


@pytest.mark.requires_livekit
@pytest.mark.skipif(not _livekit_up(), reason="needs the livekit SDK and SIM_LIVEKIT_URL up")
@pytest.mark.parametrize("path", ["sip-livekit", "livekit-only"])
def test_the_livekit_paths_measure_a_one_way_delay(tmp_path: Path, path: str) -> None:
    out = tmp_path / "out"
    assert benchmark_voip.main(["--path", path, *QUICK, "--out", str(out)]) == 0
    payload, _rows = read_result(out, "voip")
    assert payload["status"] in ("OK", "PARTIAL"), payload.get("reason")
    assert payload["aggregates"]["one_way_delay_ms"]["n"] >= 1
    assert all(sample["measure"] == "one_way" for sample in payload["samples"])


# -- `--concurrent N` (I3 E6f, HLD 80 §80.8.3) ---------------------------------------------------

CONCURRENT_QUICK = [
    "--bursts",
    "3",
    "--burst-interval-ms",
    "200",
    "--burst-ms",
    "60",
    "--warmup-ms",
    "200",
]


def test_the_concurrent_shape_runs_in_the_gate_on_sip_loopback(tmp_path: Path) -> None:
    """The brief's gate obligation: `--concurrent` on `sip-loopback` with a small N, GPU-free, no
    network — it launches the REAL standalone gateway subprocess (E6a/E6e's own entry point) on
    its own ports and tears it down."""
    out = tmp_path / "out"
    n = 2
    argv = ["--path", "sip-loopback", "--concurrent", str(n), *CONCURRENT_QUICK, "--out", str(out)]
    assert benchmark_voip.main(argv) == 0
    payload, rows = read_result(out, "voip")
    assert_envelope(payload, "voip")
    assert_csv_header_is_the_sample_keys(payload, rows)
    assert payload["config"]["path"] == "sip-loopback"
    assert payload["config"]["concurrent"] == n
    assert len(payload["samples"]) == n * 3
    call_indices = {sample["call_index"] for sample in payload["samples"]}
    assert call_indices == {0, 1}
    for sample in payload["samples"]:
        assert sample["concurrency"] == n
        assert sample["measure"] == "round_trip/2"
    aggregates = payload["aggregates"]
    assert aggregates["concurrency"] == n
    assert aggregates["bursts_sent"] == n * 3 and aggregates["bursts_detected"] == n * 3
    assert aggregates["rtp_lost"] == 0
    assert aggregates["rtp_packet_loss_rate"] == 0.0
    assert aggregates["one_way_delay_ms"]["n"] == n * 3
    assert isinstance(aggregates["meets_target"], bool)
    # gateway_cpu_percent may have zero samples on a very short run (the sampler's own interval);
    # the key's presence, not a positive count, is what the shape test owes.
    assert "gateway_cpu_percent" in aggregates or any(
        "gateway_cpu_percent not measured" in note for note in payload["notes"]
    )


@pytest.mark.parametrize(
    ("extra", "reason_fragment"),
    [
        (["--path", "livekit-only", "--concurrent", "2"], "only defined for sip-loopback"),
        (["--path", "sip-loopback", "--concurrent", "0"], "must be >= 1"),
    ],
)
def test_concurrent_is_refused_honestly_outside_its_shape(
    tmp_path: Path, extra: list[str], reason_fragment: str
) -> None:
    out = tmp_path / "out"
    assert benchmark_voip.main([*extra, *CONCURRENT_QUICK, "--out", str(out)]) == 0
    payload, rows = read_result(out, "voip")
    assert_envelope(payload, "voip", status="NOT_RUN")
    assert rows == []
    assert reason_fragment in payload["reason"]


@pytest.mark.requires_livekit
@pytest.mark.skipif(not _livekit_up(), reason="needs the livekit SDK and SIM_LIVEKIT_URL up")
def test_concurrent_sip_livekit_measures_n_independent_calls(tmp_path: Path) -> None:
    out = tmp_path / "out"
    n = 2
    argv = ["--path", "sip-livekit", "--concurrent", str(n), *CONCURRENT_QUICK, "--out", str(out)]
    assert benchmark_voip.main(argv) == 0
    payload, _rows = read_result(out, "voip")
    assert payload["status"] in ("OK", "PARTIAL"), payload.get("reason")
    assert payload["config"]["concurrent"] == n
    assert {sample["call_index"] for sample in payload["samples"]} == set(range(n))
    assert all(sample["measure"] == "one_way" for sample in payload["samples"])
    assert payload["aggregates"]["concurrency"] == n

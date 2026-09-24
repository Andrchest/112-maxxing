#!/usr/bin/env python
"""VoIP one-way delay benchmark (ТЗ ¶161 «задержка … (VoIP) не более 150 мс»; HLD 80 §80.8.3, D22).

Mouth-to-ear on **one host clock**: the sender emits 20 ms 8 kHz frames carrying a 1 kHz burst
every `--burst-interval-ms` at known send instants; the far end detects each burst by energy and
stamps its arrival (`ToneBurstProbe`, `voice_agent.transport.sip.softphone`); delay = arrival −
send, at sample resolution. Same host, so no clock synchronisation is involved. The number
**excludes** a softphone's own capture/playout buffering and a hardware phone's jitter buffer —
both are stated in the result's notes and in `docs/benchmarks/voip.md`.

Paths (`--path`):

* `sip-loopback` (the gate's, via `benchmarks/tests/`) — our UA → the in-process gateway →
  echo `999` → back to the UA, on ephemeral loopback ports. The measured quantity is the **round
  trip**; `one_way_delay_ms` is reported as half of it (the path is symmetric by construction:
  same sockets, same loop), and `measure: "round_trip/2"` says so on every sample.
* `sip-livekit` (`requires_livekit`) — our UA → the gateway (jitter buffer `--jitter-ms`, 20 ms
  playout clock) → `LiveKitRoomBridge` (8→48 kHz) → the LiveKit SFU → a probe participant
  subscribed in the same room.
  A true one-way number, and the one 80 §80.11's falsification checkpoint reads (p95 ≤ 150 ms).
* `livekit-only` (`requires_livekit`) — a publisher participant → the SFU → a subscriber, both
  `LiveKitRoomBridge`s: the SFU hop alone, for comparison.

The `livekit` SDK is imported only inside `voice_agent.transport` (`check_imports.py` forbids it
under `benchmarks/`); an absent SDK, missing `SIM_LIVEKIT_API_KEY`/`SECRET`, or no server on
`--livekit-url` is an honest `NOT_RUN` with the reason — never a number (`_common.write_result`).
GPU-free by design.

**`--concurrent N`** (I3 E6f, 80 §80.8.3's "Load" bullet) runs N simultaneous calls on
`sip-loopback` or `sip-livekit` (the two paths a real gateway is exercised on) and reports per-N
one-way delay percentiles, RTP packet loss, jitter, and gateway/SFU CPU — every PID sampled is a
**captured** one (`subprocess.Popen.pid`, `docker inspect .State.Pid`, or the harness's own
`os.getpid()`), never a `pgrep`-style pattern (`_common.ProcCpuSampler`). `sip-loopback` launches
the REAL standalone gateway process (`voice_agent.sip_gateway`, the exact `sip-gateway` compose
entry point) on ports of its own, so `gateway_cpu_percent` there is that subprocess alone;
`sip-livekit` keeps the gateway in-process (as the single-call path does), so its
`gateway_cpu_percent` is the whole harness process and says so in the envelope's `notes` —
`sfu_cpu_percent` there is the dev LiveKit container's own PID, found via `docker compose ... ps`
+ `docker inspect`, omitted (not zero) when docker or the container is not available.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from _common import (
    REPO_ROOT,
    Envelope,
    ProcCpuSampler,
    aggregate,
    finish,
    load_profile_for_bench,
    not_run,
    parse_common_args,
)

BENCHMARK = "voip"
PATHS = ("sip-loopback", "sip-livekit", "livekit-only")
#: ТЗ ¶161 (REQ-2139): one-way VoIP delay no more than 150 ms.
TARGET_ONE_WAY_P95_MS = 150.0
FRAME_S = 0.02
BENCH_NUMBER = "7000"
#: `--concurrent`'s per-call dialed numbers on `sip-livekit` (distinct from the single-call
#: `BENCH_NUMBER` and the `sip-loopback` echo `999`); `{prefix}{index:03d}` per call.
_CONCURRENT_NUMBER_PREFIX = "9500"
#: `--concurrent`'s standalone `sip-loopback` gateway subprocess: an RTP range distinct from the
#: single-call paths' default (`20000-20199`, E6a/E6e) so a concurrent run can never collide with
#: an already-running dev `sip-gateway`. Even ports only (`PortAllocator`), 100 slots.
_STANDALONE_RTP_BASE = 31000
_STANDALONE_RTP_SPAN = 200
#: `--concurrent`'s `sip-livekit` call-start ramp (seconds/call, see `_run_concurrent_sip_livekit`):
#: measured necessary at N=10 against the single-process dev SFU, where an all-at-once start
#: overwhelmed its connection-setup pipeline (`PublishTrackError`s, not a delay/loss finding).
_CONCURRENT_RAMP_S = 0.15


def _extra(parser: Any) -> None:
    parser.add_argument("--path", choices=PATHS, default="sip-loopback")
    parser.add_argument("--bursts", type=int, default=30, help="bursts per run (80 §80.8.3: 30)")
    parser.add_argument("--burst-interval-ms", type=int, default=2000)
    parser.add_argument("--burst-ms", type=int, default=100)
    parser.add_argument(
        "--warmup-ms", type=int, default=1000, help="silence sent before the first burst"
    )
    parser.add_argument("--jitter-ms", type=int, default=40, help="the gateway's jitter buffer")
    parser.add_argument(
        "--livekit-url",
        default=None,
        help="LiveKit ws:// URL (default: $SIM_LIVEKIT_URL, else ws://127.0.0.1:7880)",
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=None,
        metavar="N",
        help=(
            "80 §80.8.3 load sweep: N simultaneous calls on sip-loopback/sip-livekit "
            "(1/5/10/20/40 is the documented sweep); single-call mode when omitted"
        ),
    )


def _env(name: str) -> str | None:
    from app.config.settings import read_env_value

    return read_env_value(name)


def _livekit_preflight(url: str) -> str | None:
    if importlib.util.find_spec("livekit") is None:
        return (
            "the livekit SDK is not installed (`sim-voice-agent`'s `transport-livekit` extra); "
            "run `make deps-livekit`"
        )
    if not (_env("SIM_LIVEKIT_API_KEY") and _env("SIM_LIVEKIT_API_SECRET")):
        return "SIM_LIVEKIT_API_KEY / SIM_LIVEKIT_API_SECRET are not set"
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme in ("wss", "https") else 80)
    try:
        with socket.create_connection((host, port), timeout=1.0):
            pass
    except OSError as exc:
        return f"no LiveKit server answers on {url} ({exc.__class__.__name__})"
    return None


def _token(url: str, room: str, identity: str) -> str:
    from app.infrastructure.transport.livekit_token_service import LiveKitTokenService

    service = LiveKitTokenService(
        _env("SIM_LIVEKIT_API_KEY") or "",
        _env("SIM_LIVEKIT_API_SECRET") or "",
        livekit_url=url,
        ttl_minutes=10,
    )
    return service.mint(room_name=room, participant_identity=identity).token


def _free_port(host: str = "127.0.0.1") -> int:
    """One free TCP port on `host` — bind to port 0, read what the OS picked, close (E6f: giving
    the standalone gateway subprocess its own ports, not the single-call paths' defaults)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


async def _spawn_standalone_gateway(*, jitter_ms: int) -> tuple[subprocess.Popen[bytes], int, str]:
    """Launch the REAL standalone gateway process (`python -m voice_agent.sip_gateway`, E6a/E6e's
    own entry point — the exact code the `sip-gateway` compose service runs), on loopback, on
    ports distinct from any other running instance. Its PID (`process.pid`, captured directly from
    `Popen`) is what `--concurrent`'s `gateway_cpu_percent` samples on `sip-loopback` — an isolated
    number, not the harness's own CPU.

    No `SIM_SIP_BACKEND_URL` is set, so the gateway runs standalone: `default_router` answers only
    echo `999` (E6a), which is exactly what `sip-loopback`'s single-call path measures too.

    Returns `(process, sip_port, password)`. Raises `RuntimeError` (the caller turns it into a
    `FAILED` envelope) if the process exits or its health endpoint never answers within 10 s.
    """
    sip_port = _free_port()
    http_port = _free_port()
    password = secrets.token_hex(16)
    env = dict(os.environ)
    env.update(
        {
            "SIM_ENV_FILE": "",
            "SIM_SIP_BIND_HOST": "127.0.0.1",
            "SIM_SIP_PORT": str(sip_port),
            "SIM_SIP_RTP_PORT_RANGE": (
                f"{_STANDALONE_RTP_BASE}-{_STANDALONE_RTP_BASE + _STANDALONE_RTP_SPAN - 1}"
            ),
            "SIM_SIP_GATEWAY_HTTP_PORT": str(http_port),
            "SIM_SIP_PASSWORD": password,
            "SIM_SIP_REALM": "voip-bench",
            "SIM_SIP_JITTER_MS": str(jitter_ms),
        }
    )
    env.pop("SIM_SIP_BACKEND_URL", None)  # standalone mode: echo 999 only, never the domain
    argv = [sys.executable, "-m", "voice_agent.sip_gateway", "--log-level", "WARNING"]
    process = await asyncio.to_thread(
        subprocess.Popen,
        argv,  # a fixed, literal argv; no shell, no untrusted input
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{http_port}/health"
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = process.stdout.read().decode("utf-8", "replace") if process.stdout else ""
            raise RuntimeError(f"the standalone gateway exited before it was ready:\n{tail}")
        try:
            status = await asyncio.to_thread(_probe_health, url)  # loopback only
            if status == 200:
                return process, sip_port, password
        except OSError:
            pass
        await asyncio.sleep(0.1)
    process.terminate()
    raise RuntimeError(f"the standalone gateway did not answer {url} within 10s")


def _probe_health(url: str) -> int:
    """Loopback-only GET, called off the event loop via `asyncio.to_thread`."""
    with urllib.request.urlopen(url, timeout=0.5) as response:
        return int(response.status)


async def _stop_standalone_gateway(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        await asyncio.to_thread(process.wait, timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        await asyncio.to_thread(process.wait, timeout=5)


def _sfu_container_pid() -> tuple[int | None, str]:
    """The dev LiveKit SFU's host PID, via `docker compose ... ps -q livekit` then
    `docker inspect --format {{.State.Pid}}` — a PID **captured from docker's own state**, never a
    `ps`/`pgrep` name pattern. `(None, reason)` when `docker` is absent, compose has no `livekit`
    service up, or its state cannot be read; the caller omits `sfu_cpu_percent` rather than write
    a number with no process behind it (never zero)."""
    docker = shutil.which("docker")
    if docker is None:
        return None, "no `docker` binary on PATH"
    compose_file = str(REPO_ROOT / "infra" / "docker-compose.yml")
    try:
        ps = subprocess.run(
            [docker, "compose", "-f", compose_file, "ps", "-q", "livekit"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"`docker compose ps` failed: {exc}"
    container_id = ps.stdout.strip().splitlines()[0] if ps.stdout.strip() else ""
    if not container_id:
        return None, "no `livekit` container is up under infra/docker-compose.yml"
    try:
        inspect = subprocess.run(
            [docker, "inspect", "--format", "{{.State.Pid}}", container_id],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"`docker inspect` failed: {exc}"
    pid_text = inspect.stdout.strip()
    if not pid_text.isdigit() or int(pid_text) <= 0:
        return None, f"`docker inspect` returned no usable PID ({pid_text!r})"
    return int(pid_text), ""


async def _drive(
    probe: Any,
    send: Callable[[bytes], object],
    *,
    bursts: int,
    warmup_ms: int,
) -> None:
    """Send warm-up silence, then `bursts` probe intervals, at a drift-free 20 ms cadence."""
    loop = asyncio.get_running_loop()
    silence = b"\x00" * 320
    warm = warmup_ms // 20
    total = warm + bursts * probe.interval_frames
    started = loop.time()
    for i in range(total):
        index = i - warm
        result = send(probe.frame(index) if index >= 0 else silence)
        if inspect.isawaitable(result):
            await result
        if index >= 0:
            probe.mark_sent(index, time.monotonic())
        await asyncio.sleep(max(0.0, started + (i + 1) * FRAME_S - loop.time()))
    await asyncio.sleep(0.5)  # the tail of the last burst


async def _run_sip_loopback(args: Any, probe: Any, envelope: Envelope) -> dict[str, Any]:
    from voice_agent.transport.sip.gateway import SipGateway, SipGatewayConfig
    from voice_agent.transport.sip.softphone import SoftPhone

    password = secrets.token_hex(16)  # a per-run throwaway: nothing leaves this process
    gateway = SipGateway(
        SipGatewayConfig(
            password=password,
            bind_host="127.0.0.1",
            sip_port=0,
            rtp_port_range=None,
            http_port=None,
            media_ip="127.0.0.1",
            jitter_ms=args.jitter_ms,
            tcp=False,
        )
    )
    await gateway.start()
    try:
        phone = SoftPhone(
            server=("127.0.0.1", gateway.udp_port or 0), username="bench", password=password
        )
        async with phone:
            if (await phone.register()).status != 200:
                raise RuntimeError("the in-process gateway refused the benchmark's REGISTER")
            call = await phone.call("999")
            call.on_audio = probe.observe
            await _drive(probe, call.send_pcm, bursts=args.bursts, warmup_ms=args.warmup_ms)
            rtp = call.rtp
            assert rtp is not None
            stats = {
                "rtp_sent": rtp.sent,
                "rtp_received": rtp.stats.received,
                "rtp_lost": rtp.stats.lost,
                "rtp_jitter_ms": round(rtp.stats.jitter_ms, 3),
            }
            await call.hangup()
    finally:
        await gateway.stop()
    envelope.note(
        "sip-loopback: UA -> in-process gateway -> echo 999 -> UA on 127.0.0.1; the measured "
        "quantity is the round trip, one_way_delay_ms = round_trip / 2 (symmetric path)"
    )
    return stats


async def _run_sip_livekit(args: Any, probe: Any, envelope: Envelope, url: str) -> dict[str, Any]:
    from voice_agent.transport.sip.bridge import LiveKitRoomBridge, sip_participant_identity
    from voice_agent.transport.sip.gateway import Route, RouteKind, SipGateway, SipGatewayConfig
    from voice_agent.transport.sip.softphone import SoftPhone

    room = f"voip-bench-{uuid.uuid4().hex[:12]}"
    listener = LiveKitRoomBridge(
        url=url, token=_token(url, room, "voip-probe"), identity="voip-probe"
    )

    def router(dialed: str, from_user: str | None) -> Route:
        if dialed != BENCH_NUMBER:
            return Route(RouteKind.REJECT, status=404)

        def factory(call_id: str) -> LiveKitRoomBridge:
            identity = sip_participant_identity(call_id)
            return LiveKitRoomBridge(url=url, token=_token(url, room, identity), identity=identity)

        return Route(RouteKind.BRIDGE, bridge_factory=factory)

    password = secrets.token_hex(16)
    gateway = SipGateway(
        SipGatewayConfig(
            password=password,
            bind_host="127.0.0.1",
            sip_port=0,
            rtp_port_range=None,
            http_port=None,
            media_ip="127.0.0.1",
            jitter_ms=args.jitter_ms,
            tcp=False,
        ),
        router=router,
    )
    await listener.open(lambda pcm: probe.observe(pcm, time.monotonic()))
    await gateway.start()
    try:
        phone = SoftPhone(
            server=("127.0.0.1", gateway.udp_port or 0), username="bench", password=password
        )
        async with phone:
            if (await phone.register()).status != 200:
                raise RuntimeError("the in-process gateway refused the benchmark's REGISTER")
            call = await phone.call(BENCH_NUMBER, timeout_s=30)
            await asyncio.wait_for(listener.track_subscribed.wait(), 15)
            await _drive(probe, call.send_pcm, bursts=args.bursts, warmup_ms=args.warmup_ms)
            rtp = call.rtp
            assert rtp is not None
            stats = {"rtp_sent": rtp.sent}
            await call.hangup()
    finally:
        await gateway.stop()
        await listener.close()
    envelope.note(
        f"sip-livekit: UA -> gateway (jitter buffer {args.jitter_ms} ms) -> LiveKitRoomBridge "
        f"-> SFU {url} -> probe participant; one host clock, one-way"
    )
    return stats


async def _run_livekit_only(args: Any, probe: Any, envelope: Envelope, url: str) -> dict[str, Any]:
    from voice_agent.transport.sip.bridge import LiveKitRoomBridge

    room = f"voip-bench-{uuid.uuid4().hex[:12]}"
    publisher = LiveKitRoomBridge(url=url, token=_token(url, room, "voip-pub"), identity="voip-pub")
    listener = LiveKitRoomBridge(url=url, token=_token(url, room, "voip-sub"), identity="voip-sub")
    await listener.open(lambda pcm: probe.observe(pcm, time.monotonic()))
    await publisher.open(lambda _pcm: None)
    try:
        await asyncio.wait_for(listener.track_subscribed.wait(), 15)
        await _drive(probe, publisher.push, bursts=args.bursts, warmup_ms=args.warmup_ms)
    finally:
        await publisher.close()
        await listener.close()
    envelope.note(f"livekit-only: publisher -> SFU {url} -> subscriber; one host clock, one-way")
    return {}


# -------------------------------------------------------------------------------------------
# `--concurrent N` (I3 E6f, 80 §80.8.3's "Load" bullet)
# -------------------------------------------------------------------------------------------


async def _run_concurrent_sip_loopback(
    args: Any, probes: list[Any]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    """N softphones -> the REAL standalone gateway subprocess -> echo `999` -> back, concurrently.
    Returns `(per_call_rtp_stats, cpu_aggregates, notes)`."""
    from voice_agent.transport.sip.softphone import SoftPhone

    n = len(probes)
    process, sip_port, password = await _spawn_standalone_gateway(jitter_ms=args.jitter_ms)
    cpu = ProcCpuSampler(process.pid)
    cpu.start()
    try:

        async def _one_call(index: int, probe: Any) -> dict[str, Any]:
            phone = SoftPhone(
                server=("127.0.0.1", sip_port), username=f"bench{index}", password=password
            )
            async with phone:
                if (await phone.register()).status != 200:
                    raise RuntimeError(f"call {index}: the standalone gateway refused REGISTER")
                call = await phone.call("999")
                call.on_audio = probe.observe
                await _drive(probe, call.send_pcm, bursts=args.bursts, warmup_ms=args.warmup_ms)
                rtp = call.rtp
                assert rtp is not None
                stats = {
                    "rtp_sent": rtp.sent,
                    "rtp_lost": rtp.stats.lost,
                    "rtp_jitter_ms": rtp.stats.jitter_ms,
                }
                await call.hangup()
            return stats

        per_call = list(await asyncio.gather(*(_one_call(i, probes[i]) for i in range(n))))
    finally:
        gateway_cpu = cpu.stop()
        await _stop_standalone_gateway(process)

    cpu_aggs: dict[str, dict[str, Any]] = {}
    notes: list[str] = [
        f"sip-loopback --concurrent {n}: {n} independent softphones -> a REAL standalone gateway "
        f"subprocess (its own PID, ports distinct from the single-call default) -> echo 999 -> "
        "back; round trip/2, same measurement as the single-call sip-loopback path"
    ]
    if gateway_cpu.get("n", 0) > 0:
        cpu_aggs["gateway_cpu_percent"] = gateway_cpu
    else:
        notes.append("gateway_cpu_percent not measured: the run was too short to sample")
    return per_call, cpu_aggs, notes


async def _run_concurrent_sip_livekit(
    args: Any, probes: list[Any], url: str
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    """N softphones -> ONE in-process gateway (as the single-call path) -> N `LiveKitRoomBridge`
    pairs, one dedicated room per call -> the SFU, concurrently. Returns `(per_call_rtp_stats,
    cpu_aggregates, notes)`."""
    from voice_agent.transport.sip.bridge import LiveKitRoomBridge
    from voice_agent.transport.sip.gateway import Route, RouteKind, SipGateway, SipGatewayConfig
    from voice_agent.transport.sip.softphone import SoftPhone

    n = len(probes)
    run_tag = uuid.uuid4().hex[:8]

    def dialed_for(index: int) -> str:
        return f"{_CONCURRENT_NUMBER_PREFIX}{index:03d}"

    def router(dialed: str, from_user: str | None) -> Route:
        if not dialed.startswith(_CONCURRENT_NUMBER_PREFIX):
            return Route(RouteKind.REJECT, status=404)

        def factory(call_id: str) -> LiveKitRoomBridge:
            identity = f"sip-{call_id[:16]}"
            room = f"voip-bench-{run_tag}-{dialed}"
            return LiveKitRoomBridge(url=url, token=_token(url, room, identity), identity=identity)

        return Route(RouteKind.BRIDGE, bridge_factory=factory)

    password = secrets.token_hex(16)
    gateway = SipGateway(
        SipGatewayConfig(
            password=password,
            bind_host="127.0.0.1",
            sip_port=0,
            rtp_port_range=None,
            http_port=None,
            media_ip="127.0.0.1",
            jitter_ms=args.jitter_ms,
            tcp=False,
        ),
        router=router,
    )
    await gateway.start()
    sfu_pid, sfu_reason = _sfu_container_pid()
    sfu_cpu = ProcCpuSampler(sfu_pid) if sfu_pid is not None else None
    if sfu_cpu is not None:
        sfu_cpu.start()
    gateway_cpu_sampler = ProcCpuSampler(os.getpid())
    gateway_cpu_sampler.start()
    listeners: list[LiveKitRoomBridge] = []
    try:
        for index, probe in enumerate(probes):
            room = f"voip-bench-{run_tag}-{dialed_for(index)}"
            listener = LiveKitRoomBridge(
                url=url,
                token=_token(url, room, f"voip-probe-{index}"),
                identity=f"voip-probe-{index}",
            )
            await listener.open(lambda pcm, _probe=probe: _probe.observe(pcm, time.monotonic()))
            listeners.append(listener)

        async def _one_call(index: int, probe: Any) -> dict[str, Any]:
            # A short, documented ramp (`_CONCURRENT_RAMP_S` per call) instead of every call's
            # REGISTER/INVITE/track-publish landing on the SFU in the same event-loop tick: a real
            # call surge arrives over seconds, not one instant, and an all-at-once thundering herd
            # was measured to overwhelm the single-process dev SFU's connection setup pipeline
            # (`PublishTrackError: ... track publication timed out`) well below its steady-state
            # capacity — a harness/dev-SFU setup artefact, not the number 80 §80.8.3 asks for.
            await asyncio.sleep(index * _CONCURRENT_RAMP_S)
            phone = SoftPhone(
                server=("127.0.0.1", gateway.udp_port or 0),
                username=f"bench{index}",
                password=password,
            )
            async with phone:
                if (await phone.register()).status != 200:
                    raise RuntimeError(f"call {index}: the in-process gateway refused REGISTER")
                call = await phone.call(dialed_for(index), timeout_s=30)
                await asyncio.wait_for(listeners[index].track_subscribed.wait(), 15)
                await _drive(probe, call.send_pcm, bursts=args.bursts, warmup_ms=args.warmup_ms)
                rtp = call.rtp
                assert rtp is not None
                stats = {
                    "rtp_sent": rtp.sent,
                    "rtp_lost": rtp.stats.lost,
                    "rtp_jitter_ms": rtp.stats.jitter_ms,
                }
                await call.hangup()
            return stats

        per_call = list(await asyncio.gather(*(_one_call(i, probes[i]) for i in range(n))))
    finally:
        gateway_cpu = gateway_cpu_sampler.stop()
        sfu_cpu_agg = sfu_cpu.stop() if sfu_cpu is not None else None
        await gateway.stop()
        for listener in listeners:
            await listener.close()

    cpu_aggs: dict[str, dict[str, Any]] = {}
    notes: list[str] = [
        f"sip-livekit --concurrent {n}: {n} independent softphones -> ONE in-process gateway "
        f"(as the single-call sip-livekit path) -> {n} dedicated LiveKit rooms -> the SFU {url}, "
        "concurrently; gateway_cpu_percent below samples this whole harness process (the "
        "UA-driving loop included, not gateway-isolated CPU) — sip-loopback's --concurrent run "
        "gives an isolated gateway figure instead"
    ]
    if gateway_cpu.get("n", 0) > 0:
        cpu_aggs["gateway_cpu_percent"] = gateway_cpu
    if sfu_cpu_agg is not None and sfu_cpu_agg.get("n", 0) > 0:
        cpu_aggs["sfu_cpu_percent"] = sfu_cpu_agg
    else:
        notes.append(f"sfu_cpu_percent not measured: {sfu_reason or 'no samples collected'}")
    return per_call, cpu_aggs, notes


async def _run_concurrent(args: Any) -> Envelope:
    from voice_agent.transport.sip.softphone import ToneBurstProbe

    n = args.concurrent
    url = args.livekit_url or _env("SIM_LIVEKIT_URL") or "ws://127.0.0.1:7880"
    config: dict[str, Any] = {
        "path": args.path,
        "concurrent": n,
        "bursts": args.bursts,
        "burst_interval_ms": args.burst_interval_ms,
        "burst_ms": args.burst_ms,
        "warmup_ms": args.warmup_ms,
        "jitter_buffer_ms": args.jitter_ms,
        "codec": "PCMA",
        "ptime_ms": 20,
        "target_one_way_p95_ms": TARGET_ONE_WAY_P95_MS,
        "tag": args.tag,
    }
    if args.path == "sip-livekit":
        config["livekit_url"] = url
        config["concurrent_ramp_s"] = _CONCURRENT_RAMP_S
        reason = _livekit_preflight(url)
        if reason is not None:
            return not_run(BENCHMARK, args.profile, reason, config=config)
    try:
        probes = [
            ToneBurstProbe(interval_ms=args.burst_interval_ms, burst_ms=args.burst_ms)
            for _ in range(n)
        ]
    except ValueError as exc:
        return not_run(BENCHMARK, args.profile, f"bad burst parameters: {exc}", config=config)

    envelope = Envelope(benchmark=BENCHMARK, status="OK", profile=args.profile, config=config)
    envelope.note(
        "delay excludes a softphone's own capture/playout buffering and a hardware phone's "
        "jitter buffer, same as the single-call paths; `--provider` is irrelevant (no model runs)"
    )
    try:
        if args.path == "sip-loopback":
            per_call, cpu_aggs, cpu_notes = await _run_concurrent_sip_loopback(args, probes)
            halve = True
        else:
            per_call, cpu_aggs, cpu_notes = await _run_concurrent_sip_livekit(args, probes, url)
            halve = False
    except Exception as exc:
        envelope.status = "FAILED"
        envelope.reason = f"{type(exc).__name__}: {exc}"
        return envelope
    for note in cpu_notes:
        envelope.note(note)

    total_sent = 0
    total_lost = 0
    jitter_readings: list[float] = []
    for call_index, probe in enumerate(probes):
        for burst_index, delay in enumerate(probe.delays_ms()):
            sample: dict[str, Any] = {
                "id": f"{args.path}:{n}:{call_index}:{burst_index}",
                "path": args.path,
                "concurrency": n,
                "call_index": call_index,
                "burst_index": burst_index,
                "measure": "round_trip/2" if halve else "one_way",
                "one_way_delay_ms": round(delay / 2 if halve else delay, 3),
            }
            if halve:
                sample["round_trip_ms"] = round(delay, 3)
            envelope.samples.append(sample)
        total_sent += len(probe.sent)
        stats = per_call[call_index]
        total_lost += int(stats.get("rtp_lost") or 0)
        jitter = stats.get("rtp_jitter_ms")
        if jitter is not None:
            jitter_readings.append(float(jitter))

    if not envelope.samples:
        envelope.status = "FAILED"
        envelope.reason = f"{total_sent} bursts sent across {n} calls, none detected at the far end"
        return envelope

    one_way = aggregate([s["one_way_delay_ms"] for s in envelope.samples])
    detected = len(envelope.samples)
    total_rtp_sent = sum(int(s.get("rtp_sent") or 0) for s in per_call)
    envelope.aggregates = {
        "concurrency": n,
        "one_way_delay_ms": one_way,
        "bursts_sent": total_sent,
        "bursts_detected": detected,
        "burst_loss_rate": round(1 - detected / total_sent, 4) if total_sent else None,
        "target_one_way_p95_ms": TARGET_ONE_WAY_P95_MS,
        "meets_target": one_way["p95"] is not None and one_way["p95"] <= TARGET_ONE_WAY_P95_MS,
        "rtp_sent": total_rtp_sent,
        "rtp_lost": total_lost,
        "rtp_packet_loss_rate": (round(total_lost / total_rtp_sent, 4) if total_rtp_sent else None),
        "rtp_jitter_ms": aggregate(jitter_readings),
        **cpu_aggs,
    }
    if halve:
        envelope.aggregates["round_trip_ms"] = aggregate(
            [s["round_trip_ms"] for s in envelope.samples]
        )
    if detected < total_sent:
        envelope.status = "PARTIAL"
        envelope.reason = (
            f"{total_sent - detected} of {total_sent} bursts not detected across {n} calls"
        )
    return envelope


async def run(args: Any) -> Envelope:
    load_profile_for_bench(args.profile)
    if args.concurrent is not None:
        if args.path not in ("sip-loopback", "sip-livekit"):
            return not_run(
                BENCHMARK,
                args.profile,
                f"--concurrent is only defined for sip-loopback/sip-livekit (80 §80.8.3), "
                f"not {args.path!r}",
                config={"path": args.path, "concurrent": args.concurrent},
            )
        if args.concurrent < 1:
            return not_run(
                BENCHMARK,
                args.profile,
                f"--concurrent must be >= 1, got {args.concurrent}",
                config={"path": args.path, "concurrent": args.concurrent},
            )
        return await _run_concurrent(args)
    from voice_agent.transport.sip.softphone import ToneBurstProbe

    url = args.livekit_url or _env("SIM_LIVEKIT_URL") or "ws://127.0.0.1:7880"
    config: dict[str, Any] = {
        "path": args.path,
        "bursts": args.bursts,
        "burst_interval_ms": args.burst_interval_ms,
        "burst_ms": args.burst_ms,
        "warmup_ms": args.warmup_ms,
        "jitter_buffer_ms": args.jitter_ms,
        "codec": "PCMA",
        "ptime_ms": 20,
        "target_one_way_p95_ms": TARGET_ONE_WAY_P95_MS,
        "tag": args.tag,
    }
    if args.path != "sip-loopback":
        config["livekit_url"] = url
        reason = _livekit_preflight(url)
        if reason is not None:
            return not_run(BENCHMARK, args.profile, reason, config=config)
    try:
        probe = ToneBurstProbe(interval_ms=args.burst_interval_ms, burst_ms=args.burst_ms)
    except ValueError as exc:
        return not_run(BENCHMARK, args.profile, f"bad burst parameters: {exc}", config=config)

    envelope = Envelope(benchmark=BENCHMARK, status="OK", profile=args.profile, config=config)
    envelope.note(
        "delay excludes a softphone's own capture/playout buffering (typically 40-80 ms) and a "
        "hardware phone's adaptive jitter buffer; `--provider` is irrelevant here (no model runs)"
    )
    stats: dict[str, Any] = {}
    try:
        if args.path == "sip-loopback":
            stats = await _run_sip_loopback(args, probe, envelope)
        elif args.path == "sip-livekit":
            stats = await _run_sip_livekit(args, probe, envelope, url)
        else:
            stats = await _run_livekit_only(args, probe, envelope, url)
    except Exception as exc:
        envelope.status = "FAILED"
        envelope.reason = f"{type(exc).__name__}: {exc}"
        return envelope

    delays = probe.delays_ms()
    halve = args.path == "sip-loopback"
    for index, delay in enumerate(delays):
        sample: dict[str, Any] = {
            "id": f"{args.path}:{index}",
            "path": args.path,
            "burst_index": index,
            "measure": "round_trip/2" if halve else "one_way",
            "one_way_delay_ms": round(delay / 2 if halve else delay, 3),
        }
        if halve:
            sample["round_trip_ms"] = round(delay, 3)
        envelope.samples.append(sample)
    sent = len(probe.sent)
    if not envelope.samples:
        envelope.status = "FAILED"
        envelope.reason = f"{sent} bursts sent, none detected at the far end"
        return envelope
    one_way = aggregate([s["one_way_delay_ms"] for s in envelope.samples])
    envelope.aggregates = {
        "one_way_delay_ms": one_way,
        "bursts_sent": sent,
        "bursts_detected": len(envelope.samples),
        "burst_loss_rate": round(1 - len(envelope.samples) / sent, 4) if sent else None,
        "target_one_way_p95_ms": TARGET_ONE_WAY_P95_MS,
        "meets_target": one_way["p95"] is not None and one_way["p95"] <= TARGET_ONE_WAY_P95_MS,
        **stats,
    }
    if halve:
        envelope.aggregates["round_trip_ms"] = aggregate(
            [s["round_trip_ms"] for s in envelope.samples]
        )
    if len(envelope.samples) < sent:
        envelope.status = "PARTIAL"
        envelope.reason = f"{sent - len(envelope.samples)} of {sent} bursts not detected"
    return envelope


def main(argv: list[str] | None = None) -> int:
    args = parse_common_args(BENCHMARK, argv, extra=_extra, description=__doc__)
    envelope = asyncio.run(run(args))
    return finish(envelope, args.out)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())

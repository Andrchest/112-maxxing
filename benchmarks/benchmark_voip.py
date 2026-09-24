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
GPU-free by design. The concurrency sweep (`--concurrent N`, 1/5/10/20/40) is epic E6f's.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import secrets
import socket
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from _common import Envelope, aggregate, finish, load_profile_for_bench, not_run, parse_common_args

BENCHMARK = "voip"
PATHS = ("sip-loopback", "sip-livekit", "livekit-only")
#: ТЗ ¶161 (REQ-2139): one-way VoIP delay no more than 150 ms.
TARGET_ONE_WAY_P95_MS = 150.0
FRAME_S = 0.02
BENCH_NUMBER = "7000"


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


async def run(args: Any) -> Envelope:
    load_profile_for_bench(args.profile)
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

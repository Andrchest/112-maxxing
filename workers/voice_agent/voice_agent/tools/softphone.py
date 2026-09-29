"""`python -m voice_agent.tools.softphone` — our own software IP phone (HLD 80 §80.2.1, §80.8.2).

ТЗ ¶175's "software emulation of an IP phone" with no hardware phone and nothing downloaded: it
registers with the gateway and dials a number, e.g. the echo extension `999`.

    SIM_SIP_PASSWORD=... python -m voice_agent.tools.softphone \\
        --server 127.0.0.1:5060 --register trainee --dial 999 --duration 5 --capture out.wav

The ДДС numbers (I3 E6e, the gateway wired to the backend): `101`…`104` and `7xxx` reach a service
head, `112` the AI 112 operator, the claimant's number the claimant; the call is answered when the
AI party picks up (`--answer-timeout`, default 30 s). `--answer` instead waits to be called — the
trainee's «Позвонить старшему» in the browser, or a brigade's `CALL_IN` — and picks up after
`--answer-delay` seconds. The gateway's `407` INVITE challenge is answered automatically.

Without `--headset` it needs no sound card: it sends a 1 kHz tone burst every second (or a WAV
with `--wav`), writes what comes back to `--capture`, and prints a summary — codec, RTP sent /
received / lost, sequence and timestamp continuity, jitter, and the echo round trip measured on
the bursts. `--headset` (bench-only) swaps the tone for `sox`'s `rec` (microphone → RTP) and the
capture for `play` (RTP → speakers); `sox` must be installed (it is on the dev machine).

Encrypted (I7 E44): `--transport tls --server <host>:5061 --ca infra/certs/ca.crt` registers
over TLS (the gateway's certificate checked against the local CA) and talks SRTP; the summary's
`media` says `SRTP` or `RTP`.

The password is read from the environment variable named by `--password-env` (default
`SIM_SIP_PASSWORD`, then the `.env` file) — never from the command line, never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools
import json
import shutil
import socket
import sys
import time
import wave
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.config.settings import read_env_value

from voice_agent.transport.sip.message import PT_PCMA, PT_PCMU
from voice_agent.transport.sip.rtp import CLOCK_RATE, FRAME_BYTES, Resampler, rms, seq_diff
from voice_agent.transport.sip.softphone import CallFailed, SoftCall, SoftPhone, ToneBurstProbe

__all__ = ["continuity", "main", "run"]

_CODEC_NAMES = {PT_PCMA: "PCMA", PT_PCMU: "PCMU"}
_SOX_FORMAT = ["-q", "-r", "8000", "-c", "1", "-b", "16", "-e", "signed-integer", "-t", "raw"]


def _server(text: str, default_port: int = 5060) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    if not host:
        return text, default_port
    return host, int(port)


def _local_host_for(server_host: str) -> str:
    """The address the server can reach us on: our route towards it."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect((server_host, 9))
            return str(probe.getsockname()[0])
        except OSError:
            return "127.0.0.1"


def continuity(call: SoftCall) -> dict[str, Any]:
    """Sequence/timestamp continuity of the received stream (every step +1 and +160)."""
    packets = [packet for _, packet in call.received]
    pairs = list(itertools.pairwise(packets))
    seq_breaks = sum(1 for a, b in pairs if seq_diff(b.sequence, a.sequence) != 1)
    ts_breaks = sum(
        1
        for a, b in pairs
        if (b.timestamp - a.timestamp) % (1 << 32) != 160 * seq_diff(b.sequence, a.sequence)
    )
    ssrcs = {packet.ssrc for packet in packets}
    return {"seq_breaks": seq_breaks, "ts_breaks": ts_breaks, "ssrc_count": len(ssrcs)}


def _load_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit mono PCM")
        pcm = handle.readframes(handle.getnframes())
        rate = handle.getframerate()
    return Resampler(rate, CLOCK_RATE).convert(pcm)


def _write_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(CLOCK_RATE)
        handle.writeframes(pcm)


async def _pump_tone(call: SoftCall, probe: ToneBurstProbe, duration_s: float) -> int:
    loop = asyncio.get_running_loop()
    started = loop.time()
    frames = int(duration_s * 1000 / 20)
    for index in range(frames):
        call.send_pcm(probe.frame(index))
        probe.mark_sent(index, time.monotonic())
        await asyncio.sleep(max(0.0, started + (index + 1) * 0.02 - loop.time()))
    return frames


async def _pump_wav(call: SoftCall, pcm: bytes, duration_s: float) -> int:
    loop = asyncio.get_running_loop()
    started = loop.time()
    frames = int(duration_s * 1000 / 20)
    for index in range(frames):
        start = (index * FRAME_BYTES) % max(len(pcm), FRAME_BYTES)
        chunk = pcm[start : start + FRAME_BYTES].ljust(FRAME_BYTES, b"\x00")
        call.send_pcm(chunk)
        await asyncio.sleep(max(0.0, started + (index + 1) * 0.02 - loop.time()))
    return frames


async def _pump_headset(call: SoftCall, duration_s: float) -> int:
    rec = await asyncio.create_subprocess_exec(
        "rec", *_SOX_FORMAT, "-", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    play = await asyncio.create_subprocess_exec(
        "play", *_SOX_FORMAT, "-", stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    assert rec.stdout is not None and play.stdin is not None
    stdin = play.stdin
    call.on_audio = lambda pcm, _t: stdin.write(pcm)
    frames = 0
    deadline = time.monotonic() + duration_s if duration_s > 0 else float("inf")
    try:
        while time.monotonic() < deadline and not call._ended.is_set():
            chunk = await rec.stdout.readexactly(FRAME_BYTES)
            call.send_pcm(chunk)
            frames += 1
    except (asyncio.IncompleteReadError, asyncio.CancelledError):
        pass
    finally:
        for process in (rec, play):
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            with contextlib.suppress(Exception):
                await process.wait()
    return frames


async def run(args: argparse.Namespace, password: str) -> dict[str, Any]:
    transport = str(args.transport)
    host, port = _server(args.server, 5061 if transport == "tls" else 5060)
    local_host = args.local_host or _local_host_for(host)
    codecs = {"pcma": (PT_PCMA, PT_PCMU), "pcmu": (PT_PCMU, PT_PCMA)}[args.codec]
    summary: dict[str, Any] = {"server": f"{host}:{port}", "user": args.register}
    answer = bool(getattr(args, "answer", False))
    async with SoftPhone(
        server=(host, port),
        username=args.register,
        password=password,
        transport=transport,
        tls_ca=getattr(args, "ca", None),
        local_host=local_host,
        domain=args.domain,
        codecs=codecs,
        answer_mode="auto" if answer else "busy",
        answer_delay_s=float(getattr(args, "answer_delay", 1.0)),
    ) as phone:
        registered = await phone.register(expires=args.expires)
        summary["register"] = registered.status
        if registered.status != 200 or not (args.dial or answer):
            return summary
        probe = ToneBurstProbe(interval_ms=1000, burst_ms=200)
        if answer:
            try:
                call = await asyncio.wait_for(phone.incoming.get(), args.answer_timeout)
            except TimeoutError:
                summary["call"] = {"incoming": None}
                return summary
            confirmed = await call.wait_confirmed(10.0)
            summary["call"] = {"incoming": call.number, "final": 200 if confirmed else None}
            if not confirmed:
                return summary
        else:
            try:
                call = await phone.call(args.dial, timeout_s=args.answer_timeout)
            except CallFailed as exc:
                summary["call"] = {"final": exc.status, "reason": exc.reason}
                return summary
            summary["call"] = {"provisional": call.provisional, "final": call.final_status}
            summary["invite_challenged"] = call.challenged  # the gateway's 407 (E6e)
        summary["codec"] = _CODEC_NAMES.get(call.codec) if call.codec is not None else None
        summary["media"] = "SRTP" if call.srtp else "RTP"
        if not args.headset:
            call.on_audio = probe.observe
        started = time.monotonic()
        if args.headset:
            frames = await _pump_headset(call, args.duration)
        elif args.wav:
            frames = await _pump_wav(call, _load_wav(Path(args.wav)), args.duration)
        else:
            frames = await _pump_tone(call, probe, args.duration)
        await asyncio.sleep(0.3)  # let the tail of the far end's audio arrive
        summary["duration_s"] = round(time.monotonic() - started, 2)
        rtp = call.rtp
        assert rtp is not None
        received_pcm = call.received_pcm()
        summary["rtp"] = {
            "frames_sent": frames,
            "packets_sent": rtp.sent,
            "packets_received": rtp.stats.received,
            "lost": rtp.stats.lost,
            "jitter_ms": round(rtp.stats.jitter_ms, 2),
            **continuity(call),
            "received_rms": rms(received_pcm),
        }
        if not args.headset and not args.wav:
            delays = probe.delays_ms()
            summary["echo_round_trip_ms"] = {
                "bursts_sent": len(probe.sent),
                "bursts_detected": len(delays),
                "min": round(min(delays), 2) if delays else None,
                "max": round(max(delays), 2) if delays else None,
            }
        if args.capture:
            _write_wav(Path(args.capture), received_pcm)
            summary["capture"] = args.capture
        summary["ended_by_remote"] = call.ended_by_remote
        summary["bye"] = await call.hangup() if not call.ended_by_remote else None
        if args.unregister:
            summary["unregister"] = (await phone.unregister()).status
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m voice_agent.tools.softphone",
        description="Register with the sim112 SIP gateway and place a call (ТЗ ¶175).",
    )
    parser.add_argument("--server", default="127.0.0.1:5060", help="gateway host[:port]")
    parser.add_argument("--register", required=True, metavar="USER", help="SIP username")
    parser.add_argument("--dial", default=None, metavar="NUMBER", help="number to call, e.g. 999")
    parser.add_argument(
        "--answer",
        action="store_true",
        help="wait to be called (click-to-call, CALL_IN) instead of dialling",
    )
    parser.add_argument("--answer-delay", type=float, default=1.0, help="ring this long first")
    parser.add_argument("--password-env", default="SIM_SIP_PASSWORD", metavar="NAME")
    parser.add_argument("--transport", choices=("udp", "tcp", "tls"), default="udp")
    parser.add_argument(
        "--ca", default=None, help="CA file for --transport tls (e.g. infra/certs/ca.crt)"
    )
    parser.add_argument("--codec", choices=("pcma", "pcmu"), default="pcma", help="offer order")
    parser.add_argument("--domain", default=None, help="SIP domain (default: the server host)")
    parser.add_argument("--local-host", default=None, help="our address (default: auto)")
    parser.add_argument("--expires", type=int, default=300)
    parser.add_argument("--duration", type=float, default=5.0, help="seconds of audio (0 = ∞)")
    parser.add_argument("--answer-timeout", type=float, default=30.0)
    parser.add_argument("--wav", default=None, help="send this mono 16-bit WAV instead of a tone")
    parser.add_argument("--capture", default=None, help="write the received audio to this WAV")
    parser.add_argument("--headset", action="store_true", help="sox rec/play (bench only)")
    parser.add_argument("--unregister", action="store_true", help="unbind before exiting")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.headset and not (shutil.which("rec") and shutil.which("play")):
        print("error: --headset needs sox's `rec` and `play` on PATH", file=sys.stderr)
        return 2
    if args.headset and args.duration == 5.0:
        args.duration = 0.0
    password = read_env_value(args.password_env) or ""
    if not password:
        print(f"error: {args.password_env} is unset or empty", file=sys.stderr)
        return 2
    try:
        summary = asyncio.run(run(args, password))
    except KeyboardInterrupt:
        return 130
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        for key, value in summary.items():
            print(f"{key}: {value}")
    ok = summary.get("register") == 200 and (
        not (args.dial or args.answer) or (summary.get("call") or {}).get("final") == 200
    )
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())

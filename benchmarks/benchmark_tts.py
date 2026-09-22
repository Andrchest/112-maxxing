#!/usr/bin/env python
"""TTS benchmark (SPEC §25, §35, §40; HLD `60-inference-ops.md` §7.3).

Input `benchmarks/data/tts/lines.jsonl` — `{id, text, category}` with
`category ∈ {SHORT, MEDIUM, LONG, NUMERIC, ADDRESS}`, Russian caller-style lines.

Per sample: `first_audio_latency_ms` (request → first `TtsChunk`), `total_synthesis_latency_ms`,
`output_audio_ms`, `rtf`, `peak_vram_mb` (NVML every 100 ms around the call).
Cancellation sub-suite: `cancel_latency_ms`, `chunks_after_cancel` (must be 0 or 1) and
`alignment_is_exact`, measured on the `TtsStream.cancel()` seam — the same seam
`app.application.voice.tts_speech_sink.TtsSpeechSink` cancels a barge-in on (E14). The transport
half of a barge-in (clearing the outbound queue) is `benchmark_e2e.py`'s `cutoff_latency_ms`, so
the two scripts measure the two halves once each rather than both measuring a blurred sum.

`--tts-provider piper|qwen3_tts|chatterbox|fake`; run once per provider so they are comparable
(SPEC §25). `chatterbox` is `NOT_RUN` ("provider not implemented"); `qwen3_tts` talks to a worker
the *caller* started (`--tts-base-url`, default the settings' `http://127.0.0.1:8112`) and is
`NOT_RUN` with that URL in `reason` when it is not reachable — this script never starts a worker
and never signals one.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from _common import (
    Envelope,
    NvmlSampler,
    aggregate,
    elapsed_ms,
    finish,
    load_jsonl,
    load_profile_for_bench,
    not_run,
    parse_common_args,
    profile_config_subtree,
    resolve_model_path,
)

BENCHMARK = "tts"
DEFAULT_LINES = Path("benchmarks/data/tts/lines.jsonl")
DEFAULT_TTS_BASE_URL = "http://127.0.0.1:8112"


def _extra(parser: Any) -> None:
    parser.add_argument("--lines", type=Path, default=DEFAULT_LINES, help="lines.jsonl corpus")
    parser.add_argument(
        "--tts-provider",
        choices=("piper", "qwen3_tts", "chatterbox", "fake"),
        default=None,
        help="override the profile's tts.provider (default: the profile's, or `fake` with "
        "--provider fake)",
    )
    parser.add_argument(
        "--tts-base-url",
        default=DEFAULT_TTS_BASE_URL,
        help="Qwen3-TTS worker base URL (default: the settings' 8112 loopback)",
    )
    parser.add_argument("--voice", default=None, help="override the profile's voice_id / speaker")
    parser.add_argument(
        "--cancel-after-ms",
        type=int,
        default=120,
        help="cancellation sub-suite: cancel each stream this many ms after the first chunk",
    )
    parser.add_argument(
        "--no-cancel-suite", action="store_true", help="skip the cancellation sub-suite"
    )
    parser.add_argument(
        "--nvml", choices=("auto", "stub", "off"), default="auto", help="VRAM sampler (test-only)"
    )


async def _build_provider(args: Any, profile: Any, kind: str) -> tuple[Any, str | None]:
    """`(provider, not_run_reason)` — a `reason` means no provider could honestly be built."""
    if kind == "fake":
        from app.inference.tts.fake_tts import FakeTTS

        return FakeTTS(), None
    if kind == "chatterbox":
        return None, "Chatterbox Multilingual: provider not implemented in this repo (E20 list)"
    if kind == "piper":
        raw = profile.tts.fallback_model_path or profile.tts.model_path
        voice_path, exists = resolve_model_path(raw, args.models_root)
        if not exists:
            return None, f"Piper voice not found: {voice_path}"
        from app.inference.tts.piper_tts import PiperTTS

        return PiperTTS(voice_path=str(voice_path)), None
    from app.inference.tts.qwen3_tts import Qwen3TTS

    return (
        Qwen3TTS(
            base_url=args.tts_base_url,
            speaker=args.voice or profile.tts.voice_id,
        ),
        None,
    )


async def run(args: Any) -> Envelope:
    profile = load_profile_for_bench(args.profile)
    kind = args.tts_provider or ("fake" if args.provider == "fake" else profile.tts.provider)
    config = profile_config_subtree(profile, "tts")
    config.update(
        {
            "provider_mode": args.provider,
            "tts_provider": kind,
            "lines": str(args.lines),
            "cancel_after_ms": args.cancel_after_ms,
            "runs": args.runs,
            "seed": args.seed,
            "tag": args.tag,
        }
    )
    if kind == "qwen3_tts":
        config["tts_base_url"] = args.tts_base_url

    if not args.lines.is_file():
        return not_run(
            BENCHMARK, args.profile, f"lines corpus not found: {args.lines}", config=config
        )
    rows = load_jsonl(args.lines)
    if not rows:
        return not_run(
            BENCHMARK, args.profile, f"lines corpus is empty: {args.lines}", config=config
        )

    provider, reason = await _build_provider(args, profile, kind)
    if provider is None:
        return not_run(BENCHMARK, args.profile, reason or "no provider", config=config)

    sampler = NvmlSampler(stub=args.nvml == "stub") if args.nvml != "off" else None
    envelope = Envelope(
        benchmark=BENCHMARK,
        status="OK",
        profile=args.profile,
        config=config,
        hardware=sampler.hardware if sampler else {},
    )
    if sampler is not None:
        envelope.note(f"nvml_mode={sampler.mode}")
        sampler.start()

    try:
        await provider.warm_up()
    except Exception as exc:
        if sampler is not None:
            sampler.stop()
        where = args.tts_base_url if kind == "qwen3_tts" else kind
        return not_run(
            BENCHMARK,
            args.profile,
            f"{kind} warm-up failed ({where}): {type(exc).__name__}: {exc}",
            config=config,
            hardware=envelope.hardware,
        )

    try:
        max_chunk_ms = profile.tts.max_chunk_ms
        for run_index in range(max(1, args.runs)):
            for row in rows:
                envelope.samples.append(
                    await _synthesize(provider, row, run_index, max_chunk_ms, sampler)
                )
                if not args.no_cancel_suite:
                    envelope.samples.append(
                        await _cancel(provider, row, run_index, max_chunk_ms, args.cancel_after_ms)
                    )
    except Exception as exc:
        envelope.status = "FAILED"
        envelope.reason = f"{type(exc).__name__}: {exc}"
    finally:
        if sampler is not None:
            peak, count = sampler.stop()
            envelope.note(f"nvml_samples={count} peak_used_mb={peak}")
        await provider.close()

    if envelope.samples:
        envelope.aggregates = _aggregates(envelope.samples)
    elif envelope.status == "OK":
        envelope.status = "NOT_RUN"
        envelope.reason = "no sample produced a measurement"
    return envelope


async def _synthesize(
    provider: Any, row: dict[str, Any], run_index: int, max_chunk_ms: int, sampler: Any
) -> dict[str, Any]:
    from app.application.ports.tts import TtsVoiceSpec

    # `voice_id=""` (not `provider.provider_name`, e.g. "qwen3_tts") — a real `TtsVoiceSpec` names
    # a VOICE, not a provider. `Qwen3TTS.stream()` treats an empty `voice_id` as "use the speaker
    # I was constructed with" (`app.inference.tts.qwen3_tts`'s own fallback rule) and validates
    # anything non-empty against the four vendor speakers, so passing the provider's own name broke
    # every real Qwen3-TTS run with `ValueError: TtsVoiceSpec.voice_id='qwen3_tts' is not one of the
    # vendor speakers` (found running this script for real, E19-D). `PiperTTS`/`FakeTTS` never read
    # `voice.voice_id` at all, so this is safe for every provider.
    voice = TtsVoiceSpec(voice_id="", speaking_rate=1.0)
    request_id = f"bench-tts-{row['id']}-{run_index}"
    started = time.perf_counter()
    first_ms: float | None = None
    audio_ms = 0
    chunks = 0
    exact = True
    stream = provider.stream(
        str(row["text"]), voice, request_id=request_id, max_chunk_ms=max_chunk_ms
    )
    async for chunk in stream:
        if first_ms is None:
            first_ms = elapsed_ms(started)
        chunks += 1
        audio_ms += chunk.audio_ms
        exact = exact and chunk.alignment_is_exact
    total_ms = elapsed_ms(started)
    return {
        "id": row["id"],
        "run_index": run_index,
        "suite": "synthesis",
        "category": row.get("category", ""),
        "chars": len(str(row["text"])),
        "first_audio_latency_ms": round(first_ms, 3) if first_ms is not None else None,
        "total_synthesis_latency_ms": round(total_ms, 3),
        "output_audio_ms": audio_ms,
        "rtf": round(total_ms / audio_ms, 6) if audio_ms else None,
        "chunks": chunks,
        "alignment_is_exact": exact,
        "peak_vram_mb": sampler.peak_used_mb if sampler is not None else None,
        "provider": provider.provider_name,
        "model_version": provider.model_version,
    }


async def _cancel(
    provider: Any, row: dict[str, Any], run_index: int, max_chunk_ms: int, cancel_after_ms: int
) -> dict[str, Any]:
    """Cancel mid-stream and measure what the product's barge-in path would see (SPEC §18)."""
    from app.application.ports.tts import TtsVoiceSpec

    voice = TtsVoiceSpec(voice_id="", speaking_rate=1.0)  # see `_synthesize`'s comment
    request_id = f"bench-tts-cancel-{row['id']}-{run_index}"
    stream = provider.stream(
        str(row["text"]), voice, request_id=request_id, max_chunk_ms=max_chunk_ms
    )
    iterator = stream.__aiter__()
    first = await iterator.__anext__()
    await asyncio.sleep(cancel_after_ms / 1000.0)
    cancel_started = time.perf_counter()
    await stream.cancel()
    after = 0
    async for _chunk in iterator:
        after += 1
    cancel_latency_ms = elapsed_ms(cancel_started)
    return {
        "id": row["id"],
        "run_index": run_index,
        "suite": "cancellation",
        "category": row.get("category", ""),
        "cancel_latency_ms": round(cancel_latency_ms, 3),
        "chunks_after_cancel": after,
        "alignment_is_exact": first.alignment_is_exact,
        "provider": provider.provider_name,
        "model_version": provider.model_version,
    }


def _aggregates(samples: list[dict[str, Any]]) -> dict[str, Any]:
    synthesis = [s for s in samples if s["suite"] == "synthesis"]
    cancellation = [s for s in samples if s["suite"] == "cancellation"]
    by_category: dict[str, Any] = {}
    for sample in synthesis:
        by_category.setdefault(str(sample["category"]), []).append(sample)

    def slab(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "n": len(rows),
            "first_audio_latency_ms": aggregate(
                [
                    r["first_audio_latency_ms"]
                    for r in rows
                    if r["first_audio_latency_ms"] is not None
                ]
            ),
            "total_synthesis_latency_ms": aggregate(
                [r["total_synthesis_latency_ms"] for r in rows]
            ),
            "rtf": aggregate([r["rtf"] for r in rows if r["rtf"] is not None]),
            "peak_vram_mb_max": max(
                (r["peak_vram_mb"] for r in rows if r["peak_vram_mb"] is not None), default=None
            ),
        }

    aggregates: dict[str, Any] = {
        "overall": slab(synthesis),
        "by_category": {k: slab(v) for k, v in sorted(by_category.items())},
    }
    if cancellation:
        aggregates["cancellation"] = {
            "n": len(cancellation),
            "cancel_latency_ms": aggregate([r["cancel_latency_ms"] for r in cancellation]),
            "chunks_after_cancel_max": max(r["chunks_after_cancel"] for r in cancellation),
            "alignment_is_exact_all": all(r["alignment_is_exact"] for r in cancellation),
        }
    return aggregates


def main(argv: list[str] | None = None) -> int:
    args = parse_common_args(BENCHMARK, argv, extra=_extra, description=__doc__)
    envelope = asyncio.run(run(args))
    return finish(envelope, args.out)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())

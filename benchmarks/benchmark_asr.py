#!/usr/bin/env python
"""ASR benchmark (SPEC §19, §35, §40; HLD `60-inference-ops.md` §7.1).

Manifest-driven: every row of `benchmarks/data/asr/manifest.jsonl` names a 16 kHz mono WAV, its
reference transcript, its `category` (SHORT | MEDIUM | LONG | ADDRESS | NUMBER | TERMINOLOGY), its
`condition` (CLEAN | NOISY), its `duration_ms` and — additive (this epic's R5) — its `source`
(`piper:<voice>` for a synthesized item, `human:<who>` for a recorded one), so a reader can always
tell whether a WER figure measures GigaAM against a human voice or against Piper's pronunciation.

Per sample: `latency_ms`, `rtf` (= latency / duration), `wer`, `cer`, `entity_accuracy`.
Aggregates: overall, per `category × condition`, and per `source`.

`--provider real` loads `GigaAMProvider` through the `ASRProvider` port (SPEC §19: the benchmark
never names a model class in the measurement path either); `--provider fake` drives the D13
`FakeASR`, which replays the manifest's own references — a complete envelope, WER 0, no weights,
no GPU. That is the shape the gate exercises (`benchmarks/tests/`).

A missing corpus file or a missing model directory is an honest `NOT_RUN` with the path in
`reason` — never an estimate (SPEC §27).

**Shape warm-up (E19-B2).** `provider.warm_up()` only loads the model; it does not run a single
`transcribe()` call. On `--device cuda`, GigaAM's STFT front-end (`n_fft=320`, `gigaam_provider.py`)
goes through cuFFT, whose plan cache is keyed by input length: the *first* call at a given audio
duration pays a one-time plan-build cost roughly 10x a warm call at the same duration (measured:
E19-B2's report, `docs/benchmarks/asr.md` "E19-B2"), and every later call at that same duration is
fast. Because `benchmarks/data/asr/manifest.jsonl` is sorted `(category, condition, id)`, every
`CLEAN` item of a category is measured before its `NOISY` twin — which shares its exact
`duration_ms` (noise does not change a clip's length) — so, before this fix, every `CLEAN` bucket
silently absorbed the one-time per-shape cost and every `NOISY` bucket looked ~10x faster than
`CLEAN` for no acoustic reason at all (confirmed by an order-reversal experiment: swapping which
condition each category processes first flips which one looks "slow"). `_shape_warm_up()` runs one
untimed `transcribe()` per distinct `duration_ms` in the corpus, before the timed `--runs` loop —
so every shape is already warm by the time a sample is measured, regardless of manifest order, and
the reported `latency_ms`/`rtf` reflect steady-state decode cost for every category × condition
alike (the same state a `warmup.asr_sample_path`-prewarmed DEV profile would actually run in).

**Seeded shuffle (E19-B2, second half of the same fix).** Shape warm-up closed the *median* gap,
but a smaller tail asymmetry survived it: the manifest's fixed `(category, condition, id)` order
still puts every `CLEAN` item ahead of its `NOISY` twin, so within the timed loop a `NOISY` call is
always the one *closer* (fewer differently-shaped calls since the shape was last used) to its own
shape's previous occurrence. The timed loop therefore processes each `--runs` repetition of the
corpus in a `random.Random(--seed + run_index)`-shuffled order — deterministic and reproducible,
never literally random — so which condition is "the near one" for a given shape is randomised
rather than fixed by the manifest, and no `category × condition` bucket is structurally favoured.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import time
import wave
from pathlib import Path
from typing import Any

from _common import (
    Envelope,
    NvmlSampler,
    aggregate,
    cer,
    elapsed_ms,
    entity_accuracy,
    finish,
    load_jsonl,
    load_profile_for_bench,
    not_run,
    parse_common_args,
    profile_config_subtree,
    resolve_model_path,
    wer,
)

BENCHMARK = "asr"
DEFAULT_MANIFEST = Path("benchmarks/data/asr/manifest.jsonl")


def _extra(parser: Any) -> None:
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="corpus manifest (default: benchmarks/data/asr/manifest.jsonl)",
    )
    parser.add_argument(
        "--asr-provider",
        choices=("gigaam", "faster_whisper"),
        default="gigaam",
        help=(
            "gigaam (default) or faster_whisper — the optional SPEC §19 fallback, never fetched "
            "by this project (E12 ruling 4); selecting it always answers NOT_RUN unless "
            "--whisper-model-path/SIM_WHISPER_MODEL_PATH names a real model a developer supplied"
        ),
    )
    parser.add_argument(
        "--whisper-model-path",
        type=Path,
        default=None,
        help="a faster-whisper CTranslate2 model dir (default: $SIM_WHISPER_MODEL_PATH, unset)",
    )
    parser.add_argument(
        "--model-version",
        choices=("v3_e2e_ctc", "v3_ctc"),
        default=None,
        help="override the profile's asr.model_version (SPEC §19: both are benchmarked)",
    )
    parser.add_argument(
        "--device", choices=("cuda", "cpu"), default=None, help="override the profile's asr.device"
    )
    parser.add_argument(
        "--model-dir", type=Path, default=None, help="override the resolved GigaAM checkpoint dir"
    )


def _path_exists(raw: str | Path) -> bool:
    """Sync helper so the ASR-provider check can run under `asyncio.to_thread` (ruff ASYNC240:
    `run()` is async and must not block on a fresh `Path(...).exists()` call directly)."""
    return Path(raw).exists()


def read_wav(path: Path) -> tuple[bytes, int, int]:
    """`(pcm_s16le, sample_rate, duration_ms)` for a mono WAV.

    Raises on a file that is not 16-bit mono PCM — a corpus is never silently resampled.
    """
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit mono PCM")
        frames = handle.getnframes()
        rate = handle.getframerate()
        pcm = handle.readframes(frames)
    return pcm, rate, round(frames * 1000 / rate) if rate else 0


async def _build_provider(args: Any, profile: Any, model_dir: Path, references: list[str]) -> Any:
    if args.provider == "fake":
        from app.inference.asr.fake_asr import FakeASR

        return FakeASR(script=list(references))
    if args.asr_provider == "faster_whisper":
        # Reached only when `run()`'s early NOT_RUN check found a real
        # `--whisper-model-path`/`SIM_WHISPER_MODEL_PATH` (E12 ruling 4: never true on this
        # project's own dev machines so far, kept for a developer who supplies their own model).
        from app.inference.asr.faster_whisper_provider import FasterWhisperProvider

        return FasterWhisperProvider(
            model_path=str(args.whisper_model_path or os.environ.get("SIM_WHISPER_MODEL_PATH")),
            device=args.device or profile.asr.device,
        )
    from app.inference.asr.gigaam_provider import GigaAMProvider

    return GigaAMProvider(
        model_dir=str(model_dir),
        model_version=args.model_version or profile.asr.model_version,
        device=args.device or profile.asr.device,
        compute_type=profile.asr.compute_type,
    )


async def run(args: Any) -> Envelope:
    profile = load_profile_for_bench(args.profile)
    model_version = args.model_version or profile.asr.model_version
    device = args.device or profile.asr.device
    config = profile_config_subtree(profile, "asr")
    config.update(
        {
            "provider_mode": args.provider,
            "asr_provider": args.asr_provider,
            "model_version": model_version,
            "device": device,
            "manifest": str(args.manifest),
            "runs": args.runs,
            "seed": args.seed,
            "tag": args.tag,
        }
    )

    if args.provider == "real" and args.asr_provider == "faster_whisper":
        # SPEC §19's optional fallback. `FasterWhisperProvider` exists
        # (`app.inference.asr.faster_whisper_provider`) but this project has never fetched a
        # faster-whisper model (E12 ruling 4: "not fetched by this project at all") — a developer
        # who has their own CTranslate2 model can point `--whisper-model-path`/
        # `SIM_WHISPER_MODEL_PATH` at it; on this machine, as on every dev machine so far, neither
        # is set, so this is an honest NOT_RUN, never an estimate.
        whisper_path = args.whisper_model_path or os.environ.get("SIM_WHISPER_MODEL_PATH")
        whisper_path_exists = bool(whisper_path) and await asyncio.to_thread(
            _path_exists, whisper_path
        )
        if not whisper_path_exists:
            return not_run(
                BENCHMARK,
                args.profile,
                "faster-whisper: not installed by this project (E12 ruling 4) — "
                f"--whisper-model-path/SIM_WHISPER_MODEL_PATH not set to an existing path "
                f"(got: {whisper_path!r})",
                config=config,
            )
        config["whisper_model_path"] = str(whisper_path)

    if not args.manifest.is_file():
        return not_run(
            BENCHMARK, args.profile, f"manifest not found: {args.manifest}", config=config
        )
    rows = load_jsonl(args.manifest)
    if not rows:
        return not_run(
            BENCHMARK, args.profile, f"manifest is empty: {args.manifest}", config=config
        )

    base = args.manifest.parent
    missing = [row["path"] for row in rows if not (base / row["path"]).is_file()]
    if missing:
        return not_run(
            BENCHMARK,
            args.profile,
            f"{len(missing)} corpus file(s) missing, first: {base / missing[0]}",
            config=config,
        )

    model_dir: Path | None = None
    if args.provider == "real" and args.asr_provider == "gigaam":
        if args.model_dir is not None:
            model_dir, exists = args.model_dir, args.model_dir.exists()
        else:
            # The profile names the e2e checkpoint; `--model-version v3_ctc` needs the sibling dir.
            wanted = profile.asr.model_path.replace(
                profile.asr.model_version.replace("_", "-"), model_version.replace("_", "-")
            )
            model_dir, exists = resolve_model_path(wanted, args.models_root)
        if not exists:
            return not_run(
                BENCHMARK,
                args.profile,
                f"ASR model directory not found: {model_dir}",
                config=config,
            )
        config["model_dir"] = str(model_dir)

    envelope = Envelope(benchmark=BENCHMARK, status="OK", profile=args.profile, config=config)
    # HLD §7.0's envelope always carries `hardware:{gpu_name, driver, total_vram_mb}` — a single
    # instantaneous NVML/nvidia-smi read is enough here (unlike `benchmark_tts.py`/
    # `benchmark_vram.py`, `benchmark_asr.py` does not track a VRAM delta over time).
    sampler = NvmlSampler()
    envelope.hardware = sampler.hardware
    envelope.note(f"nvml_mode={sampler.mode}")
    references = [str(row["reference"]) for row in rows] * max(1, args.runs)
    provider = await _build_provider(args, profile, model_dir or Path("."), references)

    try:
        warm_started = time.perf_counter()
        await provider.warm_up()
        envelope.note(f"warm_up_ms={elapsed_ms(warm_started):.1f}")
        if args.provider == "real":
            shape_started = time.perf_counter()
            shape_n = await _shape_warm_up(provider, base, rows)
            envelope.note(
                f"shape_warmup_ms={elapsed_ms(shape_started):.1f} shape_warmup_n={shape_n} "
                "(E19-B2: one untimed transcribe() per distinct duration_ms before any timed "
                "sample — see benchmark_asr.py module docstring 'Shape warm-up')"
            )
        for run_index in range(max(1, args.runs)):
            # E19-B2: even after `_shape_warm_up`, this corpus's `(category, condition, id)`
            # manifest order still puts every CLEAN item of a category ahead of its NOISY twin —
            # a residual latency-tail asymmetry survived shape warm-up (measured: CLEAN samples
            # over 100 ms far outnumbered NOISY ones even though the medians matched), most
            # plausibly explained by a same-shape allocation/plan-cache growing "cooler" the more
            # differently-shaped calls intervene since it was last used, which the fixed manifest
            # order always puts more of before a CLEAN item than before its NOISY twin. A seeded
            # per-run shuffle (`--seed`, R1's "seed for every random choice") gives CLEAN and
            # NOISY an equal, randomised chance of being "the near one" or "the far one" for a
            # given shape, so no `category × condition` bucket is systematically favoured or
            # penalised — aggregates stay honest without hiding the genuine tail variance.
            # `--provider fake` is scoped out: `FakeASR` replays its script by call *order*
            # (`benchmarks/tests/`'s gate contract), so shuffling here would pair the wrong
            # scripted reference with the wrong row — pointless anyway, since a fake provider has
            # no shape-dependent cache to be honest about.
            if args.provider == "real":
                traversal = list(rows)
                random.Random(args.seed + run_index).shuffle(traversal)
            else:
                traversal = rows
            for row in traversal:
                sample = await _one(provider, base, row, run_index)
                envelope.samples.append(sample)
    except Exception as exc:
        envelope.status = "FAILED"
        envelope.reason = f"{type(exc).__name__}: {exc}"
    finally:
        with_close = getattr(provider, "close", None)
        if with_close is not None:
            await with_close()

    if envelope.samples:
        envelope.aggregates = _aggregates(envelope.samples)
    elif envelope.status == "OK":
        envelope.status = "NOT_RUN"
        envelope.reason = "no sample produced a measurement"
    return envelope


async def _shape_warm_up(provider: Any, base: Path, rows: list[dict[str, Any]]) -> int:
    """One untimed `transcribe()` per distinct `duration_ms` in the corpus, discarded — see the
    module docstring's "Shape warm-up" section for why this exists (E19-B2). Returns the count of
    distinct shapes warmed. A failure here is not fatal to the benchmark: it only means the first
    timed sample of that shape pays the cold cost instead, which the benchmark would have measured
    honestly anyway before this fix existed — never worth turning a whole run `FAILED` over."""
    seen: set[int] = set()
    warmed = 0
    for row in rows:
        duration_ms = int(row.get("duration_ms") or 0)
        if duration_ms in seen:
            continue
        seen.add(duration_ms)
        try:
            pcm, rate, _ = read_wav(base / row["path"])
            await provider.transcribe(pcm, rate, request_id=f"bench-asr-shape-warmup-{row['id']}")
            warmed += 1
        except Exception:
            # A warm-up failure must not hide the real measurement that follows it.
            continue
    return warmed


async def _one(provider: Any, base: Path, row: dict[str, Any], run_index: int) -> dict[str, Any]:
    pcm, rate, wav_duration_ms = read_wav(base / row["path"])
    duration_ms = int(row.get("duration_ms") or wav_duration_ms)
    request_id = f"bench-asr-{row['id']}-{run_index}"
    started = time.perf_counter()
    result = await provider.transcribe(pcm, rate, request_id=request_id)
    latency_ms = elapsed_ms(started)
    reference = str(row["reference"])
    return {
        "id": row["id"],
        "run_index": run_index,
        "category": row.get("category", ""),
        "condition": row.get("condition", ""),
        "source": row.get("source", ""),
        "duration_ms": duration_ms,
        "latency_ms": round(latency_ms, 3),
        "rtf": round(latency_ms / duration_ms, 6) if duration_ms else None,
        "wer": round(wer(reference, result.text), 6),
        "cer": round(cer(reference, result.text), 6),
        "entity_accuracy": entity_accuracy(reference, result.text),
        "provider": result.provider,
        "model_version": result.model_version,
        "hypothesis": result.text,
        "reference": reference,
    }


def _slice(samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n": len(samples),
        "latency_ms": aggregate([s["latency_ms"] for s in samples]),
        "rtf": aggregate([s["rtf"] for s in samples if s["rtf"] is not None]),
        "wer": aggregate([s["wer"] for s in samples]),
        "cer": aggregate([s["cer"] for s in samples]),
        "entity_accuracy": aggregate(
            [s["entity_accuracy"] for s in samples if s["entity_accuracy"] is not None]
        ),
    }


def _aggregates(samples: list[dict[str, Any]]) -> dict[str, Any]:
    by_category_condition: dict[str, Any] = {}
    by_source: dict[str, Any] = {}
    for sample in samples:
        by_category_condition.setdefault(f"{sample['category']}/{sample['condition']}", []).append(
            sample
        )
        by_source.setdefault(str(sample["source"]), []).append(sample)
    return {
        "overall": _slice(samples),
        "by_category_condition": {k: _slice(v) for k, v in sorted(by_category_condition.items())},
        "by_source": {k: _slice(v) for k, v in sorted(by_source.items())},
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_common_args(BENCHMARK, argv, extra=_extra, description=__doc__)
    envelope = asyncio.run(run(args))
    return finish(envelope, args.out)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())

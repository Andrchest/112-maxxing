#!/usr/bin/env python
"""Builds `benchmarks/data/asr/{clean,noisy}/**/*.wav` + `manifest.jsonl` from `texts.jsonl`
(SPEC §19, §40; HLD `60-inference-ops.md` §7.1; this epic's R5).

Deterministic and seeded, CPU only, no GPU lock needed:

1. Every row of `texts.jsonl` (`{id, category, text}`) is synthesized once with Piper
   (`ru_RU-irina-medium.onnx`, CPU) into a 16 kHz mono 16-bit PCM WAV under `clean/<category>/`.
   This script calls the raw `piper-tts` package directly (`piper.PiperVoice.load()` +
   `.synthesize()`), the same entry point `benchmarks/data/warmup/build_warmup.py` (E19-F) uses —
   **not** the product's async `PiperTTS` adapter (`backend/app/inference/tts/piper_tts.py`),
   which exists to be driven from an `asyncio` event loop inside the voice pipeline and would add
   nothing here beyond an `asyncio.run()` wrapper around the exact same two calls. Documented per
   this task's brief ("say which"). **`ru_RU-irina-medium` synthesizes at 22050 Hz, not 16 kHz**
   (its own `.onnx.json` `audio.sample_rate`, measured) — `GigaAMProvider` requires exactly
   16000 Hz (`ValueError: GigaAMProvider needs 16000 Hz`, hit and fixed by this task). This script
   therefore resamples every synthesized clip with the product's own
   `app.application.voice.resampler.Resampler` (D1: reuse, not reimplement — the same linear
   interpolation the live pipeline itself uses on inbound transport audio), run once over the
   whole clip as a single `AudioFrame` rather than the streaming per-frame path the live pipeline
   drives it from.
2. A `noisy/<category>/` twin of every synthesized item is built by mixing the clean waveform with
   seeded Gaussian noise at a fixed SNR (`--snr-db`, default 10 dB — SPEC §40 "clean/noisy
   samples"), computed from *that item's own* RMS via `noise_rms = signal_rms / 10**(snr_db/20)`,
   `numpy.random.default_rng(seed)` so re-running this script reproduces byte-identical noise.
   Piper's own synthesis is **not** bit-reproducible (`build_warmup.py`'s docstring: VITS's
   noise-scale RNG lives inside the ONNX graph, not on a Python-seedable path) — the seed here
   governs corpus order, the noise layer and nothing about the ONNX inference itself, and this
   script is `--seed`-deterministic in every respect *it* controls, documented rather than claiming
   more.
3. The one human recording, `backend/tests/models/assets/ru_sample.wav` (GigaAM's own published
   example, MIT licence — see that directory's `README.md`), is copied into `clean/long/` with its
   published transcript as `reference`, `source: "human:gigaam-sample"`, and no synthesized `noisy`
   twin (this script does not alter a licensed recording; a human `NOISY` sample is exactly the kind
   of contribution `README.md` "how to add a human recording" describes).
4. `manifest.jsonl` is written with rows `{id, path, reference, category, condition, duration_ms,
   source}`, `path` relative to `benchmarks/data/asr/` — `benchmark_asr.py`'s own contract.

Usage: `uv run python benchmarks/data/asr/build_corpus.py [--voice-path PATH] [--seed N]
[--snr-db N] [--out DIR]`
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
DEFAULT_VOICE_PATH = _REPO_ROOT / "models" / "piper" / "ru_RU-irina-medium.onnx"
DEFAULT_TEXTS_PATH = _HERE / "texts.jsonl"
DEFAULT_OUT_DIR = _HERE
HUMAN_SAMPLE_SRC = _REPO_ROOT / "backend" / "tests" / "models" / "assets" / "ru_sample.wav"
# The published transcript for this exact recording (`backend/tests/models/assets/README.md`,
# GigaAM's own `colab_example.ipynb`) — copied verbatim, not re-derived.
HUMAN_SAMPLE_REFERENCE = (
    "ничьих не требуя похвал счастлив уж я надеждой сладкой что дева с трепетом любви "
    "посмотрит может быть украдкой на песни грешные мои у лукоморья дуб зеленый"
)
HUMAN_SAMPLE_ID = "long_human_01"

SEED = 20260922
SNR_DB = 10.0


def load_texts(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


TARGET_SAMPLE_RATE = 16_000


def _resample_16k(pcm: bytes, source_rate: int) -> bytes:
    """`pcm` (16-bit mono PCM at `source_rate`) resampled to `TARGET_SAMPLE_RATE` with the
    product's own `Resampler` (D1: reuse, not reimplement) — the exact linear-interpolation method
    the live pipeline applies to inbound transport audio, run once over the whole clip as a single
    `AudioFrame` rather than the streaming per-frame path the pipeline drives it through."""
    if source_rate == TARGET_SAMPLE_RATE:
        return pcm
    from app.application.ports.call_transport import AudioFrame
    from app.application.voice.resampler import Resampler

    # A small `frame_samples` keeps the un-drained remainder `flush()` zero-pads to well under
    # 10 ms of silence, regardless of the clip's length.
    resampler = Resampler(target_sample_rate=TARGET_SAMPLE_RATE, frame_samples=160)
    frame = AudioFrame(
        pcm=pcm,
        sample_rate=source_rate,
        num_channels=1,
        samples_per_channel=len(pcm) // 2,
        capture_offset_ms=0,
    )
    frames = resampler.process(frame) + resampler.flush()
    return b"".join(f.pcm for f in frames)


def synth_clean(voice: Any, text: str) -> tuple[bytes, int]:
    """`(pcm_s16le, sample_rate)` for one Piper synthesis, resampled to `TARGET_SAMPLE_RATE`
    (R5: "16 kHz mono int16 WAV") if the voice's native rate differs. Raises on a synthesis
    failure — a corpus item that could not be built is never silently skipped."""
    pieces = [chunk.audio_int16_bytes for chunk in voice.synthesize(text)]
    pcm = b"".join(pieces)
    native_rate = int(voice.config.sample_rate)
    return _resample_16k(pcm, native_rate), TARGET_SAMPLE_RATE


def mix_noise(pcm: bytes, *, snr_db: float, rng: np.random.Generator) -> bytes:
    """Adds seeded Gaussian noise to 16-bit mono PCM at `snr_db` (computed from this item's own
    RMS), clipped to the int16 range. Silence (RMS 0) is returned unchanged — there is no signal
    to set an SNR against."""
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    signal_rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
    if signal_rms <= 0.0:
        return pcm
    noise_rms = signal_rms / (10.0 ** (snr_db / 20.0))
    noise = rng.normal(loc=0.0, scale=noise_rms, size=samples.shape)
    mixed = np.clip(samples + noise, -32768, 32767).astype("<i2")
    return mixed.tobytes()


def write_wav(path: Path, pcm: bytes, sample_rate: int) -> int:
    """Writes 16-bit mono PCM; returns the duration in whole milliseconds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    n_samples = len(pcm) // 2
    return round(n_samples * 1000 / sample_rate) if sample_rate else 0


def read_wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
    return round(frames * 1000 / rate) if rate else 0


def build(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not args.voice_path.is_file():
        raise FileNotFoundError(
            f"Piper voice not found: {args.voice_path} — run `make models-piper` first"
        )
    from piper import PiperVoice

    voice = PiperVoice.load(str(args.voice_path), str(args.voice_path) + ".json")
    rows = load_texts(args.texts)
    rng = np.random.default_rng(args.seed)

    manifest: list[dict[str, Any]] = []
    for row in rows:
        category = str(row["category"])
        item_id = str(row["id"])
        text = str(row["text"])
        pcm, sample_rate = synth_clean(voice, text)

        clean_rel = f"clean/{category.lower()}/{item_id}.wav"
        clean_path = args.out / clean_rel
        duration_ms = write_wav(clean_path, pcm, sample_rate)
        manifest.append(
            {
                "id": item_id,
                "path": clean_rel,
                "reference": text,
                "category": category,
                "condition": "CLEAN",
                "duration_ms": duration_ms,
                "source": f"piper:{args.voice_path.stem}",
            }
        )

        noisy_pcm = mix_noise(pcm, snr_db=args.snr_db, rng=rng)
        noisy_rel = f"noisy/{category.lower()}/{item_id}.wav"
        noisy_path = args.out / noisy_rel
        noisy_duration_ms = write_wav(noisy_path, noisy_pcm, sample_rate)
        manifest.append(
            {
                "id": item_id,
                "path": noisy_rel,
                "reference": text,
                "category": category,
                "condition": "NOISY",
                "duration_ms": noisy_duration_ms,
                "source": f"piper:{args.voice_path.stem}",
            }
        )

    if not args.no_human_sample:
        if not HUMAN_SAMPLE_SRC.is_file():
            raise FileNotFoundError(f"human sample not found: {HUMAN_SAMPLE_SRC}")
        human_rel = "clean/long/long_human_01.wav"
        human_path = args.out / human_rel
        human_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HUMAN_SAMPLE_SRC, human_path)
        manifest.append(
            {
                "id": HUMAN_SAMPLE_ID,
                "path": human_rel,
                "reference": HUMAN_SAMPLE_REFERENCE,
                "category": "LONG",
                "condition": "CLEAN",
                "duration_ms": read_wav_duration_ms(human_path),
                "source": "human:gigaam-sample",
            }
        )

    manifest.sort(key=lambda row: (row["category"], row["condition"], row["id"]))
    return manifest


def write_manifest(manifest: list[dict[str, Any]], path: Path) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in manifest), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice-path", type=Path, default=DEFAULT_VOICE_PATH, dest="voice_path")
    parser.add_argument("--texts", type=Path, default=DEFAULT_TEXTS_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--snr-db", type=float, default=SNR_DB, dest="snr_db")
    parser.add_argument(
        "--no-human-sample",
        action="store_true",
        help="skip copying backend/tests/models/assets/ru_sample.wav (for a quick dry run)",
    )
    args = parser.parse_args(argv)

    manifest = build(args)
    write_manifest(manifest, args.out / "manifest.jsonl")
    by_cat: dict[str, int] = {}
    for row in manifest:
        by_cat[f"{row['category']}/{row['condition']}"] = (
            by_cat.get(f"{row['category']}/{row['condition']}", 0) + 1
        )
    print(f"wrote {len(manifest)} manifest rows to {args.out / 'manifest.jsonl'}", file=sys.stderr)
    for key in sorted(by_cat):
        print(f"  {key}: {by_cat[key]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

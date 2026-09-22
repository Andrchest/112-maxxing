"""Builds `benchmarks/data/e2e/turns.jsonl` + its WAVs — the trainee-side turns
`benchmarks/benchmark_e2e.py` plays into the pipeline (E19-E, HLD 60 §7.4, SPEC §40).

Nine turns of the demo scenario `scenarios/examples/apartment-fire/v1` in the order a real
System-112 interview takes them: greeting, address, what is burning, victims, floor, apartment
number, phone confirmation, a reassurance and a closing. Two of them carry `interrupt_after_ms`,
which is what puts them in `benchmark_e2e.py`'s barge-in sub-suite — the trainee starts talking
that many milliseconds after the caller's first audio, and the benchmark reports
`cutoff_latency_ms` against `50-voice-pipeline.md` §6.2's 250 ms budget.

**The audio is Piper's, not a human's.** `ru_RU-irina-medium` on CPU synthesizes every line, so an
end-to-end number measured with this corpus measures the pipeline against Piper's pronunciation of
dispatcher Russian, not against human variation — exactly the caveat `README.md` beside this file
states. Adding a human recording is a two-step change (drop a 16 kHz mono WAV in `wav/`, add its
row), and no code here needs to know.

Piper's voice runs at 22 050 Hz; the pipeline's format is 16 kHz mono s16le
(`VoiceTurnConfig.sample_rate`). The conversion goes through the product's own
`app.application.voice.resampler.Resampler` rather than a second resampler written here, so the
samples the VAD and GigaAM see in a benchmark are produced by the same code path that carries a
real LiveKit call's audio (§3.1).

Not byte-for-byte reproducible: Piper's VITS graph draws its noise inside the ONNX graph, so a
`numpy.random.seed()` here cannot pin it — the same reason
`benchmarks/data/warmup/build_warmup.py` documents. `SEED` is kept for whatever is numpy-side and
the committed WAVs are a one-time build output; what matters and is checked is the format
(16 kHz mono 16-bit), the per-file and total size budget, and that every manifest row resolves.

Usage: `uv run python benchmarks/data/e2e/build_turns.py [--voice-path PATH] [--out-dir DIR]`
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

DEFAULT_VOICE_PATH = _REPO_ROOT / "models" / "piper" / "ru_RU-irina-medium.onnx"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent
SEED = 1206
TARGET_SAMPLE_RATE = 16_000
#: R7's committed budget for this corpus ("Turn WAVs ... <= 3 MB committed").
MAX_TOTAL_BYTES = 3 * 1024 * 1024

#: `source` for every row: the manifest says plainly who produced the audio (R5's honesty rule,
#: applied to the E2E corpus too). A human recording dropped in later carries `human:<who>`.
SOURCE = "piper:ru_RU-irina-medium"

#: The turns. Each line is deliberately ONE breath group with no internal punctuation: Piper puts
#: a real pause at a comma or a sentence break, and a pause longer than the profile's
#: `endpoint_silence_ms` (320 ms on DEV_3060TI*) makes the VAD end the turn there and start
#: another — which is correct behaviour, but it turns one scripted turn into two and leaves the
#: second one talking over the caller's answer.
#:
#: `text` is the trainee's (the operator's) line — this corpus is the trainee side of
#: the call; the caller's answers come from the scenario through the dialogue chain, never from
#: here. Vocabulary is the demo scenario's own (улица Николаева, дом 27, квартира 45, 4-й/5-й
#: этаж, +7 910 123-45-67), so the ASR stage is asked the addresses and numbers the assessment
#: rules actually score.
TURNS: tuple[dict[str, object], ...] = (
    {
        "id": "greeting",
        "text": "Служба сто двенадцать что у вас случилось?",
    },
    {
        "id": "address",
        "text": "Назовите улицу и номер дома",
    },
    {
        "id": "what_is_burning",
        "text": "Что именно горит в квартире?",
    },
    {
        "id": "victims",
        "text": "В квартире остались люди?",
    },
    {
        # Barge-in: the operator cuts in while the caller is still describing the building.
        "id": "floor",
        "text": "На каком этаже квартира?",
        "interrupt_after_ms": 400,
    },
    {
        "id": "apartment",
        "text": "Назовите номер квартиры",
    },
    {
        "id": "phone_confirm",
        "text": "Подтвердите ваш номер телефона",
    },
    {
        # Barge-in: the operator talks over a frightened caller to calm them down.
        "id": "reassurance",
        "text": "Пожарные уже выехали оставайтесь на связи",
        "interrupt_after_ms": 700,
    },
    {
        "id": "closing",
        "text": "Информация принята в квартиру не заходите",
    },
)


def _synthesize(voice: object, text: str) -> tuple[bytes, int]:
    """One Piper synthesis: `(pcm s16le, sample_rate)` at the voice's own rate."""
    pcm = b"".join(chunk.audio_int16_bytes for chunk in voice.synthesize(text))  # type: ignore[attr-defined]
    return pcm, int(voice.config.sample_rate)  # type: ignore[attr-defined]


def _to_16k_mono(pcm: bytes, source_rate: int) -> bytes:
    """Piper's 22 050 Hz mono to the pipeline's 16 kHz mono, through the product's `Resampler`.

    Reusing `app.application.voice.resampler.Resampler` (rather than writing a second
    interpolator here) means the benchmark corpus is shaped by the same downmix → linear
    interpolation → peak-normalise chain a real call's audio goes through (§3.1), so a latency
    measured on it is not measured on audio the product would never see.
    """
    from app.application.ports.call_transport import AudioFrame
    from app.application.voice.resampler import Resampler

    samples = len(pcm) // 2
    resampler = Resampler(target_sample_rate=TARGET_SAMPLE_RATE, frame_samples=512)
    frames = resampler.process(
        AudioFrame(
            pcm=pcm,
            sample_rate=source_rate,
            num_channels=1,
            samples_per_channel=samples,
            capture_offset_ms=0,
        )
    )
    frames.extend(resampler.flush())
    return b"".join(frame.pcm for frame in frames)


def _write_wav(path: Path, pcm: bytes) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(TARGET_SAMPLE_RATE)
        handle.writeframes(pcm)
    return len(pcm) / 2 / TARGET_SAMPLE_RATE


def build(voice_path: Path, out_dir: Path) -> list[dict[str, object]]:
    """Synthesize every turn, write `wav/<id>.wav` and return the manifest rows."""
    json_path = voice_path.with_suffix(voice_path.suffix + ".json")
    if not voice_path.is_file() or not json_path.is_file():
        raise FileNotFoundError(
            f"Piper voice not found: {voice_path} (+ {json_path.name}) — "
            "run `make models-piper` first"
        )
    np.random.seed(SEED)  # best-effort; see the module docstring

    from piper import PiperVoice

    voice = PiperVoice.load(str(voice_path), str(json_path))
    rows: list[dict[str, object]] = []
    total = 0
    for turn in TURNS:
        relative = f"wav/{turn['id']}.wav"
        pcm, rate = _synthesize(voice, str(turn["text"]))
        converted = _to_16k_mono(pcm, rate)
        duration_s = _write_wav(out_dir / relative, converted)
        total += len(converted)
        row: dict[str, object] = {
            "id": turn["id"],
            "text": turn["text"],
            "path": relative,
            "duration_ms": round(duration_s * 1000),
            "source": SOURCE,
        }
        if "interrupt_after_ms" in turn:
            row["interrupt_after_ms"] = turn["interrupt_after_ms"]
        rows.append(row)
    if total > MAX_TOTAL_BYTES:
        raise ValueError(
            f"the corpus is {total / 1024 / 1024:.2f} MiB of PCM, over the 3 MiB budget (R7) — "
            "shorten a line or drop a turn"
        )
    manifest = out_dir / "turns.jsonl"
    manifest.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice-path", type=Path, default=DEFAULT_VOICE_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    rows = build(args.voice_path, args.out_dir)
    total_ms = sum(int(row["duration_ms"]) for row in rows)  # type: ignore[call-overload]
    print(
        f"wrote {len(rows)} turn(s) to {args.out_dir / 'turns.jsonl'} "
        f"({total_ms / 1000:.1f}s total, seed={SEED}, voice={args.voice_path.name})"
    )
    for row in rows:
        interrupt = row.get("interrupt_after_ms")
        marker = f"  interrupt_after_ms={interrupt}" if interrupt is not None else ""
        print(f"  {row['id']:<16} {int(row['duration_ms']) / 1000:5.2f}s{marker}")  # type: ignore[call-overload]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

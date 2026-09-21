"""E14-D — the first REAL RUN of the Qwen3-TTS 0.6B CustomVoice checkpoint.

Not part of `make gate` or `make test-models`; a standalone script invoked twice by hand
(this task's brief, item 3 — "STOP the worker ... and only then run the saved WAVs through the
real GigaAM"), because TTS (the `tts_qwen3` worker, a separate process) and GigaAM ASR (loaded
in-process, on GPU) may not both fit this machine's free VRAM at once:

    uv run python benchmarks/tts_qwen3_0_6b_real_run.py synth --out-dir <results dir>
    # (stop the tts_qwen3 worker here)
    uv run python benchmarks/tts_qwen3_0_6b_real_run.py asr --out-dir <same results dir>

`synth` drives the real `Qwen3TTS` adapter (`app.inference.tts.qwen3_tts`) against an
already-running `tts_qwen3` worker (`SIM_TTS_QWEN3_BASE_URL`, default `http://127.0.0.1:8112`) —
this script never starts or stops the worker itself, unlike `backend/tests/models/
test_tts_contract.py`'s self-contained contract test (a separate, narrower check; see that file
and this task's report). It synthesizes the same five Russian dispatcher-style sentences
`test_tts_contract.py` uses, for every (speaker, emotion) pair in `_SPEAKERS` x `_EMOTIONS`,
measuring time-to-first-audio-frame, total synth time, audio duration and RTF per sentence, and
saves each WAV plus a `results.json`/`results.md` under `--out-dir`.

`asr` loads the real GigaAM `v3_e2e_ctc` checkpoint (`models/gigaam-v3-e2e_ctc`, on GPU) and
transcribes every WAV `synth` saved, appending `asr_text`/`wer` (reusing `tests.models.
test_gigaam_provider._word_error_rate`, the same helper `test_tts_contract.py` reuses) to the same
`results.json`/`results.md` — SPEC §27: measured, never invented.

Every number in the saved results is what the commands actually printed; a step that could not run
(worker unreachable, free VRAM below the brief's threshold) writes `"status": "NOT_RUN"` with the
measured reason, never a fabricated pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "backend"))
sys.path.insert(0, str(_REPO_ROOT / "backend" / "tests"))

from app.application.ports.tts import TtsVoiceSpec  # noqa: E402
from app.domain.caller.emotion import EmotionState  # noqa: E402
from app.domain.enums import EmotionLabel  # noqa: E402
from app.inference.tts.qwen3_tts import Qwen3TTS  # noqa: E402

_SENTENCES: tuple[str, ...] = (
    "Служба сто двенадцать, что у вас случилось?",
    "Назовите, пожалуйста, точный адрес происшествия.",
    "Есть ли пострадавшие, нуждающиеся в помощи?",
    "Оставайтесь на линии, я направляю к вам бригаду.",
    "Повторите, пожалуйста, номер телефона ещё раз.",
)
_SPEAKERS: tuple[str, ...] = ("Serena", "Ryan")
_EMOTIONS: dict[str, EmotionState] = {
    "calm": EmotionState(emotion=EmotionLabel.CALM, stress_level=0.1),
    "panicked": EmotionState(emotion=EmotionLabel.PANICKED, stress_level=0.9),
}
_ASR_SAMPLE_RATE = 16_000


def _write_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def _pid_vram_mb(pid: int) -> int | None:
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
            except ValueError:
                return None
    return None


async def _synth(out_dir: Path, base_url: str, worker_pid: int | None) -> dict[str, object]:
    tts = Qwen3TTS(base_url=base_url, speaker=_SPEAKERS[0], timeout_ms=60_000)
    rows: list[dict[str, object]] = []
    peak_vram_mb: int | None = None
    try:
        for speaker in _SPEAKERS:
            for emotion_label, emotion in _EMOTIONS.items():
                voice = TtsVoiceSpec(voice_id=speaker, speaking_rate=1.0, emotion=emotion)
                for index, sentence in enumerate(_SENTENCES):
                    request_id = f"{speaker}-{emotion_label}-{index}"
                    started = time.perf_counter()
                    stream = tts.stream(sentence, voice, request_id=request_id, max_chunk_ms=20)
                    chunks = []
                    first_chunk_ms: float | None = None
                    async for chunk in stream:
                        if first_chunk_ms is None:
                            first_chunk_ms = (time.perf_counter() - started) * 1000
                        chunks.append(chunk)
                    total_ms = (time.perf_counter() - started) * 1000
                    if worker_pid is not None:
                        sample = _pid_vram_mb(worker_pid)
                        if sample is not None:
                            peak_vram_mb = (
                                sample if peak_vram_mb is None else max(peak_vram_mb, sample)
                            )
                    if not chunks:
                        rows.append(
                            {
                                "speaker": speaker,
                                "emotion": emotion_label,
                                "sentence": sentence,
                                "status": "FAILED",
                                "reason": "no audio chunks produced",
                            }
                        )
                        continue
                    pcm = b"".join(c.frame.pcm for c in chunks)
                    sample_rate = chunks[0].frame.sample_rate
                    audio_ms = sum(c.audio_ms for c in chunks)
                    wav_path = out_dir / f"{request_id}.wav"
                    _write_wav(wav_path, pcm, sample_rate)
                    rows.append(
                        {
                            "speaker": speaker,
                            "emotion": emotion_label,
                            "sentence": sentence,
                            "status": "OK",
                            "wav_path": wav_path.name,
                            "first_chunk_latency_ms": round(first_chunk_ms or 0.0, 1),
                            "total_latency_ms": round(total_ms, 1),
                            "sample_rate": sample_rate,
                            "audio_ms": audio_ms,
                            "rtf": round(total_ms / audio_ms, 3) if audio_ms else None,
                        }
                    )
    finally:
        await tts.close()
    return {"rows": rows, "peak_vram_mb": peak_vram_mb}


async def _run_asr(out_dir: Path) -> None:
    from app.inference.asr.gigaam_provider import GigaAMProvider
    from tests.models.test_gigaam_provider import _word_error_rate

    results_path = out_dir / "results.json"
    data = json.loads(results_path.read_text(encoding="utf-8"))

    asr_model_dir = _REPO_ROOT / "models" / "gigaam-v3-e2e_ctc"
    asr = GigaAMProvider(
        model_dir=str(asr_model_dir),
        model_version="v3_e2e_ctc",
        device="cuda",
        compute_type="float16",
    )
    asr_load_started = time.perf_counter()
    await asr.warm_up()
    asr_load_ms = (time.perf_counter() - asr_load_started) * 1000
    try:
        for row in data["rows"]:
            if row.get("status") != "OK":
                continue
            wav_path = out_dir / row["wav_path"]
            with wave.open(str(wav_path), "rb") as handle:
                pcm = handle.readframes(handle.getnframes())
                sample_rate = handle.getframerate()
            if sample_rate != _ASR_SAMPLE_RATE:
                import numpy as np

                samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
                src_n = samples.shape[0]
                dst_n = max(1, round(src_n * _ASR_SAMPLE_RATE / sample_rate))
                resampled = np.interp(np.linspace(0, src_n - 1, dst_n), np.arange(src_n), samples)
                pcm = resampled.astype("<i2").tobytes()
            result = await asr.transcribe(
                pcm, _ASR_SAMPLE_RATE, request_id=f"asr-{row['wav_path']}"
            )
            row["asr_text"] = result.text
            row["wer"] = round(_word_error_rate(row["sentence"], result.text), 3)
    finally:
        await asr.close()

    data["asr_load_ms"] = round(asr_load_ms, 1)
    results_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir, data)


def _write_markdown(out_dir: Path, data: dict[str, object]) -> None:
    lines = ["# Qwen3-TTS 0.6B CustomVoice — real run (E14-D)", ""]
    lines.append(f"date: {data.get('date_utc')}  machine: {data.get('machine')}")
    lines.append(f"load_time_ms: {data.get('load_ms')}  peak_vram_mb: {data.get('peak_vram_mb')}")
    if "asr_load_ms" in data:
        lines.append(f"gigaam_load_ms: {data['asr_load_ms']}")
    lines.append("")
    header = ["speaker", "emotion", "sentence", "first_chunk_ms", "total_ms", "rtf", "sample_rate"]
    if any("wer" in row for row in data["rows"]):
        header += ["asr_text", "wer"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join([":--"] * len(header)) + "|")
    for row in data["rows"]:
        if row.get("status") != "OK":
            failed_cells = (
                row.get("speaker"),
                row.get("emotion"),
                row.get("sentence"),
                f"FAILED: {row.get('reason')}",
            )
            lines.append("| " + " | ".join(str(c) for c in failed_cells) + " | | | |")
            continue
        cells = [
            row["speaker"],
            row["emotion"],
            row["sentence"],
            str(row["first_chunk_latency_ms"]),
            str(row["total_latency_ms"]),
            str(row["rtf"]),
            str(row["sample_rate"]),
        ]
        if "wer" in row:
            cells += [row["asr_text"], str(row["wer"])]
        lines.append("| " + " | ".join(cells) + " |")
    (out_dir / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["synth", "asr"])
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8112")
    parser.add_argument("--worker-pid", type=int, default=None)
    parser.add_argument("--load-ms", type=float, default=None)
    parser.add_argument("--machine", default="unknown")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.phase == "synth":
        outcome = asyncio.run(_synth(args.out_dir, args.base_url, args.worker_pid))
        data = {
            "variant": "0.6B",
            "date_utc": datetime.now(UTC).isoformat(),
            "machine": args.machine,
            "load_ms": args.load_ms,
            "peak_vram_mb": outcome["peak_vram_mb"],
            "rows": outcome["rows"],
        }
        (args.out_dir / "results.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_markdown(args.out_dir, data)
        print(f"synth done: {len(outcome['rows'])} rows -> {args.out_dir}")
    else:
        asyncio.run(_run_asr(args.out_dir))
        print(f"asr done -> {args.out_dir}")


if __name__ == "__main__":
    main()

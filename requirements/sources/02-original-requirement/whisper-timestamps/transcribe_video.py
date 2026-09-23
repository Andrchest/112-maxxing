#!/usr/bin/env python3
"""Transcribe the downloaded video with faster-whisper and create timestamped outputs."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from faster_whisper import WhisperModel

VIDEO = Path("/home/andreipc/everything/Город 9. Департамент по делам гражданской обороны.mp4")
BASE = VIDEO.with_suffix("")
MODEL_ID = "deepdml/faster-whisper-large-v3-turbo-ct2"


def srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds_:02d},{millis:03d}"


def vtt_time(seconds: float) -> str:
    return srt_time(seconds).replace(",", ".")


def main() -> int:
    if not VIDEO.exists():
        print(f"Video not found: {VIDEO}", file=sys.stderr)
        return 2

    print(f"Loading {MODEL_ID} on CUDA (FP16)...", flush=True)
    model = WhisperModel(
        MODEL_ID,
        device="cuda",
        device_index=0,
        compute_type="float16",
        cpu_threads=4,
        num_workers=1,
    )

    print("Transcribing...", flush=True)
    started = time.monotonic()
    segments, info = model.transcribe(
        str(VIDEO),
        task="transcribe",
        language=None,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        word_timestamps=True,
        condition_on_previous_text=True,
        chunk_length=30,
    )

    srt_tmp = BASE.with_suffix(".srt.part")
    vtt_tmp = BASE.with_suffix(".vtt.part")
    txt_tmp = BASE.with_suffix(".txt.part")
    json_tmp = BASE.with_suffix(".json.part")
    records: list[dict] = []
    count = 0

    with (
        srt_tmp.open("w", encoding="utf-8") as srt,
        vtt_tmp.open("w", encoding="utf-8") as vtt,
        txt_tmp.open("w", encoding="utf-8") as txt,
    ):
        vtt.write("WEBVTT\n\n")
        for segment in segments:
            count += 1
            text = segment.text.strip()
            srt.write(f"{count}\n{srt_time(segment.start)} --> {srt_time(segment.end)}\n{text}\n\n")
            vtt.write(f"{vtt_time(segment.start)} --> {vtt_time(segment.end)}\n{text}\n\n")
            txt.write(text + "\n")
            records.append(
                {
                    "id": segment.id,
                    "start": segment.start,
                    "end": segment.end,
                    "text": text,
                    "avg_logprob": segment.avg_logprob,
                    "no_speech_prob": segment.no_speech_prob,
                    "words": [
                        {
                            "start": word.start,
                            "end": word.end,
                            "word": word.word,
                            "probability": word.probability,
                        }
                        for word in (segment.words or [])
                    ],
                }
            )
            if count % 25 == 0:
                elapsed = time.monotonic() - started
                print(f"segments={count}, audio={segment.end:.1f}s, elapsed={elapsed:.0f}s", flush=True)

    metadata = {
        "video": str(VIDEO),
        "model": MODEL_ID,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "duration_after_vad": info.duration_after_vad,
        "segments": records,
    }
    with json_tmp.open("w", encoding="utf-8") as output_json:
        json.dump(metadata, output_json, ensure_ascii=False, indent=2)

    os.replace(srt_tmp, BASE.with_suffix(".srt"))
    os.replace(vtt_tmp, BASE.with_suffix(".vtt"))
    os.replace(txt_tmp, BASE.with_suffix(".txt"))
    os.replace(json_tmp, BASE.with_suffix(".json"))

    elapsed = time.monotonic() - started
    print(f"Done: {count} segments, language={info.language}, elapsed={elapsed:.0f}s", flush=True)
    print(f"SRT:  {BASE.with_suffix('.srt')}", flush=True)
    print(f"VTT:  {BASE.with_suffix('.vtt')}", flush=True)
    print(f"TXT:  {BASE.with_suffix('.txt')}", flush=True)
    print(f"JSON: {BASE.with_suffix('.json')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

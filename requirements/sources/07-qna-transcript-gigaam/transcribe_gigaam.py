#!/usr/bin/env python3
"""Transcribe the video with the locally cached GigaAM v3 e2e-CTC model."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import torch

MODEL_DIR = Path("/home/andreipc/112-maxxing/models/gigaam-v3-e2e_ctc")
VIDEO = Path("/home/andreipc/everything/Город 9. Департамент по делам гражданской обороны.mp4")
BASE = VIDEO.parent / f"{VIDEO.stem}.gigaam"
SAMPLE_RATE = 16_000
CHUNK_SECONDS = 22
BATCH_SIZE = 4


def srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds_:02d},{millis:03d}"


def main() -> int:
    if not VIDEO.exists() or not MODEL_DIR.exists():
        print("Video or local GigaAM model is missing", file=sys.stderr)
        return 2

    sys.path.insert(0, str(MODEL_DIR))
    from modeling_gigaam import GigaAMModel, load_audio

    print("Loading local GigaAM v3 e2e-CTC on CUDA...", flush=True)
    model = GigaAMModel.from_pretrained(str(MODEL_DIR)).cuda().eval()
    print("Loading and resampling audio...", flush=True)
    audio = load_audio(str(VIDEO))
    duration = audio.numel() / SAMPLE_RATE
    chunk_samples = CHUNK_SECONDS * SAMPLE_RATE
    total_chunks = (audio.numel() + chunk_samples - 1) // chunk_samples
    print(f"Audio: {duration:.1f}s, chunks: {total_chunks}, batch: {BATCH_SIZE}", flush=True)

    results: list[dict] = []
    started = time.monotonic()
    for batch_start in range(0, total_chunks, BATCH_SIZE):
        chunks = []
        lengths = []
        ranges = []
        for chunk_index in range(batch_start, min(batch_start + BATCH_SIZE, total_chunks)):
            start_sample = chunk_index * chunk_samples
            end_sample = min(start_sample + chunk_samples, audio.numel())
            chunk = audio[start_sample:end_sample]
            chunks.append(chunk)
            lengths.append(chunk.numel())
            ranges.append((start_sample / SAMPLE_RATE, end_sample / SAMPLE_RATE))

        max_length = max(lengths)
        batch = torch.zeros(len(chunks), max_length, dtype=audio.dtype)
        for index, chunk in enumerate(chunks):
            batch[index, : chunk.numel()] = chunk
        batch = batch.cuda(non_blocking=True)
        length_tensor = torch.tensor(lengths, device="cuda", dtype=torch.long)

        with torch.inference_mode():
            encoded, encoded_len = model.model.forward(batch, length_tensor)
            texts = model.model.decoding.decode(model.model.head, encoded, encoded_len)

        for (start, end), text in zip(ranges, texts):
            text = " ".join(text.split())
            if text:
                results.append({"start": start, "end": end, "text": text})

        done = min(batch_start + BATCH_SIZE, total_chunks)
        elapsed = time.monotonic() - started
        print(f"chunks={done}/{total_chunks}, audio={ranges[-1][1]:.1f}s, elapsed={elapsed:.1f}s", flush=True)

    srt_tmp = BASE.with_suffix(".srt.part")
    txt_tmp = BASE.with_suffix(".txt.part")
    json_tmp = BASE.with_suffix(".json.part")
    with srt_tmp.open("w", encoding="utf-8") as srt, txt_tmp.open("w", encoding="utf-8") as txt:
        for index, item in enumerate(results, start=1):
            srt.write(f"{index}\n{srt_time(item['start'])} --> {srt_time(item['end'])}\n{item['text']}\n\n")
            txt.write(item["text"] + "\n")

    metadata = {
        "video": str(VIDEO),
        "model": "GigaAM v3 e2e-CTC (local)",
        "model_dir": str(MODEL_DIR),
        "duration": duration,
        "chunk_seconds": CHUNK_SECONDS,
        "timestamp_granularity": "chunk boundaries",
        "segments": results,
    }
    with json_tmp.open("w", encoding="utf-8") as output_json:
        json.dump(metadata, output_json, ensure_ascii=False, indent=2)

    srt_tmp.replace(BASE.with_suffix(".srt"))
    txt_tmp.replace(BASE.with_suffix(".txt"))
    json_tmp.replace(BASE.with_suffix(".json"))
    elapsed = time.monotonic() - started
    print(f"Done: {len(results)} segments, elapsed={elapsed:.1f}s", flush=True)
    print(f"SRT: {BASE.with_suffix('.srt')}", flush=True)
    print(f"TXT: {BASE.with_suffix('.txt')}", flush=True)
    print(f"JSON: {BASE.with_suffix('.json')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

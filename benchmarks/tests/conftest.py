"""Gate-side fixtures for the five SPEC §35 benchmark scripts (E19-A, this epic's R2).

These tests run every script's `main()` with `--provider fake` into a tmp directory and assert the
**shape** of what came out: the HLD §7.0 envelope's keys, the CSV header, `status: "OK"`, and the
`NOT_RUN`/`FAILED` honesty rules. They never assert a *number* — a fake provider's latency is not
a measurement and this directory must never be mistaken for one.

Nothing here is marked `requires_models`: the whole directory is gate-side, needs no GPU, no model
file, no network and no running server (D13).

`benchmarks/` goes on `sys.path` because the scripts import each other as top-level modules
(`from _common import ...`), which is how they behave when run as
`uv run python benchmarks/benchmark_asr.py`. There is deliberately **no** `__init__.py` in this
directory: `backend/tests/` is already an importable package named `tests`, and a second one would
collide under xdist's import machinery.
"""

from __future__ import annotations

import json
import math
import struct
import sys
import wave
from pathlib import Path

import pytest

BENCHMARKS_DIR = Path(__file__).resolve().parent.parent
if str(BENCHMARKS_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_DIR))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def write_wav(path: Path, *, duration_ms: int = 500, sample_rate: int = 16_000) -> None:
    """A 16 kHz mono 16-bit tone — enough audio for the VAD to see one turn."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = (sample_rate * duration_ms) // 1000
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(
            b"".join(
                struct.pack("<h", int(9000 * math.sin(2 * math.pi * 220 * n / sample_rate)))
                for n in range(frames)
            )
        )


@pytest.fixture
def asr_corpus(tmp_path: Path) -> Path:
    """A two-item ASR manifest + its WAVs, in the HLD §7.1 tree shape (R5's `source` included)."""
    root = tmp_path / "asr"
    rows = [
        {
            "id": "addr_001",
            "path": "clean/addr_001.wav",
            "reference": "улица Ленина дом двадцать семь квартира пять",
            "category": "ADDRESS",
            "condition": "CLEAN",
            "duration_ms": 500,
            "source": "piper:ru_RU-irina-medium",
        },
        {
            "id": "num_001",
            "path": "noisy/num_001.wav",
            "reference": "пострадавших трое",
            "category": "NUMBER",
            "condition": "NOISY",
            "duration_ms": 500,
            "source": "human:gigaam-sample",
        },
    ]
    for row in rows:
        write_wav(root / row["path"])
    manifest = root / "manifest.jsonl"
    manifest.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    return manifest


@pytest.fixture
def tts_corpus(tmp_path: Path) -> Path:
    rows = [
        {"id": "short_001", "text": "Пожар в квартире.", "category": "SHORT"},
        {"id": "addr_001", "text": "Улица Ленина, дом 27.", "category": "ADDRESS"},
    ]
    path = tmp_path / "lines.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    return path


@pytest.fixture
def e2e_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "e2e"
    write_wav(root / "clean" / "turn_001.wav", duration_ms=900)
    path = root / "turns.jsonl"
    path.write_text(
        json.dumps({"id": "turn_001", "path": "clean/turn_001.wav"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def llm_corpora() -> tuple[Path, Path]:
    """The committed fixture corpora (`benchmarks/tests/fixtures/`), not `benchmarks/data/`."""
    return (
        FIXTURES / "interpreter_cases.jsonl",
        FIXTURES / "dialogue_cases.jsonl",
    )

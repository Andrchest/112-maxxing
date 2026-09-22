#!/usr/bin/env python
"""Convert `benchmarks/interpreter_eval/ru_operator_utterances.yaml` into the JSONL corpus
`benchmark_llm.py --suite interpreter` reads (E19, ruling R6).

The YAML is the hand-labelled eval set E13-B3 built and measured; it stays the single source of
truth for the labels. This converter is deterministic and lossless: every one of its items becomes
one JSONL row with its `id`, `utterance`, `expected` block, its `uncertain` flag and its `notes`
copied **verbatim** — nothing is re-labelled, dropped or reordered here. The `scenario` key of the
YAML document is carried on the first row, which is where `benchmark_llm.py` reads it from.

Run it from the repository root:

    uv run python benchmarks/data/llm/convert_interpreter_cases.py

It rewrites `benchmarks/data/llm/interpreter_cases.jsonl` in place and prints the row count plus
the number of `uncertain` rows, so a reviewer can check both against the YAML.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "benchmarks" / "interpreter_eval" / "ru_operator_utterances.yaml"
TARGET = REPO_ROOT / "benchmarks" / "data" / "llm" / "interpreter_cases.jsonl"

#: The key order every row is written with (stable output, reviewable diffs).
FIELDS = ("id", "scenario", "utterance", "expected", "uncertain", "notes")


def convert(source: Path = SOURCE) -> list[dict[str, Any]]:
    """Return the JSONL rows for `source`, in the YAML's own order."""
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    scenario = str(document["scenario"])
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(document["items"]):
        row: dict[str, Any] = {
            "id": str(item["id"]),
            "utterance": str(item["utterance"]),
            "expected": item["expected"],
        }
        # `benchmark_llm.py` reads the scenario off the first row only; carrying it on every row
        # would invite the two copies to drift.
        if index == 0:
            row["scenario"] = scenario
        if item.get("uncertain"):
            row["uncertain"] = True
        if item.get("notes"):
            row["notes"] = " ".join(str(item["notes"]).split())
        rows.append({key: row[key] for key in FIELDS if key in row})
    return rows


def main() -> int:
    rows = convert()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    uncertain = sum(1 for row in rows if row.get("uncertain"))
    print(f"{TARGET.relative_to(REPO_ROOT)}: {len(rows)} rows, {uncertain} uncertain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fenced-yaml-block extraction from `docs/hld/30-scenario-format.md`, used by this package's
tests so that no YAML example is retyped into a test file (task brief E3-D). Same mechanism as
`tests/unit/domain/world/_yaml_examples.py` (kept as a separate module so each test package under
`backend/tests/unit/domain/{world,scoring}/**` stays self-contained, per the task brief's FILES
list).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# backend/tests/unit/domain/scoring/_yaml_examples.py -> repo root is 5 parents up.
SCENARIO_FORMAT_DOC = Path(__file__).resolve().parents[5] / "docs" / "hld" / "30-scenario-format.md"

_FENCE_RE = re.compile(r"```yaml\n(.*?)```", re.DOTALL)


def extract_yaml_blocks(heading: str, doc_path: Path = SCENARIO_FORMAT_DOC) -> list[Any]:
    """Return one parsed object per ```yaml fenced block under the Markdown line `heading`.

    `heading` must match a full heading line exactly (e.g. "## 30.7 `scoring_rules`"). The section
    runs until the next heading whose `#` level is <= that heading's level; `#`-prefixed lines
    *inside* a fence (YAML comments) do not count as headings.
    """
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    start = None
    level = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            level = len(line) - len(line.lstrip("#"))
            break
    if start is None or level is None:
        raise AssertionError(f"heading {heading!r} not found in {doc_path}")

    end = len(lines)
    in_fence = False
    for j in range(start, len(lines)):
        current = lines[j]
        if current.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if current.startswith("#"):
            current_level = len(current) - len(current.lstrip("#"))
            if current_level <= level:
                end = j
                break

    section = "\n".join(lines[start:end])
    return [yaml.safe_load(block) for block in _FENCE_RE.findall(section)]

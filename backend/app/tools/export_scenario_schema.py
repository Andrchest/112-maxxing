"""`python -m app.tools.export_scenario_schema [--check] [--path FILE]` — JSON Schema export (D4).

Writes the JSON Schema of `ScenarioVersion` to `scenarios/schemas/scenario_version.schema.json`.
The output is deterministic — sorted keys, two-space indent, one trailing newline — so a rebuild of
an unchanged model is a byte-identical file and `git diff` stays empty.

`--check` does not write: it exits 1 when the committed file is missing or differs from what the
current models would produce, which is the staleness check `make scenarios` runs (D4,
`30-scenario-format.md` §30.1).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.domain.scenario.version import ScenarioVersion

DEFAULT_SCHEMA_PATH = Path("scenarios/schemas/scenario_version.schema.json")


def render_schema() -> str:
    """The canonical, byte-stable JSON Schema document for `ScenarioVersion`."""
    schema = ScenarioVersion.model_json_schema(mode="validation")
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_schema(), encoding="utf-8")


def check_schema(path: Path) -> list[str]:
    """Return the reasons `path` is stale (empty list = up to date)."""
    if not path.is_file():
        return [f"{path} does not exist; run `python -m app.tools.export_scenario_schema`"]
    if path.read_text(encoding="utf-8") != render_schema():
        return [f"{path} is stale; run `python -m app.tools.export_scenario_schema`"]
    return []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Export the ScenarioVersion JSON Schema (D4)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 when the committed schema differs from the models",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help=f"schema file to write or check (default: {DEFAULT_SCHEMA_PATH})",
    )
    args = parser.parse_args(argv)
    path: Path = args.path

    if args.check:
        problems = check_schema(path)
        for problem in problems:
            print(problem)
        if problems:
            return 1
        print(f"OK {path} is up to date")
        return 0

    write_schema(path)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

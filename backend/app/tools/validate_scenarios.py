"""`python -m app.tools.validate_scenarios [dir]` — scenario file validation CLI.

In E2 this only checks that each `scenarios/examples/**/v*.yaml` file parses as YAML and prints one
PASS/FAIL line per file. Real load-time validation (SPEC §4-§6, D4) is TODO(E3), behind
`validate_file`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

DEFAULT_SCENARIOS_DIR = Path("scenarios/examples")


def validate_file(path: Path) -> list[str]:
    """Return the list of validation errors for one scenario file (empty = valid).

    In E2 this only checks that the file parses as YAML. TODO(E3): full load-time validation per
    D4 (fact model cross-references, role_chain registration, scoring rules, event graph cycles,
    etc. — SPEC §4-§6).
    """
    try:
        with path.open(encoding="utf-8") as f:
            yaml.safe_load(f)
    except yaml.YAMLError as exc:
        return [f"{path}: {exc}"]
    return []


def main(argv: list[str]) -> int:
    scenarios_dir = Path(argv[0]) if argv else DEFAULT_SCENARIOS_DIR
    files = sorted(scenarios_dir.glob("**/v*.yaml"))

    if not files:
        print("0 scenario files")
        return 0

    exit_code = 0
    for path in files:
        errors = validate_file(path)
        if errors:
            exit_code = 1
            print(f"FAIL {path}")
            for error in errors:
                print(f"  {error}")
        else:
            print(f"PASS {path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

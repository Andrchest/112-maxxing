"""`python -m app.tools.validate_scenarios [dir]` — scenario load-time validation CLI (D4).

Runs the full §30.8 validation of `30-scenario-format.md` over every `<slug>/v<N>.yaml` file under
the given directory (default `scenarios/examples`). Prints one `PASS`/`FAIL` line per file, every
violation of a failing file (each prefixed with its `R<nn>:` rule number) and every non-fatal
warning, and exits 1 if any file fails — or if the directory holds no scenario at all, since
`make scenarios` must not go green on an empty or mistyped path.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.domain.common.errors import ScenarioValidationError
from app.domain.scenario.validation import scenario_version_warnings
from app.infrastructure.scenarios.yaml_loader import discover, load_scenario_version

DEFAULT_SCENARIOS_DIR = Path("scenarios/examples")


def validate_file(path: Path) -> list[str]:
    """Return every validation violation for one scenario file (empty list = valid)."""
    try:
        load_scenario_version(path)
    except ScenarioValidationError as exc:
        return list(exc.violations)
    return []


def warnings_for(path: Path) -> list[str]:
    """Non-fatal warnings for a file that validates; empty for a file that does not."""
    try:
        version = load_scenario_version(path)
    except ScenarioValidationError:
        return []
    return scenario_version_warnings(version)


def main(argv: list[str]) -> int:
    scenarios_dir = Path(argv[0]) if argv else DEFAULT_SCENARIOS_DIR
    files = discover(scenarios_dir)

    if not files:
        print(f"FAIL {scenarios_dir}: no <slug>/v<N>.yaml scenario file found")
        return 1

    exit_code = 0
    for path in files:
        violations = validate_file(path)
        if violations:
            exit_code = 1
            print(f"FAIL {path}")
            for violation in violations:
                print(f"  {violation}")
            continue
        print(f"PASS {path}")
        for warning in warnings_for(path):
            print(f"  WARN {warning}")

    print(f"{len(files)} scenario file(s) checked")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Loading scenario YAML files from disk (HLD `30-scenario-format.md`, D2, D4).

`scenarios/examples/<slug>/v<N>.yaml`, one file per version (D4). This module owns the I/O and the
path convention; parsing and the thirty load-time rules belong to `app.domain.scenario`.

HLD gap — "the slug in the file must match the path": the SPEC §4 top-level key list (and therefore
`ScenarioVersion`) has no `slug` key at all — the slug identifies the owning `Scenario` (§10.15),
which lives in its own type and its own table (D4). The only path/content agreement a version file
can express is its `version` number against the `v<N>.yaml` file name, which is what
`load_scenario_version` enforces; `scenario_slug(path)` exposes the directory-derived slug for the
importer (`app.application.scenarios.import_scenarios`) that creates the `Scenario` row.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from app.domain.common.errors import ScenarioValidationError
from app.domain.scenario.validation import validate_scenario_document
from app.domain.scenario.version import ScenarioVersion

VERSION_FILE_PATTERN = re.compile(r"^v(?P<version>\d+)\.yaml$")

__all__ = ["VERSION_FILE_PATTERN", "discover", "load_scenario_version", "scenario_slug"]


def discover(root: Path) -> list[Path]:
    """Every `<slug>/v<N>.yaml` file under `root`, sorted by (slug, version)."""
    found: list[tuple[str, int, Path]] = []
    for path in root.glob("*/v*.yaml"):
        match = VERSION_FILE_PATTERN.match(path.name)
        if match is None or not path.is_file():
            continue
        found.append((path.parent.name, int(match.group("version")), path))
    return [path for _slug, _version, path in sorted(found)]


def scenario_slug(path: Path) -> str:
    """The owning `Scenario`'s slug for a `<slug>/v<N>.yaml` file: its directory name."""
    return path.parent.name


def load_scenario_version(path: Path) -> ScenarioVersion:
    """Load, parse and fully validate one scenario file (§30.1, §30.8).

    Raises `ScenarioValidationError` whose `violations` lists every problem found: an unreadable or
    malformed YAML file, a file name that does not follow `v<N>.yaml`, a `version` key that does
    not match that file name, and every §30.8 rule the document breaks.
    """
    violations = list(_path_violations(path))
    document = _load_yaml(path, violations)
    if document is None:
        raise ScenarioValidationError(violations)

    violations.extend(validate_scenario_document(document))
    violations.extend(_version_mismatch(path, document))
    if violations:
        raise ScenarioValidationError(sorted(violations))
    return ScenarioVersion.model_validate(document)


def _path_violations(path: Path) -> list[str]:
    if VERSION_FILE_PATTERN.match(path.name) is None:
        return [f"path: {path.name!r} is not a 'v<N>.yaml' scenario version file"]
    return []


def _load_yaml(path: Path, violations: list[str]) -> Mapping[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except OSError as exc:
        violations.append(f"path: cannot read {path}: {exc}")
        return None
    except yaml.YAMLError as exc:
        violations.append(f"yaml: {path} is not valid YAML: {exc}")
        return None
    if not isinstance(document, Mapping):
        violations.append(f"yaml: {path} must contain a mapping at the top level")
        return None
    return document


def _version_mismatch(path: Path, document: Mapping[str, Any]) -> list[str]:
    match = VERSION_FILE_PATTERN.match(path.name)
    if match is None:
        return []
    expected = int(match.group("version"))
    declared = document.get("version")
    if declared != expected:
        return [
            f"path: file {path.name!r} declares version {declared!r}, "
            f"expected {expected} from the file name"
        ]
    return []

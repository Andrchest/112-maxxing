#!/usr/bin/env python3
"""Import-boundary checker (D2).

Stdlib `ast` only — no third-party dependency, so it can run before `uv sync` even completes and
inside any layer's own test suite. It walks every `.py` file under `backend/`, `workers/`, and
`benchmarks/` (skipping ignored directories such as `.venv`) and reports every import that
violates the table in `docs/hld/00-decisions.md` D2.

CLI: `python backend/tools/check_imports.py [--root DIR]` (default: the repository root, resolved
from this file's location). Prints one `file:line: <layer> must not import <module>` line per
violation and exits 1 if there is at least one; exits 0 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------------------------
# Rules as data (D2). Order matters: rules are applied most-specific-first and, for a given
# forbidden module prefix, the first matching rule's label wins — later, broader rules (the
# "any app.*" wildcard, or the global "(anywhere)" rule) are skipped for a prefix a more specific
# rule already covers for that file.
# --------------------------------------------------------------------------------------------

# Package roots this checker understands, relative to `--root`, and the dotted-module prefix each
# one corresponds to.
PACKAGE_ROOTS: list[tuple[Path, str]] = [
    (Path("backend/app"), "app"),
    (Path("workers/voice_agent/voice_agent"), "voice_agent"),
]

# Directories under `--root` that are scanned at all (everything else — frontend/, docs/,
# scenarios/, infra/, .git, .venv, node_modules, ... — is ignored).
SCAN_DIRS: list[str] = ["backend", "workers", "benchmarks"]

# Directory names skipped anywhere in the walk.
IGNORED_DIR_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".git",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
    }
)


def _in_package(target: str, prefix: str) -> bool:
    """True if dotted module `target` is `prefix` itself or lives inside it."""
    return target == prefix or target.startswith(prefix + ".")


def _is_app(mod: str | None) -> bool:
    return mod is not None and _in_package(mod, "app")


def _is_domain(mod: str | None) -> bool:
    return mod is not None and _in_package(mod, "app.domain")


def _is_application(mod: str | None) -> bool:
    return mod is not None and _in_package(mod, "app.application")


#: The composition root (D2, D8). Every layered design needs exactly one module that imports both
#: `app.application` and `app.infrastructure` — that is what "wiring" *is* — and naming it here is
#: how the rule stays a rule instead of becoming a convention. The allowance is for this one
#: module, by exact dotted name: no other module under `app.api` may import `app.infrastructure`,
#: `app.db` or a vendor SDK, and `backend/tests/unit/test_check_imports.py` asserts that the
#: allowance is exactly one name long.
COMPOSITION_ROOT = "app.api.container"


def _is_api(mod: str | None) -> bool:
    return mod is not None and _in_package(mod, "app.api") and mod != COMPOSITION_ROOT


def _is_voice_agent_transport(mod: str | None) -> bool:
    return mod is not None and _in_package(mod, "voice_agent.transport")


def _is_voice_agent_non_transport(mod: str | None) -> bool:
    return (
        mod is not None
        and _in_package(mod, "voice_agent")
        and not _in_package(mod, "voice_agent.transport")
    )


def _anywhere(_mod: str | None) -> bool:
    return True


@dataclass(frozen=True)
class LayerRule:
    label: str
    applies_to: Callable[[str | None], bool]
    forbidden: tuple[str, ...]


RULES: list[LayerRule] = [
    LayerRule(
        label="app.domain",
        applies_to=_is_domain,
        forbidden=(
            "fastapi",
            "starlette",
            "sqlalchemy",
            "alembic",
            "redis",
            "livekit",
            "httpx",
            "asyncpg",
            "uvicorn",
            "app.application",
            "app.api",
            "app.infrastructure",
            "app.inference",
            "app.db",
            "time",
        ),
    ),
    LayerRule(
        label="app.application",
        applies_to=_is_application,
        forbidden=(
            "fastapi",
            "starlette",
            "sqlalchemy",
            "alembic",
            "redis",
            "livekit",
            "httpx",
            "asyncpg",
            "app.api",
            "app.infrastructure",
            "app.inference",
            "app.db",
        ),
    ),
    LayerRule(
        label="app.api",
        applies_to=_is_api,
        forbidden=("sqlalchemy", "livekit", "app.db", "app.inference"),
    ),
    LayerRule(
        label="app",
        applies_to=_is_app,
        forbidden=("livekit", "voice_agent", "openai", "anthropic"),
    ),
    LayerRule(
        label="voice_agent.transport",
        applies_to=_is_voice_agent_transport,
        forbidden=("openai", "anthropic"),
    ),
    LayerRule(
        label="voice_agent",
        applies_to=_is_voice_agent_non_transport,
        forbidden=("livekit", "openai", "anthropic"),
    ),
    LayerRule(
        label="(anywhere)",
        applies_to=_anywhere,
        forbidden=("openai", "anthropic"),
    ),
]

# Randomness rule (D2/D7): only `app.domain` is restricted, and it has an exception the generic
# forbidden-prefix table above cannot express, so it is handled separately below. The only
# allowed form is `from random import Random`.
RANDOM_MODULE = "random"
RANDOM_ALLOWED_NAME = "Random"


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str

    def render(self, relative_to: Path) -> str:
        try:
            shown = self.path.relative_to(relative_to)
        except ValueError:
            shown = self.path
        return f"{shown}:{self.line}: {self.message}"


def iter_python_files(root: Path) -> Iterator[Path]:
    for scan_dir_name in SCAN_DIRS:
        scan_dir = root / scan_dir_name
        if not scan_dir.is_dir():
            continue
        yield from _walk(scan_dir)


def _walk(directory: Path) -> Iterator[Path]:
    for entry in sorted(directory.iterdir()):
        if entry.is_dir():
            if entry.name in IGNORED_DIR_NAMES or entry.name.endswith(".egg-info"):
                continue
            yield from _walk(entry)
        elif entry.suffix == ".py":
            yield entry


def module_and_package(path: Path, root: Path) -> tuple[str | None, str | None]:
    """Return (dotted module name, dotted package name) for `path`, or (None, None).

    `None` means the file is not under a recognized package root (`PACKAGE_ROOTS`); it is still
    scanned for the global "(anywhere)" rule, just not for layer-specific rules or the randomness
    rule (which only applies inside `app.domain`).
    """
    for base_dir, package_prefix in PACKAGE_ROOTS:
        base = root / base_dir
        try:
            rel = path.relative_to(base)
        except ValueError:
            continue
        parts = list(rel.parts)
        is_init = parts[-1] == "__init__.py"
        mod_parts = parts[:-1] if is_init else [*parts[:-1], parts[-1][: -len(".py")]]
        module_name = ".".join([package_prefix, *mod_parts]) if mod_parts else package_prefix
        if is_init:
            package_name = module_name
        elif parts[:-1]:
            package_name = ".".join([package_prefix, *parts[:-1]])
        else:
            package_name = package_prefix
        return module_name, package_name
    return None, None


def _resolve_from_import(node: ast.ImportFrom, package: str | None) -> str | None:
    """Resolve `from X import ...` (X possibly relative) to an absolute dotted module or None."""
    if node.level == 0:
        return node.module
    if package is None:
        return node.module
    package_parts = package.split(".")
    keep = max(0, len(package_parts) - (node.level - 1))
    base_parts = package_parts[:keep]
    if node.module:
        base_parts = [*base_parts, node.module]
    return ".".join(base_parts) if base_parts else None


def _merged_forbidden(module_name: str | None) -> dict[str, str]:
    """Merge forbidden-prefix -> layer-label for every rule that applies to `module_name`."""
    merged: dict[str, str] = {}
    for rule in RULES:
        if not rule.applies_to(module_name):
            continue
        for prefix in rule.forbidden:
            merged.setdefault(prefix, rule.label)
    return merged


def _forbidden_violation(
    path: Path, line: int, imported: str, forbidden: dict[str, str]
) -> Violation | None:
    for prefix, label in forbidden.items():
        if _in_package(imported, prefix):
            return Violation(path, line, f"{label} must not import {imported}")
    return None


def check_file(path: Path, root: Path) -> list[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Violation(path, 1, f"could not read file: {exc}")]

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [Violation(path, exc.lineno or 1, f"could not parse file: {exc.msg}")]

    module_name, package_name = module_and_package(path, root)
    forbidden = _merged_forbidden(module_name)
    is_domain = _is_domain(module_name)

    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if is_domain and _in_package(alias.name, RANDOM_MODULE):
                    violations.append(
                        Violation(
                            path,
                            node.lineno,
                            f"app.domain must not import {alias.name} "
                            f"(only `from random import {RANDOM_ALLOWED_NAME}` is allowed)",
                        )
                    )
                    continue
                violation = _forbidden_violation(path, node.lineno, alias.name, forbidden)
                if violation is not None:
                    violations.append(violation)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_from_import(node, package_name)
            if resolved is None:
                continue
            if is_domain and resolved == RANDOM_MODULE:
                for alias in node.names:
                    if alias.name != RANDOM_ALLOWED_NAME:
                        violations.append(
                            Violation(
                                path,
                                node.lineno,
                                f"app.domain must not import {RANDOM_MODULE}.{alias.name} "
                                f"(only `from random import {RANDOM_ALLOWED_NAME}` is allowed)",
                            )
                        )
                continue
            violation = _forbidden_violation(path, node.lineno, resolved, forbidden)
            if violation is not None:
                violations.append(violation)

    return violations


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="D2 import-boundary checker")
    default_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--root", type=Path, default=default_root)
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()

    violations: list[Violation] = []
    for path in iter_python_files(root):
        violations.extend(check_file(path, root))

    violations.sort(key=lambda v: (str(v.path), v.line, v.message))
    for violation in violations:
        print(violation.render(root))

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

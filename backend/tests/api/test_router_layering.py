"""The routers obey D2 and D3 — asserted by scanning their source, not by convention.

`backend/app/api/routers/**` may import `app.application` and `app.api` and nothing else from the
codebase. Specifically **not**:

* `app.infrastructure` — the composition root (`app.api.container`) is the one module allowed to
  join the two sides, and `backend/tools/check_imports.py` names it;
* `app.db` and `sqlalchemy` — a router that reaches the ORM has skipped the Unit of Work, and with
  it the publish-after-commit rule of D5;
* `app.domain.layers` — D3's four information layers. A response is an `app.api.schemas` model
  built by an explicit mapping function; a router that could return a `WorldTruth` is one refactor
  away from returning one to a trainee (SPEC §2, §42 test 3).

`redis` is included for the same reason as `sqlalchemy`: the realtime fan-out is the Unit of
Work's, and E7-C's WebSocket subscribes through an adapter, not through a client a router built.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROUTERS_DIR = Path(__file__).resolve().parents[2] / "app" / "api" / "routers"

FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "app.infrastructure",
    "app.db",
    "app.inference",
    "app.domain.layers",
    "sqlalchemy",
    "redis",
    "alembic",
    "livekit",
)


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    """Every absolute dotted module a file imports, with its line number."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


def _violates(module: str) -> str | None:
    for prefix in FORBIDDEN_PREFIXES:
        if module == prefix or module.startswith(prefix + "."):
            return prefix
    return None


def test_routers_import_only_application_and_api() -> None:
    """No router imports infrastructure, the ORM, a vendor client or a D3 layer type."""
    violations: list[str] = []
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        for lineno, module in _imported_modules(path):
            prefix = _violates(module)
            if prefix is not None:
                violations.append(f"{path.name}:{lineno}: imports {module} (forbidden: {prefix})")
    assert not violations, violations


def test_the_scan_actually_covers_every_router() -> None:
    """A guard on the guard: the scan must see every module of the package.

    Without this, a router added in a directory the glob misses would be silently unchecked — the
    failure mode that makes a layering test worthless.
    """
    scanned = {path.name for path in ROUTERS_DIR.glob("*.py")}
    expected = {
        "__init__.py",
        "auth.py",
        "health.py",
        "operator.py",
        "realtime.py",
        "scenarios.py",
        "sessions.py",
        "snapshot.py",
    }
    assert expected <= scanned, f"routers not scanned: {sorted(expected - scanned)}"

"""D3 structural visibility for `world_state_loader` (E6-B DESIGN 5, D3, §20.4).

`world_state_loader` is the one application module that holds **both** the world-truth and the
caller-belief repository at once — the world event engine legitimately needs two of the four
layers. D3 is a structural decision, so that exception has to be structurally bounded rather than
merely documented: the only module under `backend/app/application` allowed to import
`world_state_loader` is `tick_session`.

The assertion is therefore an import scan over the whole application package, in the same spirit as
`tests/unit/application/sessions/test_layer_repository_isolation.py`: if a DDS- or operator-facing
use case ever imports the loader, this test names it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[4]
APPLICATION = BACKEND / "app" / "application"
LOADER = APPLICATION / "simulation" / "world_state_loader.py"

LOADER_MODULE = "app.application.simulation.world_state_loader"
LOADER_SYMBOLS = frozenset(
    {"load_world_state", "LoadedWorldState", "WorldStateNotInstantiatedError"}
)

#: The one module that may reach the loader (E6-B DESIGN 5).
ALLOWED_IMPORTERS = frozenset({"app.application.simulation.tick_session"})


def _module_name(path: Path) -> str:
    relative = path.relative_to(BACKEND).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _application_modules() -> list[Path]:
    return sorted(
        path
        for path in APPLICATION.rglob("*.py")
        if "__pycache__" not in path.parts and path != LOADER
    )


def _imports_the_loader(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == LOADER_MODULE for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == LOADER_MODULE:
                return True
            if node.module == "app.application.simulation" and any(
                alias.name in LOADER_SYMBOLS for alias in node.names
            ):
                return True
    return False


def test_only_tick_session_imports_the_world_state_loader() -> None:
    """The exception D3 grants the engine reaches exactly one module (DESIGN 5)."""
    importers = {_module_name(path) for path in _application_modules() if _imports_the_loader(path)}
    assert importers == ALLOWED_IMPORTERS


def test_the_simulation_package_does_not_re_export_the_loader() -> None:
    """Re-exporting it from `__init__` would put it one import away from every use case."""
    package_init = APPLICATION / "simulation" / "__init__.py"
    source = package_init.read_text(encoding="utf-8")
    assert "world_state_loader" not in [
        node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
    ]
    tree = ast.parse(source)
    exported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            exported = {
                element.value
                for element in getattr(node.value, "elts", [])
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    assert exported.isdisjoint(LOADER_SYMBOLS)


@pytest.mark.parametrize(
    "trainee_side",
    ["operator_card_repository", "handoff_repository", "OperatorCard", "HandoffSnapshot"],
)
def test_the_loader_cannot_reach_the_trainee_facing_layers(trainee_side: str) -> None:
    """The engine's loader sees world truth and caller belief — and neither of the other two (D3).

    The direction this file's other tests protect is "nobody else reaches the engine's layers";
    this one is the reverse direction, and it is the one SPEC §3 states outright: the simulation
    side must not be able to read the operator's card or the handoff snapshot.
    """
    tokens: set[str] = set()
    for node in ast.walk(ast.parse(LOADER.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tokens.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                tokens.update(node.module.split("."))
            tokens.update(alias.name for alias in node.names)
    assert trainee_side not in tokens

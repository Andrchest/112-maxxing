"""SPEC §3 structural rule: the four information layers share no references (HLD
`10-domain-model.md` §10.3, D3).

Two independent checks, both via `ast` (no import-time coupling between the check and the modules
under test):

1. The four layer modules (`world_truth`, `caller_belief`, `operator_card`, `handoff`) are pairwise
   import-free — none imports another.
2. No field on `WorldTruth`, `CallerBelief`, `OperatorCard` or `HandoffSnapshot` has a type
   annotation naming another layer type.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

LAYERS_DIR = Path(__file__).resolve().parents[4] / "app" / "domain" / "layers"

LAYER_MODULES = {
    "world_truth": "WorldTruth",
    "caller_belief": "CallerBelief",
    "operator_card": "OperatorCard",
    "handoff": "HandoffSnapshot",
}

LAYER_TYPE_NAMES = frozenset(LAYER_MODULES.values())


def _module_path(module_stem: str) -> Path:
    path = LAYERS_DIR / f"{module_stem}.py"
    assert path.is_file(), f"expected layer module at {path}"
    return path


def _parse(module_stem: str) -> ast.Module:
    return ast.parse(_module_path(module_stem).read_text(encoding="utf-8"))


def _imported_module_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module_stem", sorted(LAYER_MODULES))
def test_layer_module_does_not_import_a_sibling_layer_module(module_stem: str) -> None:
    tree = _parse(module_stem)
    imported = _imported_module_names(tree)

    other_stems = [stem for stem in LAYER_MODULES if stem != module_stem]
    for other_stem in other_stems:
        forbidden = f"app.domain.layers.{other_stem}"
        offenders = {
            name for name in imported if name == forbidden or name.startswith(forbidden + ".")
        }
        assert not offenders, f"{module_stem}.py must not import layer module {other_stem}.py"


def _annotation_names(annotation: ast.expr) -> set[str]:
    """Every bare `Name` referenced anywhere inside a type annotation expression."""
    return {node.id for node in ast.walk(annotation) if isinstance(node, ast.Name)}


def _class_field_annotation_names(tree: ast.Module, class_name: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign):
                    names |= _annotation_names(stmt.annotation)
    return names


@pytest.mark.parametrize(("module_stem", "type_name"), sorted(LAYER_MODULES.items()))
def test_layer_type_field_annotations_do_not_name_another_layer_type(
    module_stem: str, type_name: str
) -> None:
    tree = _parse(module_stem)
    referenced = _class_field_annotation_names(tree, type_name)

    other_layer_type_names = LAYER_TYPE_NAMES - {type_name}
    offenders = referenced & other_layer_type_names
    assert not offenders, (
        f"{type_name} ({module_stem}.py) must not name another layer type in a field "
        f"annotation, found: {sorted(offenders)}"
    )

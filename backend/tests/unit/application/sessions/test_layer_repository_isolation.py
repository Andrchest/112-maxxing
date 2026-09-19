"""D3 structural visibility for the layer repositories (§20.4, E5-B DESIGN 6, E5-C ruling 1).

D3 is "four layers, four storage locations", and it is meant to hold *structurally*: a component
that may only read the handoff must not be able to reach world truth at all. The ports and the
adapters express that as **one module per layer** — four port modules and four adapter modules,
each naming exactly one layer type and exactly one table, with no shared base class and no generic
"layer repository".

Because each layer owns a module, the assertion can be the literal thing D3 asks for: an *import*
scan. The card and handoff modules (port and adapter) import nothing whose dotted module name or
imported symbol mentions world truth or caller belief, and the world-truth and caller-belief
modules import nothing that mentions the card or the handoff. There is no path between the two
sides — not by policy, by imports.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[4]
PORTS = BACKEND / "app" / "application" / "ports"
ADAPTERS = BACKEND / "app" / "infrastructure" / "persistence"

#: Every spelling of the engine-written layers that could appear in an import: the domain types,
#: the ORM models and the module basenames.
ENGINE_LAYER_NAMES = frozenset(
    {
        "WorldTruth",
        "CallerBelief",
        "IncidentWorldState",
        "IncidentCallerBelief",
        "world_truth_repository",
        "caller_belief_repository",
    }
)

#: The same, for the trainee-facing side the engine-written modules must not reach either.
TRAINEE_LAYER_NAMES = frozenset(
    {
        "OperatorCard",
        "HandoffSnapshot",
        "IncidentCard",
        "operator_card_repository",
        "handoff_repository",
    }
)

#: `(module path, the names that module may not import)`.
ISOLATED_MODULES: tuple[tuple[Path, frozenset[str]], ...] = (
    (PORTS / "operator_card_repository.py", ENGINE_LAYER_NAMES),
    (PORTS / "handoff_repository.py", ENGINE_LAYER_NAMES),
    (ADAPTERS / "operator_card_repository.py", ENGINE_LAYER_NAMES),
    (ADAPTERS / "handoff_repository.py", ENGINE_LAYER_NAMES),
    (PORTS / "world_truth_repository.py", TRAINEE_LAYER_NAMES),
    (PORTS / "caller_belief_repository.py", TRAINEE_LAYER_NAMES),
    (ADAPTERS / "world_truth_repository.py", TRAINEE_LAYER_NAMES),
    (ADAPTERS / "caller_belief_repository.py", TRAINEE_LAYER_NAMES),
)

LAYER_PORT_MODULES: tuple[tuple[Path, str], ...] = (
    (PORTS / "world_truth_repository.py", "WorldTruthRepository"),
    (PORTS / "caller_belief_repository.py", "CallerBeliefRepository"),
    (PORTS / "operator_card_repository.py", "OperatorCardRepository"),
    (PORTS / "handoff_repository.py", "HandoffRepository"),
)

LAYER_ADAPTER_MODULES: tuple[tuple[Path, str], ...] = (
    (ADAPTERS / "world_truth_repository.py", "SqlAlchemyWorldTruthRepository"),
    (ADAPTERS / "caller_belief_repository.py", "SqlAlchemyCallerBeliefRepository"),
    (ADAPTERS / "operator_card_repository.py", "SqlAlchemyOperatorCardRepository"),
    (ADAPTERS / "handoff_repository.py", "SqlAlchemyHandoffRepository"),
)


def _imported_tokens(path: Path) -> set[str]:
    """Every dotted-name part and imported/aliased symbol of every import in the module."""
    tokens: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tokens.update(alias.name.split("."))
                if alias.asname:
                    tokens.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                tokens.update(node.module.split("."))
            for alias in node.names:
                tokens.add(alias.name)
                if alias.asname:
                    tokens.add(alias.asname)
    return tokens


@pytest.mark.parametrize(
    "path,forbidden",
    ISOLATED_MODULES,
    ids=[f"{row[0].parent.name}.{row[0].stem}" for row in ISOLATED_MODULES],
)
def test_layer_module_imports_no_other_layer(path: Path, forbidden: frozenset[str]) -> None:
    """One module per layer, and no import crossing between the two sides (D3)."""
    offenders = sorted(forbidden.intersection(_imported_tokens(path)))
    assert not offenders, (
        f"{path.parent.name}/{path.name} imports {offenders}: D3 says the two sides must be "
        "structurally unable to reach each other"
    )


def test_every_layer_port_is_its_own_class_with_no_shared_base() -> None:
    """Four independent `Protocol`s — a shared base would reintroduce the single access path."""
    for path, class_name in LAYER_PORT_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        assert set(classes) == {class_name}, f"{path.name} must declare {class_name} alone"
        bases = {base.id for base in classes[class_name].bases if isinstance(base, ast.Name)}
        assert bases == {"Protocol"}, f"{class_name} must derive from Protocol alone, got {bases}"


def test_every_layer_adapter_takes_only_an_async_session() -> None:
    """DESIGN 6: "separate classes taking only an `AsyncSession`"."""
    for path, class_name in LAYER_ADAPTER_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        assert set(classes) == {class_name}, f"{path.name} must declare {class_name} alone"
        node = classes[class_name]
        init = next(
            (
                item
                for item in node.body
                if isinstance(item, ast.FunctionDef) and item.name == "__init__"
            ),
            None,
        )
        assert init is not None, f"{node.name} has no __init__"
        arg_names = [arg.arg for arg in init.args.args]
        assert arg_names == ["self", "session"], f"{node.name}.__init__ takes {arg_names}"
        annotation = init.args.args[1].annotation
        assert isinstance(annotation, ast.Name) and annotation.id == "AsyncSession"

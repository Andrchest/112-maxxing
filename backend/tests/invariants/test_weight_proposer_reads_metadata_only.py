"""The weight proposer sees scenario metadata only — never world truth (HLD 70 §70.3.7, I3 E9a;
the INV 1/2 and R3 reading: a boundary is enforced by imports, signatures and behaviour).

1. **Imports.** The prompt module and both adapters import no scenario type, no information
   layer, no repository and no Unit of Work: a module that cannot import a type cannot be handed
   one by a future refactor either.
2. **Signatures.** `build_messages` takes exactly `cards: Sequence[CardMetadata]`;
   `WeightProposer.propose` takes `cards` and a `request_id`; the adapters' constructors take an
   `LLMClient`, the fallback and numbers — no repository, no Unit of Work. `CardMetadata` has
   exactly the whitelisted fields, each of a plain type.
3. **Behaviour.** A prompt built from the demo scenario (a world with facts the caller does not
   know) contains the title but, outside it, not one world value, not the scene summary, not one
   caller value.
"""

from __future__ import annotations

import ast
import inspect
import typing
from pathlib import Path
from typing import Any

from app.application.lessons.weight_prompt import build_messages
from app.application.ports.weight_proposer import WeightProposer
from app.domain.lesson.weights import CardMetadata, card_metadata
from app.domain.scenario.version import ScenarioVersion
from app.infrastructure.weights.heuristic_proposer import HeuristicWeightProposer
from app.infrastructure.weights.llm_proposer import LlmWeightProposer

from tests.fixtures.scenarios import demo_document

BACKEND = Path(__file__).resolve().parents[2]

PROMPT_PATH_MODULES: tuple[Path, ...] = (
    BACKEND / "app" / "application" / "lessons" / "weight_prompt.py",
    BACKEND / "app" / "infrastructure" / "weights" / "llm_proposer.py",
    BACKEND / "app" / "infrastructure" / "weights" / "heuristic_proposer.py",
    BACKEND / "app" / "application" / "ports" / "weight_proposer.py",
)

FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "app.domain.scenario",
    "app.domain.layers",
    "app.domain.facts",
    "app.application.ports.world_truth_repository",
    "app.application.ports.caller_belief_repository",
    "app.application.ports.scenario_repository",
    "app.application.ports.unit_of_work",
    "app.db",
    "app.infrastructure.persistence",
)

#: `CardMetadata`'s whole surface: title, difficulty, card type, services, timers, special
#: variants and provenance — the brief's list, nothing else.
WHITELISTED_FIELDS: frozenset[str] = frozenset(
    {
        "position",
        "title",
        "difficulty",
        "card_source",
        "role_chain",
        "required_service_count",
        "optional_service_count",
        "accept_within_ms",
        "fill_within_ms",
        "not_completed_after_ms",
        "has_competence_decline",
        "has_card_check",
        "provenance_source",
        "provenance_ticket",
        "provenance_call",
        "generation_candidate",
    }
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_the_prompt_path_imports_no_scenario_layer_or_repository() -> None:
    violations = [
        f"{path.name}: {module}"
        for path in PROMPT_PATH_MODULES
        for module in _imports(path)
        if any(module == bad or module.startswith(bad + ".") for bad in FORBIDDEN_IMPORTS)
    ]
    assert not violations, violations


def test_the_prompt_builder_takes_exactly_the_card_metadata() -> None:
    signature = inspect.signature(build_messages)
    assert list(signature.parameters) == ["cards"]
    hints = typing.get_type_hints(build_messages)
    assert hints["cards"] == typing.Sequence[CardMetadata] or str(hints["cards"]).endswith(
        "Sequence[app.domain.lesson.weights.CardMetadata]"
    )


def test_the_proposer_port_and_adapters_take_no_scenario_and_no_store() -> None:
    assert list(inspect.signature(WeightProposer.propose).parameters) == [
        "self",
        "cards",
        "request_id",
    ]
    for adapter in (LlmWeightProposer, HeuristicWeightProposer):
        assert list(inspect.signature(adapter.propose).parameters) == [
            "self",
            "cards",
            "request_id",
        ]
    assert list(inspect.signature(LlmWeightProposer.__init__).parameters) == [
        "self",
        "llm",
        "fallback",
        "max_tokens",
        "temperature",
        "timeout_ms",
    ]


def test_card_metadata_has_exactly_the_whitelisted_plain_fields() -> None:
    assert set(CardMetadata.model_fields) == WHITELISTED_FIELDS
    plain = (int, str, bool, type(None))

    def leaves(annotation: Any) -> list[Any]:
        args = [arg for arg in typing.get_args(annotation) if arg is not Ellipsis]
        return [leaf for arg in args for leaf in leaves(arg)] if args else [annotation]

    for name, field in CardMetadata.model_fields.items():
        for leaf in leaves(field.annotation):
            is_str_enum = isinstance(leaf, type) and issubclass(leaf, str)
            assert leaf in plain or is_str_enum, f"{name}: {leaf!r} is not a plain value"


def test_a_prompt_from_the_demo_scenario_carries_no_world_or_caller_value() -> None:
    document = demo_document()
    version = ScenarioVersion.model_validate(document)
    [system, user] = build_messages([card_metadata(1, version)])
    prompt = system.content + "\n" + user.content
    assert version.title in prompt
    # The title is authored metadata the instructor sees anyway (it may name the town); every
    # other word of the prompt must come from `CardMetadata`, never from a fact.
    prompt = prompt.replace(version.title, "")

    leaked: list[str] = []
    if version.world_truth.scene_summary_ru in prompt:
        leaked.append("scene_summary_ru")
    for path, fact in version.world_truth.facts.items():
        value = fact.world_value
        if isinstance(value, str) and len(value) >= 4 and value in prompt:
            leaked.append(f"world {path}={value!r}")
    for path, caller_fact in version.caller_knowledge.facts.items():
        value = caller_fact.caller_value
        if isinstance(value, str) and len(value) >= 4 and value in prompt:
            leaked.append(f"caller {path}={value!r}")
    assert not leaked, leaked

"""The caller prompt's information boundary — SPEC §21, D3, ruling R3.

SPEC §21: the Fact Access Gate is "the ONLY normal path through which scenario facts reach the
caller-response LLM". That sentence has three halves, and all three are enforced here by tests
rather than by convention:

1. **Imports.** `prompt_builder.py`, `generator.py` and `prompts/caller.py` import none of
   `app.domain.layers.world_truth`, `app.domain.facts.definitions`, `app.domain.scenario`,
   `app.application.dialogue.forbidden_values`, `app.application.dialogue.dialogue_context`. A
   module that cannot import a type cannot be handed one by a future refactor either.
2. **Signatures.** No parameter annotation of the builder's or the generator's public methods
   names `WorldTruth`, `ScenarioVersion`, `FactDefinition` or `CallerBelief`. This is the half a
   reader checks: "what could arrive through this call?".
3. **Behaviour.** A package with `allowed == ()` renders a prompt containing **no** caller or
   world value of the demo scenario. The type-level guarantees are worth nothing if the text still
   leaks, and the §43 adversarial suite repeats this measurement over sixty-odd turns.

Only `forbidden_values.py`, `dialogue_context.py` and `responder.py` may touch a `FactDefinition`,
and the first assertion pins that list too: the validator legitimately *sees* scenario values (D10,
§7.6) but it receives them as strings, from code, never as a scenario object.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from app.application.dialogue.generator import CallerResponseGenerator
from app.application.dialogue.prompt_builder import CallerPromptBuilder
from app.application.dialogue.text_normalization import normalize_text
from app.domain.caller.emotion import EmotionState
from app.domain.enums import EmotionLabel
from app.domain.facts.gate import AllowedFactsPackage
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion

from tests.fixtures.scenarios import demo_document

BACKEND = Path(__file__).resolve().parents[2]
DIALOGUE = BACKEND / "app" / "application" / "dialogue"

#: The three modules that decide what the model sees. Nothing else is in the prompt path.
PROMPT_PATH_MODULES: tuple[Path, ...] = (
    DIALOGUE / "prompt_builder.py",
    DIALOGUE / "generator.py",
    DIALOGUE / "prompts" / "caller.py",
)

#: Dotted module prefixes none of them may import (R3, verbatim).
FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "app.domain.layers.world_truth",
    "app.domain.facts.definitions",
    "app.domain.scenario",
    "app.application.dialogue.forbidden_values",
    "app.application.dialogue.dialogue_context",
)

#: Type names that must not appear in a builder/generator parameter annotation.
FORBIDDEN_ANNOTATIONS: tuple[str, ...] = (
    "WorldTruth",
    "ScenarioVersion",
    "FactDefinition",
    "CallerBelief",
)

#: The only modules of `app.application.dialogue` allowed to name `FactDefinition` at all (R3).
FACT_DEFINITION_MODULES: frozenset[str] = frozenset(
    {"forbidden_values.py", "dialogue_context.py", "responder.py", "catalog.py"}
)


def _imported_modules(path: Path) -> set[str]:
    """Every dotted module name `path` imports, however it imports it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


# ---------------------------------------------------------------------------------------------
# 1. Imports
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", PROMPT_PATH_MODULES, ids=lambda path: path.name)
def test_the_prompt_path_imports_nothing_that_could_carry_a_scenario_value(path: Path) -> None:
    """R3's import scan, the structural half of SPEC §21."""
    imported = _imported_modules(path)
    offending = sorted(
        name
        for name in imported
        for forbidden in FORBIDDEN_IMPORTS
        if name == forbidden or name.startswith(f"{forbidden}.")
    )
    assert offending == [], f"{path.name} imports {offending}"


def test_only_the_three_documented_modules_touch_fact_definitions() -> None:
    """R3: the gate's inputs stay on the gate's side of the boundary.

    The scan is over the parsed tree, not the file's text: several modules *mention*
    `FactDefinition` in a docstring precisely to say that they never receive one, and a prose
    mention is the opposite of a dependency.
    """
    offenders: list[str] = []
    for path in sorted(DIALOGUE.rglob("*.py")):
        relative = str(path.relative_to(DIALOGUE))
        if path.name in FACT_DEFINITION_MODULES or path.name == "__init__.py":
            continue
        if "FactDefinition" in _referenced_names(path):
            offenders.append(relative)
    assert offenders == [], f"unexpected FactDefinition users: {offenders}"


def _referenced_names(path: Path) -> set[str]:
    """Every identifier the module actually *uses* — no comments, no docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            found.update(alias.asname or alias.name for alias in node.names)
    return found


# ---------------------------------------------------------------------------------------------
# 2. Signatures
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("owner", "method"),
    [
        (CallerPromptBuilder, "build"),
        (CallerResponseGenerator, "generate"),
        (CallerResponseGenerator, "__init__"),
        (CallerPromptBuilder, "__init__"),
    ],
    ids=lambda value: getattr(value, "__name__", str(value)),
)
def test_no_public_parameter_names_a_forbidden_type(owner: type, method: str) -> None:
    signature = inspect.signature(getattr(owner, method))
    annotations = [
        str(parameter.annotation)
        for parameter in signature.parameters.values()
        if parameter.annotation is not inspect.Parameter.empty
    ]
    rendered = " | ".join(annotations)
    offending = [name for name in FORBIDDEN_ANNOTATIONS if name in rendered]
    assert offending == [], f"{owner.__name__}.{method} can receive {offending}"


def test_the_builder_takes_the_package_and_the_persona_and_nothing_else() -> None:
    """The positional list of §3.5, so a reviewer can read the boundary off one line."""
    names = list(inspect.signature(CallerPromptBuilder.build).parameters)
    assert names == [
        "self",
        "package",
        "profile",
        "emotion",
        "already_revealed",
        "window",
        "utterance",
    ]


# ---------------------------------------------------------------------------------------------
# 3. Behaviour
# ---------------------------------------------------------------------------------------------


def test_an_empty_package_renders_no_scenario_value_at_all() -> None:
    """SPEC §21, measured on the rendered text rather than on the type system."""
    version = ScenarioVersion.model_validate(demo_document())
    definitions = build_fact_definitions(version)
    messages = CallerPromptBuilder().build(
        AllowedFactsPackage(),
        version.caller_profile,
        EmotionState(emotion=EmotionLabel.FRIGHTENED, stress_level=0.6),
        (),
        (),
        "Что случилось?",
    )
    haystack = normalize_text("\n".join(message.content for message in messages)).texts

    leaked: list[str] = []
    for definition in definitions.values():
        for value in (definition.world_value, definition.caller_value):
            if value is None or isinstance(value, bool):
                continue
            rendered = str(value).strip()
            if len(rendered) < 2:
                continue
            needle = normalize_text(rendered).texts
            if needle and _contains(haystack, needle):
                leaked.append(rendered)

    assert leaked == [], f"the prompt leaked {sorted(set(leaked))}"


def test_the_scan_would_catch_a_leak() -> None:
    """The bite of the test above: the same scan over a prompt that *does* carry a value."""
    version = ScenarioVersion.model_validate(demo_document())
    haystack = normalize_text("ALLOWED_FACTS:\n- Улица: улица Николаева").texts
    needle = normalize_text(str(version.world_truth.facts["address.street"].world_value)).texts

    assert _contains(haystack, needle)


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[start : start + len(needle)] == needle
        for start in range(len(haystack) - len(needle) + 1)
    )

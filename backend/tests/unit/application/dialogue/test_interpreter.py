"""`DialogueInterpreter` — schema, repair-once, fallback, budgets, and the SPEC §21 import/
signature boundary (HLD `50-voice-pipeline.md` §3.3, §5.1, D10, SPEC §20).

`FakeLLM` only (D13) — the real `LlamaCppClient` gets `backend/tests/models/
test_llama_cpp_contract.py`, marker `requires_models`.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from enum import Enum as _Enum
from pathlib import Path
from typing import Any

import pytest
from app.application.dialogue.interpreter import (
    INTERPRETER_GRAMMAR,
    INTERPRETER_JSON_SCHEMA,
    DialogueInterpreter,
    DialogueTurn,
    InterpretedUtterance,
    InterpreterConfig,
    build_interpretation_schema,
    interpreter_config_from_settings,
)
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.config.settings import Settings
from app.domain.enums import SpeechAct
from app.domain.facts.definitions import FactCatalog, FactCatalogEntry
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion
from app.inference.llm.fake_llm import FakeLLM
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tests.fixtures.scenarios import demo_document

BACKEND = Path(__file__).resolve().parents[4]
INTERPRETER_MODULE = BACKEND / "app" / "application" / "dialogue" / "interpreter.py"

_SMALL_CONFIG = InterpreterConfig(
    max_tokens=200,
    temperature=0.0,
    top_p=1.0,
    timeout_ms=2500,
    catalog_cap=60,
    catalog_token_budget=1800,
    window_token_budget=1200,
    utterance_token_budget=200,
)


def _catalog(*fact_ids: str) -> FactCatalog:
    return FactCatalog(
        FactCatalogEntry(fact_id=fact_id, label_ru=fact_id, aliases_ru=(), categories=())
        for fact_id in fact_ids
    )


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "speech_act": "QUESTION",
        "requested_facts": [{"fact_id": "incident.address", "explicit": True}],
        "operator_assertions": [],
        "confirmation_targets": [],
        "semantic_confidence": 0.9,
    }
    payload.update(overrides)
    return payload


def _interpreter(
    llm: FakeLLM, *, config: InterpreterConfig = _SMALL_CONFIG
) -> tuple[DialogueInterpreter, NullMetricsRecorder]:
    metrics = NullMetricsRecorder()
    return DialogueInterpreter(llm, metrics, config=config), metrics


# ---------------------------------------------------------------------------------------------
# Success and repair/fallback ladder (§5.1, §20)
# ---------------------------------------------------------------------------------------------


async def test_a_valid_first_response_is_returned_without_repair_or_fallback() -> None:
    llm = FakeLLM([_valid_payload()])
    interpreter, metrics = _interpreter(llm)

    outcome = await interpreter.interpret(
        "Какой у вас адрес?", (), _catalog("incident.address"), request_id="r1", turn_index=0
    )

    assert outcome.fallback_used is False
    assert outcome.repair_retry_used is False
    assert outcome.failure_reason is None
    assert outcome.interpretation.speech_act is SpeechAct.QUESTION
    assert outcome.interpretation.requested_facts[0].fact_id == "incident.address"
    assert len(llm.calls) == 1
    assert len(metrics.metrics) == 1
    assert metrics.metrics[0].retry_count == 0
    assert metrics.metrics[0].status == "OK"


async def test_invalid_json_then_a_valid_repair_succeeds() -> None:
    llm = FakeLLM(["не json совсем", _valid_payload()])
    interpreter, metrics = _interpreter(llm)

    outcome = await interpreter.interpret(
        "Какой у вас адрес?", (), _catalog("incident.address"), request_id="r1", turn_index=0
    )

    assert outcome.fallback_used is False
    assert outcome.repair_retry_used is True
    assert len(llm.calls) == 2
    assert len(metrics.metrics) == 2
    assert [m.retry_count for m in metrics.metrics] == [0, 1]
    # The repair prompt must carry the previous output and a validation error, not just retry blind.
    repair_user_message = llm.calls[1].messages[-1]
    assert "не json совсем" in repair_user_message.content
    assert "invalid JSON" in repair_user_message.content or "JSON" in repair_user_message.content


async def test_two_invalid_responses_fall_back_deterministically() -> None:
    llm = FakeLLM(["мусор 1", "мусор 2"])
    interpreter, _metrics = _interpreter(llm)

    outcome = await interpreter.interpret(
        "Какой у вас адрес?", (), _catalog("incident.address"), request_id="r1", turn_index=0
    )

    assert outcome.fallback_used is True
    assert outcome.repair_retry_used is True
    assert outcome.interpretation == InterpretedUtterance(
        speech_act=SpeechAct.UNINTELLIGIBLE,
        requested_facts=(),
        operator_assertions=(),
        confirmation_targets=(),
        semantic_confidence=0.0,
    )
    assert outcome.failure_reason is not None
    assert len(llm.calls) == 2


async def test_a_timeout_falls_back_without_attempting_a_repair() -> None:
    llm = FakeLLM([TimeoutError("wedged")])
    interpreter, metrics = _interpreter(llm)

    outcome = await interpreter.interpret(
        "Алло, служба 112", (), _catalog("incident.address"), request_id="r1", turn_index=0
    )

    assert outcome.fallback_used is True
    assert outcome.repair_retry_used is False
    assert len(llm.calls) == 1, "a transport failure has no raw output to repair from"
    assert metrics.metrics[0].status == "TIMEOUT"


async def test_an_llm_error_falls_back_without_attempting_a_repair() -> None:
    llm = FakeLLM([RuntimeError("connection reset")])
    interpreter, metrics = _interpreter(llm)

    outcome = await interpreter.interpret(
        "Алло", (), _catalog("incident.address"), request_id="r1", turn_index=0
    )

    assert outcome.fallback_used is True
    assert outcome.repair_retry_used is False
    assert metrics.metrics[0].status == "ERROR"


async def test_an_unknown_fact_id_is_a_validation_failure_never_a_silent_drop() -> None:
    """SPEC §20 last line: the interpreter must repair, not quietly remove the bad id."""
    bad = _valid_payload(requested_facts=[{"fact_id": "not.in.catalog", "explicit": True}])
    llm = FakeLLM([bad, _valid_payload()])
    interpreter, _metrics = _interpreter(llm)

    outcome = await interpreter.interpret(
        "Какой у вас адрес?", (), _catalog("incident.address"), request_id="r1", turn_index=0
    )

    assert outcome.repair_retry_used is True, "an unknown id must trigger the repair path"
    assert outcome.fallback_used is False
    assert outcome.interpretation.requested_facts[0].fact_id == "incident.address"
    repair_prompt = llm.calls[1].messages[-1].content
    assert "not.in.catalog" in repair_prompt


async def test_an_unknown_fact_id_that_is_never_fixed_falls_back() -> None:
    bad = _valid_payload(confirmation_targets=["ghost.fact"])
    llm = FakeLLM([bad, bad])
    interpreter, _metrics = _interpreter(llm)

    outcome = await interpreter.interpret(
        "Повторите?", (), _catalog("incident.address"), request_id="r1", turn_index=0
    )

    assert outcome.fallback_used is True
    assert "ghost.fact" not in [f.fact_id for f in outcome.interpretation.requested_facts]


# ---------------------------------------------------------------------------------------------
# Schema (SPEC §20/§10): >8 items, extra field, generated-not-copied
# ---------------------------------------------------------------------------------------------


def test_more_than_eight_requested_facts_is_rejected() -> None:
    payload = _valid_payload(
        requested_facts=[{"fact_id": f"f{i}", "explicit": True} for i in range(9)]
    )
    with pytest.raises(ValidationError):
        InterpretedUtterance.model_validate_json(json.dumps(payload, ensure_ascii=False))


def test_an_extra_top_level_field_is_rejected() -> None:
    payload = _valid_payload(unexpected_field="not allowed")
    with pytest.raises(ValidationError):
        InterpretedUtterance.model_validate_json(json.dumps(payload, ensure_ascii=False))


def test_the_schema_enum_is_exactly_the_code_enums_members() -> None:
    speech_act_schema = INTERPRETER_JSON_SCHEMA["$defs"]["SpeechAct"]
    assert set(speech_act_schema["enum"]) == {member.value for member in SpeechAct}
    assert len(speech_act_schema["enum"]) == 10


def test_the_schema_is_generated_not_hand_copied() -> None:
    """Build an unrelated model with a *different*-sized enum through the same generator function
    and see the schema follow it — proof the enum list is not a literal baked into this module."""

    class ExtendedAct(str, _Enum):
        A = "A"
        B = "B"
        C = "C"  # a size no real INTERPRETER_JSON_SCHEMA enum has

    class _ToyModel(BaseModel):
        model_config = ConfigDict(extra="forbid")

        act: ExtendedAct
        items: tuple[str, ...] = Field(max_length=8)

    schema = build_interpretation_schema(_ToyModel)
    assert set(schema["$defs"]["ExtendedAct"]["enum"]) == {"A", "B", "C"}
    # A schema of a differently-shaped model differs from the real, 10-member
    # INTERPRETER_JSON_SCHEMA — the generator is not returning a constant.
    assert schema != INTERPRETER_JSON_SCHEMA


def test_top_level_schema_forbids_additional_properties_and_requires_all_five_fields() -> None:
    assert INTERPRETER_JSON_SCHEMA["additionalProperties"] is False
    assert set(INTERPRETER_JSON_SCHEMA["required"]) == {
        "speech_act",
        "requested_facts",
        "operator_assertions",
        "confirmation_targets",
        "semantic_confidence",
    }


# ---------------------------------------------------------------------------------------------
# The prompt never carries a scenario value (SPEC §21, D10) — sweep, whole-value comparison
# ---------------------------------------------------------------------------------------------


def _demo_catalog_and_definitions() -> tuple[FactCatalog, dict[str, Any]]:
    from app.application.dialogue.catalog import build_fact_catalog

    version = ScenarioVersion.model_validate(demo_document())
    definitions = build_fact_definitions(version)
    return build_fact_catalog(definitions), definitions


async def test_the_prompt_never_carries_a_demo_scenario_value() -> None:
    catalog, definitions = _demo_catalog_and_definitions()
    llm = FakeLLM([_valid_payload(requested_facts=[])])
    interpreter, _metrics = _interpreter(llm, config=InterpreterConfig())

    await interpreter.interpret(
        "Какой у вас адрес?",
        (DialogueTurn(speaker="OPERATOR", text="Алло, служба 112"),),
        catalog,
        request_id="r1",
        turn_index=0,
    )

    sent = "\n".join(message.content for message in llm.calls[0].messages)

    # Whole-token, word-boundary matches only — a bare substring check on a short numeric value
    # (e.g. "27") would false-positive against an unrelated longer id that merely contains those
    # digits (the flaky-"27" lesson of `reports/e11-0.md`). Identifier-typed fields never enter
    # `values` at all: only the free-text world/caller value strings are swept.
    values: set[str] = set()
    for item in definitions.values():
        for value in (item.world_value, item.caller_value):
            if isinstance(value, str) and value and len(value) >= 4:
                values.add(value)
    assert values, "the demo scenario has string-valued facts"

    leaked = sorted(
        value
        for value in values
        if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", sent, flags=re.UNICODE)
    )
    assert not leaked, f"the interpreter prompt carries scenario values: {leaked}"


# ---------------------------------------------------------------------------------------------
# Token budgets: deterministic cropping (§5.3)
# ---------------------------------------------------------------------------------------------


def test_catalog_cropping_is_deterministic_and_respects_the_cap() -> None:
    from app.application.dialogue.interpreter import _render_catalog

    catalog = _catalog(*(f"fact.number.{i:03d}" for i in range(200)))
    tiny_config = InterpreterConfig(catalog_cap=5, catalog_token_budget=20)

    first = _render_catalog(catalog, tiny_config)
    second = _render_catalog(catalog, tiny_config)
    assert first == second
    assert first.count("fact.number.") <= 5


def test_window_cropping_drops_the_oldest_turns_first() -> None:
    from app.application.dialogue.interpreter import _render_window

    long_turn = "слово " * 200
    window = tuple(DialogueTurn(speaker="OPERATOR", text=f"{i}: {long_turn}") for i in range(6))
    tiny_config = InterpreterConfig(window_token_budget=50, max_window_turns=6)

    rendered = _render_window(window, tiny_config)
    assert "0:" not in rendered, "the oldest turn should have been dropped first"
    assert rendered == _render_window(window, tiny_config)


def test_utterance_cropping_keeps_the_start_and_is_deterministic() -> None:
    from app.application.dialogue.interpreter import _fit_utterance

    long_utterance = "а" * 5000
    tiny_config = InterpreterConfig(utterance_token_budget=10)

    cropped = _fit_utterance(long_utterance, tiny_config)
    assert cropped == _fit_utterance(long_utterance, tiny_config)
    assert cropped == long_utterance[: len(cropped)]
    assert len(cropped) <= tiny_config.utterance_token_budget * 3


# ---------------------------------------------------------------------------------------------
# Signature/import scan (SPEC §21-shaped: no scenario value can reach this module)
# ---------------------------------------------------------------------------------------------


def test_interpreter_module_imports_nothing_from_domain_layers() -> None:
    tree = ast.parse(
        INTERPRETER_MODULE.read_text(encoding="utf-8"), filename=str(INTERPRETER_MODULE)
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    offenders = {module for module in imported if module.startswith("app.domain.layers")}
    assert not offenders, f"interpreter.py imports layer modules: {offenders}"


def test_interpret_has_no_parameter_typed_with_a_layer_or_a_fact_definition() -> None:
    signature = inspect.signature(DialogueInterpreter.interpret)
    forbidden_words = {
        "world",
        "worldtruth",
        "callerbelief",
        "operatorcard",
        "handoff",
        "factdefinition",
    }
    for name, parameter in signature.parameters.items():
        if name == "self":
            continue
        spelled = f"{name} {parameter.annotation}".lower()
        words = set(re.findall(r"[a-z]+", spelled))
        assert not words & forbidden_words, f"parameter {name!r} names a layer or FactDefinition"


# ---------------------------------------------------------------------------------------------
# E13-B3: grammar XOR response_format, cache_prompt/id_slot, prefix stability, settings (CHANGE
# items 1, 3, 4)
# ---------------------------------------------------------------------------------------------


async def test_grammar_is_sent_and_response_format_is_omitted_when_use_grammar_is_true() -> None:
    llm = FakeLLM([_valid_payload()])
    config = InterpreterConfig(use_grammar=True)
    interpreter, _metrics = _interpreter(llm, config=config)

    await interpreter.interpret(
        "Какой у вас адрес?", (), _catalog("incident.address"), request_id="r1", turn_index=0
    )

    call = llm.calls[0]
    assert call.response_format is None
    assert call.extra_body["grammar"] == INTERPRETER_GRAMMAR


async def test_response_format_is_sent_and_grammar_is_omitted_when_use_grammar_is_false() -> None:
    llm = FakeLLM([_valid_payload()])
    config = InterpreterConfig(use_grammar=False)
    interpreter, _metrics = _interpreter(llm, config=config)

    await interpreter.interpret(
        "Какой у вас адрес?", (), _catalog("incident.address"), request_id="r1", turn_index=0
    )

    call = llm.calls[0]
    assert call.response_format is not None
    assert call.response_format.schema == INTERPRETER_JSON_SCHEMA
    assert "grammar" not in call.extra_body


async def test_cache_prompt_and_id_slot_are_always_sent_regardless_of_use_grammar() -> None:
    llm = FakeLLM([_valid_payload(), _valid_payload()])
    for use_grammar in (True, False):
        interpreter, _metrics = _interpreter(llm, config=InterpreterConfig(use_grammar=use_grammar))
        await interpreter.interpret(
            "Какой у вас адрес?", (), _catalog("incident.address"), request_id="r1", turn_index=0
        )
        call = llm.calls[-1]
        assert call.extra_body["cache_prompt"] is True
        assert call.extra_body["id_slot"] == 0


async def test_fixed_prefix_is_byte_identical_across_calls_variable_part_last() -> None:
    """CHANGE item 3: system + few-shot + catalog first, turn window + utterance last."""
    llm = FakeLLM([_valid_payload(), _valid_payload()])
    interpreter, _metrics = _interpreter(llm, config=InterpreterConfig())
    catalog = _catalog("incident.address", "people.total_inside")

    await interpreter.interpret(
        "Какой у вас адрес?",
        (DialogueTurn(speaker="OPERATOR", text="Алло"),),
        catalog,
        request_id="r1",
        turn_index=0,
    )
    await interpreter.interpret(
        "Сколько пострадавших?",
        (
            DialogueTurn(speaker="OPERATOR", text="Алло"),
            DialogueTurn(speaker="CALLER", text="Помогите"),
        ),
        catalog,
        request_id="r2",
        turn_index=1,
    )

    first_messages = llm.calls[0].messages
    second_messages = llm.calls[1].messages
    assert len(first_messages) == len(second_messages)
    assert len(first_messages) > 2, "few-shot messages must be present between system and user"

    fixed_first, variable_first = first_messages[:-1], first_messages[-1]
    fixed_second, variable_second = second_messages[:-1], second_messages[-1]
    assert fixed_first == fixed_second, "the fixed prefix must be byte-identical across turns"
    assert variable_first.role == "user"
    assert variable_second.role == "user"
    assert variable_first.content != variable_second.content, "the variable part must differ"
    assert first_messages[0].role == "system"


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        "redis_url": "redis://localhost:56379/0",
        "jwt_secret": "test-only-secret",
        "livekit_url": "ws://localhost:7880",
        "livekit_api_key": "devkey",
        "livekit_api_secret": "devsecret1234567890",
        "llm_base_url": "http://localhost:8080/v1",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_interpreter_config_from_settings_reads_the_three_sim_llm_interpreter_keys() -> None:
    settings = _settings(
        llm_interpreter_max_tokens=111,
        llm_interpreter_timeout_ms=999,
        llm_interpreter_use_grammar=False,
    )
    config = interpreter_config_from_settings(settings)
    assert config.max_tokens == 111
    assert config.timeout_ms == 999
    assert config.use_grammar is False


def test_interpreter_config_from_settings_defaults_use_grammar_to_true() -> None:
    config = interpreter_config_from_settings(_settings())
    assert config.use_grammar is True

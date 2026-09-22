"""`build_interpretation_grammar` (HLD `50-voice-pipeline.md` §5.1, this brief's CHANGE item 1).

No llama-server, no `requires_models` marker: this only checks the GBNF *text* the generator
produces. It was additionally checked once by hand against the real llama.cpp GBNF parser
(`test-gbnf-validator`, from the owner's build at `/home/andreipc/src/llama.cpp/build`) — see this
task's report — which is not repeated here so the gate stays hermetic.
"""

from __future__ import annotations

from enum import Enum as _Enum

import pytest
from app.application.dialogue.grammar import build_interpretation_grammar
from app.application.dialogue.interpreter import INTERPRETER_GRAMMAR, InterpretedUtterance
from app.domain.enums import SpeechAct
from pydantic import BaseModel, ConfigDict, Field


def test_root_rule_references_the_top_level_object() -> None:
    assert INTERPRETER_GRAMMAR.splitlines()[0] == "root ::= interpreted-utterance"


def test_every_speech_act_member_appears_as_a_quoted_alternative_in_enum_order() -> None:
    speech_act_line = next(
        line for line in INTERPRETER_GRAMMAR.splitlines() if line.startswith("speech-act ::=")
    )
    expected = " | ".join(f'"\\"{member.value}\\""' for member in SpeechAct)
    assert speech_act_line == f"speech-act ::= {expected}"


def test_object_field_order_is_the_models_declaration_order() -> None:
    """ "Fixed key order = the model's field order" — literally checked against
    `InterpretedUtterance.model_fields`, not re-typed by hand."""
    root_line = next(
        line
        for line in INTERPRETER_GRAMMAR.splitlines()
        if line.startswith("interpreted-utterance ::=")
    )
    field_names = list(InterpretedUtterance.model_fields)
    positions = [root_line.index(f'"\\"{name}\\":"') for name in field_names]
    assert positions == sorted(positions), "keys are not in declaration order"


def test_no_whitespace_rule_and_no_whitespace_character_class() -> None:
    """CHANGE item 1: the grammar never allows insignificant whitespace anywhere structural.

    llama.cpp's own `grammars/json.gbnf` names its insignificant-whitespace rule `ws` and defines
    it with a `[ \\t]`/`[ \\t\\n]`-shaped character class; this grammar has neither. (A plain
    substring search for a quoted `" "` token would false-positive on any two adjacent quoted
    literals in the pretty-printed source, e.g. `"}" "\\"operator_assertions\\":"` — that space is
    grammar-*source* formatting, not a rule that matches a space in the target text — so this
    checks the two constructs this generator could actually emit instead.)
    """
    assert "ws ::=" not in INTERPRETER_GRAMMAR
    assert "\\t" not in INTERPRETER_GRAMMAR
    assert "[ " not in INTERPRETER_GRAMMAR


def test_array_fields_are_bounded_by_the_fields_max_length() -> None:
    # requested_facts/operator_assertions/confirmation_targets are all Field(max_length=8): one
    # first item plus up to 7 more, i.e. `{0,7}`.
    assert INTERPRETER_GRAMMAR.count("{0,7}") == 3


def test_the_grammar_is_generated_not_hand_copied() -> None:
    """Build an unrelated model with a *different*-sized `str` `Enum` through the same generator
    function and see the alternation list follow it — proof this is not a literal baked into the
    module, mirroring `test_interpreter.py`'s analogous JSON-schema test."""

    class ExtendedAct(str, _Enum):
        A = "A"
        B = "B"
        C = "C"  # a size no real speech-act rule has

    class _ToyModel(BaseModel):
        model_config = ConfigDict(extra="forbid")

        act: ExtendedAct
        items: tuple[str, ...] = Field(max_length=8)
        confidence: float = Field(ge=0.0, le=1.0)

    grammar = build_interpretation_grammar(_ToyModel)
    act_line = next(line for line in grammar.splitlines() if line.startswith("extended-act ::="))
    assert act_line == 'extended-act ::= "\\"A\\"" | "\\"B\\"" | "\\"C\\""'
    assert grammar != INTERPRETER_GRAMMAR


def test_adding_a_speech_act_member_would_change_both_the_schema_and_the_grammar() -> None:
    """Same proof as above, phrased the way the brief asks for it: one source, two renderings."""
    from app.application.dialogue.interpreter import build_interpretation_schema

    class FourAct(str, _Enum):
        Q = "Q"
        A = "A"
        S = "S"
        Z = "Z"

    class _ToyModel(BaseModel):
        model_config = ConfigDict(extra="forbid")

        act: FourAct

    schema = build_interpretation_schema(_ToyModel)
    grammar = build_interpretation_grammar(_ToyModel)
    assert set(schema["$defs"]["FourAct"]["enum"]) == {"Q", "A", "S", "Z"}
    act_line = next(line for line in grammar.splitlines() if line.startswith("four-act ::="))
    assert all(f'"\\"{m}\\""' in act_line for m in ("Q", "A", "S", "Z"))


def test_a_tuple_field_without_max_length_is_rejected_not_silently_unbounded() -> None:
    class _Unbounded(BaseModel):
        model_config = ConfigDict(extra="forbid")

        items: tuple[str, ...]

    with pytest.raises(NotImplementedError):
        build_interpretation_grammar(_Unbounded)


def test_an_unsupported_annotation_is_rejected_not_silently_permissive() -> None:
    class _HasInt(BaseModel):
        model_config = ConfigDict(extra="forbid")

        count: int

    with pytest.raises(NotImplementedError):
        build_interpretation_grammar(_HasInt)


def test_nested_object_rules_are_defined_exactly_once() -> None:
    assert INTERPRETER_GRAMMAR.count("requested-fact ::=") == 1
    assert INTERPRETER_GRAMMAR.count("operator-assertion ::=") == 1


# ---------------------------------------------------------------------------------------------
# E13-B4 item 3: `build_caller_response_grammar` — a thin wrapper, not a fork
# ---------------------------------------------------------------------------------------------


def test_build_caller_response_grammar_is_the_same_builder_not_a_fork() -> None:
    """ "Reuse that module; add a function, do not fork it" (E13-B4 item 3): checked directly —
    the wrapper produces byte-identical output to calling `build_interpretation_grammar` itself
    on the same model, for a model shaped nothing like `InterpretedUtterance`."""
    from app.application.dialogue.grammar import build_caller_response_grammar

    class _Utterance(BaseModel):
        model_config = ConfigDict(extra="forbid")

        utterance: str

    assert build_caller_response_grammar(_Utterance) == build_interpretation_grammar(_Utterance)


def test_build_caller_response_grammar_matches_callerutterance() -> None:
    from app.application.dialogue.generator import CALLER_GRAMMAR
    from app.application.dialogue.grammar import build_caller_response_grammar
    from app.application.dialogue.validator import CallerUtterance

    assert build_caller_response_grammar(CallerUtterance) == CALLER_GRAMMAR
    assert CALLER_GRAMMAR.splitlines()[0] == "root ::= caller-utterance"
    # E19-C2: the caller's utterance is `speech-string`, not `jsonstring` — a JSON string the
    # grammar forces to carry at least one Cyrillic letter, so `{"utterance":"}"}` cannot be
    # generated at all (`grammar.SpokenText` on `CallerUtterance.utterance`).
    assert 'caller-utterance ::= "{" "\\"utterance\\":" speech-string "}"' in CALLER_GRAMMAR
    assert "speech-string ::= " in CALLER_GRAMMAR
    assert "jsonstring" not in CALLER_GRAMMAR


# ---------------------------------------------------------------------------------------------
# E19-C2: `SpokenText` — the caller's utterance must carry at least one Cyrillic letter
# ---------------------------------------------------------------------------------------------


def test_spoken_text_is_what_switches_jsonstring_for_speech_string() -> None:
    """The constraint lives on the MODEL, not in a caller-specific branch of the generator.

    Two toy models differing only in the marker: one gets `jsonstring`, the other `speech-string`.
    That is what keeps `build_caller_response_grammar` a thin wrapper rather than a fork.
    """
    from typing import Annotated

    from app.application.dialogue.grammar import SpokenText

    class _Plain(BaseModel):
        model_config = ConfigDict(extra="forbid")

        text: str

    class _Spoken(BaseModel):
        model_config = ConfigDict(extra="forbid")

        text: Annotated[str, SpokenText()]

    plain = build_interpretation_grammar(_Plain)
    spoken = build_interpretation_grammar(_Spoken)
    assert '"\\"text\\":" jsonstring' in plain
    assert "speech-string" not in plain
    assert '"\\"text\\":" speech-string' in spoken
    assert "jsonstring" not in spoken


def test_the_speech_string_rule_requires_a_cyrillic_letter() -> None:
    """The rule is `"\\"" speech-char* <cyrillic> speech-char* "\\""` — a string with no letter
    (`""`, `"}"`, `"..."`) has no derivation, which is what stops the model emitting it at all
    (E19-C measured the Qwen3.5 family emitting a bare `}` on 13-27 of 46 real dialogue turns)."""
    from app.application.dialogue.generator import CALLER_GRAMMAR

    rule = next(
        line for line in CALLER_GRAMMAR.splitlines() if line.startswith("speech-string ::=")
    )
    assert rule == 'speech-string ::= "\\"" speech-char* [а-яА-ЯёЁ] speech-char* "\\""'
    #: `ё`/`Ё` are outside the `а-я`/`А-Я` ranges and have to be listed separately.
    assert "ёЁ" in rule
    #: `speech-char` is the same JSON-string character class `jsonstring` uses — one definition.
    speech_char = next(
        line for line in CALLER_GRAMMAR.splitlines() if line.startswith("speech-char ::=")
    )
    assert speech_char == (
        r'speech-char ::= [^"\\\x7F\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})'
    )


def test_the_caller_json_schema_is_unchanged_by_the_marker() -> None:
    """`SpokenText` is a grammar-only marker: the `response_format=json_schema` fallback path
    (`GeneratorConfig.use_grammar=False`) must see exactly the string field it always saw."""
    from app.application.dialogue.generator import CALLER_JSON_SCHEMA

    assert CALLER_JSON_SCHEMA["properties"]["utterance"]["type"] == "string"
    assert "pattern" not in CALLER_JSON_SCHEMA["properties"]["utterance"]

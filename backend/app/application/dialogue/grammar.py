"""GBNF grammar generator for the interpreter's constrained output (HLD `50-voice-pipeline.md`
§5.1, this task's brief CHANGE item 1).

`build_interpretation_grammar(model)` introspects a pydantic v2 model — the SAME
`InterpretedUtterance` class that `interpreter.build_interpretation_schema` turns into
`INTERPRETER_JSON_SCHEMA` — and emits a whitespace-free GBNF grammar for llama-server's `grammar`
request field. One source, two renderings: a test in `backend/tests/unit/application/dialogue/
test_grammar.py` builds an unrelated toy model with a differently-sized `str` `Enum` through this
same function and asserts the grammar's alternatives follow the enum, proving this is not a
hand-copied literal.

Deliberately narrow — it supports exactly the field shapes `InterpretedUtterance` and its nested
models use (`str` `Enum`, `str`, `bool`, a `[0, 1]`-bounded `float`, a nested `BaseModel`, and a
`Field(max_length=N)`-bounded `tuple` of any of those) and raises `NotImplementedError` naming the
unsupported field for anything else, rather than silently emitting a permissive grammar for a type
it does not understand.

Object field order in the grammar is the model's declaration order (`model_fields` is an ordered
mapping in pydantic v2) — "fixed key order = the model's field order" (CHANGE item 1). No rule in
this module ever emits an insignificant-whitespace token: every structural JSON character
(`{`, `}`, `[`, `]`, `,`, `:`, the value quotes) is a bare string literal with nothing around it,
which is what makes the grammar force the single-line compact JSON CHANGE item 1 also asks the
prompt to request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum as _Enum
from typing import Any, get_args, get_origin

from annotated_types import Ge, Le, MaxLen
from pydantic import BaseModel
from pydantic.fields import FieldInfo

__all__ = ["SpokenText", "build_caller_response_grammar", "build_interpretation_grammar"]


@dataclass(frozen=True, slots=True)
class SpokenText:
    """Marks a `str` field as text a human will HEAR, not a machine-readable string (E19-C2).

    `Annotated[str, SpokenText()]` makes this generator emit `speech-string` instead of
    `jsonstring` for that field: a JSON string that must contain **at least one Cyrillic letter**.
    Without it the caller's GBNF grammar happily accepts `""`, `"}"` or `"..."` as a valid
    utterance, which E19-C measured the Qwen3.5 family producing on 13-27 of 46 dialogue turns —
    a caller that "says" `}` is nonsense in a trainee's ear.

    The constraint lives on the **model** (`validator.CallerUtterance`), not in a caller-specific
    branch of this module, so the module's own promise holds: one source (the pydantic model), two
    renderings (JSON schema and GBNF), and `build_caller_response_grammar` stays a thin wrapper
    that forks nothing. pydantic ignores the marker for validation and for
    `model_json_schema()`, so `CALLER_JSON_SCHEMA` — the non-grammar fallback — is unchanged by it.
    """


#: Standard JSON string content (escapes + the same excluded-control-char class as llama.cpp's own
#: `grammars/json.gbnf`). Shared by `jsonstring` and `speech-char` so the two can never drift.
_JSON_CHAR = r'[^"\\\x7F\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})'
#: With no trailing `ws` — this grammar never allows insignificant space.
_JSONSTRING_RULE = f'jsonstring ::= "\\"" ( {_JSON_CHAR} )* "\\""'
#: Russian letters, including `ё`/`Ё`, which are outside the `а-я`/`А-Я` ranges.
_CYRILLIC_LETTER = "[а-яА-ЯёЁ]"
#: What a spoken line may contain (E20-I): JSON string content MINUS escapes and the structural
#: characters `{ } [ ] < > \\`. The real `make up` walk heard the DEV caller say `}I не знаю…` —
#: the Cyrillic-letter rule above passes it, because the line does contain Cyrillic. A human caller
#: never pronounces a brace, a bracket or an escape; Russian quotes are «», so `"` is not needed
#: inside speech either.
_SPEECH_CHAR = r"[^\"\\\x7F\x00-\x1F{}\[\]<>`]"
_SPEECH_CHAR_RULE = f"speech-char ::= {_SPEECH_CHAR}"
#: A JSON string with at least one Cyrillic letter somewhere in it — see `SpokenText`.
_SPEECH_STRING_RULE = f'speech-string ::= "\\"" speech-char* {_CYRILLIC_LETTER} speech-char* "\\""'
_BOOLEAN_RULE = 'boolean ::= "true" | "false"'
#: `semantic_confidence`'s `ge=0.0, le=1.0` (§20/§10) — a decimal literally between 0 and 1.
_UNIT_FLOAT_RULE = r'unit-float ::= ("0" | "1") ("." [0-9]{1,4})?'
#: Fallback for any other float field a future model might add (no `ge`/`le` == [0, 1]).
_NUMBER_RULE = r'number ::= "-"? ("0" | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [-+]? [0-9]+)?'

_CAMEL_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _kebab(name: str) -> str:
    """`RequestedFact` -> `requested-fact` (GBNF non-terminals are dashed lowercase words)."""
    return _CAMEL_BOUNDARY_RE.sub("-", name).lower()


def _max_len(field: FieldInfo) -> int | None:
    for constraint in field.metadata:
        if isinstance(constraint, MaxLen):
            return constraint.max_length
    return None


def _is_unit_interval(field: FieldInfo) -> bool:
    lower = upper = None
    for constraint in field.metadata:
        if isinstance(constraint, Ge):
            lower = constraint.ge
        if isinstance(constraint, Le):
            upper = constraint.le
    return lower == 0.0 and upper == 1.0


def _array_rule(item_rule: str, max_items: int) -> str:
    if max_items <= 0:
        return '"[" "]"'
    if max_items == 1:
        return f'"[" ({item_rule})? "]"'
    return f'"[" ({item_rule} ("," {item_rule}){{0,{max_items - 1}}})? "]"'


class _GrammarBuilder:
    """Accumulates named GBNF rules while walking `model`'s fields, memoising by rule name so a
    type referenced from two places (or twice in the same model) is defined once."""

    def __init__(self) -> None:
        self._rule_bodies: dict[str, str] = {}
        self.needs_jsonstring = False
        self.needs_speech_string = False
        self.needs_boolean = False
        self.needs_unit_float = False
        self.needs_number = False

    def object_rule_name(self, model: type[BaseModel]) -> str:
        name = _kebab(model.__name__)
        if name in self._rule_bodies:
            return name
        self._rule_bodies[name] = ""  # reserve the slot before recursing (breaks any cycle)
        parts = [
            f'"\\"{field_name}\\":" '
            + self._field_rule(field, field_name=field_name, owner=model.__name__)
            for field_name, field in model.model_fields.items()
        ]
        self._rule_bodies[name] = f"{name} ::= " + '"{" ' + ' "," '.join(parts) + ' "}"'
        return name

    def enum_rule_name(self, enum_cls: type[_Enum]) -> str:
        name = _kebab(enum_cls.__name__)
        if name in self._rule_bodies:
            return name
        alternatives = " | ".join(f'"\\"{member.value}\\""' for member in enum_cls)
        self._rule_bodies[name] = f"{name} ::= {alternatives}"
        return name

    def _field_rule(self, field: FieldInfo, *, field_name: str, owner: str) -> str:
        annotation = field.annotation
        if get_origin(annotation) is tuple:
            (item_type,) = [a for a in get_args(annotation) if a is not Ellipsis]
            max_items = _max_len(field)
            if max_items is None:
                raise NotImplementedError(
                    f"{owner}.{field_name}: tuple field has no Field(max_length=...) — the "
                    "grammar generator only supports bounded arrays."
                )
            item_rule = self._scalar_or_object_rule(item_type, field_name=field_name, owner=owner)
            return _array_rule(item_rule, max_items)
        return self._scalar_or_object_rule(
            annotation, field_name=field_name, owner=owner, field=field
        )

    def _scalar_or_object_rule(
        self, annotation: Any, *, field_name: str, owner: str, field: FieldInfo | None = None
    ) -> str:
        if isinstance(annotation, type) and issubclass(annotation, _Enum):
            return self.enum_rule_name(annotation)
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return self.object_rule_name(annotation)
        if annotation is str:
            if field is not None and any(
                isinstance(marker, SpokenText) for marker in field.metadata
            ):
                self.needs_speech_string = True
                return "speech-string"
            self.needs_jsonstring = True
            return "jsonstring"
        if annotation is bool:
            self.needs_boolean = True
            return "boolean"
        if annotation is float:
            if field is not None and _is_unit_interval(field):
                self.needs_unit_float = True
                return "unit-float"
            self.needs_number = True
            return "number"
        raise NotImplementedError(
            f"{owner}.{field_name}: the grammar generator has no rule for annotation {annotation!r}"
        )

    def render(self, root_name: str) -> str:
        lines = [f"root ::= {root_name}"]
        lines.extend(body for body in self._rule_bodies.values() if body)
        if self.needs_jsonstring:
            lines.append(_JSONSTRING_RULE)
        if self.needs_speech_string:
            lines.append(_SPEECH_STRING_RULE)
            lines.append(_SPEECH_CHAR_RULE)
        if self.needs_boolean:
            lines.append(_BOOLEAN_RULE)
        if self.needs_unit_float:
            lines.append(_UNIT_FLOAT_RULE)
        if self.needs_number:
            lines.append(_NUMBER_RULE)
        return "\n".join(lines) + "\n"


def build_interpretation_grammar(model: type[BaseModel]) -> str:
    """A whitespace-free GBNF grammar for `model`'s compact-JSON serialisation.

    Generated from the same pydantic model (and, transitively, the same `str` `Enum` classes) as
    `interpreter.build_interpretation_schema` — not a hand-maintained literal. See the module
    docstring for exactly which field shapes are supported.
    """
    builder = _GrammarBuilder()
    root_name = builder.object_rule_name(model)
    return builder.render(root_name)


def build_caller_response_grammar(model: type[BaseModel]) -> str:
    """A whitespace-free GBNF grammar for the caller generator's `{"utterance": "..."}` schema
    (E13-B4, CHANGE item 3).

    `build_interpretation_grammar` is already model-agnostic (it introspects whatever
    `type[BaseModel]` it is given) — this is a thin, separately-named wrapper around it rather
    than a fork, so `generator.py` gets its own call site without a second copy of `_GrammarBuilder`
    or its rules. Called with `app.application.dialogue.validator.CallerUtterance`.
    """
    return build_interpretation_grammar(model)

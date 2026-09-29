"""The 112 card schema as data (HLD `70-i3-alignment.md` §70.5, D17).

A card schema is the list of `CardFieldSpec`s a card is made of. `v1` is today's 38 `CARD_FIELDS`
(`operator_card.py` keeps the name as the v1 alias); `v2` is the organizer card, authored in
`reference/card-schema/v2.yaml`. This module is the one parser for both: `parse_card_schema`
turns a schema *document* (the parsed YAML mapping) into a `CardSchema`. It does no I/O — the
file-backed reference adapter reads the file and hands the mapping in (D2).

**Additive `CardFieldSpec` properties (§70.5.2).** `group`, `order`, `control`, `options`,
`visible_when`, `required_in_block`, `routing_relevant` (and, I7 E55, `max_length`). A v1 document
carries only the six original keys and gets the neutral values the contract names: `group: null`,
`order` = position, `control` by value type (`SELECT` for an enum, `CHECKBOX` for a boolean, else
`TEXT`), `options: null`, `visible_when: null`, `required_in_block: false`,
`routing_relevant: false`, `max_length: null`.

**Options and the classifier binding (D18, B1 §4).** A v2 option's `code` is a classifier
identifier: a questionnaire chip's code is the признак text as `v046_24.json` carries it, a yes/no
that is a routing sub-column condition carries the flag key of `v046_24.columns.json`, a «Что
случилось» entry carries the classifier `group_no` it opens, and the address selects carry the
catalog's `okrug` / `district` strings. A chip standing for several признаки lists them in
`classifier_features` (default `[code]`). An option bound to nothing in the classifier — an
administrative «Что случилось» entry (A-3) or a chip the classifier has no признак for — says
`routing: none`. A `BOOLEAN` field may carry exactly one option: the code the toggle stands for
when it is on (the header flags «Пострадавшие», «Нет доступа / Заблокированные», …).

**`CardCondition` (§70.5.2)** is card-local — `{all: [...]} | {any: [...]} | {not: …} |
{field_path, op, value}` over the card's own values — and is *not* a leaf of the world
`Condition` language, so HLD 30 rules 26/31 are untouched. `visible_when` is advisory: a hidden
field is still accepted by `set_field`, exactly like `required_for_handoff`. The evaluator here
and the frontend's run over the one shared fixture file
`reference/card-schema/conditions.fixtures.json`.

`# ruff: noqa: RUF001` — Cyrillic in docstrings and messages is trainee-facing Russian.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from app.domain.common.errors import CardFieldError
from app.domain.common.values import FactValue
from app.domain.enums import CallerRelationship, IncidentType, ValueType

__all__ = [
    "BASE_SPEC_KEYS",
    "CardCondition",
    "CardConditionAll",
    "CardConditionAny",
    "CardConditionLeaf",
    "CardConditionNot",
    "CardControl",
    "CardFieldGroup",
    "CardFieldSpec",
    "CardOption",
    "CardOptionUnknownError",
    "CardSchema",
    "CardSchemaError",
    "CardValueTooLongError",
    "ConditionOp",
    "build_card_schema",
    "check_value",
    "condition_document",
    "evaluate_condition",
    "parse_card_schema",
]

BASE_SPEC_KEYS: tuple[str, ...] = (
    "field_path",
    "value_type",
    "enum_name",
    "label_ru",
    "scoring_relevant",
    "required_for_handoff",
)
"""The six properties `CardFieldSpec` had before I3 — all a v1 document carries."""


class CardSchemaError(ValueError):
    """A card schema document is malformed (unknown group, duplicate path, bad condition, …)."""


class CardOptionUnknownError(CardFieldError):
    """A value is not one of the field's option codes (`422 CARD_OPTION_UNKNOWN`)."""


class CardValueTooLongError(CardFieldError):
    """A `STRING` value is longer than the field's `max_length` (I7 E55; the card's «0 / 1999»
    counter). A `CardFieldError`, so `setCardField` answers `422 CARD_VALUE_TYPE_MISMATCH`."""


class CardControl(str, Enum):
    """How the UI renders a field (§70.5.2, `openapi.yaml`'s `CardControl`)."""

    TEXT = "TEXT"
    TEXTAREA = "TEXTAREA"
    NUMBER = "NUMBER"
    SELECT = "SELECT"
    TOGGLE_SET = "TOGGLE_SET"
    CHIPS = "CHIPS"
    CHECKBOX = "CHECKBOX"
    PHONE = "PHONE"


class ConditionOp(str, Enum):
    """The five `CardCondition` leaf operators (§70.5.2)."""

    EQ = "EQ"
    NE = "NE"
    IN = "IN"
    CONTAINS = "CONTAINS"
    PRESENT = "PRESENT"


class CardOption(BaseModel):
    """One option of a data-driven field (`openapi.yaml`'s `CardOption`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    label_ru: str = Field(min_length=1)
    classifier_features: tuple[str, ...] | None = None
    """The classifier признаки this option stands for; `None` means `[code]` (B1 §4)."""
    routing: Literal["none"] | None = None
    """`none`: bound to nothing in the classifier (an administrative entry, A-3)."""

    @property
    def classifier_feature_texts(self) -> tuple[str, ...]:
        """The признак texts this option stands for — empty for a `routing: none` option."""
        if self.routing == "none":
            return ()
        return self.classifier_features if self.classifier_features is not None else (self.code,)


class CardConditionLeaf(BaseModel):
    """`{field_path, op, value}` over one card value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str = Field(min_length=1)
    op: ConditionOp
    value: FactValue = None


class CardConditionAll(BaseModel):
    """`{all: [...]}` — every branch holds."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    all_: tuple[CardCondition, ...] = Field(alias="all", min_length=1)


class CardConditionAny(BaseModel):
    """`{any: [...]}` — at least one branch holds."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    any_: tuple[CardCondition, ...] = Field(alias="any", min_length=1)


class CardConditionNot(BaseModel):
    """`{not: …}` — the branch does not hold."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    not_: CardCondition = Field(alias="not")


type CardCondition = CardConditionAll | CardConditionAny | CardConditionNot | CardConditionLeaf
"""A card-local visibility condition (§70.5.2; `openapi.yaml`'s `CardCondition`)."""

CardConditionAll.model_rebuild()
CardConditionAny.model_rebuild()
CardConditionNot.model_rebuild()


def condition_document(condition: CardCondition) -> dict[str, Any]:
    """A condition back as its document form (`all` / `any` / `not` keys, not the aliases)."""
    return condition.model_dump(mode="json", by_alias=True)


def _is_filled(value: FactValue) -> bool:
    return value is not None and value != "" and value != []


def evaluate_condition(condition: CardCondition, values: Mapping[str, FactValue]) -> bool:
    """Does `condition` hold over the card `values`? Pure and total.

    * `EQ` — the path is set and its value equals `value`; `NE` — not `EQ` (an unset path is
      "not equal");
    * `IN` — `value` is a list; a scalar card value is one of it, a list card value shares an
      item with it;
    * `CONTAINS` — the card value is a list holding `value` (every item of it, when `value` is a
      list); a non-list card value never contains anything;
    * `PRESENT` — the path holds something other than `null`, `""` or `[]` (`false` counts as
      set: the toggle was answered). `value` is ignored.

    Codes are compared exactly — conditions name option codes of the same schema.
    """
    if isinstance(condition, CardConditionAll):
        return all(evaluate_condition(branch, values) for branch in condition.all_)
    if isinstance(condition, CardConditionAny):
        return any(evaluate_condition(branch, values) for branch in condition.any_)
    if isinstance(condition, CardConditionNot):
        return not evaluate_condition(condition.not_, values)
    actual = values.get(condition.field_path)
    expected = condition.value
    match condition.op:
        case ConditionOp.EQ:
            return _is_filled(actual) and actual == expected
        case ConditionOp.NE:
            return not (_is_filled(actual) and actual == expected)
        case ConditionOp.IN:
            if not isinstance(expected, list) or not _is_filled(actual):
                return False
            if isinstance(actual, list):
                return any(item in expected for item in actual)
            return actual in expected
        case ConditionOp.CONTAINS:
            if not isinstance(actual, list):
                return False
            wanted = expected if isinstance(expected, list) else [expected]
            return all(item in actual for item in wanted)
        case ConditionOp.PRESENT:
            return _is_filled(actual)


def _condition_paths(condition: CardCondition) -> Iterable[str]:
    if isinstance(condition, CardConditionAll):
        for branch in condition.all_:
            yield from _condition_paths(branch)
    elif isinstance(condition, CardConditionAny):
        for branch in condition.any_:
            yield from _condition_paths(branch)
    elif isinstance(condition, CardConditionNot):
        yield from _condition_paths(condition.not_)
    else:
        yield condition.field_path


_DEFAULT_CONTROL: Mapping[ValueType, CardControl] = MappingProxyType(
    {ValueType.ENUM: CardControl.SELECT, ValueType.BOOLEAN: CardControl.CHECKBOX}
)


class CardFieldSpec(BaseModel):
    """One card field (§10.6; the I3 additive properties of §70.5.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str
    value_type: ValueType
    enum_name: str | None = None
    label_ru: str
    scoring_relevant: bool = False
    required_for_handoff: bool = False
    group: str | None = None
    order: int = Field(default=0, ge=0)
    control: CardControl = CardControl.TEXT
    options: tuple[CardOption, ...] | None = None
    visible_when: CardCondition | None = None
    required_in_block: bool = False
    routing_relevant: bool = False
    max_length: int | None = Field(default=None, ge=1)
    """The longest `STRING` value the field takes (I7 E55); `None`: unbounded."""

    @model_validator(mode="before")
    @classmethod
    def _default_control(cls, data: Any) -> Any:
        """`control` defaults by value type — the neutral value of a v1 field."""
        if isinstance(data, Mapping) and data.get("control") is None:
            value_type = data.get("value_type")
            try:
                parsed = ValueType(value_type)
            except ValueError:
                return data
            return {**data, "control": _DEFAULT_CONTROL.get(parsed, CardControl.TEXT)}
        return data

    @model_validator(mode="after")
    def _options_fit_the_type(self) -> CardFieldSpec:
        if self.max_length is not None and self.value_type is not ValueType.STRING:
            raise ValueError(f"{self.field_path}: only a STRING field takes max_length")
        if self.options is None:
            if self.value_type is ValueType.ENUM and self.enum_name is None:
                raise ValueError(f"{self.field_path}: an ENUM field needs enum_name or options")
            return self
        if self.value_type is ValueType.ENUM:
            if self.enum_name is not None:
                raise ValueError(f"{self.field_path}: an ENUM field has enum_name or options")
        elif self.value_type is ValueType.BOOLEAN:
            if len(self.options) != 1:
                raise ValueError(f"{self.field_path}: a BOOLEAN field carries exactly one option")
        elif self.value_type is not ValueType.STRING_LIST:
            raise ValueError(f"{self.field_path}: {self.value_type.value} fields take no options")
        codes = [option.code for option in self.options]
        if len(codes) != len(set(codes)):
            raise ValueError(f"{self.field_path}: duplicate option codes")
        if not codes:
            raise ValueError(f"{self.field_path}: an empty option list")
        return self

    @property
    def option_codes(self) -> frozenset[str]:
        """Every option code; empty when the field has no options."""
        return frozenset(option.code for option in self.options or ())

    def option(self, code: str) -> CardOption | None:
        """The option with `code`, or `None`."""
        return next((option for option in self.options or () if option.code == code), None)


class CardFieldGroup(BaseModel):
    """One layout block of a schema (`header`, `applicant`, `address`, …)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    label_ru: str


class CardSchema(BaseModel):
    """A versioned card schema: fields in document order, the layout groups, the file's sha256."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: str = Field(min_length=1)
    fields: tuple[CardFieldSpec, ...]
    groups: tuple[CardFieldGroup, ...] = ()
    sha256: str | None = None
    """The manifest's sha256 of the file; `None` for the code-backed `v1` (`CARD_SCHEMA_V1`)."""

    _by_path: Mapping[str, CardFieldSpec] = PrivateAttr(default_factory=dict)

    def model_post_init(self, context: Any, /) -> None:
        paths = [spec.field_path for spec in self.fields]
        duplicates = sorted({path for path in paths if paths.count(path) > 1})
        if duplicates:
            raise CardSchemaError(f"card schema {self.schema_id}: duplicate paths {duplicates}")
        group_ids = {group.id for group in self.groups}
        for spec in self.fields:
            if spec.group is not None and spec.group not in group_ids:
                raise CardSchemaError(
                    f"card schema {self.schema_id}: {spec.field_path} names unknown group "
                    f"{spec.group!r}"
                )
            if spec.visible_when is not None:
                for path in _condition_paths(spec.visible_when):
                    if path not in paths:
                        raise CardSchemaError(
                            f"card schema {self.schema_id}: {spec.field_path}.visible_when "
                            f"names unknown path {path!r}"
                        )
        self._by_path = MappingProxyType({spec.field_path: spec for spec in self.fields})

    def spec(self, field_path: str) -> CardFieldSpec | None:
        """The field at `field_path`, or `None` when the schema has no such field."""
        return self._by_path.get(field_path)

    def __contains__(self, field_path: object) -> bool:
        return isinstance(field_path, str) and field_path in self._by_path

    @property
    def field_paths(self) -> tuple[str, ...]:
        return tuple(spec.field_path for spec in self.fields)

    def visible(self, field_path: str, values: Mapping[str, FactValue]) -> bool:
        """Is the field shown for these values? Advisory only (hidden fields are accepted)."""
        spec = self.spec(field_path)
        if spec is None or spec.visible_when is None:
            return spec is not None
        return evaluate_condition(spec.visible_when, values)


def _with_orders(fields: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Give every field without an explicit `order` its position inside its group."""
    positions: dict[str | None, int] = {}
    ordered: list[dict[str, Any]] = []
    for raw in fields:
        item = dict(raw)
        group = item.get("group")
        position = positions.get(group, 0)
        positions[group] = position + 1
        if item.get("order") is None:
            item["order"] = position
        ordered.append(item)
    return ordered


def parse_card_schema(document: Mapping[str, Any], *, sha256: str | None = None) -> CardSchema:
    """A schema document (`reference/card-schema/<id>.yaml`, parsed) as a `CardSchema`.

    Keys other than `schema_id`, `groups` and `fields` (e.g. `source`) are provenance and ignored.
    Raises `CardSchemaError` on a malformed document.
    """
    try:
        fields = document["fields"]
        return CardSchema(
            schema_id=str(document["schema_id"]),
            fields=tuple(CardFieldSpec.model_validate(item) for item in _with_orders(fields)),
            groups=tuple(
                CardFieldGroup.model_validate(item) for item in document.get("groups") or ()
            ),
            sha256=sha256,
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, CardSchemaError):
            raise
        raise CardSchemaError(f"malformed card schema document: {error}") from error


def build_card_schema(
    schema_id: str, fields: Sequence[CardFieldSpec], *, sha256: str | None = None
) -> CardSchema:
    """A schema from code-backed specs, each given its neutral `order` (its position)."""
    return CardSchema(
        schema_id=schema_id,
        fields=tuple(spec.model_copy(update={"order": index}) for index, spec in enumerate(fields)),
        sha256=sha256,
    )


_ENUM_REGISTRY: Mapping[str, type[Enum]] = MappingProxyType(
    {"IncidentType": IncidentType, "CallerRelationship": CallerRelationship}
)
"""The code-backed enums a v1 `ENUM` field names; a v2 `ENUM` field carries `options` instead."""


def _matches_type(value: FactValue, spec: CardFieldSpec) -> bool:
    if spec.value_type is ValueType.STRING:
        return isinstance(value, str)
    if spec.value_type is ValueType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if spec.value_type is ValueType.FLOAT:
        return isinstance(value, float)
    if spec.value_type is ValueType.BOOLEAN:
        return isinstance(value, bool)
    if spec.value_type is ValueType.ENUM:
        if not isinstance(value, str):
            return False
        if spec.options is not None:
            return True  # the option check below decides
        enum_cls = _ENUM_REGISTRY.get(spec.enum_name or "")
        return enum_cls is not None and any(value == member.value for member in enum_cls)
    if spec.value_type is ValueType.STRING_LIST:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False


def check_value(spec: CardFieldSpec, value: FactValue) -> None:
    """Raise unless `value` fits `spec`: `CardFieldError` for a `value_type` mismatch,
    `CardOptionUnknownError` for a code that is not one of the field's options (a v2 `ENUM`, or
    an item of a `STRING_LIST` with options), `CardValueTooLongError` for a string longer than the
    field's `max_length`. A `BOOLEAN` field's single option is its code, not a value set, so it
    constrains nothing here."""
    if not _matches_type(value, spec):
        raise CardFieldError(
            f"value {value!r} does not match value_type {spec.value_type!r} "
            f"for field {spec.field_path!r}"
        )
    if spec.max_length is not None and isinstance(value, str) and len(value) > spec.max_length:
        raise CardValueTooLongError(
            f"a value of {len(value)} characters is longer than max_length {spec.max_length} "
            f"of field {spec.field_path!r}"
        )
    if spec.options is None or spec.value_type is ValueType.BOOLEAN:
        return
    codes = spec.option_codes
    items = value if isinstance(value, list) else [value]
    unknown = [item for item in items if item not in codes]
    if unknown:
        raise CardOptionUnknownError(f"{unknown!r} is not an option of field {spec.field_path!r}")

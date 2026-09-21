"""The five `comparison` modes and the "is this value filled in" test (§10.14 #2, #3, #4, #10).

One module, pure and total over every `FactValue` shape (`str | int | float | bool | list[str] |
None`): `CARD_FIELD_CORRECT` and `CARD_CONTRADICTION` name the same five modes, and two copies of
"are these equal" would be two chances for the stored and the recomputed number to disagree
(SPEC §28).

Nothing here raises. A mode that cannot be applied to the pair it is given (a
`NUMERIC_TOLERANCE` over two words, a `SET_EQUAL` over a boolean) answers "not equal" rather than
exploding: a scenario author's mistake must show up as a lost point with evidence, not as a
`score()` that cannot produce a report at all.
"""

from __future__ import annotations

from typing import Literal

from app.domain.common.values import FactValue

Comparison = Literal[
    "EXACT", "CASE_INSENSITIVE", "NUMERIC_TOLERANCE", "SET_EQUAL", "NORMALIZED_DIGITS"
]

__all__ = ["Comparison", "compare", "is_present", "render_value"]


def compare(
    actual: FactValue,
    expected: FactValue,
    *,
    mode: Comparison,
    tolerance: float = 0.0,
) -> bool:
    """`True` when `actual` equals `expected` under `mode` (§10.14 #2)."""
    match mode:
        case "EXACT":
            return _exact(actual, expected)
        case "CASE_INSENSITIVE":
            return _case_insensitive(actual, expected)
        case "NUMERIC_TOLERANCE":
            return _numeric(actual, expected, tolerance)
        case "SET_EQUAL":
            return _set_equal(actual, expected)
        case "NORMALIZED_DIGITS":
            return _normalized_digits(actual, expected)


def is_present(value: FactValue, *, treat_false_as_present: bool = True) -> bool:
    """`True` when the field counts as filled in (§10.14 #3, #10).

    `None` is never present. A string is present when it holds something other than whitespace;
    a list when it is non-empty; a number always. `False` is present only when
    `treat_false_as_present` — "no gas cylinder on the balcony" is an answer, but a scenario may
    prefer to treat an untouched checkbox as a gap.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return bool(value) or treat_false_as_present
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return True


def render_value(value: FactValue) -> str:
    """A short, deterministic rendering of a card or fact value for a `note_ru` string."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)


# ---------------------------------------------------------------------------------------------
# The five modes.
# ---------------------------------------------------------------------------------------------


def _as_text(value: FactValue) -> str | None:
    """A scalar rendered as text; `None` for `None` and for list values."""
    if value is None or isinstance(value, list):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _as_number(value: FactValue) -> float | None:
    """A scalar read as a number, or `None` when it is not one. `bool` is not a number here."""
    if isinstance(value, bool) or value is None or isinstance(value, list):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(value.replace(",", ".").strip())
    except ValueError:
        return None


def _as_set(value: FactValue) -> frozenset[str] | None:
    """A value read as a set of normalised strings, or `None` when it is not set-shaped."""
    if value is None:
        return None
    if isinstance(value, list):
        return frozenset(item.strip().casefold() for item in value)
    text = _as_text(value)
    if text is None:
        return None
    return frozenset(part.strip().casefold() for part in text.split(",") if part.strip())


def _exact(actual: FactValue, expected: FactValue) -> bool:
    if isinstance(actual, list) or isinstance(expected, list):
        return actual == expected
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    if isinstance(actual, int | float) and isinstance(expected, int | float):
        return float(actual) == float(expected)
    return _as_text(actual) == _as_text(expected)


def _case_insensitive(actual: FactValue, expected: FactValue) -> bool:
    left, right = _as_text(actual), _as_text(expected)
    if left is None or right is None:
        return _exact(actual, expected)
    return left.strip().casefold() == right.strip().casefold()


def _numeric(actual: FactValue, expected: FactValue, tolerance: float) -> bool:
    left, right = _as_number(actual), _as_number(expected)
    if left is None or right is None:
        return False
    return abs(left - right) <= abs(tolerance)


def _set_equal(actual: FactValue, expected: FactValue) -> bool:
    left, right = _as_set(actual), _as_set(expected)
    if left is None or right is None:
        return False
    return left == right


def _normalized_digits(actual: FactValue, expected: FactValue) -> bool:
    left, right = _as_text(actual), _as_text(expected)
    if left is None or right is None:
        return False
    left_digits = "".join(character for character in left if character.isdigit())
    right_digits = "".join(character for character in right if character.isdigit())
    if not left_digits or not right_digits:
        # Nothing to normalise on one side: "дом 27" vs "двадцать семь" is not a digit match.
        return False
    return left_digits == right_digits

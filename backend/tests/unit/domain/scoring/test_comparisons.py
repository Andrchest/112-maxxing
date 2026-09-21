"""`app.domain.scoring.comparisons` — the five modes and `is_present` (HLD §10.14 #2, #3).

Every mode is exercised on a match, a mismatch and a shape it cannot handle, because the contract
is that the module is *total*: a scenario author's mistake becomes a lost point with evidence, not
a `score()` that cannot produce a report.
"""

from __future__ import annotations

import pytest
from app.domain.common.values import FactValue
from app.domain.scoring.comparisons import Comparison, compare, is_present, render_value


@pytest.mark.parametrize(
    ("mode", "actual", "expected", "tolerance", "equal"),
    [
        ("EXACT", "27", "27", 0.0, True),
        ("EXACT", "27", "72", 0.0, False),
        ("EXACT", 27, 27.0, 0.0, True),
        ("EXACT", True, 1, 0.0, False),
        ("EXACT", ["a", "b"], ["a", "b"], 0.0, True),
        ("EXACT", ["a", "b"], ["b", "a"], 0.0, False),
        ("CASE_INSENSITIVE", " Смоленск ", "смоленск", 0.0, True),
        ("CASE_INSENSITIVE", "Смоленск", "Вязьма", 0.0, False),
        ("CASE_INSENSITIVE", ["a"], ["a"], 0.0, True),
        ("NUMERIC_TOLERANCE", 78, 80, 2.0, True),
        ("NUMERIC_TOLERANCE", 78, 81, 2.0, False),
        ("NUMERIC_TOLERANCE", "4,5", "4.5", 0.0, True),
        ("NUMERIC_TOLERANCE", "четыре", 4, 0.0, False),
        ("NUMERIC_TOLERANCE", True, 1, 0.0, False),
        ("SET_EQUAL", ["FIRE_RESCUE", "AMBULANCE"], ["AMBULANCE", "FIRE_RESCUE"], 0.0, True),
        ("SET_EQUAL", ["FIRE_RESCUE"], ["AMBULANCE"], 0.0, False),
        ("SET_EQUAL", "a, b", ["b", "a"], 0.0, True),
        ("SET_EQUAL", None, ["a"], 0.0, False),
        ("NORMALIZED_DIGITS", "д. 27", "27", 0.0, True),
        ("NORMALIZED_DIGITS", "27", "72", 0.0, False),
        ("NORMALIZED_DIGITS", "двадцать семь", "27", 0.0, False),
        ("NORMALIZED_DIGITS", ["27"], "27", 0.0, False),
    ],
)
def test_every_comparison_mode(
    mode: Comparison,
    actual: FactValue,
    expected: FactValue,
    tolerance: float,
    equal: bool,
) -> None:
    assert compare(actual, expected, mode=mode, tolerance=tolerance) is equal


@pytest.mark.parametrize("mode", ["EXACT", "CASE_INSENSITIVE", "SET_EQUAL", "NORMALIZED_DIGITS"])
def test_every_mode_is_total_over_none(mode: Comparison) -> None:
    """A `None` on either side answers, it never raises."""
    assert compare(None, None, mode=mode) in (True, False)
    assert compare(None, "27", mode=mode) in (True, False)


@pytest.mark.parametrize(
    ("value", "treat_false_as_present", "present"),
    [
        (None, True, False),
        ("", True, False),
        ("   ", True, False),
        ("27", True, True),
        ([], True, False),
        (["a"], True, True),
        (0, True, True),
        (False, True, True),
        (False, False, False),
        (True, False, True),
    ],
)
def test_is_present(value: FactValue, treat_false_as_present: bool, present: bool) -> None:
    assert is_present(value, treat_false_as_present=treat_false_as_present) is present


def test_render_value_is_deterministic_and_russian() -> None:
    assert render_value(None) == "—"
    assert render_value(True) == "да"
    assert render_value(False) == "нет"
    assert render_value(["a", "b"]) == "a, b"
    assert render_value(27) == "27"

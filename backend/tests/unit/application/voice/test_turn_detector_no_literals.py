"""SPEC §17's other half: the detector holds no magic value (D9, HLD §4.1).

"Make this configuration, not a hard-coded magic value" is only enforceable if something checks.
A parametrised behaviour test catches a hard-coded *endpoint*; this `ast` scan catches the next
one before it is written, by refusing any numeric literal in `turn_detector.py` other than `0`
and `1` — the two that are structural (a cleared counter, a step of one turn index) rather than
tunable.
"""

from __future__ import annotations

import ast
from pathlib import Path

import app.application.voice.turn_detector as turn_detector_module

ALLOWED_NUMBERS: frozenset[int] = frozenset({0, 1})


def test_turn_detector_contains_no_tunable_numeric_literal() -> None:
    """Every threshold, window and duration must come from `VoiceTurnConfig`."""
    source_path = Path(turn_detector_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))

    offenders: list[tuple[int, object]] = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)
        and node.value not in ALLOWED_NUMBERS
    ]

    assert not offenders, (
        "turn_detector.py must read every tunable from VoiceTurnConfig (SPEC §17); "
        f"numeric literals found at {offenders}"
    )

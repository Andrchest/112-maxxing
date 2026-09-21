"""`app.inference.tts.instruct.build_instruct` — pure, table-driven, no LLM/caller text ever
reaches it (this task's brief, item 2)."""

from __future__ import annotations

import itertools

import pytest
from app.domain.caller.emotion import EmotionState
from app.domain.enums import EmotionLabel
from app.inference.tts.instruct import build_instruct, stress_bucket


@pytest.mark.parametrize(
    ("stress_level", "expected"),
    [
        (0.0, "low"),
        (0.1, "low"),
        (0.33, "low"),
        (0.34, "medium"),
        (0.5, "medium"),
        (0.66, "medium"),
        (0.6667, "high"),
        (0.9, "high"),
        (1.0, "high"),
    ],
)
def test_stress_bucket_thirds(stress_level: float, expected: str) -> None:
    assert stress_bucket(stress_level) == expected


@pytest.mark.parametrize(
    ("emotion", "stress_level"),
    list(itertools.product(list(EmotionLabel), [0.0, 0.5, 1.0])),
)
def test_every_label_and_bucket_has_an_entry(emotion: EmotionLabel, stress_level: float) -> None:
    text = build_instruct(EmotionState(emotion=emotion, stress_level=stress_level))
    assert text.startswith("Speak in a ")
    assert text.endswith(" manner.")


def test_deterministic() -> None:
    state = EmotionState(emotion=EmotionLabel.PANICKED, stress_level=0.95)
    assert build_instruct(state) == build_instruct(state)


def test_distinct_labels_produce_distinct_text_at_the_same_stress_bucket() -> None:
    texts = {
        build_instruct(EmotionState(emotion=label, stress_level=0.9)) for label in EmotionLabel
    }
    assert len(texts) == len(list(EmotionLabel))


def test_output_is_english_ascii_never_the_russian_trainee_facing_alphabet() -> None:
    for emotion in EmotionLabel:
        for stress in (0.0, 0.5, 1.0):
            text = build_instruct(EmotionState(emotion=emotion, stress_level=stress))
            assert text.isascii()

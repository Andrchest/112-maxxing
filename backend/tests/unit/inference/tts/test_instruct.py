"""`app.inference.tts.instruct.build_instruct` — pure, table-driven, no LLM/caller text ever
reaches it (this task's brief, item 2). I8 V0: style version 2, the owner's evaluated presets."""

from __future__ import annotations

import itertools

import pytest
from app.domain.caller.emotion import EmotionState
from app.domain.enums import CallerVoiceStyle, EmotionLabel
from app.inference.tts.instruct import (
    STYLE_PRESETS,
    STYLE_VERSION,
    build_instruct,
    preset_name,
    stress_bucket,
)

#: The emo-lab `STYLE_PRESETS` strings (`~/emo-lab/tools/qwen_studio.py`, commit 5a02e3e8),
#: repeated here so a rewording in `instruct.py` fails the gate (the lab's "never reword" rule).
_LAB_PRESETS = {
    "calm_fast": (
        "Speak quickly and matter-of-factly, like a real person dictating an address over the "
        "phone, without pauses."
    ),
    "panic_fast": (
        "Speak very fast and breathlessly, in panic, like a real person on an emergency call, "
        "words rushing out with no pauses."
    ),
    "fear": "Speak in a frightened, trembling voice, as if terrified and on the verge of tears.",
    "pain_gasp": (
        "Speak in severe physical pain: short words forced out through groans, heavy breathing "
        "between phrases, the voice tight and strained."
    ),
    "anger": "Speak angrily and forcefully, with a raised, sharp voice.",
}


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


def test_style_version_is_two_and_the_presets_are_the_lab_strings_verbatim() -> None:
    assert STYLE_VERSION == 2
    assert STYLE_PRESETS == _LAB_PRESETS


def test_no_chinese_preset_is_reachable() -> None:
    assert not any(name.endswith("_zh") for name in STYLE_PRESETS)


@pytest.mark.parametrize(
    ("emotion", "stress_level"),
    list(itertools.product(list(EmotionLabel), [0.0, 0.5, 1.0])),
)
def test_every_label_and_bucket_has_a_preset(emotion: EmotionLabel, stress_level: float) -> None:
    state = EmotionState(emotion=emotion, stress_level=stress_level)
    assert preset_name(state) in STYLE_PRESETS
    assert build_instruct(state) == STYLE_PRESETS[preset_name(state)]


@pytest.mark.parametrize(
    ("emotion", "low_medium", "high"),
    [
        (EmotionLabel.CALM, "calm_fast", "calm_fast"),
        (EmotionLabel.WORRIED, "calm_fast", "fear"),
        (EmotionLabel.FRIGHTENED, "fear", "fear"),
        (EmotionLabel.PANICKED, "panic_fast", "panic_fast"),
        (EmotionLabel.ANGRY, "anger", "anger"),
        (EmotionLabel.CONFUSED, "calm_fast", "fear"),
        (EmotionLabel.APATHETIC, "calm_fast", "calm_fast"),
    ],
)
def test_the_table_is_plan_section_2_4(emotion: EmotionLabel, low_medium: str, high: str) -> None:
    assert preset_name(EmotionState(emotion=emotion, stress_level=0.0)) == low_medium
    assert preset_name(EmotionState(emotion=emotion, stress_level=0.5)) == low_medium
    assert preset_name(EmotionState(emotion=emotion, stress_level=1.0)) == high


@pytest.mark.parametrize("emotion", list(EmotionLabel))
def test_pain_voice_style_overrides_every_emotion(emotion: EmotionLabel) -> None:
    state = EmotionState(emotion=emotion, stress_level=0.9)
    assert preset_name(state, CallerVoiceStyle.PAIN) == "pain_gasp"
    assert build_instruct(state, CallerVoiceStyle.PAIN) == STYLE_PRESETS["pain_gasp"]


def test_every_voice_style_has_a_preset() -> None:
    state = EmotionState(emotion=EmotionLabel.CALM, stress_level=0.0)
    for style in CallerVoiceStyle:
        assert build_instruct(state, style) in STYLE_PRESETS.values()


def test_deterministic() -> None:
    state = EmotionState(emotion=EmotionLabel.PANICKED, stress_level=0.95)
    assert build_instruct(state) == build_instruct(state)


def test_output_is_english_ascii_never_the_russian_trainee_facing_alphabet() -> None:
    for emotion in EmotionLabel:
        for stress in (0.0, 0.5, 1.0):
            text = build_instruct(EmotionState(emotion=emotion, stress_level=stress))
            assert text.isascii()
    for text in STYLE_PRESETS.values():
        assert text.isascii()

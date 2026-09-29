"""`build_instruct` — `EmotionState` -> the English "instruct" sentence Qwen3-TTS CustomVoice
expects (`app.inference.tts.qwen3_tts`, this task's brief item 2, MANAGER RULING 3-adjacent).

Qwen3-TTS CustomVoice has no native prosody/pitch/rate controls (recon §1.1, §6 item 6): the only
expressive lever is a free-form English `instruct` string, e.g. the owner's own worker's
`"Speak in a alarmed and fearful, urgent, and hesitant manner."` (recon §1.1,
`tools/qwen3_tts_worker.py:143-145`). Two rules keep this from becoming an LLM-controlled text
channel, which SPEC forbids the caller pipeline from ever exposing:

* **The input is `EmotionState` only** — `emotion` (`app.domain.enums.EmotionLabel`, a closed
  7-value enum) and `stress_level` (`float`, `[0.0, 1.0]`), both simulation state written only by
  deterministic `EmotionRule`s (`app.domain.caller.emotion`, D4). No LLM output, no caller-typed
  text and no scenario-authored free text ever reaches this function — there is no parameter for
  any of them.
* **The output is a lookup into a fixed table**, not a template interpolating anything: every one
  of the 7 labels x 3 stress buckets names one preset below, so the full output space is
  enumerable and reviewable in one place, not generated at runtime.

I8 V0 (style version 2, `STYLE_VERSION`): the presets are the instruction sentences the owner
evaluated by ear in his TTS lab, copied VERBATIM from `~/emo-lab/tools/qwen_studio.py`
`STYLE_PRESETS` at emo-lab commit `5a02e3e838da2573bde3c9deb65635532ff69fc6` — never reworded
(the lab's rule: a reworded preset is a new style version). The table is the I8 A1 plan §2.4. The
`*_zh` presets are excluded by construction (not in `STYLE_PRESETS`). The one input besides
`EmotionState` is `CallerVoiceStyle` — a closed scenario enum (`caller_profile.voice_style`), still
no free text.

Pure, deterministic, no I/O — unit-tested directly (`backend/tests/unit/inference/tts/
test_instruct.py`), no `qwen-tts`/`torch` import anywhere near it.
"""

from __future__ import annotations

from app.domain.caller.emotion import EmotionState
from app.domain.enums import CallerVoiceStyle, EmotionLabel

__all__ = [
    "STYLE_PRESETS",
    "STYLE_VERSION",
    "StressBucket",
    "build_instruct",
    "preset_name",
    "stress_bucket",
]

StressBucket = str  # "low" | "medium" | "high" — see `stress_bucket()`

#: Bumped whenever a preset text or the table below changes (the lab's "never reword between
#: runs" rule). 1 was the E14-B `"Speak in a {descriptor} manner."` table.
STYLE_VERSION = 2

#: Thirds of the `[0.0, 1.0]` range `EmotionState.stress_level` is defined over
#: (`app.domain.caller.emotion.EmotionState`, `Field(ge=0.0, le=1.0)`). `<` on the low bound and
#: `<=` nowhere: every value in `[0.0, 1.0]` lands in exactly one bucket.
_LOW_MAX = 1.0 / 3.0
_MEDIUM_MAX = 2.0 / 3.0

#: VERBATIM from `~/emo-lab/tools/qwen_studio.py` `STYLE_PRESETS` (emo-lab commit `5a02e3e8`);
#: see the module docstring. Do not edit a string here without bumping `STYLE_VERSION`.
STYLE_PRESETS: dict[str, str] = {
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
    # NOT owner-rated: the lab's `anger` preset was never listened to by the owner (A1 §2.4, §5
    # Q6); it is used for ANGRY until the owner's listening set (I8 V5) decides.
    "anger": "Speak angrily and forcefully, with a raised, sharp voice.",
}

#: `(EmotionLabel, StressBucket) -> STYLE_PRESETS key` (A1 §2.4). CONFUSED does not use the lab's
#: `confused` preset: it asks for "long pauses", the opposite of the owner's main complaint.
_PRESET_TABLE: dict[tuple[EmotionLabel, StressBucket], str] = {
    (EmotionLabel.CALM, "low"): "calm_fast",
    (EmotionLabel.CALM, "medium"): "calm_fast",
    (EmotionLabel.CALM, "high"): "calm_fast",
    (EmotionLabel.WORRIED, "low"): "calm_fast",
    (EmotionLabel.WORRIED, "medium"): "calm_fast",
    (EmotionLabel.WORRIED, "high"): "fear",
    (EmotionLabel.FRIGHTENED, "low"): "fear",
    (EmotionLabel.FRIGHTENED, "medium"): "fear",
    (EmotionLabel.FRIGHTENED, "high"): "fear",
    (EmotionLabel.PANICKED, "low"): "panic_fast",
    (EmotionLabel.PANICKED, "medium"): "panic_fast",
    (EmotionLabel.PANICKED, "high"): "panic_fast",
    (EmotionLabel.ANGRY, "low"): "anger",
    (EmotionLabel.ANGRY, "medium"): "anger",
    (EmotionLabel.ANGRY, "high"): "anger",
    (EmotionLabel.CONFUSED, "low"): "calm_fast",
    (EmotionLabel.CONFUSED, "medium"): "calm_fast",
    (EmotionLabel.CONFUSED, "high"): "fear",
    (EmotionLabel.APATHETIC, "low"): "calm_fast",
    (EmotionLabel.APATHETIC, "medium"): "calm_fast",
    (EmotionLabel.APATHETIC, "high"): "calm_fast",
}

#: `CallerVoiceStyle -> STYLE_PRESETS key`: a scenario style hint overrides the emotion table.
_VOICE_STYLE_PRESETS: dict[CallerVoiceStyle, str] = {
    CallerVoiceStyle.PAIN: "pain_gasp",
}


def stress_bucket(stress_level: float) -> StressBucket:
    """`[0.0, 1.0]` -> `"low"` / `"medium"` / `"high"`, in equal thirds."""
    if stress_level < _LOW_MAX:
        return "low"
    if stress_level < _MEDIUM_MAX:
        return "medium"
    return "high"


def preset_name(emotion: EmotionState, voice_style: CallerVoiceStyle | None = None) -> str:
    """The `STYLE_PRESETS` key for this turn: the scenario's `voice_style` when it has one, else
    `(emotion.emotion, stress_bucket(emotion.stress_level))`'s table entry."""
    if voice_style is not None:
        return _VOICE_STYLE_PRESETS[voice_style]
    return _PRESET_TABLE[(emotion.emotion, stress_bucket(emotion.stress_level))]


def build_instruct(emotion: EmotionState, voice_style: CallerVoiceStyle | None = None) -> str:
    """`EmotionState` (+ the scenario's closed `voice_style`) -> the `instruct` string sent to
    Qwen3-TTS CustomVoice.

    A pure table lookup — every `(EmotionLabel, bucket)` and every `CallerVoiceStyle` has an
    entry, so this never raises for a valid `EmotionState`.
    """
    return STYLE_PRESETS[preset_name(emotion, voice_style)]

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
  of the 7 labels x 3 stress buckets has its own literal English descriptor below, so the full
  output space is enumerable and reviewable in one place, not generated at runtime.

Pure, deterministic, no I/O — unit-tested directly (`backend/tests/unit/inference/tts/
test_instruct.py`), no `qwen-tts`/`torch` import anywhere near it.
"""

from __future__ import annotations

from app.domain.caller.emotion import EmotionState
from app.domain.enums import EmotionLabel

__all__ = ["StressBucket", "build_instruct", "stress_bucket"]

StressBucket = str  # "low" | "medium" | "high" — see `stress_bucket()`

#: Thirds of the `[0.0, 1.0]` range `EmotionState.stress_level` is defined over
#: (`app.domain.caller.emotion.EmotionState`, `Field(ge=0.0, le=1.0)`). `<` on the low bound and
#: `<=` nowhere: every value in `[0.0, 1.0]` lands in exactly one bucket.
_LOW_MAX = 1.0 / 3.0
_MEDIUM_MAX = 2.0 / 3.0

#: `(EmotionLabel, StressBucket) -> English descriptor`, dropped into `"Speak in a {descriptor}
#: manner."`. Every one of the 7 labels x 3 buckets is a distinct, hand-written entry — no
#: interpolation, no string formatting of caller/scenario text (see module docstring).
_INSTRUCT_TABLE: dict[tuple[EmotionLabel, StressBucket], str] = {
    (EmotionLabel.CALM, "low"): "calm and composed",
    (EmotionLabel.CALM, "medium"): "calm but attentive",
    (EmotionLabel.CALM, "high"): "calm under pressure",
    (EmotionLabel.WORRIED, "low"): "mildly worried",
    (EmotionLabel.WORRIED, "medium"): "worried and uneasy",
    (EmotionLabel.WORRIED, "high"): "worried and anxious",
    (EmotionLabel.FRIGHTENED, "low"): "slightly frightened",
    (EmotionLabel.FRIGHTENED, "medium"): "frightened and unsettled",
    (EmotionLabel.FRIGHTENED, "high"): "frightened and trembling",
    (EmotionLabel.PANICKED, "low"): "on edge and panicked",
    (EmotionLabel.PANICKED, "medium"): "panicked and rushed",
    (EmotionLabel.PANICKED, "high"): "panicked and hysterical",
    (EmotionLabel.ANGRY, "low"): "irritated",
    (EmotionLabel.ANGRY, "medium"): "angry and sharp",
    (EmotionLabel.ANGRY, "high"): "angry and shouting",
    (EmotionLabel.CONFUSED, "low"): "a little confused",
    (EmotionLabel.CONFUSED, "medium"): "confused and hesitant",
    (EmotionLabel.CONFUSED, "high"): "confused and disoriented",
    (EmotionLabel.APATHETIC, "low"): "flat and apathetic",
    (EmotionLabel.APATHETIC, "medium"): "apathetic and detached",
    (EmotionLabel.APATHETIC, "high"): "apathetic and numb",
}


def stress_bucket(stress_level: float) -> StressBucket:
    """`[0.0, 1.0]` -> `"low"` / `"medium"` / `"high"`, in equal thirds."""
    if stress_level < _LOW_MAX:
        return "low"
    if stress_level < _MEDIUM_MAX:
        return "medium"
    return "high"


def build_instruct(emotion: EmotionState) -> str:
    """`EmotionState` -> the `instruct` string sent to Qwen3-TTS CustomVoice.

    A pure table lookup keyed by `(emotion.emotion, stress_bucket(emotion.stress_level))` — every
    key is present in `_INSTRUCT_TABLE` for every `EmotionLabel`, so this never raises for a valid
    `EmotionState`.
    """
    descriptor = _INSTRUCT_TABLE[(emotion.emotion, stress_bucket(emotion.stress_level))]
    return f"Speak in a {descriptor} manner."

"""`CallerProfile` (HLD `10-domain-model.md` §10.5, SPEC §6, D4).

Scenario data describing the simulated caller persona; `baseline_emotion` never mutates.
`current_emotion` and `stress_level` are deliberately not fields here — per D4 they live in
`CallerBelief.emotion` as an `EmotionState` and change only through `apply_emotion_rules`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import AgeGroup, CallerRelationship, EmotionLabel


class CallerProfile(BaseModel):
    """Every SPEC §6 field except `current_emotion`/`stress_level` (D4)."""

    model_config = ConfigDict(extra="forbid")

    identity_ru: str
    relationship: CallerRelationship
    language: str
    voice_id: str
    age_group: AgeGroup
    baseline_emotion: EmotionLabel
    cooperativeness: float = Field(ge=0.0, le=1.0)
    verbosity: float = Field(ge=0.0, le=1.0)
    confusion: float = Field(ge=0.0, le=1.0)
    interruption_tendency: float = Field(ge=0.0, le=1.0)
    speaking_rate: float = Field(ge=0.5, le=2.0)
    baseline_stress_level: float = Field(ge=0.0, le=1.0)
    persona_whitelist_ru: tuple[str, ...] = ()

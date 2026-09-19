"""Tests for `app.domain.caller.profile.CallerProfile` (HLD `10-domain-model.md` §10.5, SPEC §6).

Range validation for every bounded float field: `cooperativeness`, `verbosity`, `confusion`,
`interruption_tendency`, `baseline_stress_level` (0.0-1.0) and `speaking_rate` (0.5-2.0).
"""

from __future__ import annotations

import pytest
from app.domain.caller.profile import CallerProfile
from app.domain.enums import AgeGroup, CallerRelationship, EmotionLabel
from pydantic import ValidationError

ZERO_ONE_FIELDS = (
    "cooperativeness",
    "verbosity",
    "confusion",
    "interruption_tendency",
    "baseline_stress_level",
)


def _base_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "identity_ru": "Соседка из квартиры 41",
        "relationship": CallerRelationship.NEIGHBOUR,
        "language": "ru-RU",
        "voice_id": "voice-1",
        "age_group": AgeGroup.ADULT,
        "baseline_emotion": EmotionLabel.WORRIED,
        "cooperativeness": 0.5,
        "verbosity": 0.5,
        "confusion": 0.5,
        "interruption_tendency": 0.5,
        "speaking_rate": 1.0,
        "baseline_stress_level": 0.5,
    }
    kwargs.update(overrides)
    return kwargs


def test_caller_profile_constructs_with_valid_values() -> None:
    profile = CallerProfile(**_base_kwargs())  # type: ignore[arg-type]
    assert profile.relationship is CallerRelationship.NEIGHBOUR
    assert profile.persona_whitelist_ru == ()


@pytest.mark.parametrize("field", ZERO_ONE_FIELDS)
@pytest.mark.parametrize("value", [0.0, 1.0, 0.5])
def test_zero_one_fields_accept_the_valid_range(field: str, value: float) -> None:
    CallerProfile(**_base_kwargs(**{field: value}))  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ZERO_ONE_FIELDS)
@pytest.mark.parametrize("value", [-0.01, 1.01, -1.0, 2.0])
def test_zero_one_fields_reject_out_of_range(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        CallerProfile(**_base_kwargs(**{field: value}))  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0.5, 2.0, 1.0])
def test_speaking_rate_accepts_the_valid_range(value: float) -> None:
    CallerProfile(**_base_kwargs(speaking_rate=value))  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0.49, 2.01, 0.0, 3.0])
def test_speaking_rate_rejects_out_of_range(value: float) -> None:
    with pytest.raises(ValidationError):
        CallerProfile(**_base_kwargs(speaking_rate=value))  # type: ignore[arg-type]


def test_caller_profile_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CallerProfile(**_base_kwargs(bogus=True))  # type: ignore[arg-type]


def test_caller_profile_has_no_current_emotion_or_stress_level_field() -> None:
    # D4: current_emotion / stress_level live in CallerBelief.emotion, not here.
    assert "current_emotion" not in CallerProfile.model_fields
    assert "stress_level" not in CallerProfile.model_fields

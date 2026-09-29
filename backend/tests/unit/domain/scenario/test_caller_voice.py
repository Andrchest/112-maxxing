"""I8 V0: the caller's voice in the scenario — `caller_profile.voice_style` (schema 2, closed enum,
only `PAIN`) and the voice-id warnings (an adult voice for an ELDERLY caller; a voice gender the
`identity_ru` surname contradicts). Warnings, never violations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.domain.enums import CallerVoiceStyle
from app.domain.scenario.validation import (
    scenario_version_warnings,
    validate_scenario_document,
)
from app.domain.scenario.version import ScenarioVersion
from app.infrastructure.scenarios.yaml_loader import discover, load_scenario_version

from tests.fixtures.scenarios import demo_document

TICKETS_DIR = Path(__file__).resolve().parents[5] / "scenarios" / "tickets"
#: The «Пострадавший, звонит сам» tickets — the injured person calls about themselves.
PAIN_TICKETS = frozenset(
    {
        "ticket-06-call-2",
        "ticket-07-call-2",
        "ticket-11-call-3",
        "ticket-15-call-3",
        "ticket-21-call-2",
        "ticket-23-call-2",
        "ticket-23-call-2-card-error",
        "ticket-29-call-3",
    }
)


def _schema_2(document: dict[str, Any]) -> dict[str, Any]:
    document["schema_version"] = 2
    return document


def test_a_schema_2_document_with_voice_style_loads_and_dumps_it() -> None:
    document = _schema_2(demo_document())
    document["caller_profile"]["voice_style"] = "PAIN"
    assert validate_scenario_document(document) == []
    version = ScenarioVersion.model_validate(document)
    assert version.caller_profile.voice_style is CallerVoiceStyle.PAIN
    assert version.model_dump(mode="json")["caller_profile"]["voice_style"] == "PAIN"


def test_a_document_without_voice_style_dumps_without_the_key() -> None:
    """P5/D4: a document written before I8 keeps its canonical dump, hence its sha."""
    version = ScenarioVersion.model_validate(demo_document())
    assert version.caller_profile.voice_style is None
    assert "voice_style" not in version.model_dump(mode="json")["caller_profile"]


def test_r01_refuses_voice_style_in_a_schema_1_document() -> None:
    document = demo_document()
    document["caller_profile"]["voice_style"] = "PAIN"
    violations = validate_scenario_document(document)
    assert violations
    assert all(violation.startswith("R01:") for violation in violations)
    assert any("voice_style" in violation for violation in violations)


def test_an_unknown_voice_style_is_refused() -> None:
    document = _schema_2(demo_document())
    document["caller_profile"]["voice_style"] = "WHISPER"
    violations = validate_scenario_document(document)
    assert any(violation.startswith("R01:") for violation in violations)


def _warnings(**caller_profile: Any) -> list[str]:
    document = demo_document()
    document["caller_profile"].update(caller_profile)
    return scenario_version_warnings(ScenarioVersion.model_validate(document))


def test_the_demo_scenario_has_no_voice_warning() -> None:
    assert _warnings() == []


def test_an_elderly_caller_with_an_adult_voice_warns() -> None:
    warnings = _warnings(age_group="ELDERLY")
    assert len(warnings) == 1
    assert "ELDERLY" in warnings[0]


def test_an_elderly_caller_with_an_elderly_voice_does_not_warn() -> None:
    assert _warnings(age_group="ELDERLY", voice_id="ru_female_elderly_01") == []


@pytest.mark.parametrize(
    ("identity_ru", "voice_id"),
    [
        ("Очевидец: Иванова Елена Сергеевна", "ru_male_adult_01"),
        ("Бабушка ребёнка: Степанова Антонина Марковна", "ru_male_elderly_01"),
        ("Прохожий: Соколов Иван Петрович", "ru_female_adult_01"),
        ("Заявитель: Тихий Олег Юрьевич", "ru_female_adult_01"),
        ("Хозяйка: Толстая Анна", "ru_male_adult_02"),
    ],
)
def test_a_surname_contradicting_the_voice_gender_warns(identity_ru: str, voice_id: str) -> None:
    warnings = _warnings(identity_ru=identity_ru, voice_id=voice_id)
    assert len(warnings) == 1
    assert "surname" in warnings[0]


@pytest.mark.parametrize(
    ("identity_ru", "voice_id"),
    [
        ("Очевидец: Иванова Елена Сергеевна", "ru_female_adult_01"),
        ("Прохожий: Соколов Иван Петрович", "ru_male_adult_01"),
        # No surname, or an ending that gives no gender: never guessed.
        ("Соседка Ирина Петровна из квартиры 41", "ru_male_adult_01"),
        ("Жилец дома: Ким Олег Юрьевич", "ru_female_adult_01"),
        ("Очевидец: Слобода Юрий Петрович", "ru_female_adult_01"),
        ("Мама пострадавшего ребёнка", "ru_male_adult_01"),
        # A voice id outside the logical pattern is not checked.
        ("Очевидец: Иванова Елена Сергеевна", "Serena"),
    ],
)
def test_no_warning_without_a_contradiction(identity_ru: str, voice_id: str) -> None:
    assert _warnings(identity_ru=identity_ru, voice_id=voice_id) == []


def test_the_injured_caller_tickets_carry_the_pain_style_and_only_they_do() -> None:
    styled = set()
    for path in discover(TICKETS_DIR):
        version = load_scenario_version(path)
        profile = version.caller_profile
        if profile.voice_style is not None:
            styled.add(path.parent.name)
            assert profile.voice_style is CallerVoiceStyle.PAIN
            assert profile.identity_ru.startswith("Пострадавший, звонит сам")
        else:
            assert "voice_style" not in version.model_dump(mode="json")["caller_profile"]
    assert styled == PAIN_TICKETS


def test_no_ticket_has_a_voice_gender_contradiction() -> None:
    for path in discover(TICKETS_DIR):
        warnings = scenario_version_warnings(load_scenario_version(path))
        assert not [warning for warning in warnings if "surname" in warning], path

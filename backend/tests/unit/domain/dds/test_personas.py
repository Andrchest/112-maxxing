"""The ДДС phone's personas, resolved by catalog category (I3 E6c, HLD `80-telephony.md` §80.4.1,
D24).

The persona file is reference data — `reference/personas/v1.yaml`, sha-pinned in the manifest and
named by pack `v046_24-r1` — and `resolve_persona` is pure: a scenario's override (R42) first, then
the service's catalog `code`, then its `kind`. The fixtures the E6c row names: `101`, `102`, `103`,
`104` by code and a `DISTRICT` service by kind.
"""

from __future__ import annotations

import pytest
from app.domain.dds.personas import (
    DEFAULT_ANSWER_AFTER_MS,
    Persona,
    PersonaApplies,
    PersonaCatalog,
    PersonaGender,
    resolve_persona,
)
from app.domain.dds.response import ServiceResponseStatus
from app.domain.routing.catalog import ReferenceCatalog
from app.infrastructure.reference.file_catalog import FileReferenceCatalog


@pytest.fixture(scope="module")
def reference() -> ReferenceCatalog:
    return FileReferenceCatalog().catalog()


@pytest.fixture(scope="module")
def personas(reference: ReferenceCatalog) -> PersonaCatalog:
    catalog = reference.personas("v046_24-r1")
    assert catalog is not None
    return catalog


@pytest.mark.parametrize(
    ("service_id", "persona_id", "gender", "voice_id"),
    [
        ("FIRE_RESCUE", "BRIGADE_101", PersonaGender.MALE, "ru_male_adult_01"),
        ("POLICE", "BRIGADE_102", PersonaGender.MALE, "ru_male_adult_01"),
        ("AMBULANCE", "BRIGADE_103", PersonaGender.FEMALE, "ru_female_adult_01"),
        ("GAS_SERVICE", "BRIGADE_104", PersonaGender.MALE, "ru_male_adult_02"),
        ("DDS_DISTRICT_AKADEMICHESKIY", "DDS_DISTRICT", PersonaGender.MALE, "ru_male_adult_02"),
        ("TSODD", "CITY_DEFAULT", PersonaGender.MALE, "ru_male_adult_01"),
    ],
)
def test_the_catalog_category_picks_the_persona(
    reference: ReferenceCatalog,
    personas: PersonaCatalog,
    service_id: str,
    persona_id: str,
    gender: PersonaGender,
    voice_id: str,
) -> None:
    """`code` 101…104 by code; a district ДДС and a code-less city service by kind."""
    services = reference.services("v046_24-r1")
    assert services is not None
    entry = services.get(service_id)
    assert entry is not None
    persona = resolve_persona(personas, code=entry.code, kind=entry.kind.value)
    assert persona is not None
    assert (persona.id, persona.gender, persona.voice_id) == (persona_id, gender, voice_id)


def test_code_wins_over_kind(personas: PersonaCatalog) -> None:
    """101 is a CITY service: its code persona wins over `CITY_DEFAULT`."""
    persona = resolve_persona(personas, code="101", kind="CITY")
    assert persona is not None and persona.id == "BRIGADE_101"
    fallback = resolve_persona(personas, code="999", kind="CITY")
    assert fallback is not None and fallback.id == "CITY_DEFAULT"


def test_a_scenario_override_wins_and_an_unknown_one_is_ignored(personas: PersonaCatalog) -> None:
    chosen = resolve_persona(personas, code="101", kind="CITY", override="DDS_DISTRICT")
    assert chosen is not None and chosen.id == "DDS_DISTRICT"
    unknown = resolve_persona(personas, code="101", kind="CITY", override="NO_SUCH")
    assert unknown is not None and unknown.id == "BRIGADE_101"


def test_no_personas_resolve_to_none(reference: ReferenceCatalog) -> None:
    """`legacy-r1` has no phone (schema 1 is `OFF` forever, P5)."""
    assert reference.personas("legacy-r1") is None
    assert resolve_persona(None, code="101", kind="CITY") is None


def test_every_persona_speaks_the_memo_and_answers_after_the_default(
    personas: PersonaCatalog,
) -> None:
    brigade = personas.get("BRIGADE_101")
    assert brigade is not None
    assert brigade.answer_after_ms == DEFAULT_ANSWER_AFTER_MS
    assert brigade.vocabulary[ServiceResponseStatus.ARRIVED] == "Прибыли на место"
    assert brigade.title_ru == "Начальник караула ПСЧ"
    for persona in personas.personas:
        assert persona.greeting_ru.strip()
        assert persona.voice_id.startswith("ru_")
        assert not persona.no_answer and not persona.busy


def test_a_persona_applies_to_exactly_one_of_code_and_kind() -> None:
    with pytest.raises(ValueError):
        PersonaApplies(code="101", kind="CITY")
    with pytest.raises(ValueError):
        PersonaApplies()


def test_a_persona_id_is_listed_once() -> None:
    persona = Persona(
        id="X",
        applies=PersonaApplies(code="101"),
        title_ru="Т",
        gender=PersonaGender.MALE,
        voice_id="ru_male_adult_01",
        greeting_ru="Слушаю.",
    )
    with pytest.raises(ValueError):
        PersonaCatalog(catalog_id="v1", personas=(persona, persona))

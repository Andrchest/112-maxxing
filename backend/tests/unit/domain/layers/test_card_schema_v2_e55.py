"""Card v2 fields of the card instruction (I7 E55, ТЗ gap G16; owner decisions 2026-09-29).

Every label below is verbatim from «Инструкция_по_заведению_карточки_2507ГСИ.docx» (cited in
`reference/card-schema/v2.yaml` as "instr ¶N" / "instr fig. N"):

* «Статус заявителя» carries the six statuses of instr ¶271–277, in the instruction's order;
* «Канал связи» (`applicant.channel`) is a select of the channels the instruction names, plus
  «Другое» last (owner decision 2026-09-29 No. 12);
* «Количество» (`flags.casualties_count`, INTEGER) shows only once «Пострадавшие» is on;
* «Отказ от реагирования» (`flags.response_refused`) shows only in the 103 questionnaire, is not
  routed and not scored;
* «Описание со слов заявителя» takes at most 1999 characters (the «0 / 1999» counter); a longer
  value is `CardValueTooLongError` (a `CardFieldError`: `422 CARD_VALUE_TYPE_MISMATCH`).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from app.domain.common.actors import ActorRef
from app.domain.common.errors import CardFieldError
from app.domain.common.ids import CardId, CardRevisionId, IncidentId
from app.domain.enums import ActorType, ValueType
from app.domain.layers.card_schema import (
    CardControl,
    CardFieldSpec,
    CardSchemaError,
    CardValueTooLongError,
    check_value,
    parse_card_schema,
)
from app.domain.layers.operator_card import OperatorCard, set_field

REPO_ROOT = Path(__file__).resolve().parents[5]
V2 = parse_card_schema(
    yaml.safe_load((REPO_ROOT / "reference" / "card-schema" / "v2.yaml").read_text("utf-8"))
)
TRAINEE = ActorRef(actor_type=ActorType.TRAINEE, actor_id=uuid4())


def _spec(path: str) -> CardFieldSpec:
    spec = V2.spec(path)
    assert spec is not None, path
    return spec


def test_the_caller_status_is_the_six_statuses_of_the_instruction() -> None:
    spec = _spec("caller.status")
    assert spec.value_type is ValueType.ENUM and spec.control is CardControl.SELECT
    assert [option.label_ru for option in spec.options or ()] == [
        "очевидец",
        "пострадавший",
        "родственник",
        "знакомый",
        "ребенок",
        "участник",
    ]
    # The one code sessions already recorded keeps its meaning.
    eyewitness = spec.option("EYEWITNESS")
    assert eyewitness is not None and eyewitness.label_ru == "очевидец"


def test_the_channel_is_a_select_of_the_channels_the_instruction_names() -> None:
    spec = _spec("applicant.channel")
    assert (spec.label_ru, spec.group, spec.control) == ("Канал связи", "applicant", "SELECT")
    labels = [option.label_ru for option in spec.options or ()]
    assert labels == [
        "Билайн",
        "ЕССМ",
        "Линия ДСП (связь с руководством смены)",
        "МГТС-112",
        "Мегафон",
        "Мобильное приложение",
        "МТС",
        "МЧС",
        "Теле2",
        "Другое",  # owner decision 2026-09-29 No. 12: the rest of the list
    ]
    assert not spec.scoring_relevant and not spec.routing_relevant
    # Right after «Статус заявителя», as fig. 16 shows it («выберите статус» | «МТС»).
    applicant = [field.field_path for field in V2.fields if field.group == "applicant"]
    assert applicant.index("applicant.channel") == applicant.index("caller.status") + 1


def test_the_casualties_count_shows_only_when_casualties_is_on() -> None:
    spec = _spec("flags.casualties_count")
    assert (spec.label_ru, spec.value_type, spec.control) == (
        "Количество",
        ValueType.INTEGER,
        CardControl.NUMBER,
    )
    assert spec.group == "flags" and not spec.scoring_relevant and not spec.routing_relevant
    assert V2.visible("flags.casualties_count", {"flags.casualties": True})
    assert not V2.visible("flags.casualties_count", {"flags.casualties": False})
    assert not V2.visible("flags.casualties_count", {})


def test_the_response_refusal_shows_only_in_the_103_questionnaire() -> None:
    spec = _spec("flags.response_refused")
    assert (spec.label_ru, spec.value_type, spec.group) == (
        "Отказ от реагирования",
        ValueType.BOOLEAN,
        "q_ambulance",
    )
    assert [(o.code, o.label_ru, o.routing) for o in spec.options or ()] == [
        ("RESPONSE_REFUSED", "Отказ от реагирования Скорой", "none")
    ]
    assert not spec.scoring_relevant and not spec.routing_relevant
    assert {group.id: group.label_ru for group in V2.groups}["q_ambulance"] == "Происшествие 103"
    assert V2.visible("flags.response_refused", {"incident.types": ["22"]})
    assert V2.visible("flags.response_refused", {"incident.types": ["1", "22"]})
    assert not V2.visible("flags.response_refused", {"incident.types": ["1"]})
    ambulance = _spec("incident.types").option("22")
    assert ambulance is not None and ambulance.label_ru == "103"


def test_the_description_takes_at_most_1999_characters() -> None:
    spec = _spec("description.text")
    assert spec.max_length == 1999
    check_value(spec, "ы" * 1999)
    with pytest.raises(CardValueTooLongError, match="1999"):
        check_value(spec, "ы" * 2000)
    assert issubclass(CardValueTooLongError, CardFieldError)
    # `set_field` applies it too (the path `setCardField` takes).
    card = OperatorCard(card_id=CardId(uuid4()), incident_id=IncidentId(uuid4()), values={})
    with pytest.raises(CardValueTooLongError):
        set_field(
            card, "description.text", "ы" * 2000, TRAINEE, 1_000, CardRevisionId(uuid4()), schema=V2
        )
    # No other v2 field is capped.
    assert [field.field_path for field in V2.fields if field.max_length is not None] == [
        "description.text"
    ]


def test_the_new_fields_take_their_values() -> None:
    card = OperatorCard(card_id=CardId(uuid4()), incident_id=IncidentId(uuid4()), values={})
    for path, value in (
        ("caller.status", "CHILD"),
        ("applicant.channel", "MTS"),
        ("flags.casualties", True),
        ("flags.casualties_count", 3),
        ("incident.types", ["22"]),
        ("flags.response_refused", True),
    ):
        card, revision, _event = set_field(
            card, path, value, TRAINEE, 1_000, CardRevisionId(uuid4()), schema=V2
        )
        assert revision is not None, path
    assert card.values["flags.casualties_count"] == 3
    with pytest.raises(CardFieldError):
        set_field(
            card, "flags.casualties_count", "3", TRAINEE, 1_000, CardRevisionId(uuid4()), schema=V2
        )


def test_max_length_is_for_a_string_field_only() -> None:
    field = {"field_path": "a.b", "value_type": "INTEGER", "label_ru": "A", "max_length": 5}
    with pytest.raises(CardSchemaError):
        parse_card_schema({"schema_id": "x", "fields": [field]})
    with pytest.raises(CardSchemaError):
        parse_card_schema(
            {"schema_id": "x", "fields": [{**field, "value_type": "STRING", "max_length": 0}]}
        )

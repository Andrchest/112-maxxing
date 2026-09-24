"""The 112 card schema as data (HLD 70 §70.5, D17; I3 E3a).

* `v1.yaml` ≡ today's `CARD_FIELDS`, field by field — the v1 card every existing session uses;
* the shared `CardCondition` fixtures evaluate to their `expected`;
* `set_field` validates against the session's schema: a v2 path is unknown to v1, an option code
  outside the field's options is `CardOptionUnknownError` (`422 CARD_OPTION_UNKNOWN`), and a field
  hidden by `visible_when` is still accepted (advisory, §70.5.2);
* `v2.yaml` is well formed: every `visible_when` names a v2 path, the address selects are the
  catalog's okrug/district strings, the continued paths keep their v1 value types.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from app.domain.common.actors import ActorRef
from app.domain.common.errors import CardFieldError
from app.domain.common.ids import CardId, CardRevisionId, IncidentId
from app.domain.enums import ActorType, ValueType
from app.domain.layers.card_schema import (
    BASE_SPEC_KEYS,
    CardConditionAll,
    CardControl,
    CardOptionUnknownError,
    CardSchemaError,
    evaluate_condition,
    parse_card_schema,
)
from app.domain.layers.operator_card import CARD_FIELDS, CARD_SCHEMA_V1, OperatorCard, set_field
from pydantic import TypeAdapter

REPO_ROOT = Path(__file__).resolve().parents[5]
CARD_SCHEMA_DIR = REPO_ROOT / "reference" / "card-schema"
V1 = parse_card_schema(yaml.safe_load((CARD_SCHEMA_DIR / "v1.yaml").read_text(encoding="utf-8")))
V2 = parse_card_schema(yaml.safe_load((CARD_SCHEMA_DIR / "v2.yaml").read_text(encoding="utf-8")))
FIXTURES = json.loads((CARD_SCHEMA_DIR / "conditions.fixtures.json").read_text(encoding="utf-8"))
SERVICES = yaml.safe_load(
    (REPO_ROOT / "reference" / "services" / "v1.yaml").read_text(encoding="utf-8")
)["services"]
TRAINEE = ActorRef(actor_type=ActorType.TRAINEE, actor_id=uuid4())


def _card() -> OperatorCard:
    return OperatorCard(card_id=CardId(uuid4()), incident_id=IncidentId(uuid4()), values={})


def _set(card: OperatorCard, path: str, value: object, schema: object = None) -> OperatorCard:
    updated, revision, _event = set_field(
        card,
        path,
        value,
        TRAINEE,
        1_000,
        CardRevisionId(uuid4()),
        schema=schema,  # type: ignore[arg-type]
    )
    assert revision is not None
    return updated


# -- v1 ≡ CARD_FIELDS -------------------------------------------------------------------------


def test_the_v1_file_is_card_fields_field_by_field() -> None:
    assert V1.schema_id == "v1"
    assert len(V1.fields) == len(CARD_FIELDS) == 38
    for index, (from_file, in_code) in enumerate(zip(V1.fields, CARD_FIELDS, strict=True)):
        assert from_file == in_code, from_file.field_path
        assert from_file.order == index
    assert V1.fields == CARD_SCHEMA_V1.fields


def test_the_v1_file_carries_only_the_six_pre_i3_keys() -> None:
    document = yaml.safe_load((CARD_SCHEMA_DIR / "v1.yaml").read_text(encoding="utf-8"))
    assert all(tuple(field) == BASE_SPEC_KEYS for field in document["fields"])


def test_a_v1_field_gets_the_neutral_additive_values() -> None:
    for spec in CARD_FIELDS:
        assert spec.group is None
        assert spec.options is None and spec.visible_when is None
        assert spec.required_in_block is False and spec.routing_relevant is False
        expected = {ValueType.ENUM: CardControl.SELECT, ValueType.BOOLEAN: CardControl.CHECKBOX}
        assert spec.control is expected.get(spec.value_type, CardControl.TEXT)


# -- the shared condition fixtures ------------------------------------------------------------


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda case: case["name"])
def test_the_shared_condition_fixtures(case: dict[str, object]) -> None:
    condition = TypeAdapter(CardConditionAll).validate_python({"all": [case["condition"]]})
    assert evaluate_condition(condition, case["values"]) is case["expected"]  # type: ignore[arg-type]


# -- set_field per schema ---------------------------------------------------------------------


def test_a_v2_path_is_unknown_to_the_v1_card() -> None:
    with pytest.raises(CardFieldError, match="unknown card field path"):
        _set(_card(), "incident.types", ["1"])


def test_a_v2_path_is_accepted_under_v2() -> None:
    card = _set(_card(), "incident.types", ["1", "13"], V2)
    card = _set(card, "address.district", "Бибирево", V2)
    assert card.values == {"incident.types": ["1", "13"], "address.district": "Бибирево"}


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("address.okrug", "Подмосковье"),
        ("incident.types", ["1", "999"]),
        ("q.fire.where", ["на крыше"]),
        ("caller.status", "SOMEONE"),
    ],
)
def test_a_value_outside_the_options_is_card_option_unknown(path: str, value: object) -> None:
    with pytest.raises(CardOptionUnknownError):
        _set(_card(), path, value, V2)


def test_a_type_mismatch_is_not_an_option_error() -> None:
    with pytest.raises(CardFieldError) as caught:
        _set(_card(), "incident.types", "1", V2)
    assert not isinstance(caught.value, CardOptionUnknownError)


def test_a_hidden_field_is_accepted() -> None:
    """`q.fire.offence` is shown only for a street fire with a burning object; the card has
    neither, and the write is still accepted — visibility is advisory (§70.5.2)."""
    card = _card()
    assert not V2.visible("q.fire.offence", card.values)
    card = _set(card, "q.fire.offence", ["offence"], V2)
    assert card.values["q.fire.offence"] == ["offence"]


def test_a_street_fire_shows_its_questionnaire_rows() -> None:
    values = {
        "incident.types": ["1"],
        "q.fire.where": ["на улице"],
        "q.fire.sign_street": ["открытое пламя / дым"],
        "q.fire.street_object": ["мусор"],
    }
    shown = {spec.field_path for spec in V2.fields if V2.visible(spec.field_path, values)}
    assert {"q.fire.threat_to_people", "q.fire.offence", "q.fire.gasification"} <= shown
    assert "q.fire.transport_object" not in shown
    smell = {**values, "q.fire.sign_street": ["запах гари"]}
    assert not V2.visible("q.fire.threat_to_people", smell)  # REQ-3004


# -- v2 is well formed ------------------------------------------------------------------------


def test_v2_keeps_the_v1_value_types_of_the_paths_it_continues() -> None:
    v1 = {spec.field_path: spec for spec in CARD_FIELDS}
    for spec in V2.fields:
        if spec.field_path in v1:
            assert spec.value_type is v1[spec.field_path].value_type, spec.field_path
    assert "incident.type" not in V2  # §70.5.3: `incident.type` stays in v1 only


def test_the_address_selects_are_the_catalogs_okrugs_and_districts() -> None:
    okrugs = {entry["okrug"] for entry in SERVICES if entry["kind"] == "PREFECTURE"}
    districts = {entry["district"] for entry in SERVICES if entry["kind"] == "DISTRICT"}
    okrug, district = V2.spec("address.okrug"), V2.spec("address.district")
    assert okrug is not None and district is not None
    assert okrug.option_codes == okrugs and len(okrugs) == 11
    assert district.option_codes == districts and len(districts) == 146


def test_the_routing_relevant_fields_are_the_b1_list() -> None:
    routing = {spec.field_path for spec in V2.fields if spec.routing_relevant}
    assert {
        "incident.types",
        "incident.classifier_code",
        "flags.casualties",
        "flags.ambulance_refused",
        "flags.blocked",
        "address.okrug",
        "address.district",
    } <= routing
    toggle_sets_with_codes = {
        spec.field_path
        for spec in V2.fields
        if spec.field_path.startswith("q.")
        and spec.control is CardControl.TOGGLE_SET
        and any(
            option.routing != "none" and option.code not in {"yes", "no"}
            for option in spec.options or ()
        )
    }
    assert toggle_sets_with_codes <= routing


def test_the_what_happened_list_has_the_51_entries_of_req_3001() -> None:
    types = V2.spec("incident.types")
    assert types is not None and types.options is not None
    assert len(types.options) == 51
    administrative = {option.code for option in types.options if option.routing == "none"}
    assert {"TEST_CALL", "SHIFT_HANDOVER", "REFERENCE_101", "REFERENCE_MCHS"} <= administrative


def test_a_malformed_schema_is_refused() -> None:
    field = {"field_path": "a.b", "value_type": "STRING", "label_ru": "A"}
    with pytest.raises(CardSchemaError, match="duplicate"):
        parse_card_schema({"schema_id": "x", "fields": [field, field]})
    with pytest.raises(CardSchemaError, match="unknown group"):
        parse_card_schema({"schema_id": "x", "fields": [{**field, "group": "nope"}]})
    hidden = {**field, "visible_when": {"field_path": "c.d", "op": "PRESENT"}}
    with pytest.raises(CardSchemaError, match="unknown path"):
        parse_card_schema({"schema_id": "x", "fields": [hidden]})
    with pytest.raises(CardSchemaError):
        parse_card_schema(
            {"schema_id": "x", "fields": [{**field, "options": [{"code": "a", "label_ru": "A"}]}]}
        )

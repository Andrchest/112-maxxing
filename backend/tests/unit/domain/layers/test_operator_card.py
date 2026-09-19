"""Tests for `app.domain.layers.operator_card` (HLD `10-domain-model.md` §10.6, SPEC §9).

Covers `set_field`'s happy path, unknown `field_path`, wrong `value_type` (`CardFieldError` in both
cases), revision content, the emitted `CARD_FIELD_CHANGED` `DomainEvent` (ruling R3), the
no-op-on-unchanged-value rule (no revision, no event), the `TRAINEE`/`INSTRUCTOR`-only actor
restriction, that every one of the 38 SPEC §9 field paths is present with its declared type, and
the exact `required_for_handoff` set (ruling R4).
"""

from __future__ import annotations

import uuid

import pytest
from app.domain.common.actors import ActorRef
from app.domain.common.errors import CardFieldError
from app.domain.enums import ActorType, ValueType
from app.domain.events.types import EventType
from app.domain.layers.operator_card import (
    CARD_FIELDS,
    OperatorCard,
    set_field,
)


def _new_card() -> OperatorCard:
    return OperatorCard(card_id=uuid.uuid4(), incident_id=uuid.uuid4(), values={})


def _trainee() -> ActorRef:
    return ActorRef(actor_type=ActorType.TRAINEE)


def test_card_fields_has_exactly_the_38_spec_paths() -> None:
    paths = [spec.field_path for spec in CARD_FIELDS]
    assert len(paths) == 38
    assert len(set(paths)) == 38  # no duplicates
    assert "incident.type" in paths
    assert "recipients.services" in paths


def test_set_field_happy_path_returns_new_card_and_revision() -> None:
    card = _new_card()
    actor = _trainee()
    revision_id = uuid.uuid4()

    new_card, revision, event = set_field(
        card, "address.street", "Ленина", actor, 1_000, revision_id
    )

    assert new_card is not card
    assert new_card.values["address.street"] == "Ленина"
    assert new_card.revision_counter == 1
    assert card.values == {}  # original untouched
    assert card.revision_counter == 0
    assert revision is not None
    assert revision.revision_id == revision_id
    assert revision.revision_no == 1
    assert event is not None
    assert event.event_type == EventType.CARD_FIELD_CHANGED
    assert event.actor == actor


def test_set_field_revision_content() -> None:
    card = _new_card()
    actor = _trainee()
    revision_id = uuid.uuid4()

    _, revision, event = set_field(card, "people.victims_count", 2, actor, 5_000, revision_id)
    assert revision is not None
    assert event is not None

    assert revision.field_path == "people.victims_count"
    assert revision.previous_value is None
    assert revision.new_value == 2
    assert revision.actor == actor
    assert revision.at_offset_ms == 5_000
    assert revision.card_id == card.card_id

    assert event.payload["card_id"] == card.card_id
    assert event.payload["revision_id"] == revision_id
    assert event.payload["field_path"] == "people.victims_count"
    assert event.payload["previous_value"] is None
    assert event.payload["new_value"] == 2
    assert event.monotonic_offset_ms == 5_000


def test_set_field_second_mutation_has_previous_value_and_dense_revision_no() -> None:
    card = _new_card()
    actor = _trainee()

    card, _, _ = set_field(card, "people.victims_count", 2, actor, 0, uuid.uuid4())
    card, revision, event = set_field(card, "people.victims_count", 3, actor, 100, uuid.uuid4())

    assert revision is not None
    assert revision.previous_value == 2
    assert revision.new_value == 3
    assert revision.revision_no == 2
    assert card.revision_counter == 2
    assert event is not None
    assert event.payload["previous_value"] == 2
    assert event.payload["new_value"] == 3


def test_set_field_emits_event_with_right_previous_and_new_values_across_two_edits() -> None:
    """§42-style coverage for ruling R3: two successive edits of the same field each emit a
    `CARD_FIELD_CHANGED` `DomainEvent` whose `previous_value`/`new_value` match that specific
    transition, not the field's original or final value."""
    card = _new_card()
    actor = _trainee()

    card, _, first_event = set_field(card, "caller.phone", "111", actor, 0, uuid.uuid4())
    _, _, second_event = set_field(card, "caller.phone", "222", actor, 10, uuid.uuid4())

    assert first_event is not None
    assert first_event.payload["previous_value"] is None
    assert first_event.payload["new_value"] == "111"

    assert second_event is not None
    assert second_event.payload["previous_value"] == "111"
    assert second_event.payload["new_value"] == "222"


def test_set_field_unknown_path_raises_card_field_error() -> None:
    card = _new_card()

    with pytest.raises(CardFieldError):
        set_field(card, "not.a.field", "x", _trainee(), 0, uuid.uuid4())


def test_set_field_wrong_value_type_raises_card_field_error() -> None:
    card = _new_card()

    with pytest.raises(CardFieldError):
        set_field(card, "address.floor", "third", _trainee(), 0, uuid.uuid4())


def test_set_field_enum_field_rejects_value_outside_the_enum() -> None:
    card = _new_card()

    with pytest.raises(CardFieldError):
        set_field(card, "incident.type", "NOT_A_REAL_TYPE", _trainee(), 0, uuid.uuid4())


def test_set_field_enum_field_accepts_a_real_member() -> None:
    card = _new_card()

    new_card, revision, event = set_field(
        card, "incident.type", "FIRE", _trainee(), 0, uuid.uuid4()
    )

    assert new_card.values["incident.type"] == "FIRE"
    assert revision is not None
    assert event is not None


def test_set_field_string_list_field_accepts_a_list_of_strings() -> None:
    card = _new_card()

    new_card, revision, event = set_field(
        card, "recipients.services", ["FIRE_RESCUE", "AMBULANCE"], _trainee(), 0, uuid.uuid4()
    )

    assert new_card.values["recipients.services"] == ["FIRE_RESCUE", "AMBULANCE"]
    assert revision is not None
    assert event is not None


def test_set_field_same_value_is_a_noop() -> None:
    card = _new_card()
    card, _, _ = set_field(card, "address.street", "Ленина", _trainee(), 0, uuid.uuid4())

    same_card, revision, event = set_field(
        card, "address.street", "Ленина", _trainee(), 1, uuid.uuid4()
    )

    assert revision is None
    assert event is None
    assert same_card == card


def test_set_field_rejects_actor_other_than_trainee_or_instructor() -> None:
    card = _new_card()
    asr_actor = ActorRef(actor_type=ActorType.MODEL)

    with pytest.raises(CardFieldError):
        set_field(card, "address.street", "Ленина", asr_actor, 0, uuid.uuid4())


def test_set_field_allows_instructor() -> None:
    card = _new_card()
    instructor = ActorRef(actor_type=ActorType.INSTRUCTOR)

    new_card, revision, event = set_field(
        card, "address.street", "Ленина", instructor, 0, uuid.uuid4()
    )

    assert new_card.values["address.street"] == "Ленина"
    assert revision is not None
    assert event is not None
    assert event.actor == instructor


@pytest.mark.parametrize(
    ("field_path", "bad_value"),
    [
        ("caller.full_name", 123),
        ("address.floor", "1"),
        ("caller.callback_possible", "yes"),
        ("recipients.services", "FIRE_RESCUE"),
    ],
)
def test_set_field_type_mismatches_are_rejected(field_path: str, bad_value: object) -> None:
    card = _new_card()

    with pytest.raises(CardFieldError):
        set_field(card, field_path, bad_value, _trainee(), 0, uuid.uuid4())  # type: ignore[arg-type]


def test_boolean_value_type_is_not_accidentally_accepted_as_integer() -> None:
    # ValueType.INTEGER must reject bool (bool is a subclass of int in Python).
    card = _new_card()

    with pytest.raises(CardFieldError):
        set_field(card, "address.floor", True, _trainee(), 0, uuid.uuid4())


def test_every_card_field_spec_has_a_russian_label() -> None:
    for spec in CARD_FIELDS:
        assert spec.label_ru
        assert spec.value_type in ValueType


def test_required_for_handoff_is_exactly_the_ruling_r4_set() -> None:
    """§10.6 ruling R4: advisory only — a missing field never blocks a handoff — but exactly
    these eight paths are flagged."""
    expected = {
        "incident.type",
        "address.locality",
        "address.street",
        "address.house",
        "caller.phone",
        "description.text",
        "flags.threat_to_life",
        "recipients.services",
    }
    actual = {spec.field_path for spec in CARD_FIELDS if spec.required_for_handoff}
    assert actual == expected

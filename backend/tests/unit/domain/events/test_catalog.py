"""Tests for `app.domain.events.catalog` (HLD `10-domain-model.md` §10.13, D5, SPEC §8).

Covers: the catalog covers exactly `EventType`; every SPEC §8 event name (parsed straight out of
`docs/SPEC.md`, never retyped) is present; every catalogued `actor_types` is a subset of
`ActorType`; `validate_payload` accepts a minimal valid payload and rejects a payload missing a
required key, for `CARD_FIELD_CHANGED`, `HANDOFF_CREATED` and `FACTS_DELIVERED`; and
`WORLD_TRUTH_MUTATED`/`CALLER_BELIEF_MUTATED` are visible to no trainee role (D3, D8, §42 tests 1
and 3).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.domain.common.errors import DomainError
from app.domain.enums import ActorType, RoleType
from app.domain.events.catalog import EVENT_PAYLOAD_CATALOG, validate_payload
from app.domain.events.types import EventType

SPEC_PATH = Path(__file__).resolve().parents[5] / "docs" / "SPEC.md"


def _spec_section_8_event_names() -> list[str]:
    """Parse the "Include event types for at least:" block of SPEC §8, never retyping the list."""
    text = SPEC_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"Include event types for at least:\n\n(.*?)\n\nDo not overwrite events\.",
        text,
        re.DOTALL,
    )
    assert match is not None, "could not locate the SPEC §8 event-type block"
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def test_catalog_covers_exactly_event_type() -> None:
    assert frozenset(EVENT_PAYLOAD_CATALOG) == frozenset(EventType)


def test_spec_section_8_event_names_are_all_present_in_the_catalog() -> None:
    names = _spec_section_8_event_names()
    assert len(names) == 28
    for name in names:
        assert EventType(name) in EVENT_PAYLOAD_CATALOG


@pytest.mark.parametrize("event_type", list(EventType))
def test_every_catalog_actor_types_is_a_subset_of_actor_type(event_type: EventType) -> None:
    spec = EVENT_PAYLOAD_CATALOG[event_type]
    assert spec.actor_types <= frozenset(ActorType)
    assert spec.actor_types  # never empty


@pytest.mark.parametrize("event_type", list(EventType))
def test_every_catalog_entry_key_matches_its_own_event_type(event_type: EventType) -> None:
    assert EVENT_PAYLOAD_CATALOG[event_type].event_type == event_type


def test_validate_payload_accepts_minimal_valid_card_field_changed_payload() -> None:
    payload = {
        "card_id": "c",
        "revision_id": "r",
        "revision_no": 1,
        "field_path": "address.street",
        "previous_value": None,
        "new_value": "Ленина",
        "value_type": "STRING",
        "actor_user_id": "u",
        "at_offset_ms": 0,
    }
    validate_payload(EventType.CARD_FIELD_CHANGED, payload)


def test_validate_payload_rejects_card_field_changed_payload_missing_a_key() -> None:
    payload = {
        "card_id": "c",
        "revision_id": "r",
        "revision_no": 1,
        "field_path": "address.street",
        "previous_value": None,
        "new_value": "Ленина",
        "value_type": "STRING",
        # "actor_user_id" missing
        "at_offset_ms": 0,
    }
    with pytest.raises(DomainError):
        validate_payload(EventType.CARD_FIELD_CHANGED, payload)


def test_validate_payload_accepts_minimal_valid_handoff_created_payload() -> None:
    payload = {
        "snapshot_id": "s",
        "incident_id": "i",
        "card_id": "c",
        "card_revision_id": "r",
        "recipient_services": ["FIRE_RESCUE"],
        "card_values": {},
        "content_sha256": "abc",
        "at_offset_ms": 0,
    }
    validate_payload(EventType.HANDOFF_CREATED, payload)


def test_validate_payload_rejects_handoff_created_payload_missing_a_key() -> None:
    payload = {
        "snapshot_id": "s",
        "incident_id": "i",
        "card_id": "c",
        "card_revision_id": "r",
        "recipient_services": ["FIRE_RESCUE"],
        "card_values": {},
        # "content_sha256" missing
        "at_offset_ms": 0,
    }
    with pytest.raises(DomainError):
        validate_payload(EventType.HANDOFF_CREATED, payload)


def test_validate_payload_accepts_minimal_valid_facts_delivered_payload() -> None:
    payload = {
        "turn_index": 1,
        "fact_ids": ["fact_a"],
        "delivered_via": "TTS_COMPLETED",
        "at_offset_ms": 0,
    }
    validate_payload(EventType.FACTS_DELIVERED, payload)


def test_validate_payload_rejects_facts_delivered_payload_missing_a_key() -> None:
    payload = {
        "turn_index": 1,
        # "fact_ids" missing
        "delivered_via": "TTS_COMPLETED",
        "at_offset_ms": 0,
    }
    with pytest.raises(DomainError):
        validate_payload(EventType.FACTS_DELIVERED, payload)


def test_validate_payload_ignores_missing_optional_nullable_keys() -> None:
    """`ASR_FINAL.confidence` is `"float | null"` — optional — so a payload lacking it is valid."""
    payload = {
        "call_id": "c",
        "turn_index": 1,
        "transcript_segment_id": "t",
        "audio_segment_id": None,
        "text": "hello",
        "start_ms": 0,
        "end_ms": 100,
        # "confidence" deliberately omitted
        "asr_provider": "p",
        "asr_model": "m",
    }
    validate_payload(EventType.ASR_FINAL, payload)


def test_world_truth_mutated_is_visible_to_no_trainee_role() -> None:
    """D3, D8, §42 tests 1 and 3: the WorldTruth boundary — never pushed to a trainee."""
    spec = EVENT_PAYLOAD_CATALOG[EventType.WORLD_TRUTH_MUTATED]
    assert spec.visible_to == frozenset({"INSTRUCTOR"})
    assert RoleType.OPERATOR_112 not in spec.visible_to
    assert RoleType.DDS not in spec.visible_to


def test_caller_belief_mutated_is_visible_to_no_trainee_role() -> None:
    spec = EVENT_PAYLOAD_CATALOG[EventType.CALLER_BELIEF_MUTATED]
    assert spec.visible_to == frozenset({"INSTRUCTOR"})
    assert RoleType.OPERATOR_112 not in spec.visible_to
    assert RoleType.DDS not in spec.visible_to

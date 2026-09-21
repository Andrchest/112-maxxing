"""`dialogue_interpreted_payload` / `model_fallback_used_payload` — exact catalog keys (HLD
`10-domain-model.md` §10.13, `app.domain.events.catalog.EVENT_PAYLOAD_CATALOG`)."""

from __future__ import annotations

from app.application.dialogue.events import (
    dialogue_interpreted_payload,
    model_fallback_used_payload,
)
from app.application.dialogue.interpreter import InterpretationOutcome, InterpretedUtterance
from app.domain.enums import SpeechAct
from app.domain.events.catalog import EVENT_PAYLOAD_CATALOG
from app.domain.events.types import EventType


def _outcome(**overrides: object) -> InterpretationOutcome:
    interpretation = InterpretedUtterance(
        speech_act=SpeechAct.QUESTION,
        requested_facts=(),
        operator_assertions=(),
        confirmation_targets=(),
        semantic_confidence=0.8,
    )
    defaults: dict[str, object] = {
        "interpretation": interpretation,
        "repair_retry_used": False,
        "fallback_used": False,
        "failure_reason": None,
    }
    defaults.update(overrides)
    return InterpretationOutcome(**defaults)  # type: ignore[arg-type]


def test_dialogue_interpreted_payload_has_exactly_the_catalogued_keys() -> None:
    payload = dialogue_interpreted_payload(turn_index=3, outcome=_outcome())

    expected_keys = set(EVENT_PAYLOAD_CATALOG[EventType.DIALOGUE_INTERPRETED].payload_keys)
    assert set(payload) == expected_keys


def test_dialogue_interpreted_payload_values() -> None:
    interpretation = InterpretedUtterance(
        speech_act=SpeechAct.CONFIRMATION,
        requested_facts=({"fact_id": "incident.address", "explicit": True},),  # type: ignore[arg-type]
        operator_assertions=(),
        confirmation_targets=("incident.address",),
        semantic_confidence=0.42,
    )
    outcome = InterpretationOutcome(
        interpretation=interpretation,
        repair_retry_used=True,
        fallback_used=False,
        failure_reason=None,
    )

    payload = dialogue_interpreted_payload(turn_index=5, outcome=outcome)

    assert payload["turn_index"] == 5
    assert payload["speech_act"] == "CONFIRMATION"
    assert payload["requested_facts"] == [{"fact_id": "incident.address", "explicit": True}]
    assert payload["confirmation_targets"] == ["incident.address"]
    assert payload["semantic_confidence"] == 0.42
    assert payload["repair_retry_used"] is True


def test_model_fallback_used_payload_has_exactly_the_catalogued_keys() -> None:
    payload = model_fallback_used_payload(
        component="INTERPRETER",
        reason="second failure",
        attempt=1,
        fallback_kind="UNINTELLIGIBLE_FALLBACK",
        turn_index=2,
    )

    expected_keys = set(EVENT_PAYLOAD_CATALOG[EventType.MODEL_FALLBACK_USED].payload_keys)
    assert set(payload) == expected_keys
    assert payload["component"] == "INTERPRETER"
    assert payload["turn_index"] == 2

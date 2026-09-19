"""Tests for `app.domain.layers.caller_belief.CallerBelief` (HLD `10-domain-model.md` §10.3, D3)."""

from __future__ import annotations

import uuid

import pytest
from app.domain.caller.emotion import EmotionState
from app.domain.enums import EmotionLabel, KnowledgeState
from app.domain.layers.caller_belief import CallerBelief
from pydantic import ValidationError


def _belief(**overrides: object) -> CallerBelief:
    defaults: dict[str, object] = {
        "incident_id": uuid.uuid4(),
        "emotion": EmotionState(emotion=EmotionLabel.CALM, stress_level=0.2),
    }
    defaults.update(overrides)
    return CallerBelief(**defaults)  # type: ignore[arg-type]


def test_caller_belief_defaults() -> None:
    belief = _belief()

    assert belief.revision == 0
    assert belief.facts == {}
    assert belief.knowledge == {}
    assert belief.certainty == {}
    assert belief.revealed_fact_ids == frozenset()


def test_caller_belief_holds_knowledge_and_certainty() -> None:
    belief = _belief(
        facts={"people.victim_01.inside": True},
        knowledge={"people.victim_01.inside": KnowledgeState.KNOWN},
        certainty={"people.victim_01.inside": 1.0},
        revealed_fact_ids=frozenset({"people.victim_01.inside"}),
    )

    assert belief.facts["people.victim_01.inside"] is True
    assert belief.knowledge["people.victim_01.inside"] is KnowledgeState.KNOWN
    assert "people.victim_01.inside" in belief.revealed_fact_ids


def test_caller_belief_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CallerBelief.model_validate(
            {
                "incident_id": uuid.uuid4(),
                "emotion": {"emotion": "CALM", "stress_level": 0.1},
                "bogus": 1,
            }
        )

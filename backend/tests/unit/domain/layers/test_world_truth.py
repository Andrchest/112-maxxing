"""Tests for `app.domain.layers.world_truth.WorldTruth` (HLD `10-domain-model.md` §10.3, D3)."""

from __future__ import annotations

import uuid

import pytest
from app.domain.enums import ValueType
from app.domain.layers.world_truth import WorldTruth
from pydantic import ValidationError


def test_world_truth_defaults() -> None:
    truth = WorldTruth(incident_id=uuid.uuid4())

    assert truth.revision == 0
    assert truth.facts == {}
    assert truth.value_types == {}


def test_world_truth_holds_typed_facts() -> None:
    truth = WorldTruth(
        incident_id=uuid.uuid4(),
        revision=1,
        facts={"incident.fire_source": "KITCHEN"},
        value_types={"incident.fire_source": ValueType.STRING},
    )

    assert truth.facts["incident.fire_source"] == "KITCHEN"
    assert truth.value_types["incident.fire_source"] is ValueType.STRING


def test_world_truth_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        WorldTruth.model_validate({"incident_id": uuid.uuid4(), "bogus": 1})

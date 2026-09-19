"""Tests for `app.domain.layers.handoff.HandoffSnapshot` (HLD `10-domain-model.md` §10.7, D3).

`HandoffSnapshot` must be immutable: any attempt to mutate an attribute after construction raises.
"""

from __future__ import annotations

import uuid

import pytest
from app.domain.enums import ServiceType
from app.domain.layers.handoff import HandoffSnapshot
from pydantic import ValidationError


def _snapshot() -> HandoffSnapshot:
    return HandoffSnapshot(
        snapshot_id=uuid.uuid4(),
        incident_id=uuid.uuid4(),
        card_id=uuid.uuid4(),
        card_revision_id=uuid.uuid4(),
        card_values={"address.street": "Ленина"},
        recipient_services=(ServiceType.FIRE_RESCUE,),
        created_by_user_id=uuid.uuid4(),
        created_at_offset_ms=1_000,
        content_sha256="a" * 64,
    )


def test_handoff_snapshot_constructs() -> None:
    snapshot = _snapshot()
    assert snapshot.card_values == {"address.street": "Ленина"}
    assert snapshot.recipient_services == (ServiceType.FIRE_RESCUE,)


def test_handoff_snapshot_rejects_attribute_mutation() -> None:
    snapshot = _snapshot()

    with pytest.raises(ValidationError):
        snapshot.content_sha256 = "b" * 64  # type: ignore[misc]


def test_handoff_snapshot_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        HandoffSnapshot.model_validate(
            {
                "snapshot_id": uuid.uuid4(),
                "incident_id": uuid.uuid4(),
                "card_id": uuid.uuid4(),
                "card_revision_id": uuid.uuid4(),
                "card_values": {},
                "recipient_services": (),
                "created_by_user_id": uuid.uuid4(),
                "created_at_offset_ms": 0,
                "content_sha256": "a" * 64,
                "bogus": True,
            }
        )

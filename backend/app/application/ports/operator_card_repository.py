"""`OperatorCardRepository` port (HLD `20-db-schema.md` §20.4, `10-domain-model.md` §10.3, D3).

D3 is "four layers, four storage locations". It is a *structural* decision, so it is expressed
structurally: one module per layer, mentioning exactly one layer type, rather than one convenient
"incident data" repository that would give any holder of it a path from the DDS side to the
engine-written layers. A component that may only edit the card receives this module's port and
therefore *cannot* reach the layers it may not see — not by policy, by imports.

The port has only the three operations its layer needs in this slice: `get`, `add`, `save`.
Nothing here is generic over the layer type, deliberately: a shared base class would reintroduce
the single access path the four ports exist to prevent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import IncidentId
from app.domain.layers.operator_card import OperatorCard

__all__ = ["OperatorCardRepository"]


@runtime_checkable
class OperatorCardRepository(Protocol):
    """`incident_cards` — trainee-written only (§20.4, D3, SPEC §9).

    `incident_card_revisions` is the card's append-only audit trail; writing it belongs to the
    card-editing use case — TODO(E7).
    """

    async def get(self, incident_id: IncidentId) -> OperatorCard | None:
        """The incident's operator card, or `None`."""
        ...

    async def add(self, card: OperatorCard) -> None:
        """Insert the empty card session creation makes."""
        ...

    async def save(self, card: OperatorCard) -> None:
        """Write back a mutated card (`revision_counter` included)."""
        ...

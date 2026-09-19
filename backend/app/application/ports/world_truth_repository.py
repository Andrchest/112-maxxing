"""`WorldTruthRepository` port (HLD `20-db-schema.md` §20.4, `10-domain-model.md` §10.3, D3).

D3 is "four layers, four storage locations". It is a *structural* decision, so it is expressed
structurally here: one module per layer, mentioning exactly one layer type, rather than one
convenient "incident data" repository that would give any holder of it a path from the DDS side
to `WorldTruth`. A component that may only read the handoff receives `HandoffRepository` and
therefore *cannot* reach world truth — not by policy, by types.

Each port has only the three operations its layer needs in this slice: `get`, `add`, `save`.
Nothing here is generic over the layer type, deliberately: a shared base class would reintroduce
the single access path the four ports exist to prevent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import IncidentId
from app.domain.layers.world_truth import WorldTruth

__all__ = ["WorldTruthRepository"]


@runtime_checkable
class WorldTruthRepository(Protocol):
    """`incident_world_states` — engine-written only (§20.4, D3)."""

    async def get(self, incident_id: IncidentId) -> WorldTruth | None:
        """The incident's world truth, or `None`."""
        ...

    async def add(self, world_truth: WorldTruth) -> None:
        """Insert the row scenario instantiation produced (`instantiate_world_truth`)."""
        ...

    async def save(self, world_truth: WorldTruth) -> None:
        """Write back a mutated world truth (`revision` included)."""
        ...

"""`CallerBeliefRepository` port (HLD `20-db-schema.md` §20.4, `10-domain-model.md` §10.3, D3).

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
from app.domain.layers.caller_belief import CallerBelief

__all__ = ["CallerBeliefRepository"]


@runtime_checkable
class CallerBeliefRepository(Protocol):
    """`incident_caller_beliefs` — engine-written only (§20.4, D3)."""

    async def get(self, incident_id: IncidentId) -> CallerBelief | None:
        """The incident's caller belief, or `None`."""
        ...

    async def add(self, caller_belief: CallerBelief) -> None:
        """Insert the row scenario instantiation produced (`instantiate_caller_belief`)."""
        ...

    async def save(self, caller_belief: CallerBelief) -> None:
        """Write back a mutated caller belief (`revision` included)."""
        ...

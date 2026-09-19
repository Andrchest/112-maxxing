"""`HandoffRepository` port (HLD `20-db-schema.md` §20.4, `10-domain-model.md` §10.3, D3).

D3 is "four layers, four storage locations". It is a *structural* decision, so it is expressed
structurally: one module per layer, mentioning exactly one layer type, rather than one convenient
"incident data" repository that would give any holder of it a path from the DDS side to the
engine-written layers. A component that may only read the handoff receives this module's port and
therefore *cannot* reach the layers it may not see — not by policy, by imports.

The port has only the three operations its layer needs in this slice: `get`, `add`, `save`.
Nothing here is generic over the layer type, deliberately: a shared base class would reintroduce
the single access path the four ports exist to prevent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import SnapshotId
from app.domain.layers.handoff import HandoffSnapshot

__all__ = ["HandoffRepository"]


@runtime_checkable
class HandoffRepository(Protocol):
    """`handoff_snapshots` — the by-value copy DDS reads (§20.4, D3, SPEC §10).

    A `HandoffSnapshot` is immutable at rest (§20.9 trigger), so `save` exists only for symmetry
    with the other three ports and an implementation may refuse a changed snapshot.
    """

    async def get(self, snapshot_id: SnapshotId) -> HandoffSnapshot | None:
        """The snapshot with this id, or `None`."""
        ...

    async def add(self, snapshot: HandoffSnapshot) -> None:
        """Insert a frozen snapshot (`freeze_card_to_snapshot`)."""
        ...

    async def save(self, snapshot: HandoffSnapshot) -> None:
        """Write back a snapshot; the row is immutable, so this may only be a no-op re-write."""
        ...

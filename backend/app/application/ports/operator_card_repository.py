"""`OperatorCardRepository` port (HLD `20-db-schema.md` §20.4, `10-domain-model.md` §10.3, D3).

D3 is "four layers, four storage locations". It is a *structural* decision, so it is expressed
structurally: one module per layer, mentioning exactly one layer type, rather than one convenient
"incident data" repository that would give any holder of it a path from the DDS side to the
engine-written layers. A component that may only edit the card receives this module's port and
therefore *cannot* reach the layers it may not see — not by policy, by imports.

The port has the operations its layer needs: `get`, `add`, `save` for the materialised
`incident_cards` row, and `add_revision` / `list_revisions` for `incident_card_revisions`, the
card's append-only audit trail (SPEC §9: "the final card is NOT enough"). Nothing here is generic
over the layer type, deliberately: a shared base class would reintroduce the single access path
the four ports exist to prevent.

`add_revision` takes the `ValueType` of the field alongside the domain `CardRevision` because
`incident_card_revisions.value_type` is a column of the row and not a field of the pure domain
value — the spec it comes from is `CARD_FIELDS`, which the calling use case already resolved in
order to validate the write.

There is deliberately **no** `update_revision` and no `delete_revision`: the row is immutable at
rest (the §20.9 `incident_card_revisions_append_only` trigger rejects UPDATE and DELETE), so a
port method for either would promise something the database refuses.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import CardId, IncidentId
from app.domain.enums import ValueType
from app.domain.layers.operator_card import CardRevision, OperatorCard

__all__ = ["OperatorCardRepository"]


@runtime_checkable
class OperatorCardRepository(Protocol):
    """`incident_cards` + `incident_card_revisions`, trainee-written only (§20.4, D3, SPEC §9)."""

    async def get(self, incident_id: IncidentId) -> OperatorCard | None:
        """The incident's operator card, or `None`."""
        ...

    async def add(self, card: OperatorCard) -> None:
        """Insert the empty card session creation makes."""
        ...

    async def save(self, card: OperatorCard) -> None:
        """Write back a mutated card (`revision_counter` included)."""
        ...

    async def add_revision(self, revision: CardRevision, value_type: ValueType) -> None:
        """Append one `incident_card_revisions` row — SPEC §9's previous value, actor and time.

        Exactly one row per `set_field` that actually changed something; a no-op write appends
        nothing, so `revision_no` is dense and matches `incident_cards.revision_counter`.
        """
        ...

    async def list_revisions(
        self,
        card_id: CardId,
        *,
        field_path: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[CardRevision], int]:
        """One page of the card's history plus the unpaged total, by ascending `revision_no`.

        `field_path` narrows to one card field (`listCardRevisions`' optional filter); the total
        is the count *after* that filter, so a client paginating one field is not told how many
        revisions the whole card has.
        """
        ...

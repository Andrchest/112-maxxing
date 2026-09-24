"""`deselectRecipientService` — remove one service from `recipients.services` (`openapi.yaml`).

The mirror of `select_service`, and deliberately its own module rather than a flag on it: the two
operations are two path items with two `x-emits` lists, and the INV 4 allow-list of
`backend/tests/invariants/test_inv_04_asr_never_mutates_card.py` names card writers one by one —
a shared "service toggle" module would be one more name on that list with two behaviours behind
it.

Same write path as the selection: the domain's `set_field` on `recipients.services`, one
`incident_card_revisions` row, then `CARD_FIELD_CHANGED` followed by `SERVICE_DESELECTED`, which
is the order this operation's `x-emits` lists.

Deselecting a service that is not selected is a no-op: no revision, no events, `200` with the
unchanged selection — the same shape `selectRecipientService` gives a repeated selection.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import OperatorCommandGate
from app.application.operator.select_service import AVAILABLE_SERVICES, ensure_catalog_service
from app.application.operator.views import ServiceSelectionView, card_view
from app.application.ports.id_generator import IdGenerator
from app.application.ports.reference import ReferencePort
from app.application.reference.queries import reference_catalog
from app.domain.common.ids import CardRevisionId, SessionId
from app.domain.enums import ServiceId, ValueType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.layers.card_schema import CardSchema
from app.domain.layers.operator_card import OperatorCard, set_field

__all__ = ["ACTION_ID", "SERVICES_FIELD_PATH", "DeselectRecipientService"]

ACTION_ID = "select_services"
"""`openapi.yaml`'s `x-action` for `deselectRecipientService` — the same permission as selecting."""

SERVICES_FIELD_PATH = "recipients.services"
"""The `CARD_FIELDS` path the selection is stored in (§10.6)."""


class DeselectRecipientService:
    """`deselectRecipientService` (`openapi.yaml`): remove one recipient service from the card."""

    def __init__(
        self,
        gate: OperatorCommandGate,
        ids: IdGenerator,
        reference: ReferencePort | None = None,
    ) -> None:
        self._gate = gate
        self._ids = ids
        self._reference = reference

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, service_type: str
    ) -> ServiceSelectionView:
        """Remove the service, or answer unchanged when it was not selected. An id outside the
        session's service catalog is `422 SERVICE_UNKNOWN`, as for a selection."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            service_type = ensure_catalog_service(
                reference_catalog(self._reference), ctx.full_log, service_type
            )
            card = await ctx.card()
            current = _selected(card)
            if service_type not in current:
                return _view(card, current, ctx.card_schema)

            new_selection = tuple(service for service in current if service != service_type)
            updated, revision, card_event = set_field(
                card,
                SERVICES_FIELD_PATH,
                list(new_selection),
                ctx.actor,
                ctx.now_ms,
                CardRevisionId(self._ids.new()),
                schema=ctx.card_schema,
            )
            assert revision is not None and card_event is not None  # the list really changed

            await ctx.uow.operator_cards.save(updated)
            await ctx.uow.operator_cards.add_revision(revision, _services_value_type(card_event))
            deselected = DomainEvent(
                event_type=EventType.SERVICE_DESELECTED,
                actor=ctx.actor,
                monotonic_offset_ms=ctx.now_ms,
                payload={
                    "card_id": UUID(str(card.card_id)),
                    "revision_id": UUID(str(revision.revision_id)),
                    "service_type": service_type,
                    "selected_services": list(new_selection),
                    "at_offset_ms": ctx.now_ms,
                },
            )
            await ctx.append([card_event, deselected])
            return _view(updated, new_selection, ctx.card_schema)


def _selected(card: OperatorCard) -> tuple[ServiceId, ...]:
    """The card's `recipients.services`, as service ids; empty when unset."""
    raw = card.values.get(SERVICES_FIELD_PATH)
    if not isinstance(raw, list):
        return ()
    return tuple(ServiceId(value) for value in raw)


def _services_value_type(card_event: DomainEvent) -> ValueType:
    """The `recipients.services` `ValueType`, taken from the event `set_field` just built."""
    value_type = card_event.payload["value_type"]
    assert isinstance(value_type, ValueType)
    return value_type


def _view(
    card: OperatorCard, selection: tuple[ServiceId, ...], schema: CardSchema
) -> ServiceSelectionView:
    return ServiceSelectionView(
        card_id=UUID(str(card.card_id)),
        selected_services=selection,
        available_services=AVAILABLE_SERVICES,
        card=card_view(card, schema),
    )

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

**Only 112 adds services, and nobody removes them** (memo p.14, REQ-5275; HLD 70 §70.6.4, C10;
I3 E2b′): under any card schema other than `v1`, every removal is `409
SERVICE_REMOVAL_FORBIDDEN` — selected or not, manual or automatic — and nothing is written. A `v1`
card keeps today's behaviour, and `SERVICE_DESELECTED` stays for it and for old logs. An
automatically resolved service can never be removed on either schema: it is not in
`recipients.services`.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import OperatorCommandContext, OperatorCommandGate
from app.application.operator.select_service import ensure_catalog_service
from app.application.operator.views import ServiceSelectionView, service_selection_view
from app.application.ports.id_generator import IdGenerator
from app.application.ports.reference import ReferencePort
from app.application.reference.card_schemas import session_pack_id
from app.application.reference.queries import reference_catalog
from app.domain.common.errors import DomainError
from app.domain.common.ids import CardRevisionId, SessionId
from app.domain.enums import ServiceId, ValueType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.layers.operator_card import CARD_SCHEMA_V1, OperatorCard, set_field
from app.domain.routing.catalog import ReferenceCatalog

__all__ = [
    "ACTION_ID",
    "SERVICES_FIELD_PATH",
    "DeselectRecipientService",
    "ServiceRemovalForbiddenError",
]

ACTION_ID = "select_services"
"""`openapi.yaml`'s `x-action` for `deselectRecipientService` — the same permission as selecting."""

SERVICES_FIELD_PATH = "recipients.services"
"""The `CARD_FIELDS` path the selection is stored in (§10.6)."""


class ServiceRemovalForbiddenError(DomainError):
    """A service removal under a card schema other than `v1` (`409 SERVICE_REMOVAL_FORBIDDEN`,
    HLD 70 §70.6.4, C10)."""

    code = "SERVICE_REMOVAL_FORBIDDEN"

    def __init__(self, service_id: str, schema_id: str) -> None:
        self.service_id = service_id
        self.schema_id = schema_id
        super().__init__(
            f"service {service_id!r} cannot be removed: under card schema {schema_id} only 112 "
            "adds services and nobody removes them"
        )


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
            reference = reference_catalog(self._reference)
            service_type = ensure_catalog_service(reference, ctx.full_log, service_type)
            if ctx.card_schema.schema_id != CARD_SCHEMA_V1.schema_id:
                raise ServiceRemovalForbiddenError(service_type, ctx.card_schema.schema_id)
            card = await ctx.card()
            current = _selected(card)
            if service_type not in current:
                return _view(card, ctx, reference)

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
            return _view(updated, ctx, reference)


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
    card: OperatorCard, ctx: OperatorCommandContext, reference: ReferenceCatalog
) -> ServiceSelectionView:
    return service_selection_view(
        card, ctx.card_schema, ctx.full_log, reference.services(session_pack_id(ctx.full_log))
    )

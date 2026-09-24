"""`selectRecipientService` — add one service to `recipients.services` (`openapi.yaml`, §10.6).

The selection **is** a card field. `openapi.yaml` is explicit about why that matters: this command
*"writes `recipients.services`, so it emits `CARD_FIELD_CHANGED` in addition to `SERVICE_SELECTED`:
both the service evaluators and the card evaluators must be self-sufficient from the log alone
(D5)"*. The two events are appended in exactly that order, which is the order `x-emits` lists.

It is therefore the same write path as `setCardField` — the domain's `set_field`, one
`incident_card_revisions` row, one `CARD_FIELD_CHANGED` — with the service event on top. That is
why this module is on the INV 4 allow-list of
`backend/tests/invariants/test_inv_04_asr_never_mutates_card.py` and why it, too, imports nothing
transcript-, ASR- or voice-related.

Selecting an already selected service is a no-op (`openapi.yaml`): no revision, no events, `200`
with the unchanged selection. The new list preserves selection order and appends, so the report
can show the order the trainee chose in.

A service is a catalog id (I3 E2a, D18): an id that is not in the session's reference pack's
service catalog is `422 SERVICE_UNKNOWN` — the check the closed `ServiceType` enum used to make at
parse time. The session's pack is the one `SESSION_CREATED.reference_pack` recorded (`legacy-r1`
for a session created before E2a).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import OperatorCommandGate
from app.application.operator.views import ServiceSelectionView, card_view
from app.application.ports.id_generator import IdGenerator
from app.application.ports.reference import ReferencePort
from app.application.reference.queries import reference_catalog
from app.domain.common.errors import DomainError
from app.domain.common.ids import CardRevisionId, SessionId
from app.domain.enums import LEGACY_SERVICE_IDS, ServiceId, ValueType
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.operator_card import OperatorCard, set_field
from app.domain.routing.catalog import DEFAULT_PACK_ID, ReferenceCatalog

__all__ = [
    "ACTION_ID",
    "AVAILABLE_SERVICES",
    "SERVICES_FIELD_PATH",
    "SelectRecipientService",
    "ServiceUnknownError",
    "ensure_catalog_service",
    "session_pack_id",
]

ACTION_ID = "select_services"
"""`openapi.yaml`'s `x-action` for `selectRecipientService`."""

SERVICES_FIELD_PATH = "recipients.services"
"""The `CARD_FIELDS` path the selection is stored in (§10.6)."""

AVAILABLE_SERVICES: tuple[ServiceId, ...] = LEGACY_SERVICE_IDS
"""`ServiceSelectionView.available_services`: "every service the UI offers, including plausibly
wrong ones" — the trainee must be able to pick the wrong service (SPEC §10). Still the six legacy
ids: the catalog-wide picker (hidden and deprecated entries excluded under v2) is E2b's."""


class ServiceUnknownError(DomainError):
    """The id is not in the session's service catalog (`422 SERVICE_UNKNOWN`, HLD 70 §70.6.3)."""

    code = "SERVICE_UNKNOWN"

    def __init__(self, service_id: str, pack_id: str) -> None:
        self.service_id = service_id
        self.pack_id = pack_id
        super().__init__(
            f"service {service_id!r} is not in the catalog of reference pack {pack_id}"
        )


def session_pack_id(log: Sequence[SessionEvent]) -> str:
    """`SESSION_CREATED.reference_pack.pack_id`, or `legacy-r1` for a log that predates it."""
    for event in log:
        if event.event_type is not EventType.SESSION_CREATED:
            continue
        record = event.payload.get("reference_pack")
        if isinstance(record, Mapping) and isinstance(record.get("pack_id"), str):
            return str(record["pack_id"])
        break
    return DEFAULT_PACK_ID


def ensure_catalog_service(
    reference: ReferenceCatalog, log: Sequence[SessionEvent], service_id: str
) -> ServiceId:
    """`service_id` as a `ServiceId` when the session's catalog has it; else
    `ServiceUnknownError`."""
    pack_id = session_pack_id(log)
    catalog = reference.services(pack_id) or reference.services(DEFAULT_PACK_ID)
    if catalog is None or service_id not in catalog:
        raise ServiceUnknownError(service_id, pack_id)
    return ServiceId(service_id)


def selected_services(card: OperatorCard) -> tuple[ServiceId, ...]:
    """The card's `recipients.services`, as service ids; empty when unset."""
    raw = card.values.get(SERVICES_FIELD_PATH)
    if not isinstance(raw, list):
        return ()
    return tuple(ServiceId(value) for value in raw)


class SelectRecipientService:
    """`selectRecipientService` (`openapi.yaml`): add one recipient service to the card."""

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
        """Append the service, or answer unchanged when it is already selected."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            service_type = ensure_catalog_service(
                reference_catalog(self._reference), ctx.full_log, service_type
            )
            card = await ctx.card()
            current = selected_services(card)
            if service_type in current:
                return _view(card, current)

            new_selection = (*current, service_type)
            updated, revision, card_event = set_field(
                card,
                SERVICES_FIELD_PATH,
                list(new_selection),
                ctx.actor,
                ctx.now_ms,
                CardRevisionId(self._ids.new()),
            )
            assert revision is not None and card_event is not None  # the list really changed

            await ctx.uow.operator_cards.save(updated)
            await ctx.uow.operator_cards.add_revision(revision, _services_value_type(card_event))
            selected = DomainEvent(
                event_type=EventType.SERVICE_SELECTED,
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
            await ctx.append([card_event, selected])
            return _view(updated, new_selection)


def _services_value_type(card_event: DomainEvent) -> ValueType:
    """The `recipients.services` `ValueType`, taken from the event `set_field` just built.

    Reading it off the event rather than re-deriving it keeps the `incident_card_revisions` row
    and the `CARD_FIELD_CHANGED` payload stating the same thing by construction.
    """
    value_type = card_event.payload["value_type"]
    assert isinstance(value_type, ValueType)
    return value_type


def _view(card: OperatorCard, selection: tuple[ServiceId, ...]) -> ServiceSelectionView:
    return ServiceSelectionView(
        card_id=UUID(str(card.card_id)),
        selected_services=selection,
        available_services=AVAILABLE_SERVICES,
        card=card_view(card),
    )

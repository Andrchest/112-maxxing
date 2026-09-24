"""`setCardField` — the trainee writes exactly one card field (SPEC §9, §42 test 4; §10.6, D5).

This module is one of the **three** places in `app.application` allowed to call the domain's
`set_field` or to write through `OperatorCardRepository` (the others are `select_service` and
`deselect_service`; E9's `create_handoff` will be the fourth). That allow-list is asserted
structurally by `backend/tests/invariants/test_inv_04_asr_never_mutates_card.py`, which is what
makes "the operator card is not auto-filled from ASR" a property of the code's shape rather than
a promise: no transcript, ASR or voice module is reachable from here, and no module that handles
a transcript can reach the card writer.

One field per command, never a bulk write (`openapi.yaml`): SPEC §9 requires every mutation to be
stored with its previous value and actor, and a bulk write would blur which change happened when.

Four rejections, each with the code `openapi.yaml` names:

* a `field_path` outside the session's card schema — `422 CARD_FIELD_UNKNOWN` (`CARD_FIELDS` for a
  `v1` session; the pack's schema otherwise, I3 E3a, HLD 70 §70.5.4);
* a value that does not match the field's `value_type` — `422 CARD_VALUE_TYPE_MISMATCH`;
* a value that is not one of the field's option codes (a v2 `SELECT`/toggle set) — `422
  CARD_OPTION_UNKNOWN` (I3 E3a). A field hidden by `visible_when` is accepted: visibility is
  advisory (§70.5.2);
* `recipients.services`, which is "**not** settable here; use the service commands" — `422
  VALIDATION_ERROR`. The contract names no dedicated code for that case and the field *is* known,
  so `CARD_FIELD_UNKNOWN` would be a lie; `VALIDATION_ERROR` is the 422 that says "this request
  is not the right request". See the task report, "HLD gaps".

**Routing (I3 E2b′, HLD 70 §70.6.4).** When the field is `routing_relevant` and the session's
reference pack has a classifier, the routing resolver runs over the updated card and its answer is
appended as a SIMULATION `RECIPIENTS_RESOLVED` right after `CARD_FIELD_CHANGED`, in the same
transaction. It is a recorded event, not a card write: the command still makes exactly one
revision (INV 4, D3). A `v1` session has no routing-relevant field, so nothing changes for it.

Setting a field to its value is a no-op: `revision: null`, no `incident_card_revisions` row, no
`CARD_FIELD_CHANGED`, `200` with the unchanged card (`openapi.yaml`, §10.6).

Idempotency (`client_command_id`, §40.6): the first response body is stored under
`idempotency:{user_id}:{client_command_id}` for `IDEMPOTENCY_TTL_S`, and a repeat with the same
id returns it and appends nothing. Redis losing the key only degrades to re-evaluating the
command against PostgreSQL — never to a wrong answer — which is why the store is consulted
*before* the transaction opens and is never treated as authoritative.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import OperatorCommandContext, OperatorCommandGate
from app.application.operator.views import (
    ApplicationView,
    CardRevisionView,
    OperatorCardView,
    card_view,
    revision_view,
)
from app.application.ports.id_generator import IdGenerator
from app.application.ports.idempotency_store import IdempotencyStore, idempotency_key
from app.application.reference.card_schemas import session_pack_id
from app.domain.common.errors import CardFieldError, DomainError
from app.domain.common.ids import CardRevisionId, SessionId
from app.domain.common.values import FactValue
from app.domain.enums import ServiceId
from app.domain.events.session_event import DomainEvent
from app.domain.layers.card_schema import CardOptionUnknownError, CardSchema
from app.domain.layers.operator_card import (
    CARD_FIELDS,
    CardFieldSpec,
    CardRevision,
    OperatorCard,
    set_field,
)
from app.domain.routing.resolve import pack_routing, recipients_resolved_event

__all__ = [
    "ACTION_ID",
    "SERVICES_FIELD_PATH",
    "CardFieldNotSettableError",
    "CardFieldUnknownError",
    "CardOptionNotAllowedError",
    "CardValueTypeMismatchError",
    "SetCardField",
    "SetCardFieldResult",
]

ACTION_ID = "edit_card"
"""`openapi.yaml`'s `x-action` for `setCardField`."""

SERVICES_FIELD_PATH = "recipients.services"
"""The one `CARD_FIELDS` member this endpoint refuses: the service commands own it."""

FIELD_SPECS: Mapping[str, CardFieldSpec] = {spec.field_path: spec for spec in CARD_FIELDS}
"""`CARD_FIELDS` (the v1 schema) by path. A session's own schema is `ctx.card_schema`."""


class CardFieldUnknownError(DomainError):
    """`field_path` is not a `CARD_FIELDS` member (`422 CARD_FIELD_UNKNOWN`)."""

    code = "CARD_FIELD_UNKNOWN"


class CardValueTypeMismatchError(DomainError):
    """The value does not match the field's `value_type` (`422 CARD_VALUE_TYPE_MISMATCH`)."""

    code = "CARD_VALUE_TYPE_MISMATCH"


class CardOptionNotAllowedError(DomainError):
    """The value is not one of the field's option codes (`422 CARD_OPTION_UNKNOWN`, HLD 70
    §70.5.2)."""

    code = "CARD_OPTION_UNKNOWN"


class CardFieldNotSettableError(DomainError):
    """`recipients.services` is written by the service commands only (`422 VALIDATION_ERROR`)."""

    code = "VALIDATION_ERROR"


class SetCardFieldResult(ApplicationView):
    """`openapi.yaml`'s `SetCardFieldResponse`. `revision` is `null` for a no-op write."""

    card: OperatorCardView
    revision: CardRevisionView | None


class SetCardField:
    """`setCardField` (`openapi.yaml`): set exactly one card field (SPEC §9)."""

    def __init__(
        self,
        gate: OperatorCommandGate,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
    ) -> None:
        self._gate = gate
        self._ids = ids
        self._idempotency = idempotency

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        field_path: str,
        new_value: FactValue,
        client_command_id: UUID | None = None,
    ) -> SetCardFieldResult:
        """Validate, write one revision, append `CARD_FIELD_CHANGED`, return card + revision."""
        key = (
            None if client_command_id is None else idempotency_key(user.user_id, client_command_id)
        )
        if key is not None:
            cached = await self._idempotency.get(key)
            if cached is not None:
                return SetCardFieldResult.model_validate_json(cached)

        result = await self._apply(session_id, user, field_path, new_value)

        if key is not None:
            await self._idempotency.put(key, result.model_dump_json())
        return result

    async def _apply(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        field_path: str,
        new_value: FactValue,
    ) -> SetCardFieldResult:
        if field_path == SERVICES_FIELD_PATH:
            raise CardFieldNotSettableError(
                f"{SERVICES_FIELD_PATH!r} is written by selectRecipientService / "
                f"deselectRecipientService, not by setCardField"
            )
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            spec = _spec_for(ctx.card_schema, field_path)
            card = await ctx.card()
            try:
                updated, revision, event = set_field(
                    card,
                    field_path,
                    new_value,
                    ctx.actor,
                    ctx.now_ms,
                    CardRevisionId(self._ids.new()),
                    schema=ctx.card_schema,
                )
            except CardOptionUnknownError as error:
                raise CardOptionNotAllowedError(str(error)) from error
            except CardFieldError as error:
                # The path was checked above, and the actor is a `TRAINEE` by construction of the
                # command gate, so the only remaining rejection `set_field` makes is the type one.
                raise CardValueTypeMismatchError(str(error)) from error

            if revision is None or event is None:
                # §10.6: "no revision, no event". The card is unchanged, so nothing is written.
                return SetCardFieldResult(card=card_view(card, ctx.card_schema), revision=None)

            await ctx.uow.operator_cards.save(updated)
            await ctx.uow.operator_cards.add_revision(revision, spec.value_type)
            await ctx.append([event, *self._resolution(ctx, spec, updated, revision)])
            return SetCardFieldResult(
                card=card_view(updated, ctx.card_schema), revision=revision_view(revision)
            )

    def _resolution(
        self,
        ctx: OperatorCommandContext,
        spec: CardFieldSpec,
        card: OperatorCard,
        revision: CardRevision,
    ) -> list[DomainEvent]:
        """`[RECIPIENTS_RESOLVED]` for a routing-relevant change on a pack with a classifier."""
        if not spec.routing_relevant:
            return []
        routing = pack_routing(self._gate.reference, session_pack_id(ctx.full_log))
        if routing is None:
            return []
        manual = card.values.get(SERVICES_FIELD_PATH)
        return [
            recipients_resolved_event(
                routing.resolve(card.values),
                card_id=UUID(str(card.card_id)),
                card_revision_id=UUID(str(revision.revision_id)),
                pack_id=routing.pack_id,
                manual_services=(
                    [ServiceId(item) for item in manual] if isinstance(manual, list) else []
                ),
                final=False,
                at_offset_ms=ctx.now_ms,
            )
        ]


def _spec_for(schema: CardSchema, field_path: str) -> CardFieldSpec:
    """The session schema's entry for `field_path`, or the rejection `openapi.yaml` documents."""
    spec = schema.spec(field_path)
    if spec is None:
        raise CardFieldUnknownError(
            f"unknown card field path: {field_path!r} (card schema {schema.schema_id})"
        )
    return spec

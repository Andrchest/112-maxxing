"""`createHandoff` — freeze the card and send it to DDS (`openapi.yaml`, SPEC §10; D3, D5).

SPEC §10's six steps, in one Unit of Work and in this order:

1. the optional `CreateHandoffRequest.comment_ru` is written to the card field
   `recipients.comment` **before** anything is frozen, through the domain's `set_field` — a
   normal revision and a normal `CARD_FIELD_CHANGED`. The contract's own words: it is "written to
   the card field `recipients.comment` before freezing, so it is part of the snapshot rather than
   a side channel around it". That is why this module is on INV 4's card-writer allow-list;
2. "Validate allowed workflow state" — the gate's `available_actions` check, plus
   `409 RECIPIENT_SERVICES_EMPTY` when the card names no recipient service. The state machine's
   `guard_at_least_one_recipient_service` says the same thing, but a denied guard is
   `409 INVALID_TRANSITION`, and `openapi.yaml` gives this operation its own code;
3. "Create an immutable HandoffSnapshot" / "Freeze exactly the trainee-entered information" —
   `freeze_card_to_snapshot`, a by-value deep copy with a `content_sha256` over it. Editing the
   card afterwards cannot reach the snapshot: the copy is made here, once, and the row is
   immutable at rest (§20.9);
4. "Record selected recipient services" — `recipients.services`, in the order the trainee chose;
5. "Emit HANDOFF_CREATED";
6. "Create the DDS work item from the snapshot" — `snapshot_to_assignments` fans the snapshot out
   into one `DDSAssignment` leg per recipient service, all pointing at the DDS `RoleStage`. A
   `role_chain` with no DDS stage is the one case where that step produces nothing; see
   `_next_dds_stage_id` for why the handoff is still recorded.

`x-emits` is `[HANDOFF_CREATED, STAGE_STATE_CHANGED, HANDOFF_RECEIVED]` and that is the order the
events are appended in, with `HANDOFF_RECEIVED` repeated once per leg (`SIMULATION` actor, one
per receiving service — those N events are the log's only `assignment_id -> service_type` map, so
the materializer and the scoring slice can rebuild the legs from the log alone, D5). Exactly one
`HANDOFF_CREATED` is appended however many services were chosen: one trainee action, one trainee
event (E9 analyst R2/R5). A `CARD_FIELD_CHANGED` precedes all three when — and only when — a
comment was given; it is the same write `setCardField` would have made a second earlier.

**Nothing is read from `WorldTruth`** (SPEC §3, §10, §42 test 3): this module holds the operator
command gate, which carries no world-truth or caller-belief repository, and `freeze_card_to_
snapshot` / `snapshot_to_assignments` have no parameter one could arrive through. If the operator
entered house `72` where the world says `27`, DDS receives `72`, and a field the operator never
filled stays absent.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.command_context import (
    ActionNotAvailableError,
    OperatorCommandContext,
    OperatorCommandGate,
)
from app.application.operator.select_service import selected_services
from app.application.ports.id_generator import IdGenerator
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import CardRevisionId, RoleStageId, SessionId, UserId
from app.domain.common.values import FactValue
from app.domain.dds.assignment import DDSAssignment
from app.domain.enums import (
    ActorType,
    Operator112StageState,
    RoleType,
    ServiceId,
    SessionState,
    ValueType,
)
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.layers.copies import freeze_card_to_snapshot, snapshot_to_assignments
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import OperatorCard, set_field

__all__ = [
    "ACTION_ID",
    "COMMENT_FIELD_PATH",
    "CreateHandoff",
    "HandoffAlreadyCreatedError",
    "HandoffCreatedView",
    "HandoffSnapshotView",
    "RecipientServicesEmptyError",
    "handoff_snapshot_view",
]

ACTION_ID = "create_handoff"
"""`openapi.yaml`'s `x-action` for `createHandoff`."""

COMMENT_FIELD_PATH = "recipients.comment"
"""The `CARD_FIELDS` path `CreateHandoffRequest.comment_ru` is written to."""

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)
"""`HANDOFF_RECEIVED` is `SIMULATION`-authored (§10.13): DDS being handed the work item is not a
trainee action, and the trainee performed exactly one."""

_ALREADY_HANDED_OFF: frozenset[Operator112StageState] = frozenset(
    {Operator112StageState.HANDED_OFF, Operator112StageState.STAGE_COMPLETED}
)
"""The stage states a second `createHandoff` finds itself in (see `CreateHandoff.__call__`)."""


class RecipientServicesEmptyError(DomainError):
    """The card names no recipient service (`openapi.yaml`, `409 RECIPIENT_SERVICES_EMPTY`)."""

    code = "RECIPIENT_SERVICES_EMPTY"

    def __init__(self, session_id: SessionId) -> None:
        self.session_id = session_id
        super().__init__(
            f"session {session_id}: the card's recipients.services is empty, so there is no "
            "service to hand the incident to"
        )


class HandoffAlreadyCreatedError(DomainError):
    """The 112 stage already handed off (`openapi.yaml`, `409 HANDOFF_ALREADY_CREATED`).

    A `HandoffSnapshot` is immutable and there is exactly one per 112 stage: a second call is not
    "the trainee may not do that now", it is "that has already happened", and the contract gives
    the two different codes.
    """

    code = "HANDOFF_ALREADY_CREATED"

    def __init__(self, session_id: SessionId) -> None:
        self.session_id = session_id
        super().__init__(f"session {session_id} already has a handoff snapshot")


class HandoffSnapshotView(BaseModel):
    """`openapi.yaml`'s `HandoffSnapshotView`, property names literal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: UUID
    incident_id: UUID
    card_id: UUID
    card_revision_id: UUID
    card_values: dict[str, FactValue]
    recipient_services: tuple[ServiceId, ...]
    created_by_user_id: UUID
    created_at_offset_ms: int
    content_sha256: str


class HandoffCreatedView(BaseModel):
    """`openapi.yaml`'s `HandoffCreatedView` — what `createHandoff` answers with."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: HandoffSnapshotView
    assignment_ids: tuple[UUID, ...]
    stage_state: Operator112StageState
    session_state: SessionState


def handoff_snapshot_view(snapshot: HandoffSnapshot) -> HandoffSnapshotView:
    """`HandoffSnapshot` -> `HandoffSnapshotView`; a copy, never the frozen mapping itself."""
    return HandoffSnapshotView(
        snapshot_id=UUID(str(snapshot.snapshot_id)),
        incident_id=UUID(str(snapshot.incident_id)),
        card_id=UUID(str(snapshot.card_id)),
        card_revision_id=UUID(str(snapshot.card_revision_id)),
        card_values=dict(snapshot.card_values),
        recipient_services=tuple(snapshot.recipient_services),
        created_by_user_id=UUID(str(snapshot.created_by_user_id)),
        created_at_offset_ms=snapshot.created_at_offset_ms,
        content_sha256=snapshot.content_sha256,
    )


class CreateHandoff:
    """`createHandoff` (`openapi.yaml`): freeze the card, fan it out, hand it to DDS."""

    def __init__(self, gate: OperatorCommandGate, ids: IdGenerator) -> None:
        self._gate = gate
        self._ids = ids

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, comment_ru: str | None = None
    ) -> HandoffCreatedView:
        """Run the six steps of the module docstring in one transaction.

        The `ActionNotAvailableError` translation is the contract's `HANDOFF_ALREADY_CREATED`:
        `create_handoff` leaves `available_actions` the moment the stage reaches `HANDED_OFF`, so
        the gate — which checks the action before this body runs — is where a second call lands.
        Reading the stage state off the rejection turns "not available now" into the specific
        answer the contract asks for, without a second query for an event the stage state already
        implies.
        """
        try:
            async with self._gate.open(session_id, user, ACTION_ID) as ctx:
                return await self._handoff(ctx, user, comment_ru)
        except ActionNotAvailableError as error:
            if error.stage_state in _ALREADY_HANDED_OFF:
                raise HandoffAlreadyCreatedError(session_id) from error
            raise

    # -- steps ---------------------------------------------------------------------------------

    async def _handoff(
        self, ctx: OperatorCommandContext, user: AuthenticatedUser, comment_ru: str | None
    ) -> HandoffCreatedView:
        card = await ctx.card()
        card, revision_id = await self._write_comment(ctx, card, comment_ru)

        services = selected_services(card)
        if not services:
            raise RecipientServicesEmptyError(ctx.session_id)
        if revision_id is None:
            revision_id = await self._latest_revision_id(ctx, card)

        dds_stage_id = _next_dds_stage_id(ctx)
        snapshot = freeze_card_to_snapshot(
            card, revision_id, services, UserId(user.user_id), ctx.now_ms
        )
        legs = (
            ()
            if dds_stage_id is None
            else snapshot_to_assignments(snapshot, dds_stage_id, ctx.now_ms)
        )

        await ctx.uow.handoffs.add(snapshot)
        await ctx.uow.dds_assignments.add_all(legs)

        session, stage_events = ctx.session.fire_stage_trigger(
            ctx.stage.role_stage_id,
            ACTION_ID,
            actor=ctx.actor,
            now_ms=ctx.now_ms,
            runtime=ctx.guard_runtime(),
            card=card,
        )
        await ctx.save_session(session)
        await ctx.append(
            [
                _handoff_created(ctx, snapshot),
                *stage_events,
                *(_handoff_received(ctx, snapshot, leg) for leg in legs),
            ]
        )
        return HandoffCreatedView(
            snapshot=handoff_snapshot_view(snapshot),
            assignment_ids=tuple(UUID(str(leg.assignment_id)) for leg in legs),
            stage_state=ctx.stage_state,
            session_state=ctx.session.state,
        )

    async def _write_comment(
        self, ctx: OperatorCommandContext, card: OperatorCard, comment_ru: str | None
    ) -> tuple[OperatorCard, CardRevisionId | None]:
        """Write `recipients.comment` before freezing, and report the revision it made.

        `None` for the revision means "nothing changed here" — no comment was sent, or it equals
        what the field already held — and the snapshot then points at the card's latest existing
        revision instead.
        """
        if comment_ru is None:
            return card, None
        updated, revision, card_event = set_field(
            card,
            COMMENT_FIELD_PATH,
            comment_ru,
            ctx.actor,
            ctx.now_ms,
            CardRevisionId(self._ids.new()),
        )
        if revision is None or card_event is None:
            return card, None
        value_type = card_event.payload["value_type"]
        assert isinstance(value_type, ValueType)
        await ctx.uow.operator_cards.save(updated)
        await ctx.uow.operator_cards.add_revision(revision, value_type)
        await ctx.append([card_event])
        return updated, revision.revision_id

    async def _latest_revision_id(
        self, ctx: OperatorCommandContext, card: OperatorCard
    ) -> CardRevisionId:
        """The card's newest `incident_card_revisions` row — the revision being frozen.

        There is always one: `recipients.services` is non-empty by the check above, and the only
        way it became non-empty is `selectRecipientService`, which writes a revision.
        """
        _first, total = await ctx.uow.operator_cards.list_revisions(card.card_id, limit=1)
        newest, _total = await ctx.uow.operator_cards.list_revisions(
            card.card_id, limit=1, offset=max(0, total - 1)
        )
        if not newest:  # pragma: no cover - see the docstring
            raise RecipientServicesEmptyError(ctx.session_id)
        return newest[0].revision_id


# ---------------------------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------------------------


def _handoff_created(ctx: OperatorCommandContext, snapshot: HandoffSnapshot) -> DomainEvent:
    """`HANDOFF_CREATED` (TRAINEE) — one per trainee action, whatever N is (R5)."""
    return DomainEvent(
        event_type=EventType.HANDOFF_CREATED,
        actor=ctx.actor,
        monotonic_offset_ms=ctx.now_ms,
        payload={
            "snapshot_id": UUID(str(snapshot.snapshot_id)),
            "incident_id": UUID(str(snapshot.incident_id)),
            "card_id": UUID(str(snapshot.card_id)),
            "card_revision_id": UUID(str(snapshot.card_revision_id)),
            "recipient_services": list(snapshot.recipient_services),
            "card_values": dict(snapshot.card_values),
            "content_sha256": snapshot.content_sha256,
            "at_offset_ms": ctx.now_ms,
        },
    )


def _handoff_received(
    ctx: OperatorCommandContext, snapshot: HandoffSnapshot, leg: DDSAssignment
) -> DomainEvent:
    """`HANDOFF_RECEIVED` (SIMULATION) — one per leg; the log's `assignment -> service` map."""
    return DomainEvent(
        event_type=EventType.HANDOFF_RECEIVED,
        actor=_SIMULATION,
        monotonic_offset_ms=ctx.now_ms,
        payload={
            "snapshot_id": UUID(str(snapshot.snapshot_id)),
            "assignment_id": UUID(str(leg.assignment_id)),
            "role_stage_id": UUID(str(leg.role_stage_id)),
            "service_type": leg.service_type,
            "at_offset_ms": ctx.now_ms,
        },
    )


def _next_dds_stage_id(ctx: OperatorCommandContext) -> RoleStageId | None:
    """The `RoleStageId` of the DDS stage the legs belong to, or `None` when there is none.

    HLD gap (E9 analyst §7 #14): `dds_assignments.role_stage_id` is `NOT NULL` and
    `HANDOFF_RECEIVED` carries a `role_stage_id`, so a `role_chain` of `[OPERATOR_112]` alone has
    nowhere to put the fan-out. Rule R18 permits such a chain — it only requires the roles to be
    implemented — so the reading closest to SPEC §10 is taken: the snapshot is still frozen,
    because the trainee's work is recorded either way, and `assignment_ids` comes back empty with
    no `HANDOFF_RECEIVED`, because nobody received it. Refusing instead would make the handoff,
    and with it the whole 112 stage, uncompletable on a chain the scenario format allows.
    """
    stage = ctx.session.next_stage_after(ctx.stage)
    if stage is None or stage.role_type is not RoleType.DDS:
        return None
    return stage.role_stage_id

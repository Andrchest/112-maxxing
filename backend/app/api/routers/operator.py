"""`operator` router — Operator 112 stage commands (`Operator112Module`, SPEC §7, §9, §10; D8).

Nine of the `operator` tag's eleven operations. Each endpoint is three lines of work: ask the
container for the use case, call it, map the result — the authorisation, the transaction, the
domain call and the event append all live in `app.application.operator` (see that package's
`command_context` for the one pipeline they share). A router that decided any of that would be a
second place where D8's two gates could disagree with themselves.

Every **command** awaits `tick_after_command` after its use case has committed, which is D7's
"and immediately after each command": the world engine, and the simulation-driven call-flow hook
the runner carries, see the command's effects at once rather than up to one `SIM_TICK_MS` later.
The two reads (`getOperatorCard`, `listCardRevisions`) do not tick — a read changes nothing.

Not here, and deliberately:

* `createHandoff` and `completeOperatorStage` — TODO(E9). They freeze the card into a
  `HandoffSnapshot`, create the `DDSAssignment`s and complete the 112 stage, which is the
  handover into the DDS side this epic does not build;
* `continueToNextStage` (`POST /api/v1/sessions/{session_id}/stage/continue`) — TODO(E9). It
  fires `finish_role_transition`, which a session can only reach through `complete_stage`, i.e.
  through `completeOperatorStage`. Registering it now would publish an endpoint that no sequence
  of implemented operations can make reachable, and whose 409-before-the-pause behaviour could
  not be exercised at all; E9 owns both halves and should land them together.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep, TickAfterCommandDep
from app.api.schemas.operator import (
    CardRevisionPageSchema,
    EndCallRequestSchema,
    OperatorCardViewSchema,
    OperatorStageViewSchema,
    ServiceSelectionRequestSchema,
    ServiceSelectionViewSchema,
    SetCardFieldRequestSchema,
    SetCardFieldResponseSchema,
    card_revision_schema,
    operator_card_schema,
    operator_stage_schema,
    service_selection_schema,
    set_card_field_response_schema,
)
from app.api.security import CurrentUserDep
from app.domain.common.ids import SessionId

router = APIRouter(prefix="/api/v1/sessions", tags=["operator"])


@router.post(
    "/{session_id}/operator/call/answer",
    operation_id="answerCall",
    summary="Answer the ringing call.",
    response_model=OperatorStageViewSchema,
    status_code=200,
)
async def answer_call(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> OperatorStageViewSchema:
    """`RINGING --answer--> CONNECTED`; emits `CALL_ANSWERED` then `STAGE_STATE_CHANGED`."""
    view = await container.answer_call()(SessionId(session_id), user)
    await tick(SessionId(session_id))
    return operator_stage_schema(view)


@router.post(
    "/{session_id}/operator/call/end",
    operation_id="endCall",
    summary="Hang up the call.",
    response_model=OperatorStageViewSchema,
    status_code=200,
)
async def end_call(
    session_id: UUID,
    body: EndCallRequestSchema,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> OperatorStageViewSchema:
    """Emits `CALL_ENDED` and nothing else: ending the call is not a stage transition."""
    view = await container.end_call()(SessionId(session_id), user, body.reason)
    await tick(SessionId(session_id))
    return operator_stage_schema(view)


@router.get(
    "/{session_id}/operator/card",
    operation_id="getOperatorCard",
    summary="The current incident card.",
    response_model=OperatorCardViewSchema,
    status_code=200,
)
async def get_operator_card(
    session_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> OperatorCardViewSchema:
    """The card, for a caller whose role's `DataVisibilityPolicy` lists `OPERATOR_CARD` (D3)."""
    view = await container.get_operator_card()(SessionId(session_id), user)
    return operator_card_schema(view)


@router.put(
    "/{session_id}/operator/card/field",
    operation_id="setCardField",
    summary="Set exactly one card field.",
    response_model=SetCardFieldResponseSchema,
    status_code=200,
)
async def set_card_field(
    session_id: UUID,
    body: SetCardFieldRequestSchema,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> SetCardFieldResponseSchema:
    """One field per command (SPEC §9). The trainee is the only writer (§42 test 4)."""
    result = await container.set_card_field()(
        SessionId(session_id),
        user,
        field_path=body.field_path,
        new_value=body.new_value,
        client_command_id=body.client_command_id,
    )
    await tick(SessionId(session_id))
    return set_card_field_response_schema(result)


@router.get(
    "/{session_id}/operator/card/revisions",
    operation_id="listCardRevisions",
    summary="The card's revision history.",
    response_model=CardRevisionPageSchema,
    status_code=200,
)
async def list_card_revisions(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    field_path: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CardRevisionPageSchema:
    """Ascending by `revision_no` — SPEC §9's "the final card is NOT enough", made visible."""
    revisions, total = await container.list_card_revisions()(
        SessionId(session_id), user, field_path=field_path, limit=limit, offset=offset
    )
    return CardRevisionPageSchema(
        items=[card_revision_schema(revision) for revision in revisions], total=total
    )


@router.post(
    "/{session_id}/operator/services/select",
    operation_id="selectRecipientService",
    summary="Add one recipient service to the card.",
    response_model=ServiceSelectionViewSchema,
    status_code=200,
)
async def select_recipient_service(
    session_id: UUID,
    body: ServiceSelectionRequestSchema,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> ServiceSelectionViewSchema:
    """Writes `recipients.services`, so it emits `CARD_FIELD_CHANGED` *and* `SERVICE_SELECTED`."""
    view = await container.select_recipient_service()(
        SessionId(session_id), user, body.service_type
    )
    await tick(SessionId(session_id))
    return service_selection_schema(view)


@router.post(
    "/{session_id}/operator/services/deselect",
    operation_id="deselectRecipientService",
    summary="Remove one recipient service from the card.",
    response_model=ServiceSelectionViewSchema,
    status_code=200,
)
async def deselect_recipient_service(
    session_id: UUID,
    body: ServiceSelectionRequestSchema,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> ServiceSelectionViewSchema:
    """The mirror of the selection: `CARD_FIELD_CHANGED` then `SERVICE_DESELECTED`."""
    view = await container.deselect_recipient_service()(
        SessionId(session_id), user, body.service_type
    )
    await tick(SessionId(session_id))
    return service_selection_schema(view)


@router.post(
    "/{session_id}/operator/handoff/prepare",
    operation_id="beginHandoffPreparation",
    summary="Open the handoff preparation screen.",
    response_model=OperatorStageViewSchema,
    status_code=200,
)
async def begin_handoff_preparation(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> OperatorStageViewSchema:
    """`INTERVIEW --open_handoff_preparation--> HANDOFF_PREPARATION`; deliberately unguarded."""
    view = await container.begin_handoff_preparation()(SessionId(session_id), user)
    await tick(SessionId(session_id))
    return operator_stage_schema(view)


@router.post(
    "/{session_id}/operator/handoff/cancel",
    operation_id="backToInterview",
    summary="Return from handoff preparation to the interview.",
    response_model=OperatorStageViewSchema,
    status_code=200,
)
async def back_to_interview(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> OperatorStageViewSchema:
    """`HANDOFF_PREPARATION --back_to_interview--> INTERVIEW` (guard: call still connected)."""
    view = await container.back_to_interview()(SessionId(session_id), user)
    await tick(SessionId(session_id))
    return operator_stage_schema(view)

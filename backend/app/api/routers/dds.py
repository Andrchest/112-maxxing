"""`dds` router — the DDS stage's thirteen operations (`DDSModule`, SPEC §11, §12; D3, D8).

The eleven the `dds` tag has always had, plus the two E9 added additively so that
`open_resource_selection` and `back_to_acknowledged` — `available_actions` entries §10.9 listed
with no endpoint behind them — can actually be performed.

Every endpoint is three lines of work: ask the container for the use case, call it, map the result
— the authorisation, the transaction, the domain call and the event append all live in
`app.application.dds` (see that package's `command_context` for the one pipeline the eight
commands share). A router that decided any of that would be a second place where D8's two gates
could disagree with themselves.

Every **command** awaits `tick_after_command` after its use case has committed, which is D7's
"and immediately after each command": the world engine and the DDS stage automation see the
command's effects at once rather than up to one `SIM_TICK_MS` later. That matters more here than
on the 112 side — a dispatch is exactly the thing that makes a resource transition become due.
The four reads do not tick.

`closeDdsIncident` may end the *session* (the usual `[OPERATOR_112, DDS]` chain ends here), so it
releases the runner after its commit, exactly as `abortSession` and `completeOperatorStage` do
(D7), and — new in epic E15-B — scores the session in a transaction of its own once that commit is
durable: `score_completed_session` (`app.application.handoff.complete_session`) appends the
`SCORING_RULE_EVALUATED` row per rule that its own `x-emits` promises. A `ScoringEvidenceError`
there is logged and swallowed at that call, not raised through this endpoint (see that function's
docstring): the incident still closes and the session still completes even when a rule's evidence
could not be produced.

D3, structurally: no use case reached from here holds a world-truth, caller-belief or
operator-card repository, and this module names none of them —
`backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py` scans every module that
registers an operation of the `dds` tag, which is this one.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep, TickAfterCommandDep
from app.api.schemas.dds import (
    CloseIncidentRequestSchema,
    DdsStageViewSchema,
    DispatchRequestSchema,
    DispatchResultViewSchema,
    NotificationPageSchema,
    NotificationViewSchema,
    RadioMessagePageSchema,
    ResourcePageSchema,
    ResourceSelectionRequestSchema,
    StatusUpdateRequestSchema,
    StatusUpdateViewSchema,
    dds_stage_schema,
    dispatch_result_schema,
    notification_schema,
    radio_message_page_schema,
    resource_schema,
    status_update_schema,
)
from app.api.schemas.handoff import DdsWorkItemSchema, dds_work_item_schema
from app.api.schemas.sessions import SessionDetailSchema, session_detail_schema
from app.api.security import CurrentUserDep
from app.application.handoff.complete_session import score_completed_session
from app.domain.common.ids import ResourceId, SessionId
from app.domain.enums import ResourceStatus, ServiceType, SessionState

router = APIRouter(prefix="/api/v1/sessions", tags=["dds"])


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{session_id}/dds/work-item",
    operation_id="getDdsWorkItem",
    summary="The incoming work item — built only from the HandoffSnapshot.",
    response_model=DdsWorkItemSchema,
    status_code=200,
)
async def get_dds_work_item(
    session_id: UUID, container: ContainerDep, user: CurrentUserDep
) -> DdsWorkItemSchema:
    """Assembled from `handoff_snapshots` and `dds_assignments` alone (D3, SPEC §42 test 3)."""
    view = await container.get_dds_work_item()(SessionId(session_id), user)
    return dds_work_item_schema(view)


@router.get(
    "/{session_id}/dds/resources",
    operation_id="listDdsResources",
    summary="The resource board for this assignment.",
    response_model=ResourcePageSchema,
    status_code=200,
)
async def list_dds_resources(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    service_type: ServiceType | None = None,
    status: Annotated[list[ResourceStatus] | None, Query()] = None,
) -> ResourcePageSchema:
    """Scenario-defined units only; the ETA numbers are read verbatim (D7, SPEC §11)."""
    items, total = await container.list_dds_resources()(
        SessionId(session_id), user, service_type=service_type, status=status
    )
    return ResourcePageSchema(items=[resource_schema(item) for item in items], total=total)


@router.get(
    "/{session_id}/dds/notifications",
    operation_id="listNotifications",
    summary="Notifications addressed to the caller's role.",
    response_model=NotificationPageSchema,
    status_code=200,
)
async def list_notifications(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    unacknowledged_only: bool = False,
) -> NotificationPageSchema:
    """Filtered to the caller's role; the operator console calls the same endpoint."""
    items, total = await container.list_notifications()(
        SessionId(session_id), user, unacknowledged_only=unacknowledged_only
    )
    return NotificationPageSchema(items=[notification_schema(item) for item in items], total=total)


@router.get(
    "/{session_id}/dds/radio-messages",
    operation_id="listRadioMessages",
    summary="Radio traffic addressed to the caller's role.",
    response_model=RadioMessagePageSchema,
    status_code=200,
)
async def list_radio_messages(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    after_seq_no: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> RadioMessagePageSchema:
    """No table: projected from the log's `RADIO_MESSAGE_CREATED` rows (§20.1)."""
    page = await container.list_radio_messages()(
        SessionId(session_id), user, after_seq_no=after_seq_no, limit=limit
    )
    return radio_message_page_schema(page)


# ---------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------


@router.post(
    "/{session_id}/dds/acknowledge",
    operation_id="acknowledgeDdsAssignment",
    summary="Acknowledge the work item.",
    response_model=DdsStageViewSchema,
    status_code=200,
)
async def acknowledge_dds_assignment(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> DdsStageViewSchema:
    """`RECEIVED --acknowledge--> ACKNOWLEDGED`; emits `DDS_ACKNOWLEDGED` then the stage event."""
    view = await container.acknowledge_dds_assignment()(SessionId(session_id), user)
    await tick(SessionId(session_id))
    return dds_stage_schema(view)


@router.post(
    "/{session_id}/dds/resources/selection/open",
    operation_id="openDdsResourceSelection",
    summary="Open the resource-selection screen (additive, E9).",
    response_model=DdsStageViewSchema,
    status_code=200,
)
async def open_dds_resource_selection(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> DdsStageViewSchema:
    """`ACKNOWLEDGED` or `DISPATCHED` --open_resource_selection--> `RESOURCE_SELECTION`."""
    view = await container.open_dds_resource_selection()(SessionId(session_id), user)
    await tick(SessionId(session_id))
    return dds_stage_schema(view)


@router.post(
    "/{session_id}/dds/resources/selection/cancel",
    operation_id="backToDdsAcknowledged",
    summary="Leave the resource-selection screen without selecting (additive, E9).",
    response_model=DdsStageViewSchema,
    status_code=200,
)
async def back_to_dds_acknowledged(
    session_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> DdsStageViewSchema:
    """`RESOURCE_SELECTION --back_to_acknowledged--> ACKNOWLEDGED` (guard: nothing selected)."""
    view = await container.back_to_dds_acknowledged()(SessionId(session_id), user)
    await tick(SessionId(session_id))
    return dds_stage_schema(view)


@router.post(
    "/{session_id}/dds/resources/select",
    operation_id="selectDdsResource",
    summary="Select one resource.",
    response_model=DdsStageViewSchema,
    status_code=200,
)
async def select_dds_resource(
    session_id: UUID,
    body: ResourceSelectionRequestSchema,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> DdsStageViewSchema:
    """`AVAILABLE --select--> SELECTED`; a refused guard is `409 RESOURCE_UNAVAILABLE`."""
    view = await container.select_dds_resource()(
        SessionId(session_id), user, ResourceId(body.resource_id)
    )
    await tick(SessionId(session_id))
    return dds_stage_schema(view)


@router.post(
    "/{session_id}/dds/resources/deselect",
    operation_id="deselectDdsResource",
    summary="Deselect one resource.",
    response_model=DdsStageViewSchema,
    status_code=200,
)
async def deselect_dds_resource(
    session_id: UUID,
    body: ResourceSelectionRequestSchema,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> DdsStageViewSchema:
    """`SELECTED --deselect--> AVAILABLE` (guard: the unit was not yet dispatched)."""
    view = await container.deselect_dds_resource()(
        SessionId(session_id), user, ResourceId(body.resource_id)
    )
    await tick(SessionId(session_id))
    return dds_stage_schema(view)


@router.post(
    "/{session_id}/dds/resources/dispatch",
    operation_id="dispatchDdsResources",
    summary="Dispatch every currently selected resource.",
    response_model=DispatchResultViewSchema,
    status_code=200,
)
async def dispatch_dds_resources(
    session_id: UUID,
    body: DispatchRequestSchema | None,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> DispatchResultViewSchema:
    """`dispatch` the first time, `dispatch_additional` after — one event for the whole click."""
    view = await container.dispatch_dds_resources()(
        SessionId(session_id), user, None if body is None else body.note_ru
    )
    await tick(SessionId(session_id))
    return dispatch_result_schema(view)


@router.post(
    "/{session_id}/dds/status-updates",
    operation_id="sendDdsStatusUpdate",
    summary="Send an incident status update.",
    response_model=StatusUpdateViewSchema,
    status_code=201,
)
async def send_dds_status_update(
    session_id: UUID,
    body: StatusUpdateRequestSchema,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> StatusUpdateViewSchema:
    """Not a stage transition: available in every state `ACKNOWLEDGED`..`RESOLVED`."""
    view = await container.send_dds_status_update()(
        SessionId(session_id), user, update_kind=body.update_kind, text_ru=body.text_ru
    )
    await tick(SessionId(session_id))
    return status_update_schema(view)


@router.post(
    "/{session_id}/dds/notifications/{notification_id}/acknowledge",
    operation_id="acknowledgeNotification",
    summary="Acknowledge one notification.",
    response_model=NotificationViewSchema,
    status_code=200,
)
async def acknowledge_notification(
    session_id: UUID,
    notification_id: UUID,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> NotificationViewSchema:
    """`ACKNOWLEDGE_NOTIFICATION` is held by both trainee role modules; a second call is `409`."""
    view = await container.acknowledge_notification()(SessionId(session_id), user, notification_id)
    await tick(SessionId(session_id))
    return notification_schema(view)


@router.post(
    "/{session_id}/dds/close",
    operation_id="closeDdsIncident",
    summary="Close the incident.",
    response_model=SessionDetailSchema,
    status_code=200,
)
async def close_dds_incident(
    session_id: UUID,
    body: CloseIncidentRequestSchema,
    container: ContainerDep,
    user: CurrentUserDep,
    tick: TickAfterCommandDep,
) -> SessionDetailSchema:
    """`RESOLVED --close--> CLOSED`, then the session machine (see the module docstring)."""
    view = await container.close_dds_incident()(
        SessionId(session_id),
        user,
        closure_reason=body.closure_reason,
        comment_ru=body.comment_ru,
    )
    if view.session.state is SessionState.COMPLETED:
        if container.settings.runner_enabled:
            # After the commit, exactly as `abortSession` does: a completed session must stop
            # being ticked and must give up `lock:session:{id}:runner` (D7).
            await container.runner.release(view.session.id)
        # Also after the commit, and for the same reason (D7's "after the commit", extended to
        # scoring by epic E15-B): SESSION_COMPLETED is already durable, so scoring runs in its own
        # transaction rather than risking the one that just closed the incident.
        await score_completed_session(container.unit_of_work, view.session.id)
    else:
        await tick(SessionId(session_id))
    return session_detail_schema(view)

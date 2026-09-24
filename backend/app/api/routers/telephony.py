"""`telephony` router — the SIP gateway's four operations (I3 E6e, HLD `80-telephony.md` §80.2.3,
§80.3.5, §80.7; `openapi.yaml` tag `telephony`): `dialFromSip`, `getTelephonyCall`,
`reportSipLeg`, `getSipCredential`.

Every operation is gated by the gateway's service credential (`security: sipGatewaySecret`, the
`X-Sip-Gateway-Secret` header against `SIM_SIP_GATEWAY_SECRET`) and by nothing else — a trainee's
bearer token opens none of them. The two that change a call (`dialFromSip`, `reportSipLeg`) tick the
session after their commit, as every command endpoint does (D7), so a call just rung is answered by
the AI callee on time rather than one `SIM_TICK_MS` later.

As in the `dds` router, the authorisation, the transaction, the domain call and the event append
live in `app.application.telephony`; no use case reached from here holds a world-truth,
caller-belief or operator-card repository (INV 3).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Path

from app.api.deps import ContainerDep, TickAfterCommandDep
from app.api.schemas.dds_calls import DdsCallViewSchema, dds_call_schema
from app.api.schemas.telephony import (
    SipCredentialViewSchema,
    SipDialRequestSchema,
    SipDialResponseSchema,
    SipLegReportSchema,
    sip_credential_schema,
    sip_dialed_schema,
)
from app.api.security import SipGatewayDep
from app.domain.common.ids import SessionId

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/telephony", tags=["telephony"])


@router.post(
    "/dial",
    operation_id="dialFromSip",
    summary="The SIP gateway asks the backend to start the call a registered softphone dialled.",
    response_model=SipDialResponseSchema,
    status_code=201,
)
async def dial_from_sip(
    body: SipDialRequestSchema,
    container: ContainerDep,
    _gateway: SipGatewayDep,
    tick: TickAfterCommandDep,
) -> SipDialResponseSchema:
    """Session selection + dial plan, then `startDdsCall` with the `SIP` endpoint (§80.3.5)."""
    dialed = await container.dial_from_sip()(body.sip_user, body.dialed)
    await tick(SessionId(dialed.session_id))
    return sip_dialed_schema(dialed)


@router.get(
    "/calls/{call_id}",
    operation_id="getTelephonyCall",
    summary="The gateway re-reads a call it bridges (after a Redis reconnect or its own restart).",
    response_model=DdsCallViewSchema,
    status_code=200,
)
async def get_telephony_call(
    call_id: UUID, container: ContainerDep, _gateway: SipGatewayDep
) -> DdsCallViewSchema:
    """One `dds_calls` row, without `available_actions` (the gateway is not a participant)."""
    return dds_call_schema(await container.get_telephony_call()(call_id))


@router.post(
    "/calls/{call_id}/leg",
    operation_id="reportSipLeg",
    summary="The gateway reports its softphone leg of a SIP-endpoint call.",
    response_model=DdsCallViewSchema,
    status_code=200,
)
async def report_sip_leg(
    call_id: UUID,
    body: SipLegReportSchema,
    container: ContainerDep,
    _gateway: SipGatewayDep,
    tick: TickAfterCommandDep,
) -> DdsCallViewSchema:
    """`UP` rings (or answers an INBOUND call), `FAILED` aborts, `DOWN` hangs up (§80.2.3)."""
    result = await container.report_sip_leg()(call_id, body.state, body.sip_status)
    await tick(result.session_id)
    return dds_call_schema(result.view)


@router.get(
    "/sip-credentials/{username}",
    operation_id="getSipCredential",
    summary="Per-user SIP HA1 for the registrar (migration 0015).",
    response_model=SipCredentialViewSchema,
    status_code=200,
)
async def get_sip_credential(
    container: ContainerDep,
    _gateway: SipGatewayDep,
    username: str = Path(min_length=1, max_length=128),
) -> SipCredentialViewSchema:
    """`users.sip_ha1`: `404` without one, `403` for an unknown or retired account."""
    return sip_credential_schema(await container.get_sip_credential()(username))

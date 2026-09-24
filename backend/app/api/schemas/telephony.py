"""`telephony` schemas — the SIP gateway's endpoints (I3 E6e, `openapi.yaml` `SipDialRequest`,
`SipDialResponse`, `SipLegReport`, `SipCredentialView`; HLD `80-telephony.md` §80.2.3).

Property names literal, one explicit mapping per model (D2). `SipCredentialView.ha1` is a credential
digest: it is serialised into its one response body and never logged (SPEC §41).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.telephony.dial_from_sip import SipDialed
from app.application.telephony.reads import SipCredential
from app.application.telephony.report_sip_leg import SipLegState
from app.domain.dds.call import DdsCallKind

__all__ = [
    "SipCredentialViewSchema",
    "SipDialRequestSchema",
    "SipDialResponseSchema",
    "SipLegReportSchema",
    "sip_credential_schema",
    "sip_dialed_schema",
]


class SipDialRequestSchema(ApiModel):
    """`openapi.yaml`'s `SipDialRequest`."""

    sip_user: Annotated[str, Field(min_length=1, max_length=128)]
    dialed: Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[0-9*#+]+$")]
    sip_call_id: Annotated[str, Field(min_length=1, max_length=256)]


class SipDialResponseSchema(ApiModel):
    """`openapi.yaml`'s `SipDialResponse`."""

    call_id: UUID
    session_id: UUID
    room_name: str
    kind: DdsCallKind
    persona_id: str | None


class SipLegReportSchema(ApiModel):
    """`openapi.yaml`'s `SipLegReport`."""

    state: SipLegState
    sip_status: Annotated[int | None, Field(ge=100, le=699)] = None


class SipCredentialViewSchema(ApiModel):
    """`openapi.yaml`'s `SipCredentialView`."""

    username: str
    realm: str
    ha1: str = Field(repr=False)


def sip_dialed_schema(dialed: SipDialed) -> SipDialResponseSchema:
    """`SipDialed` -> the wire model."""
    return SipDialResponseSchema(
        call_id=dialed.call_id,
        session_id=dialed.session_id,
        room_name=dialed.room_name,
        kind=dialed.kind,
        persona_id=dialed.persona_id,
    )


def sip_credential_schema(credential: SipCredential) -> SipCredentialViewSchema:
    """`SipCredential` -> the wire model."""
    return SipCredentialViewSchema(
        username=credential.username, realm=credential.realm, ha1=credential.ha1
    )

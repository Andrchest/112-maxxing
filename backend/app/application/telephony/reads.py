"""The SIP gateway's two reads (I3 E6e, HLD `80-telephony.md` §80.2.3, §80.7, `openapi.yaml`).

* `GetTelephonyCall` — `getTelephonyCall`: the gateway re-reads a call it bridges (after a Redis
  reconnect or its own restart). The view carries no `available_actions`: the gateway is not a
  participant, it only relays the softphone.
* `GetSipCredential` — `getSipCredential`: the per-user SIP HA1 (`users.sip_ha1`, migration `0015`)
  for the registrar. An account that does not exist, or is retired, is `403` — the registrar answers
  that softphone's REGISTER `403` (manager decision 3 of E6e: an unknown SIP username is refused);
  an account without an HA1 is `404`, and the deployment password then applies. The HA1 is a
  credential digest: it is returned in this one response body and never logged (SPEC §41).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.application.dds.dds_call_views import (
    DdsCallNotFoundError,
    DdsCallView,
    dds_call_view,
    persona_title_of,
    session_personas,
)
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.queries import ForbiddenForRoleError
from app.domain.common.errors import DomainError

__all__ = [
    "GetSipCredential",
    "GetTelephonyCall",
    "SipCredential",
    "SipCredentialNotSetError",
]


class SipCredentialNotSetError(DomainError):
    """The account has no per-user HA1 — the deployment password applies (`404`)."""

    code = "NOT_FOUND"

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"user {username!r} has no per-user SIP credential")


@dataclass(frozen=True)
class SipCredential:
    """`openapi.yaml`'s `SipCredentialView`."""

    username: str
    realm: str
    ha1: str = field(repr=False)


class GetTelephonyCall:
    """`getTelephonyCall` — one ДДС call by id, for the gateway."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, reference: ReferencePort | None = None
    ) -> None:
        self._unit_of_work = unit_of_work
        self._reference = reference

    async def __call__(self, call_id: UUID) -> DdsCallView:
        async with self._unit_of_work() as uow:
            call = await uow.dds_calls.get_by_id(call_id)
            if call is None:
                raise DdsCallNotFoundError(call_id)
            personas = session_personas(self._reference, await uow.events.read(call.session_id))
            await uow.commit()
        return dds_call_view(call, None, persona_title_ru=persona_title_of(call, personas))


class GetSipCredential:
    """`getSipCredential` — the per-user HA1 of an active account (see the module docstring)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, realm: str) -> None:
        self._unit_of_work = unit_of_work
        self._realm = realm

    async def __call__(self, username: str) -> SipCredential:
        async with self._unit_of_work() as uow:
            user = await uow.users.get_by_username(username)
            await uow.commit()
        if user is None or not user.is_active:
            raise ForbiddenForRoleError(f"SIP user {username!r} is not an active account")
        if user.sip_ha1 is None:
            raise SipCredentialNotSetError(username)
        return SipCredential(username=user.username, realm=self._realm, ha1=user.sip_ha1)

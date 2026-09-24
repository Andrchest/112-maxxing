"""`dialFromSip` — a registered softphone dialled a number (I3 E6e, HLD `80-telephony.md` §80.2.3
step 2, §80.3.5, `openapi.yaml`).

The SIP gateway answers the softphone's INVITE with `100 Trying` and asks this use case which call
the digits are. Three steps, in this order:

1. **The user.** `sip_user` is a `users.username` (§80.3.5: "SIP username ↔ `users.username`"); an
   unknown or retired account is `403 FORBIDDEN_FOR_ROLE` — the gateway answers the softphone `403`.
2. **The session** (§80.3.5's selection rule). The candidates are the user's `ACTIVE` sessions in
   which they are a ДДС participant, the DDS stage is the active stage and the ДДС has a phone
   (`dds_brigade_call: ON`, D25 — a session without one has nobody to ring). The session whose
   card this user opened last (`DDS_CARD_OPENED`, by wall-clock stamp) wins — `LAST_OPENED_CARD`;
   else the oldest by start — `OLDEST_ACTIVE`. None ⇒ `409 NO_ACTIVE_DDS_SESSION` (SIP `480`).
3. **The number**, by the pure dial plan (`domain/routing/dial_plan.py`) against that session's
   service catalog and the frozen snapshot's claimant number: `112` ⇒ `OPERATOR_112`; a catalog
   `code` or `7xxx` ⇒ `SERVICE_HEAD` of that service's leg on the selected card; the claimant's
   digits ⇒ `CLAIMANT`. Anything else — and a service with no leg on the card, or a leg this user
   does not play — ⇒ `404 DIAL_NUMBER_UNKNOWN` (SIP `404`).

Then the call is started by the one `startDdsCall` use case (its gate, its line-busy rule, its
persona resolution), with `SipOrigin {dialed, selection_reason}`: the endpoint is `SIP`, `dialed`
is the digits as dialled, and the selection is recorded on `DDS_CALL_STARTED` (P4). The call stays
`DIALING` until the gateway reports `leg UP` (`reportSipLeg`), which rings it.

The selection reads: no row lock is taken here (the gate takes the session's). The card, its legs
and the catalog are frozen once the DDS stage is live, so reading them before the gate opens
cannot disagree with what the gate then sees.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import dds_stage_of, load_legs
from app.application.dds.start_dds_call import SipOrigin, StartDdsCall, claimant_number
from app.application.ports.reference import ReferencePort
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.reference.card_schemas import session_pack_id
from app.application.reference.queries import reference_catalog
from app.application.sessions.queries import ForbiddenForRoleError
from app.domain.common.errors import DomainError
from app.domain.common.ids import AssignmentId, SessionId, UserId
from app.domain.dds.call import CallSelectionReason, DdsCallKind
from app.domain.dds.responders import plays_leg
from app.domain.enums import SessionState
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.routing.catalog import ServiceCatalog
from app.domain.routing.dial_plan import resolve_dial
from app.domain.session.session import SimulationSession
from app.domain.session.variants import DdsBrigadeCall

__all__ = [
    "DialFromSip",
    "DialNumberUnknownError",
    "NoActiveDdsSessionError",
    "SessionCandidate",
    "SipDialed",
    "select_dds_session",
]

_NON_DIGIT = re.compile(r"\D")
_EMPTY_CATALOG = ServiceCatalog(catalog_id="none", services=())


class DialNumberUnknownError(DomainError):
    """The dialled digits reach nobody on the selected card (`404 DIAL_NUMBER_UNKNOWN`)."""

    code = "DIAL_NUMBER_UNKNOWN"

    def __init__(self, dialed: str) -> None:
        self.dialed = dialed
        super().__init__(f"number {dialed!r} reaches nobody on the selected ДДС card")


class NoActiveDdsSessionError(DomainError):
    """No `ACTIVE` session where the user is a ДДС participant with a phone
    (`409 NO_ACTIVE_DDS_SESSION`)."""

    code = "NO_ACTIVE_DDS_SESSION"

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"user {username!r} has no ACTIVE ДДС session with a phone")


@dataclass(frozen=True)
class SipDialed:
    """`openapi.yaml`'s `SipDialResponse`: what the gateway bridges the softphone into."""

    call_id: UUID
    session_id: UUID
    room_name: str
    kind: DdsCallKind
    persona_id: str | None


@dataclass(frozen=True)
class SessionCandidate:
    """One eligible session for the selection rule."""

    session_id: SessionId
    started_at: datetime | None
    last_opened_at: datetime | None
    """When this user last opened the session's card (`DDS_CARD_OPENED`), or `None`."""


def select_dds_session(
    candidates: Sequence[SessionCandidate],
) -> tuple[SessionId, CallSelectionReason] | None:
    """§80.3.5: the card this user opened last wins, else the oldest session; `None` if empty.

    Pure and total: ties fall to the session id, so the answer never depends on list order.
    """
    opened = [item for item in candidates if item.last_opened_at is not None]
    if opened:
        chosen = max(opened, key=lambda item: (item.last_opened_at, str(item.session_id)))
        return chosen.session_id, CallSelectionReason.LAST_OPENED_CARD
    if not candidates:
        return None
    chosen = min(
        candidates,
        key=lambda item: (
            item.started_at is None,
            0.0 if item.started_at is None else item.started_at.timestamp(),
            str(item.session_id),
        ),
    )
    return chosen.session_id, CallSelectionReason.OLDEST_ACTIVE


def _eligible(session: SimulationSession, user_id: UserId) -> bool:
    """`ACTIVE`, a ДДС participant, the DDS stage live, and the ДДС has a phone (D25)."""
    return (
        session.state is SessionState.ACTIVE
        and session.plays_dds(user_id)
        and dds_stage_of(session) is not None
        and session.variants.dds_brigade_call is DdsBrigadeCall.ON
    )


def _last_opened_at(log: Sequence[SessionEvent], user_id: UserId) -> datetime | None:
    stamps = [
        event.timestamp_utc
        for event in log
        if event.event_type is EventType.DDS_CARD_OPENED and event.actor_id == user_id
    ]
    return max(stamps) if stamps else None


class DialFromSip:
    """`dialFromSip` (`openapi.yaml`)."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        start_dds_call: StartDdsCall,
        reference: ReferencePort | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._start_dds_call = start_dds_call
        self._reference = reference

    async def __call__(self, sip_user: str, dialed: str) -> SipDialed:
        digits = _NON_DIGIT.sub("", dialed)
        async with self._unit_of_work() as uow:
            stored = await uow.users.get_by_username(sip_user)
            if stored is None or not stored.is_active:
                raise ForbiddenForRoleError(f"SIP user {sip_user!r} is not an active account")
            user = AuthenticatedUser(
                user_id=stored.user_id,
                username=stored.username,
                display_name_ru=stored.display_name_ru,
                user_role=stored.user_role,
            )
            selected = select_dds_session(await self._candidates(uow, user.user_id))
            if selected is None:
                raise NoActiveDdsSessionError(sip_user)
            session_id, reason = selected
            kind, assignment_id = await self._resolve(uow, session_id, user.user_id, digits)
            await uow.commit()
        started = await self._start_dds_call(
            session_id,
            user,
            kind,
            assignment_id,
            sip=SipOrigin(dialed=digits, selection_reason=reason),
        )
        call = started.call
        return SipDialed(
            call_id=call.call_id,
            session_id=call.session_id,
            room_name=call.room_name,
            kind=call.kind,
            persona_id=call.persona_id,
        )

    async def _candidates(self, uow: UnitOfWork, user_id: UserId) -> list[SessionCandidate]:
        candidates: list[SessionCandidate] = []
        for session_id in await uow.sessions.list_active_session_ids():
            session = await uow.sessions.get(session_id)
            if session is None or not _eligible(session, user_id):
                continue
            log = await uow.events.read(session_id)
            candidates.append(
                SessionCandidate(
                    session_id=session_id,
                    started_at=session.started_at,
                    last_opened_at=_last_opened_at(log, user_id),
                )
            )
        return candidates

    async def _resolve(
        self, uow: UnitOfWork, session_id: SessionId, user_id: UserId, digits: str
    ) -> tuple[DdsCallKind, AssignmentId | None]:
        """The dial plan against the selected card (§80.3.5); `404` for anything it cannot reach."""
        session = await uow.sessions.get(session_id)
        stage = None if session is None else dds_stage_of(session)
        if stage is None:  # pragma: no cover - selected as eligible in the same transaction
            raise NoActiveDdsSessionError(str(user_id))
        legs, snapshot = await load_legs(uow, session_id, stage)
        log = await uow.events.read(session_id)
        catalog = reference_catalog(self._reference).services(session_pack_id(log))
        target = resolve_dial(
            digits,
            catalog=catalog if catalog is not None else _EMPTY_CATALOG,
            claimant_phone=claimant_number(snapshot),
        )
        if target is None:
            raise DialNumberUnknownError(digits)
        if target.kind is not DdsCallKind.SERVICE_HEAD:
            return target.kind, None
        leg = next((item for item in legs if item.service_type == target.service_id), None)
        if leg is None or not plays_leg(leg, user_id):
            raise DialNumberUnknownError(digits)
        return target.kind, leg.assignment_id

"""Lesson and incident reads (HLD 70 §70.3.6; `getLesson`, `listLessons`, `listMyIncidents`).

* `GetLesson` — the plan, the sessions, each card's materialised `card_status` and
  `display_number`. An INSTRUCTOR/ADMIN reads any lesson; a TRAINEE only a lesson they are a
  participant of (`403 PARTICIPANT_NOT_ASSIGNED` otherwise), and only the cards of their own
  workstation (`PlanEntry.participants`, I3 E9a).
* `ListLessons` — `scope=MINE` (created or participating) or `scope=ALL` (INSTRUCTOR/ADMIN only).
* `ListMyIncidents` — the caller's cross-session incident list: the ДДС «Список/Поиск
  происшествий» and the 112 «реестр». One row per session the caller participates in (or
  created), with the materialised `card_status` and the deadline offsets; the client renders
  countdowns from `session_offset_ms` and never decides a status. A trainee sees a row only once
  its card has arrived (the session is `ACTIVE`, `ROLE_TRANSITION` or terminal).

The deadlines are read off the same `CardStatusFold` the flush-before-append rule keeps: the accept
deadline of the earliest leg still without a primary decision, the fill deadline from
`CALL_ANSWERED` until the handoff exists (never under `GENERATED_CARD`, where no call runs), the
not-completed deadline from the handoff until the card is `COMPLETED`. The address line of a
ДДС row comes from the handoff snapshot, of any other row from the live card — never from
`WorldTruth` (D3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.lessons.errors import LessonNotFoundError, NotALessonParticipantError
from app.application.ports.clock import Clock
from app.application.ports.lesson_repository import StoredLessonListing
from app.application.ports.session_repository import StoredIncidentRow
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.simulation.sim_time import running_ms
from app.application.timebase import session_offset_ms
from app.domain.common.ids import IncidentId, LessonId, SessionId, SnapshotId
from app.domain.common.values import FactValue
from app.domain.dds.card_status import CardStatus, CardStatusFold, fold_card_status
from app.domain.dds.response import ServiceResponseStatus
from app.domain.enums import RoleType, SessionState
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.lesson.lesson import Lesson, LessonState
from app.domain.lesson.plan import Arrival
from app.domain.session.session import SimulationSession
from app.domain.session.variants import SessionVariants

__all__ = [
    "GetLesson",
    "IncidentListItemView",
    "LessonDetailView",
    "LessonSessionView",
    "ListLessons",
    "ListMyIncidents",
    "assemble_lesson_detail",
]

_ARRIVED = frozenset(
    {
        SessionState.ACTIVE,
        SessionState.ROLE_TRANSITION,
        SessionState.COMPLETED,
        SessionState.ABORTED,
    }
)
_ADDRESS_PARTS: tuple[tuple[str, str], ...] = (
    ("address.locality", "{}"),
    ("address.street", "{}"),
    ("address.house", "д. {}"),
    ("address.building", "корп. {}"),
    ("address.apartment", "кв. {}"),
)
_CLASSIFIER_CODE_PATH = "incident.classifier_code"


@dataclass(frozen=True)
class LessonSessionView:
    """`LessonSessionView` — one card of a lesson."""

    position: int
    session_id: SessionId
    incident_id: IncidentId
    display_number: int
    state: SessionState
    card_status: CardStatus
    arrival: Arrival
    started_at_lesson_offset_ms: int | None
    variants: SessionVariants


@dataclass(frozen=True)
class LessonDetailView:
    """`LessonDetail` as application data."""

    lesson: Lesson
    sessions: tuple[LessonSessionView, ...]


@dataclass(frozen=True)
class IncidentListItemView:
    """`IncidentListItem` as application data, property names literal."""

    session_id: SessionId
    incident_id: IncidentId
    display_number: int
    lesson_id: LessonId | None
    card_status: CardStatus
    session_state: SessionState
    arrived_at_utc: datetime | None
    session_offset_ms: int
    accept_deadline_offset_ms: int | None
    fill_deadline_offset_ms: int | None
    not_completed_deadline_offset_ms: int | None
    classifier_code: str | None
    address_line_ru: str | None
    my_role_type: RoleType | None
    service_leg_status: ServiceResponseStatus | None = None
    """ADDITIVE (I7 E50, memo p.40 «Статус службы»): the viewing ДДС participant's own leg — the
    `DDSAssignment` bound to them (I3 E9a `assigned_service_id`) — its last memo status; `None` for
    a 112-register row, for an instructor/admin viewer, or when nobody is bound to a single leg
    (one trainee plays every leg, §70.4.5 — ambiguous, so left unset rather than guessed)."""
    service_leg_status_at_offset_ms: int | None = None
    """ADDITIVE (I7 E50): when `service_leg_status` was last set."""


def _is_participant(lesson: Lesson, user: AuthenticatedUser) -> bool:
    return any(participant.user_id == user.user_id for participant in lesson.participants)


async def assemble_lesson_detail(uow: UnitOfWork, lesson: Lesson) -> LessonDetailView:
    """The lesson with one `LessonSessionView` per card, inside an open Unit of Work."""
    views: list[LessonSessionView] = []
    for card in await uow.lessons.list_cards(lesson.lesson_id):
        session = await uow.sessions.get(card.session_id)
        if session is None:  # pragma: no cover - the card was listed from the same rows
            continue
        started_offset = (
            None
            if card.started_at is None or lesson.started_at is None
            else session_offset_ms(card.started_at, lesson.started_at)
        )
        views.append(
            LessonSessionView(
                position=card.position,
                session_id=card.session_id,
                incident_id=card.incident_id,
                display_number=card.display_number,
                state=card.state,
                card_status=card.card_status,
                arrival=lesson.entry(card.position).arrival,
                started_at_lesson_offset_ms=started_offset,
                variants=session.variants,
            )
        )
    return LessonDetailView(lesson=lesson, sessions=tuple(views))


class GetLesson:
    """`getLesson`."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, lesson_id: LessonId, user: AuthenticatedUser) -> LessonDetailView:
        async with self._unit_of_work() as uow:
            lesson = await uow.lessons.get(lesson_id)
            if lesson is None:
                raise LessonNotFoundError(lesson_id)
            if not user.is_instructor_or_admin and not _is_participant(lesson, user):
                raise NotALessonParticipantError(lesson_id)
            view = await assemble_lesson_detail(uow, lesson)
            await uow.commit()
        if user.is_instructor_or_admin:
            return view
        return LessonDetailView(
            lesson=view.lesson,
            sessions=tuple(
                card for card in view.sessions if _plays_card(lesson, card.position, user)
            ),
        )


def _plays_card(lesson: Lesson, position: int, user: AuthenticatedUser) -> bool:
    """The card is the user's: its entry names no subset, or a subset that includes them."""
    chosen = lesson.entry(position).participants
    return chosen is None or user.user_id in chosen


class ListLessons:
    """`listLessons`."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        *,
        viewer: AuthenticatedUser,
        scope: str,
        state: LessonState | None,
        limit: int,
        offset: int,
    ) -> tuple[list[StoredLessonListing], int]:
        if scope == "ALL" and not viewer.is_instructor_or_admin:
            raise ForbiddenForRoleError("scope=ALL is permitted for INSTRUCTOR/ADMIN only")
        async with self._unit_of_work() as uow:
            items, total = await uow.lessons.list_lessons(
                viewer_user_id=viewer.user_id,
                mine_only=scope != "ALL",
                state=state,
                limit=limit,
                offset=offset,
            )
            await uow.commit()
        return items, total


class ListMyIncidents:
    """`listMyIncidents`."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self,
        *,
        viewer: AuthenticatedUser,
        lesson_id: LessonId | None = None,
        role_type: RoleType | None = None,
        card_status: CardStatus | None = None,
        q: str | None = None,
    ) -> list[IncidentListItemView]:
        items: list[IncidentListItemView] = []
        async with self._unit_of_work() as uow:
            rows = await uow.sessions.list_incident_rows(
                viewer_user_id=viewer.user_id, lesson_id=lesson_id
            )
            for row in rows:
                if not viewer.is_instructor_or_admin and (
                    not row.is_participant or row.session_state not in _ARRIVED
                ):
                    continue
                if role_type is not None and row.my_role_type is not role_type:
                    continue
                if card_status is not None and row.card_status is not card_status:
                    continue
                item = await self._item(uow, row, viewer)
                if q and not _matches(item, q):
                    continue
                items.append(item)
            await uow.commit()
        return items

    async def _item(
        self, uow: UnitOfWork, row: StoredIncidentRow, viewer: AuthenticatedUser
    ) -> IncidentListItemView:
        session = await uow.sessions.get(row.session_id)
        now_ms = 0 if session is None else running_ms(session, self._clock.now())
        log = await uow.events.read(row.session_id)
        fold = fold_card_status(log)
        values = await self._card_values(uow, row, log)
        leg_status, leg_status_at = await self._service_leg_status(uow, session, row, viewer)
        return IncidentListItemView(
            session_id=row.session_id,
            incident_id=row.incident_id,
            display_number=row.display_number,
            lesson_id=row.lesson_id,
            card_status=row.card_status,
            session_state=row.session_state,
            arrived_at_utc=row.started_at,
            session_offset_ms=now_ms,
            accept_deadline_offset_ms=_accept_deadline(fold),
            fill_deadline_offset_ms=_fill_deadline(fold, log),
            not_completed_deadline_offset_ms=_not_completed_deadline(fold, row.card_status),
            classifier_code=_text(values.get(_CLASSIFIER_CODE_PATH)),
            address_line_ru=_address_line(values),
            my_role_type=row.my_role_type,
            service_leg_status=leg_status,
            service_leg_status_at_offset_ms=leg_status_at,
        )

    async def _service_leg_status(
        self,
        uow: UnitOfWork,
        session: SimulationSession | None,
        row: StoredIncidentRow,
        viewer: AuthenticatedUser,
    ) -> tuple[ServiceResponseStatus | None, int | None]:
        """(I7 E50) The viewer's own leg — the `DDSAssignment` bound to them — of a ДДС row.

        `None` for a 112-register row (`my_role_type` is not `DDS`), for an instructor/admin
        viewer (`my_role_type` is only ever set from the viewer's own participation) and when the
        binding is ambiguous (nobody bound, or — impossibly, but checked — more than one leg
        bound to the same user): guessing a leg here would misattribute a status memo p.40 never
        asked this column to guess.
        """
        if session is None or row.my_role_type is not RoleType.DDS:
            return None, None
        stage = next((s for s in session.stages if s.role_type is RoleType.DDS), None)
        if stage is None:
            return None, None
        legs = await uow.dds_assignments.list_for_stage(stage.role_stage_id)
        mine = [leg for leg in legs if leg.bound_user_id == viewer.user_id]
        if len(mine) != 1:
            return None, None
        leg = mine[0]
        return leg.response_status, leg.response_status_at_offset_ms

    async def _card_values(
        self, uow: UnitOfWork, row: StoredIncidentRow, log: Sequence[SessionEvent]
    ) -> Mapping[str, FactValue]:
        """The snapshot's values for a ДДС row, the live card's for any other (D3)."""
        if row.my_role_type is RoleType.DDS:
            snapshot_id = next(
                (
                    event.payload.get("snapshot_id")
                    for event in log
                    if event.event_type is EventType.HANDOFF_RECEIVED
                ),
                None,
            )
            if snapshot_id is None:
                return {}
            snapshot = await uow.handoffs.get(SnapshotId(UUID(str(snapshot_id))))
            return {} if snapshot is None else snapshot.card_values
        card = await uow.operator_cards.get(row.incident_id)
        return {} if card is None else card.values


def _accept_deadline(fold: CardStatusFold) -> int | None:
    pending = [
        leg.accept_deadline_ms(fold.timers) for leg in fold.legs if leg.decided_at_offset_ms is None
    ]
    return min(pending) if pending else None


def _fill_deadline(fold: CardStatusFold, log: Sequence[SessionEvent]) -> int | None:
    if fold.handoff_offset_ms is not None:
        return None
    answered = next(
        (event.monotonic_offset_ms for event in log if event.event_type is EventType.CALL_ANSWERED),
        None,
    )
    return None if answered is None else answered + fold.timers.fill_within_ms


def _not_completed_deadline(fold: CardStatusFold, status: CardStatus) -> int | None:
    if fold.handoff_offset_ms is None or status is CardStatus.COMPLETED:
        return None
    return fold.handoff_offset_ms + fold.timers.not_completed_after_ms


def _text(value: FactValue | None) -> str | None:
    return None if value is None else str(value)


def _address_line(values: Mapping[str, FactValue]) -> str | None:
    parts = [
        template.format(values[path])
        for path, template in _ADDRESS_PARTS
        if values.get(path) not in (None, "")
    ]
    return ", ".join(parts) if parts else None


def _matches(item: IncidentListItemView, q: str) -> bool:
    needle = q.strip().casefold()
    haystack = [str(item.display_number), item.address_line_ru or "", item.classifier_code or ""]
    return any(needle in text.casefold() for text in haystack)

"""Card status — a derived projection of the 112 card's life (HLD `70-i3-alignment.md` §70.3.4,
§70.3.5, §70.4.6, D15, D16; I3 E4a).

Three things live here, all pure:

* **`card_status(legs, handoff_offset_ms, timers, now_offset_ms, report_released)`** — the §70.4.6
  table, evaluated in its precedence order, first match wins (assumption A-5):
  `COMPLETED > REFUSED > NOT_COMPLETED > NOT_NOTIFIED > CHECKED > WORKED > REGISTERED`.
  `NOT_NOTIFIED` is sticky: a leg that missed its accept deadline stays missed, whatever happens
  to it afterwards.
* **the legs' statuses (leg-aware since I3 E5a).** Under `dds_mode: MEMO_STATUSES` (read off
  `SESSION_CREATED.variants`) a leg's status is its own `ServiceResponseStatus`, folded from the
  `DDS_SERVICE_STATUS_SET` events of that leg, and its primary decision is the first
  `ACCEPTED`/`NOT_ACCEPTED` it reached — the stage's `DDS_ACKNOWLEDGED` decides nothing. Under
  `RESOURCE_PICKER` (and in every log written before E1) the leg status *is* §70.4.4's picker map
  of the DDS stage, so the fold applies that map at the stage event itself; the `PICKER_MIRROR`
  `DDS_SERVICE_STATUS_SET`s stage automation records afterwards carry the same values and are not
  re-read, which keeps the picker projection exactly E4a's (`ACCEPTED ≡ DDS_ACKNOWLEDGED` is the
  picker map's own `ACKNOWLEDGED → ACCEPTED`). Statuses are the memo's vocabulary as strings
  (`"RECEIVED"`, `"ACCEPTED"`, …), which keeps this module free of `dds/response.py`'s enum.
* **the flush-before-append planner** (§70.3.5). `CardStatusFold` is the projection's state,
  folded from a session's log; `plan_append` takes a batch of events a Unit of Work is about to
  append and returns the batch with every due `DDS_CARD_STATUS_CHANGED` merged in:

  - before each event, every deadline `d` with `horizon < d ≤ bound` whose passing changes the
    status is appended first, stamped with `d` itself (envelope `monotonic_offset_ms` and
    payload `deadline_offset_ms`), so a deadline event always precedes any later-stamped event in
    `seq_no` order and the stream does not depend on how often anybody looked (INV 7);
  - after the batch, a status the batch's own events changed (the handoff, the closure) is
    appended once, stamped with the batch's bound;
  - nothing is appended into a log that is closed (`SESSION_COMPLETED` / `SESSION_ABORTED`) or
    not started yet.

  `bound` is `min(event offset, running_now_ms)`: an event's own offset is "its own `now_ms`",
  and the running clock caps it because the world tick stamps its events in *simulated* ms
  (`time_scale`), while the timers are running ms and must not pass early in a scaled session.

  `horizon` is the highest offset among the events the fold has seen (the relevant ones — the
  caller reads only `RELEVANT_EVENT_TYPES`). A deadline at or below it was already decided when
  the event at the horizon was appended; re-deciding it against a later fold could invent a
  change that never happened.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.actors import ActorRef
from app.domain.enums import ActorType, ClosureReason, DDSStageState, RoleType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = [
    "CARD_STATUS_LABELS_RU",
    "DEFAULT_CARD_TIMERS",
    "PICKER_MIRROR",
    "RED_CARD_STATUSES",
    "RELEVANT_EVENT_TYPES",
    "CardLeg",
    "CardStatus",
    "CardStatusFold",
    "CardStatusReason",
    "CardTimers",
    "card_status",
    "fold_card_status",
    "mirror_leg_status",
    "plan_append",
    "reason_for",
]


class CardStatus(str, Enum):
    """The memo's seven card statuses (p.27, REQ-5305–5311), §70.4.6."""

    REGISTERED = "REGISTERED"
    WORKED = "WORKED"
    CHECKED = "CHECKED"
    NOT_NOTIFIED = "NOT_NOTIFIED"
    REFUSED = "REFUSED"
    NOT_COMPLETED = "NOT_COMPLETED"
    COMPLETED = "COMPLETED"


CARD_STATUS_LABELS_RU: Mapping[CardStatus, str] = {
    CardStatus.REGISTERED: "Зарегистрирована",
    CardStatus.WORKED: "Отработана",
    CardStatus.CHECKED: "Проверена",
    CardStatus.NOT_NOTIFIED: "Не оповещено",
    CardStatus.REFUSED: "Отказ",
    CardStatus.NOT_COMPLETED: "Не завершено",
    CardStatus.COMPLETED: "Завершена",
}
"""The memo's labels, verbatim (§70.4.6)."""

RED_CARD_STATUSES: frozenset[CardStatus] = frozenset(
    {CardStatus.NOT_NOTIFIED, CardStatus.REFUSED, CardStatus.NOT_COMPLETED}
)
"""Rendered red in the lists (REQ-5312)."""


class CardStatusReason(str, Enum):
    """Which §70.4.6 rule caused a `DDS_CARD_STATUS_CHANGED`."""

    HANDOFF_CREATED = "HANDOFF_CREATED"
    ACCEPT_DEADLINE_MISSED = "ACCEPT_DEADLINE_MISSED"
    LEG_DECLINED_OR_REFUSED = "LEG_DECLINED_OR_REFUSED"
    NOT_COMPLETED_DEADLINE = "NOT_COMPLETED_DEADLINE"
    ALL_LEGS_COMPLETED = "ALL_LEGS_COMPLETED"
    LEG_STATUS_CORRECTED = "LEG_STATUS_CORRECTED"


class CardTimers(BaseModel):
    """The schema-2 scenario key `timers` (§70.3.4) — all in session (running) milliseconds.

    Every key defaults when absent; rule R39 (`positive`, `accept < not_completed`) is enforced by
    the field bounds and by `validate_scenario_version`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    accept_within_ms: int = Field(default=30_000, gt=0)
    """Принята / Не принята within 30 s of the leg's `HANDOFF_RECEIVED` (REQ-5254, REQ-5283)."""
    fill_within_ms: int = Field(default=180_000, gt=0)
    """3 minutes to fill the card, from `CALL_ANSWERED` (REQ-6020, REQ-3010)."""
    not_completed_after_ms: int = Field(default=172_800_000, gt=0)
    """48 h → «Не завершено» from `HANDOFF_CREATED` (REQ-5310); authors scale it for a lesson."""


DEFAULT_CARD_TIMERS = CardTimers()

# -- legs --------------------------------------------------------------------------------------

_COMPLETED = "COMPLETED"
_REFUSALS = frozenset({"NOT_ACCEPTED", "REFUSED"})
_PRIMARY_DECISIONS = frozenset({"ACCEPTED", "NOT_ACCEPTED"})
_ADDED = "ADDED"
_MEMO = "MEMO_STATUSES"

PICKER_MIRROR: Mapping[DDSStageState, str] = {
    DDSStageState.RECEIVED: "RECEIVED",
    DDSStageState.ACKNOWLEDGED: "ACCEPTED",
    DDSStageState.RESOURCE_SELECTION: "ACCEPTED",
    DDSStageState.DISPATCHED: "ACCEPTED",
    DDSStageState.EN_ROUTE: "RESPONSE_STARTED",
    DDSStageState.ARRIVED: "ARRIVED",
    DDSStageState.WORKING: "WORKING",
    DDSStageState.RESOLVED: "COMPLETED",
}
"""§70.4.4's picker map: the DDS stage state → the leg's memo status. `CLOSED` is not a key —
see `mirror_leg_status`."""


def mirror_leg_status(
    state: DDSStageState, closure_reason: ClosureReason | None, previous: str
) -> str:
    """A leg's mirrored status: `PICKER_MIRROR`, and for `CLOSED` `COMPLETED` when the closure
    reason is `RESOLVED` — every other closure (and an abort) leaves the last mirrored status."""
    if state is DDSStageState.CLOSED:
        return _COMPLETED if closure_reason is ClosureReason.RESOLVED else previous
    return PICKER_MIRROR.get(state, previous)


class CardLeg(BaseModel):
    """One notified service as the card status sees it (a `DDSAssignment` leg, §70.4.3)."""

    model_config = ConfigDict(frozen=True)

    assignment_id: str
    service_type: str
    received_at_offset_ms: int
    status: str = "RECEIVED"
    """The memo status: the leg's own (memo mode) or the picker map of the stage (picker mode)."""
    decided_at_offset_ms: int | None = None
    """When the primary decision (`ACCEPTED`/`NOT_ACCEPTED`) was taken: the leg's own first one
    (memo mode) or the stage's `DDS_ACKNOWLEDGED` (picker mode)."""

    def accept_deadline_ms(self, timers: CardTimers) -> int:
        """`received + accept_within_ms` (A-10: counted from the leg's `HANDOFF_RECEIVED`)."""
        return self.received_at_offset_ms + timers.accept_within_ms

    def accept_missed(self, timers: CardTimers, now_offset_ms: int) -> bool:
        """The leg had no primary decision when its deadline passed — sticky once true.

        A deadline `d` has passed at `now ≥ d` (the flush rule appends a deadline event before an
        event stamped `d`), so a decision is in time only when it was taken strictly before `d`.
        """
        deadline = self.accept_deadline_ms(timers)
        if now_offset_ms < deadline:
            return False
        return self.decided_at_offset_ms is None or self.decided_at_offset_ms >= deadline


def card_status(
    legs: Sequence[CardLeg],
    handoff_offset_ms: int | None,
    timers: CardTimers,
    now_offset_ms: int,
    report_released: bool,
    *,
    notification_list_empty: bool | None = None,
) -> CardStatus:
    """The §70.4.6 table in its precedence order (A-5); the first matching rule wins.

    `notification_list_empty` is whether the handoff named no service at all; `None` means the
    legs *are* the notification list. The two differ for a chain without a DDS stage, whose
    handoff names services but creates no leg: its card is handed off (`WORKED`), never
    `COMPLETED` by an empty leg list.
    """
    handed_off = handoff_offset_ms is not None
    empty = not legs if notification_list_empty is None else notification_list_empty
    if handed_off and (empty or (legs and all(leg.status == _COMPLETED for leg in legs))):
        # "every leg is COMPLETED, or the notification list is empty" — both need a handoff.
        return CardStatus.COMPLETED
    if any(leg.status in _REFUSALS for leg in legs):
        return CardStatus.REFUSED
    if (
        handoff_offset_ms is not None
        and now_offset_ms >= handoff_offset_ms + timers.not_completed_after_ms
        and any(leg.status != _COMPLETED for leg in legs)
    ):
        return CardStatus.NOT_COMPLETED
    if any(leg.accept_missed(timers, now_offset_ms) for leg in legs):
        return CardStatus.NOT_NOTIFIED
    if report_released:
        return CardStatus.CHECKED
    if handed_off:
        return CardStatus.WORKED
    return CardStatus.REGISTERED


def reason_for(previous: CardStatus, new: CardStatus) -> CardStatusReason:
    """The `CardStatusReason` of a change `previous → new` that no deadline caused."""
    if new is CardStatus.COMPLETED:
        return CardStatusReason.ALL_LEGS_COMPLETED
    if new is CardStatus.REFUSED:
        return CardStatusReason.LEG_DECLINED_OR_REFUSED
    if previous is CardStatus.REFUSED:
        return CardStatusReason.LEG_STATUS_CORRECTED
    if new is CardStatus.NOT_COMPLETED:
        return CardStatusReason.NOT_COMPLETED_DEADLINE
    if new is CardStatus.NOT_NOTIFIED:
        return CardStatusReason.ACCEPT_DEADLINE_MISSED
    return CardStatusReason.HANDOFF_CREATED


# -- the fold ----------------------------------------------------------------------------------

RELEVANT_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.SESSION_CREATED,
        EventType.SESSION_STARTED,
        EventType.HANDOFF_CREATED,
        EventType.HANDOFF_RECEIVED,
        EventType.DDS_ACKNOWLEDGED,
        EventType.STAGE_STATE_CHANGED,
        EventType.DDS_INCIDENT_CLOSED,
        EventType.DDS_CARD_STATUS_CHANGED,
        EventType.SESSION_COMPLETED,
        EventType.SESSION_ABORTED,
        EventType.DDS_SERVICE_STATUS_SET,
    }
)
"""The event types the projection reads; a reader may pass the whole log, others are ignored."""

_CLOSING = frozenset({EventType.SESSION_COMPLETED, EventType.SESSION_ABORTED})
_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)


@dataclass(frozen=True)
class CardStatusFold:
    """The projection's state after a prefix of one session's log."""

    timers: CardTimers = DEFAULT_CARD_TIMERS
    started: bool = False
    closed: bool = False
    handoff_offset_ms: int | None = None
    legs: tuple[CardLeg, ...] = ()
    dds_state: DDSStageState | None = None
    closure_reason: ClosureReason | None = None
    status: CardStatus = CardStatus.REGISTERED
    horizon_ms: int | None = None
    """The highest offset among the relevant events seen; `None` before the first one."""
    notified_services: tuple[str, ...] | None = None
    """`HANDOFF_CREATED.recipient_services`; `None` when the legs are the list (a prefab)."""
    memo: bool = False
    """`SESSION_CREATED.variants.dds_mode` is `MEMO_STATUSES` (I3 E5a): the legs move by their own
    `DDS_SERVICE_STATUS_SET`s, not by the stage."""

    def status_at(self, now_offset_ms: int, *, report_released: bool = False) -> CardStatus:
        """`card_status` over this fold at `now_offset_ms`."""
        return card_status(
            self.legs,
            self.handoff_offset_ms,
            self.timers,
            now_offset_ms,
            report_released,
            notification_list_empty=(
                None if self.notified_services is None else not self.notified_services
            ),
        )

    def apply(
        self, event_type: EventType, payload: Mapping[str, Any], offset_ms: int
    ) -> CardStatusFold:
        """The fold after one more event; irrelevant types change nothing."""
        if event_type not in RELEVANT_EVENT_TYPES:
            return self
        horizon = offset_ms if self.horizon_ms is None else max(self.horizon_ms, offset_ms)
        moved = replace(self, horizon_ms=horizon)
        if event_type is EventType.SESSION_CREATED:
            raw = payload.get("timers")
            timers = CardTimers.model_validate(raw) if isinstance(raw, Mapping) else self.timers
            variants = payload.get("variants")
            memo = isinstance(variants, Mapping) and variants.get("dds_mode") == _MEMO
            return replace(moved, timers=timers, memo=memo)
        if event_type is EventType.SESSION_STARTED:
            return replace(moved, started=True)
        if event_type in _CLOSING:
            return replace(moved, closed=True)
        if event_type is EventType.HANDOFF_CREATED:
            if self.handoff_offset_ms is not None:
                return moved
            services = payload.get("recipient_services")
            return replace(
                moved,
                handoff_offset_ms=offset_ms,
                notified_services=(
                    tuple(str(service) for service in services)
                    if isinstance(services, list | tuple)
                    else None
                ),
            )
        if event_type is EventType.HANDOFF_RECEIVED:
            return self._received(moved, payload, offset_ms)
        if event_type is EventType.DDS_SERVICE_STATUS_SET:
            return self._status_set(moved, payload, offset_ms)
        if event_type is EventType.DDS_ACKNOWLEDGED:
            if self.memo:
                return moved
            legs = tuple(
                leg
                if leg.decided_at_offset_ms is not None
                else leg.model_copy(update={"decided_at_offset_ms": offset_ms})
                for leg in self.legs
            )
            return replace(moved, legs=legs)
        if event_type is EventType.DDS_INCIDENT_CLOSED:
            reason = payload.get("closure_reason")
            try:
                closure = None if reason is None else ClosureReason(str(reason))
            except ValueError:
                closure = None
            return replace(moved, closure_reason=closure)
        if event_type is EventType.STAGE_STATE_CHANGED:
            if payload.get("role_type") != RoleType.DDS.value:
                return moved
            try:
                state = DDSStageState(str(payload.get("new_state")))
            except ValueError:
                return moved
            if self.memo:
                return replace(moved, dds_state=state)
            legs = tuple(
                leg.model_copy(
                    update={"status": mirror_leg_status(state, self.closure_reason, leg.status)}
                )
                for leg in self.legs
            )
            return replace(moved, dds_state=state, legs=legs)
        # DDS_CARD_STATUS_CHANGED
        try:
            return replace(moved, status=CardStatus(str(payload.get("new_status"))))
        except ValueError:
            return moved

    @staticmethod
    def _status_set(
        moved: CardStatusFold, payload: Mapping[str, Any], offset_ms: int
    ) -> CardStatusFold:
        """A memo leg's `DDS_SERVICE_STATUS_SET`: its new status and its first primary decision.
        Ignored in picker mode, where the stage event already applied the same mirrored value."""
        if not moved.memo:
            return moved
        assignment_id = str(payload.get("assignment_id"))
        new_status = str(payload.get("new_status"))
        legs = tuple(
            leg
            if leg.assignment_id != assignment_id
            else leg.model_copy(
                update={
                    "status": new_status,
                    "decided_at_offset_ms": (
                        offset_ms
                        if leg.decided_at_offset_ms is None and new_status in _PRIMARY_DECISIONS
                        else leg.decided_at_offset_ms
                    ),
                }
            )
            for leg in moved.legs
        )
        return replace(moved, legs=legs)

    @staticmethod
    def _received(
        moved: CardStatusFold, payload: Mapping[str, Any], offset_ms: int
    ) -> CardStatusFold:
        raw_id = payload.get("assignment_id")
        if raw_id is None:
            return moved
        assignment_id = str(raw_id)
        if any(leg.assignment_id == assignment_id for leg in moved.legs):
            return moved
        state = moved.dds_state or DDSStageState.RECEIVED
        leg = CardLeg(
            assignment_id=assignment_id,
            service_type=str(payload.get("service_type", "")),
            received_at_offset_ms=offset_ms,
            status=(
                str(payload.get("initial_response_status") or _ADDED)
                if moved.memo
                else mirror_leg_status(state, moved.closure_reason, "RECEIVED")
            ),
        )
        handoff = moved.handoff_offset_ms
        # A prefab handoff (GENERATED_CARD) has no `HANDOFF_CREATED`: the card is handed off
        # when it is received.
        return replace(
            moved,
            legs=(*moved.legs, leg),
            handoff_offset_ms=offset_ms if handoff is None else handoff,
        )


def fold_card_status(events: Iterable[Any]) -> CardStatusFold:
    """Fold a log (`SessionEvent`s, or anything with `event_type`, `payload` and
    `monotonic_offset_ms`) into a `CardStatusFold`."""
    fold = CardStatusFold()
    for event in events:
        fold = fold.apply(event.event_type, event.payload, event.monotonic_offset_ms)
    return fold


# -- the planner -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Deadline:
    offset_ms: int
    reason: CardStatusReason
    leg: CardLeg | None


def _deadlines(fold: CardStatusFold, after_ms: int | None, bound_ms: int) -> list[_Deadline]:
    """Every deadline in `(after_ms, bound_ms]`, in offset order (accept deadlines first)."""
    found: list[_Deadline] = []
    for leg in fold.legs:
        found.append(
            _Deadline(
                leg.accept_deadline_ms(fold.timers), CardStatusReason.ACCEPT_DEADLINE_MISSED, leg
            )
        )
    if fold.handoff_offset_ms is not None:
        found.append(
            _Deadline(
                fold.handoff_offset_ms + fold.timers.not_completed_after_ms,
                CardStatusReason.NOT_COMPLETED_DEADLINE,
                None,
            )
        )
    due = [
        deadline
        for deadline in found
        if deadline.offset_ms <= bound_ms and (after_ms is None or deadline.offset_ms > after_ms)
    ]
    return sorted(due, key=lambda deadline: deadline.offset_ms)


@dataclass
class _Planner:
    fold: CardStatusFold
    incident_id: UUID
    out: list[DomainEvent] = field(default_factory=list)

    def emit(
        self,
        new: CardStatus,
        *,
        at_ms: int,
        reason: CardStatusReason,
        leg: CardLeg | None = None,
        deadline_ms: int | None = None,
    ) -> None:
        payload = {
            "incident_id": str(self.incident_id),
            "previous_status": self.fold.status.value,
            "new_status": new.value,
            "reason": reason.value,
            "assignment_id": None if leg is None else leg.assignment_id,
            "service_type": None if leg is None else leg.service_type,
            "deadline_offset_ms": deadline_ms,
            "at_offset_ms": at_ms,
        }
        self.out.append(
            DomainEvent(
                event_type=EventType.DDS_CARD_STATUS_CHANGED,
                actor=_SIMULATION,
                monotonic_offset_ms=at_ms,
                payload=payload,
            )
        )
        self.fold = self.fold.apply(EventType.DDS_CARD_STATUS_CHANGED, payload, at_ms)

    def settle(self, at_ms: int | None) -> None:
        """Append the change this fold's own events caused, if any."""
        if at_ms is None or not self.fold.started or self.fold.closed:
            return
        new = self.fold.status_at(at_ms)
        if new is not self.fold.status:
            self.emit(new, at_ms=at_ms, reason=reason_for(self.fold.status, new))

    def flush(self, bound_ms: int) -> None:
        """Append every due deadline whose passing changes the status, stamped with it."""
        if not self.fold.started or self.fold.closed:
            return
        for deadline in _deadlines(self.fold, self.fold.horizon_ms, bound_ms):
            new = self.fold.status_at(deadline.offset_ms)
            if new is self.fold.status:
                continue
            leg = deadline.leg
            if deadline.reason is CardStatusReason.ACCEPT_DEADLINE_MISSED:
                # Several legs received together share one deadline: the first missed leg
                # carries the event.
                leg = next(
                    (
                        candidate
                        for candidate in self.fold.legs
                        if candidate.accept_deadline_ms(self.fold.timers) == deadline.offset_ms
                        and candidate.accept_missed(self.fold.timers, deadline.offset_ms)
                    ),
                    leg,
                )
            self.emit(
                new,
                at_ms=deadline.offset_ms,
                reason=deadline.reason,
                leg=leg,
                deadline_ms=deadline.offset_ms,
            )


def plan_append(
    fold: CardStatusFold,
    batch: Sequence[DomainEvent],
    *,
    incident_id: UUID,
    running_now_ms: int,
) -> tuple[list[DomainEvent], CardStatusFold]:
    """The batch with its `DDS_CARD_STATUS_CHANGED` events merged in, and the fold after it.

    An empty `batch` is a pure flush up to `running_now_ms` — what stage automation asks for on
    every tick. See the module docstring for the rule.
    """
    planner = _Planner(fold=fold, incident_id=incident_id)
    if not batch:
        planner.flush(running_now_ms)
        return planner.out, planner.fold

    previous_bound: int | None = fold.horizon_ms
    for event in batch:
        if planner.fold.closed:
            planner.out.append(event)
            continue
        bound = min(event.monotonic_offset_ms, running_now_ms)
        if _deadlines(planner.fold, planner.fold.horizon_ms, bound):
            planner.settle(previous_bound)
            planner.flush(bound)
        if event.event_type in _CLOSING:
            planner.settle(bound)
        planner.out.append(event)
        planner.fold = planner.fold.apply(
            event.event_type, event.payload, event.monotonic_offset_ms
        )
        previous_bound = bound
    planner.settle(previous_bound)
    return planner.out, planner.fold

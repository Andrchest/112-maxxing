"""A card's times against the norms the system holds (I4 E33, HLD 71 §71.10; ТЗ ¶329
REQ-2274/2275: «времени заполнения карточки, отличия времени от нормативного (заданного в
системе)»).

Pure: a fold over one session's log, no I/O, no clock, no score. Two intervals are measured:

* `ACCEPT`, per leg: the leg's `HANDOFF_RECEIVED` → its first primary decision (`ACCEPTED` /
  `NOT_ACCEPTED`), against `accept_within_ms`;
* `FILL`, the 112 card: the first `CALL_ANSWERED` → the first `HANDOFF_CREATED`, against
  `fill_within_ms`.

The first decision is `CardStatusFold`'s, the same one the card status and the list countdowns
use (`app.domain.dds.card_status`): the leg's own first `ACCEPTED`/`NOT_ACCEPTED` under
`MEMO_STATUSES`, the stage's `DDS_ACKNOWLEDGED` under the picker. So a report never disagrees with
the «Не оповещено» the trainee saw.

**The norm is the session's recorded timer, never a literal** (I4 E31, D34). It is read from
`SESSION_CREATED.timers` — the scenario's `timers` with the instructor's override applied
(`app.domain.scenario.timers.resolve_card_timers`) — exactly as the `DEADLINE` evaluator reads it
(`app.domain.scoring.evaluators.deadline`). A log that records no timers ran with the scenario's
own ones, which the caller passes in (`ScenarioVersion.card_timers`).

`FILL` is listed only for a session whose effective chain has the 112 desk
(`SESSION_CREATED.role_chain`): a ДДС-only card (`GENERATED_CARD`) never answers a 112 call, and
the ДДС fill norm is not defined (Q-E9b-2). An interval that never closed is listed with
`measured_ms` and `deviation_ms` `None` — "not measured" is not zero. `deviation_ms` is
`measured − norm`: positive is late.

"Which of the two is the «время реакции»" is not decided (Q-E12-1): neither is labelled so.

The two counters beside the norms — failed rules and critical errors — are counted over the
**stored** results, the same rows the report shows (D11: nothing is re-scored here).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from app.domain.dds.card_status import CardTimers, fold_card_status
from app.domain.enums import RoleType
from app.domain.events.types import EventType

__all__ = [
    "NORM_EVENT_TYPES",
    "CardNorm",
    "NormKind",
    "card_norms",
    "critical_error_count",
    "failed_rule_count",
    "recorded_timers",
]


class NormKind(str, Enum):
    """`NormView.kind`."""

    ACCEPT = "ACCEPT"
    FILL = "FILL"


NORM_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.SESSION_CREATED,
        EventType.CALL_ANSWERED,
        EventType.HANDOFF_CREATED,
        EventType.HANDOFF_RECEIVED,
        EventType.DDS_ACKNOWLEDGED,
        EventType.DDS_SERVICE_STATUS_SET,
    }
)
"""Every event type `card_norms` reads; a reader may pass the whole log, others are ignored."""


@dataclass(frozen=True, slots=True)
class CardNorm:
    """One measured interval against its norm (`NormView`), plus who played the leg.

    `leg_responder` / `leg_bound_user_id` are `HANDOFF_RECEIVED.responder` / `.bound_user_id` of an
    `ACCEPT` leg (both `None` for `FILL` and for a pre-E5 log): the statistics attribute a leg's
    time to the trainee who played it, never to a scripted responder.
    """

    kind: NormKind
    service_id: str | None
    measured_ms: int | None
    norm_ms: int
    deviation_ms: int | None
    leg_responder: str | None = None
    leg_bound_user_id: str | None = None


class _Event(Protocol):
    @property
    def event_type(self) -> EventType: ...

    @property
    def payload(self) -> Mapping[str, Any]: ...

    @property
    def monotonic_offset_ms(self) -> int: ...


class _Result(Protocol):
    @property
    def passed(self) -> bool: ...

    @property
    def critical_failure(self) -> bool: ...


def recorded_timers(events: Iterable[_Event], scenario_timers: CardTimers) -> CardTimers:
    """`SESSION_CREATED.timers`, or `scenario_timers` for a log that records none (I4 E31)."""
    for event in events:
        if event.event_type is EventType.SESSION_CREATED:
            raw = event.payload.get("timers")
            if isinstance(raw, Mapping):
                return CardTimers.model_validate(raw)
            break
    return scenario_timers


def card_norms(events: Iterable[_Event], scenario_timers: CardTimers) -> tuple[CardNorm, ...]:
    """The card's `FILL` (when it has a 112 desk) and one `ACCEPT` per leg, in log order."""
    log = [event for event in events if event.event_type in NORM_EVENT_TYPES]
    timers = recorded_timers(log, scenario_timers)
    norms: list[CardNorm] = []
    if _has_112_desk(log):
        norms.append(_norm(NormKind.FILL, None, _fill_ms(log), timers.fill_within_ms))
    players = _leg_players(log)
    for leg in fold_card_status(log).legs:
        measured = (
            None
            if leg.decided_at_offset_ms is None
            else leg.decided_at_offset_ms - leg.received_at_offset_ms
        )
        responder, bound = players.get(leg.assignment_id, (None, None))
        norms.append(
            _norm(
                NormKind.ACCEPT,
                leg.service_type or None,
                measured,
                timers.accept_within_ms,
                responder=responder,
                bound_user_id=bound,
            )
        )
    return tuple(norms)


def failed_rule_count(results: Iterable[_Result]) -> int:
    """The stored results that did not pass."""
    return sum(1 for result in results if not result.passed)


def critical_error_count(results: Iterable[_Result]) -> int:
    """The stored results that are a critical failure (`ScoreReport.critical_errors`)."""
    return sum(1 for result in results if result.critical_failure)


def _norm(
    kind: NormKind,
    service_id: str | None,
    measured_ms: int | None,
    norm_ms: int,
    *,
    responder: str | None = None,
    bound_user_id: str | None = None,
) -> CardNorm:
    return CardNorm(
        kind=kind,
        service_id=service_id,
        measured_ms=measured_ms,
        norm_ms=norm_ms,
        deviation_ms=None if measured_ms is None else measured_ms - norm_ms,
        leg_responder=responder,
        leg_bound_user_id=bound_user_id,
    )


def _has_112_desk(log: list[_Event]) -> bool:
    """The effective chain has `OPERATOR_112`; a log without `role_chain` has a 112 call."""
    for event in log:
        if event.event_type is EventType.SESSION_CREATED:
            chain = event.payload.get("role_chain")
            if isinstance(chain, list | tuple):
                return RoleType.OPERATOR_112.value in {str(role) for role in chain}
            break
    return any(
        event.event_type in (EventType.CALL_ANSWERED, EventType.HANDOFF_CREATED) for event in log
    )


def _fill_ms(log: list[_Event]) -> int | None:
    """First `CALL_ANSWERED` → the first `HANDOFF_CREATED` after it, or `None`."""
    answered = next(
        (event.monotonic_offset_ms for event in log if event.event_type is EventType.CALL_ANSWERED),
        None,
    )
    if answered is None:
        return None
    handed_off = next(
        (
            event.monotonic_offset_ms
            for event in log
            if event.event_type is EventType.HANDOFF_CREATED
            and event.monotonic_offset_ms >= answered
        ),
        None,
    )
    return None if handed_off is None else handed_off - answered


def _leg_players(log: list[_Event]) -> dict[str, tuple[str | None, str | None]]:
    """`assignment_id` → (`responder`, `bound_user_id`) from each leg's `HANDOFF_RECEIVED`."""
    players: dict[str, tuple[str | None, str | None]] = {}
    for event in log:
        if event.event_type is not EventType.HANDOFF_RECEIVED:
            continue
        assignment_id = event.payload.get("assignment_id")
        if assignment_id is None or str(assignment_id) in players:
            continue
        responder = event.payload.get("responder")
        bound = event.payload.get("bound_user_id")
        players[str(assignment_id)] = (
            None if responder is None else str(responder),
            None if bound is None else str(bound),
        )
    return players

"""A card's times against the system's norms (I4 E33, HLD 71 §71.10; ТЗ ¶329 REQ-2274/2275).

The rule the suite holds above all: **the norm is the session's recorded timer, never a literal**
(I4 E31, D34) — `SESSION_CREATED.timers` when the log records them, the scenario's own `timers`
otherwise. Then: which interval each kind measures, that an interval that never closed is `None`
(not zero), and that a ДДС-only card has no 112 fill norm (Q-E9b-2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.reports.norms import (
    CardNorm,
    NormKind,
    card_norms,
    critical_error_count,
    failed_rule_count,
    recorded_timers,
)
from app.application.statistics.ports import StatisticsEvent
from app.domain.dds.card_status import DEFAULT_CARD_TIMERS, CardTimers
from app.domain.events.types import EventType

RECORDED = {"accept_within_ms": 45_000, "fill_within_ms": 120_000, "not_completed_after_ms": 90_000}
SCENARIO = CardTimers(accept_within_ms=20_000, fill_within_ms=60_000, not_completed_after_ms=50_000)


def _event(event_type: EventType, offset_ms: int, **payload: Any) -> StatisticsEvent:
    return StatisticsEvent(event_type=event_type, payload=payload, monotonic_offset_ms=offset_ms)


def _created(
    chain: list[str], *, timers: dict[str, int] | None = RECORDED, memo: bool = False
) -> StatisticsEvent:
    payload: dict[str, Any] = {"role_chain": chain}
    if timers is not None:
        payload["timers"] = timers
    if memo:
        payload["variants"] = {"dds_mode": "MEMO_STATUSES"}
    return _event(EventType.SESSION_CREATED, 0, **payload)


def _received(offset_ms: int, assignment: str, service: str, **extra: Any) -> StatisticsEvent:
    return _event(
        EventType.HANDOFF_RECEIVED,
        offset_ms,
        assignment_id=assignment,
        service_type=service,
        **extra,
    )


def _status(offset_ms: int, assignment: str, status: str) -> StatisticsEvent:
    return _event(
        EventType.DDS_SERVICE_STATUS_SET, offset_ms, assignment_id=assignment, new_status=status
    )


def test_the_norm_is_the_recorded_timer_not_the_scenario_s_or_a_literal() -> None:
    log = [
        _created(["DDS"]),
        _received(1_000, "a", "FIRE_RESCUE"),
        _event(EventType.DDS_ACKNOWLEDGED, 13_000),
    ]
    [accept] = card_norms(log, SCENARIO)
    assert accept == CardNorm(
        kind=NormKind.ACCEPT,
        service_id="FIRE_RESCUE",
        measured_ms=12_000,
        norm_ms=45_000,
        deviation_ms=-33_000,
    )


def test_a_log_without_recorded_timers_takes_the_scenario_s_own() -> None:
    log = [
        _created(["DDS"], timers=None),
        _received(0, "a", "POLICE"),
        _event(EventType.DDS_ACKNOWLEDGED, 25_000),
    ]
    [accept] = card_norms(log, SCENARIO)
    assert accept.norm_ms == SCENARIO.accept_within_ms != DEFAULT_CARD_TIMERS.accept_within_ms
    assert accept.deviation_ms == 5_000
    assert recorded_timers(log, SCENARIO) is SCENARIO


def test_a_memo_leg_is_decided_by_its_own_first_accepted_or_not_accepted() -> None:
    log = [
        _created(["DDS"], memo=True),
        _received(2_000, "a", "FIRE_RESCUE", responder="TRAINEE", bound_user_id="u-1"),
        _received(2_000, "b", "AMBULANCE", responder="SCRIPTED"),
        _received(3_000, "c", "POLICE"),
        _status(4_000, "a", "RECEIVED"),
        _status(9_000, "a", "ACCEPTED"),
        _status(20_000, "a", "NOT_ACCEPTED"),
        _status(50_000, "b", "NOT_ACCEPTED"),
        _event(EventType.DDS_ACKNOWLEDGED, 5_000),  # decides nothing under MEMO_STATUSES
    ]
    first, second, third = card_norms(log, SCENARIO)
    assert (first.measured_ms, first.deviation_ms) == (7_000, -38_000)
    assert (first.leg_responder, first.leg_bound_user_id) == ("TRAINEE", "u-1")
    assert (second.measured_ms, second.deviation_ms) == (48_000, 3_000)
    assert second.leg_responder == "SCRIPTED"
    assert (third.service_id, third.measured_ms, third.deviation_ms) == ("POLICE", None, None)


def test_the_112_fill_runs_from_the_answer_to_the_handoff() -> None:
    log = [
        _created(["OPERATOR_112", "DDS"]),
        _event(EventType.CALL_ANSWERED, 5_000),
        _event(EventType.HANDOFF_CREATED, 95_000),
        _received(96_000, "a", "FIRE_RESCUE"),
    ]
    fill, accept = card_norms(log, SCENARIO)
    assert fill == CardNorm(
        kind=NormKind.FILL,
        service_id=None,
        measured_ms=90_000,
        norm_ms=120_000,
        deviation_ms=-30_000,
    )
    assert accept.kind is NormKind.ACCEPT and accept.measured_ms is None


def test_a_fill_that_never_closed_is_not_measured_and_a_dds_only_card_has_none() -> None:
    unfinished = card_norms(
        [_created(["OPERATOR_112"]), _event(EventType.CALL_ANSWERED, 1_000)], SCENARIO
    )
    assert unfinished == (
        CardNorm(NormKind.FILL, None, measured_ms=None, norm_ms=120_000, deviation_ms=None),
    )
    assert card_norms([_created(["DDS"])], SCENARIO) == ()


@dataclass(frozen=True)
class _Result:
    passed: bool
    critical_failure: bool


def test_the_counters_count_stored_results() -> None:
    results = [_Result(True, False), _Result(False, False), _Result(False, True)]
    assert failed_rule_count(results) == 2
    assert critical_error_count(results) == 1

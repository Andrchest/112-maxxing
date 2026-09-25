"""`DEADLINE` with `max_offset_timer` (I4 E31, HLD 71 §71.8, D34).

A rule may name its norm as a per-card timer instead of a literal: the evaluator then reads the
timer from the session's recorded `SESSION_CREATED.timers` (the scenario's timers with the
instructor's override applied), or the scenario's own timers for a log that records none.

The ticket scenarios' `memo_main_service_decision_in_time` rules switched from `max_offset_ms:
30000` to `max_offset_timer: accept_within_ms`. The last group of tests proves that, with the
default timers, every one of the 108 ticket scenarios scores **exactly** as it did with the literal:
the same `ScoreReport` (results, evidence and notes included) and the same checksum, for a decision
on time, at the limit, one millisecond late, much later and never.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from app.domain.enums import ActorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.context import build_context
from app.domain.scoring.engine import report_checksum, score
from app.domain.scoring.evaluators.deadline import DeadlineConfig
from app.domain.scoring.evaluators.registry import EVALUATORS, parse_rule_config
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule
from app.infrastructure.scenarios.yaml_loader import discover, load_scenario_version, scenario_slug
from pydantic import ValidationError

from tests.unit.domain.scoring._event_log_builders import INSTRUCTOR_ID, LogBuilder, det_uuid

TICKETS_DIR = Path(__file__).resolve().parents[5] / "scenarios" / "tickets"
MEMO_RULE = "memo_main_service_decision_in_time"
RECEIVED_MS = 5_000
DEFAULT_TIMERS = {
    "accept_within_ms": 30_000,
    "fill_within_ms": 180_000,
    "not_completed_after_ms": 172_800_000,
}

TICKETS: dict[str, ScenarioVersion] = {
    scenario_slug(path): load_scenario_version(path) for path in discover(TICKETS_DIR)
}
SAMPLE = TICKETS["ticket-19-call-1"]


def _memo_rule(version: ScenarioVersion) -> ScoringRule:
    return next(rule for rule in version.scoring_rules if rule.rule_id == MEMO_RULE)


def _main_service(version: ScenarioVersion) -> str:
    match = _memo_rule(version).config["to_payload_match"]
    return str(match["service_type"])


def memo_log(
    version: ScenarioVersion,
    *,
    decision_after_ms: int | None,
    timers: Mapping[str, int] | None = DEFAULT_TIMERS,
) -> tuple[SessionEvent, ...]:
    """A memo ДДС card: received at 5 s, the main service's decision `decision_after_ms` later
    (never, for `None`), closed. `timers` is `SESSION_CREATED.timers` (`None`: not recorded)."""
    created: dict[str, Any] = {
        "session_id": str(det_uuid("timer-session")),
        "scenario_version_id": str(version.id),
        "session_mode": "SINGLE_ROLE",
        "role_chain": ["DDS"],
        "variants": {
            "card_source": "GENERATED_CARD",
            "dds_mode": "MEMO_STATUSES",
            "dds_card_check": "OFF",
            "dds_brigade_call": "ON",
        },
    }
    if timers is not None:
        created["timers"] = dict(timers)
    log = LogBuilder()
    log.add(
        EventType.SESSION_CREATED,
        created,
        actor_type=ActorType.INSTRUCTOR,
        actor_id=INSTRUCTOR_ID,
        offset_ms=0,
    )
    log.add(
        EventType.SESSION_STARTED,
        {"started_at_utc": "2026-01-01T00:00:00Z"},
        actor_type=ActorType.INSTRUCTOR,
        actor_id=INSTRUCTOR_ID,
        offset_ms=0,
    )
    log.add(
        EventType.HANDOFF_RECEIVED,
        {"service_type": _main_service(version), "at_offset_ms": RECEIVED_MS},
        actor_type=ActorType.SIMULATION,
        offset_ms=RECEIVED_MS,
    )
    end_ms = RECEIVED_MS + 600_000
    if decision_after_ms is not None:
        log.add(
            EventType.DDS_SERVICE_STATUS_SET,
            {"service_type": _main_service(version), "new_status": "ACCEPTED"},
            actor_type=ActorType.TRAINEE,
            offset_ms=RECEIVED_MS + decision_after_ms,
        )
    log.add(
        EventType.SESSION_COMPLETED,
        {"at_offset_ms": end_ms, "final_session_state": "COMPLETED", "total_events": 0},
        actor_type=ActorType.SIMULATION,
        offset_ms=end_ms,
    )
    return log.build()


def run(version: ScenarioVersion, rule: ScoringRule, events: Sequence[SessionEvent]) -> ScoreResult:
    ctx = build_context(version, events)
    return EVALUATORS[rule.evaluator_type](rule, parse_rule_config(rule), ctx)


def with_literal(version: ScenarioVersion, max_offset_ms: int = 30_000) -> ScoringRule:
    """The ticket's memo rule as it was before E31: the literal norm."""
    rule = _memo_rule(version)
    config = {key: value for key, value in rule.config.items() if key != "max_offset_timer"}
    return rule.model_copy(update={"config": {**config, "max_offset_ms": max_offset_ms}})


def version_with_literal(version: ScenarioVersion) -> ScenarioVersion:
    literal = with_literal(version)
    return version.model_copy(
        update={
            "scoring_rules": tuple(
                literal if rule.rule_id == MEMO_RULE else rule for rule in version.scoring_rules
            )
        }
    )


# ---------------------------------------------------------------------------------------------
# The config
# ---------------------------------------------------------------------------------------------


def test_the_ticket_rule_names_the_accept_timer() -> None:
    config = parse_rule_config(_memo_rule(SAMPLE))
    assert isinstance(config, DeadlineConfig)
    assert config.max_offset_timer == "accept_within_ms"
    assert config.max_offset_ms is None


def test_a_config_with_both_norms_or_none_is_refused() -> None:
    base = {
        "from_event_type": "HANDOFF_RECEIVED",
        "to_event_type": "DDS_ACKNOWLEDGED",
        "to_payload_match": None,
        "points": 4,
        "scale": "STEP",
        "linear_zero_ms": None,
    }
    with pytest.raises(ValidationError):
        DeadlineConfig.model_validate(base)
    with pytest.raises(ValidationError):
        DeadlineConfig.model_validate(
            {**base, "max_offset_ms": 30_000, "max_offset_timer": "accept_within_ms"}
        )


# ---------------------------------------------------------------------------------------------
# The norm is read from the log
# ---------------------------------------------------------------------------------------------


def test_an_overridden_timer_is_the_norm() -> None:
    """45 s recorded: a decision after 40 s passes; the literal 30 s would have failed it."""
    rule = _memo_rule(SAMPLE)
    overridden = {**DEFAULT_TIMERS, "accept_within_ms": 45_000}
    events = memo_log(SAMPLE, decision_after_ms=40_000, timers=overridden)

    result = run(SAMPLE, rule, events)

    assert result.passed and result.points_awarded == 4.0
    assert "при норме 45000 мс" in result.evidence[-1].note_ru
    assert not run(SAMPLE, with_literal(SAMPLE), events).passed


def test_a_shortened_timer_fails_a_decision_the_default_allows() -> None:
    rule = _memo_rule(SAMPLE)
    shortened = {**DEFAULT_TIMERS, "accept_within_ms": 10_000}
    events = memo_log(SAMPLE, decision_after_ms=20_000, timers=shortened)

    result = run(SAMPLE, rule, events)

    assert not result.passed and result.points_awarded == -2.0
    assert "при норме 10000 мс" in result.evidence[-1].note_ru


@pytest.mark.parametrize(("after_ms", "passed"), [(30_000, True), (30_001, False)])
def test_the_recorded_limit_itself_still_passes(after_ms: int, passed: bool) -> None:
    events = memo_log(SAMPLE, decision_after_ms=after_ms)
    assert run(SAMPLE, _memo_rule(SAMPLE), events).passed is passed


def test_a_log_without_recorded_timers_takes_the_scenario_timers() -> None:
    """A log that records no `timers` reads the scenario's own (`ScenarioVersion.card_timers`)."""
    assert SAMPLE.card_timers.accept_within_ms == 30_000
    rule = _memo_rule(SAMPLE)
    on_time = memo_log(SAMPLE, decision_after_ms=30_000, timers=None)
    late = memo_log(SAMPLE, decision_after_ms=30_001, timers=None)

    assert run(SAMPLE, rule, on_time).passed
    assert not run(SAMPLE, rule, late).passed

    scaled = SAMPLE.model_copy(
        update={"timers": SAMPLE.card_timers.model_copy(update={"accept_within_ms": 60_000})}
    )
    assert run(scaled, rule, late).passed


def test_the_fill_timer_is_read_the_same_way() -> None:
    rule = _memo_rule(SAMPLE)
    config = {**rule.config, "max_offset_timer": "fill_within_ms"}
    fill_rule = rule.model_copy(update={"config": config})
    events = memo_log(
        SAMPLE, decision_after_ms=100_000, timers={**DEFAULT_TIMERS, "fill_within_ms": 120_000}
    )
    assert run(SAMPLE, fill_rule, events).passed


# ---------------------------------------------------------------------------------------------
# Every ticket scores as it did with the literal (default timers)
# ---------------------------------------------------------------------------------------------

DECISIONS: tuple[int | None, ...] = (0, 29_999, 30_000, 30_001, 120_000, None)


@pytest.mark.parametrize("slug", sorted(TICKETS))
def test_every_ticket_scores_as_before_with_the_default_timers(slug: str) -> None:
    """The E31 switch changes no score of a ticket session run with the default timers: the
    whole report equals the report of the pre-E31 literal rule, whether the log records the
    timers (every session since I3 E4a) or not."""
    version = TICKETS[slug]
    before = version_with_literal(version)
    assert parse_rule_config(_memo_rule(version)).max_offset_timer == "accept_within_ms"  # type: ignore[attr-defined]
    for timers in (DEFAULT_TIMERS, None):
        for after_ms in DECISIONS:
            events = memo_log(version, decision_after_ms=after_ms, timers=timers)
            now, then = score(version, events), score(before, events)
            assert now == then, (slug, timers, after_ms)
            assert report_checksum(now) == report_checksum(then)
            # Not vacuous: the rule applies to this log and its verdict follows the decision.
            memo = next(result for result in now.results if result.rule_id == MEMO_RULE)
            assert memo.max_points == 4.0
            assert memo.passed is (after_ms is not None and after_ms <= 30_000)

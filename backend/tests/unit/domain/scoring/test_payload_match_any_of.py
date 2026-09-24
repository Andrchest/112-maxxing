"""`payload_match` list values mean "any of" (I3 E5b, manager decision 2; HLD 70 §70.4.4).

HLD 70's example memo rule — `DEADLINE HANDOFF_RECEIVED → DDS_SERVICE_STATUS_SET {new_status:
[ACCEPTED, NOT_ACCEPTED]}` — names the competence decision as a *set* of statuses. Before E5b a list
value only matched a list payload (sequence equality), so the rule could never hold against the
scalar `new_status`. The addition is strictly additive: a list value against a **scalar** payload
value matches when the value is one of the list's members; a list payload is still compared as a
sequence and a scalar value is compared as before.

The proof that nothing already written changes score: every existing test log — the demo's good run,
its reworded twin and every §42 mutator, plus E5a's memo log — is scored twice, once with the
pre-E5b matcher (kept below verbatim as `_legacy_payload_matches`) and once with the shipped one,
and the report checksums are equal.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from app.domain.common.ids import EventId, SessionId
from app.domain.common.values import FactValue
from app.domain.enums import ActorType, EvaluatorType, ScoringCategory
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring import shared
from app.domain.scoring.engine import report_checksum, score
from app.domain.scoring.evaluators import deadline, workflow_action
from app.domain.scoring.rules import ScoringRule
from app.domain.scoring.shared import payload_matches

from tests.unit.domain.scoring._event_log_builders import (
    MUTATORS,
    demo_scenario,
    det_uuid,
    good_log,
    reworded_log,
)
from tests.unit.domain.scoring.test_memo_scoring import (
    ACCEPT_IN_TIME,
    COMPETENCE_DECLINE,
    memo_log,
)

SCENARIO = demo_scenario()


def _legacy_payload_matches(event: SessionEvent, expected: Mapping[str, FactValue] | None) -> bool:
    """`app.domain.scoring.shared.payload_matches` as it was before I3 E5b, verbatim."""
    if not expected:
        return True
    for key, wanted in expected.items():
        if key not in event.payload:
            return False
        actual = event.payload[key]
        if isinstance(actual, list | tuple) and isinstance(wanted, list):
            if [str(item) for item in actual] != [str(item) for item in wanted]:
                return False
            continue
        if actual != wanted and str(actual) != str(wanted):
            return False
    return True


def _event(payload: Mapping[str, Any]) -> SessionEvent:
    from datetime import UTC, datetime

    return SessionEvent(
        id=EventId(det_uuid("any-of-event")),
        session_id=SessionId(det_uuid("any-of-session")),
        seq_no=1,
        event_type=EventType.DDS_SERVICE_STATUS_SET,
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        monotonic_offset_ms=0,
        actor_type=ActorType.TRAINEE,
        actor_id=None,
        payload=dict(payload),
    )


# ---------------------------------------------------------------------------------------------
# The matcher
# ---------------------------------------------------------------------------------------------


def test_a_list_value_matches_a_scalar_payload_value_that_is_one_of_its_members() -> None:
    event = _event({"new_status": "NOT_ACCEPTED", "service_type": "POLICE"})

    assert payload_matches(event, {"new_status": ["ACCEPTED", "NOT_ACCEPTED"]})
    assert payload_matches(
        event, {"new_status": ["ACCEPTED", "NOT_ACCEPTED"], "service_type": "POLICE"}
    )
    assert not payload_matches(event, {"new_status": ["ACCEPTED", "RESPONSE_STARTED"]})
    assert not payload_matches(event, {"new_status": []})


def test_scalar_and_list_payload_semantics_are_unchanged() -> None:
    event = _event({"new_status": "ACCEPTED", "services": ["FIRE_RESCUE", "AMBULANCE"]})

    assert payload_matches(event, {"new_status": "ACCEPTED"})
    assert not payload_matches(event, {"new_status": "NOT_ACCEPTED"})
    # A list payload is still a sequence comparison — not "any of", not a subset.
    assert payload_matches(event, {"services": ["FIRE_RESCUE", "AMBULANCE"]})
    assert not payload_matches(event, {"services": ["FIRE_RESCUE"]})
    assert not payload_matches(event, {"services": ["AMBULANCE", "FIRE_RESCUE"]})
    assert not payload_matches(event, {"absent": ["x"]})


# ---------------------------------------------------------------------------------------------
# The HLD 70 example rule, end to end through the evaluators
# ---------------------------------------------------------------------------------------------


def _rule(rule_id: str, evaluator: EvaluatorType, config: dict[str, Any]) -> ScoringRule:
    return ScoringRule(
        rule_id=rule_id,
        name_ru=rule_id,
        description_ru=rule_id,
        category=ScoringCategory.TIMELINESS,
        max_points=10,
        critical=False,
        evaluator_type=evaluator,
        config=config,
        applies_to_variants={"dds_mode": ("MEMO_STATUSES",)},
    )


PRIMARY_DECISION_IN_TIME = _rule(
    "memo_primary_decision_within_30s",
    EvaluatorType.DEADLINE,
    {
        "from_event_type": "HANDOFF_RECEIVED",
        "to_event_type": "DDS_SERVICE_STATUS_SET",
        "to_payload_match": {"new_status": ["ACCEPTED", "NOT_ACCEPTED"]},
        "max_offset_ms": 30_000,
        "points": 10,
        "penalty_if_late": -5,
        "scale": "STEP",
        "linear_zero_ms": None,
    },
)
TWO_PRIMARY_DECISIONS = _rule(
    "memo_two_primary_decisions",
    EvaluatorType.WORKFLOW_ACTION,
    {
        "event_type": "DDS_SERVICE_STATUS_SET",
        "payload_match": {"new_status": ["ACCEPTED", "NOT_ACCEPTED"]},
        "min_count": 2,
        "max_count": 2,
        "required_stage_state": None,
        "must_occur_after": None,
        "points": 10,
        "penalty_if_missing": -10,
        "penalty_per_excess": 0,
    },
)


def test_the_hld_example_rule_scores_the_first_primary_decision() -> None:
    """POLICE is declined at 12 s, 7 s after the leg's `HANDOFF_RECEIVED` (memo_log)."""
    version = SCENARIO.model_copy(
        update={"scoring_rules": (PRIMARY_DECISION_IN_TIME, TWO_PRIMARY_DECISIONS)}
    )
    report = score(version, memo_log())
    by_id = {result.rule_id: result for result in report.results}

    assert by_id["memo_primary_decision_within_30s"].points_awarded == 10
    assert by_id["memo_two_primary_decisions"].points_awarded == 10
    assert len(by_id["memo_two_primary_decisions"].evidence) >= 2


# ---------------------------------------------------------------------------------------------
# Rescore equality over the existing test logs
# ---------------------------------------------------------------------------------------------


def _existing_runs() -> dict[str, tuple[Any, Callable[[], Any]]]:
    runs: dict[str, tuple[Any, Callable[[], Any]]] = {
        "demo/good": (SCENARIO, good_log),
        "demo/reworded": (SCENARIO, reworded_log),
    }
    for name, build in MUTATORS.items():
        runs[f"demo/{name}"] = (SCENARIO, build)
    memo_version = SCENARIO.model_copy(
        update={"scoring_rules": (ACCEPT_IN_TIME, COMPETENCE_DECLINE)}
    )
    runs["memo/e5a"] = (memo_version, memo_log)
    runs["memo/e5a-late"] = (memo_version, lambda: memo_log(accept_at_ms=60_000))
    runs["memo/demo-rules"] = (SCENARIO, memo_log)
    return runs


@pytest.mark.parametrize("run", sorted(_existing_runs()))
def test_every_existing_log_scores_identically_under_the_legacy_matcher(
    run: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    version, build = _existing_runs()[run]
    log = build()
    shipped = score(version, log)

    for module in (shared, deadline, workflow_action):
        monkeypatch.setattr(module, "payload_matches", _legacy_payload_matches)
    legacy = score(version, log)

    assert report_checksum(shipped) == report_checksum(legacy)
    assert shipped == legacy

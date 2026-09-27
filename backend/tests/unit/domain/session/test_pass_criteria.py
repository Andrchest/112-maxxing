"""«Сдал / не сдал» (I5 E38, Q-E9b-3 variant г) — the criteria and the verdict matrix.

* defaults: `70 %`, no failed-rule limit, a critical error fails;
* every criterion alone, then combined: PASS iff every enabled criterion holds;
* all three off is refused (`422 VALIDATION_ERROR`), a value out of range is refused too;
* `create_session` records the criteria in `SESSION_CREATED.pass_criteria` (the defaults when none
  are given), and the payload still satisfies the event catalog.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.enums import RoleType, SessionMode
from app.domain.events.catalog import validate_payload
from app.domain.events.types import EventType
from app.domain.session.pass_criteria import (
    DEFAULT_PASS_CRITERIA,
    PassCriteria,
    PassCriteriaError,
    PassCriterion,
    pass_verdict,
    score_percent,
)
from app.domain.session.session import create_session
from pydantic import ValidationError

from tests.unit.domain.session import _builders as b

OFF = {"min_score_percent": None, "max_failed_rules": None, "fail_on_critical": False}
"""Every criterion off — the starting point each single-criterion case switches one on from."""


def _verdict(
    criteria: PassCriteria,
    *,
    points: float = 70.0,
    max_points: float = 100.0,
    failed: int = 0,
    critical: int = 0,
) -> tuple[bool, tuple[PassCriterion, ...]]:
    verdict = pass_verdict(
        criteria,
        total_points=points,
        total_max_points=max_points,
        failed_rule_count=failed,
        critical_error_count=critical,
    )
    return verdict.passed, verdict.failed_criteria


def _only(**on: Any) -> PassCriteria:
    return PassCriteria(**{**OFF, **on})


# -- defaults and validation ------------------------------------------------------------------


def test_the_defaults_are_70_percent_no_rule_limit_and_critical_fails() -> None:
    assert PassCriteria() == DEFAULT_PASS_CRITERIA
    assert DEFAULT_PASS_CRITERIA.min_score_percent == 70
    assert DEFAULT_PASS_CRITERIA.max_failed_rules is None
    assert DEFAULT_PASS_CRITERIA.fail_on_critical is True


def test_all_criteria_off_is_refused_as_a_validation_error() -> None:
    with pytest.raises(PassCriteriaError) as raised:
        PassCriteria(**OFF)
    assert raised.value.code == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "values",
    [
        {"min_score_percent": 101},
        {"min_score_percent": -1},
        {"max_failed_rules": -1},
        {"unknown": 1},
    ],
)
def test_a_value_out_of_range_is_refused(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PassCriteria(**values)


@pytest.mark.parametrize(
    "on",
    [
        {"min_score_percent": 0},
        {"max_failed_rules": 0},
        {"fail_on_critical": True},
    ],
)
def test_any_one_criterion_on_is_enough(on: dict[str, Any]) -> None:
    assert _only(**on)


# -- each criterion alone ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("points", "passed"),
    [(70.0, True), (100.0, True), (69.99, False), (0.0, False)],
)
def test_the_score_threshold_alone(points: float, passed: bool) -> None:
    criteria = _only(min_score_percent=70)
    # failed rules and critical errors do not matter while their criteria are off
    assert _verdict(criteria, points=points, failed=9, critical=3) == (
        passed,
        () if passed else (PassCriterion.MIN_SCORE_PERCENT,),
    )


def test_the_score_threshold_reads_the_clamped_percent_the_statistics_show() -> None:
    assert score_percent(-5.0, 10.0) == 0.0
    assert score_percent(15.0, 10.0) == 100.0
    assert score_percent(1.0, 0.0) is None
    assert _verdict(_only(min_score_percent=0), points=-5.0, max_points=10.0) == (True, ())
    # no maximum → no percent → the threshold, when on, is not met
    assert _verdict(_only(min_score_percent=0), points=0.0, max_points=0.0) == (
        False,
        (PassCriterion.MIN_SCORE_PERCENT,),
    )


@pytest.mark.parametrize(("failed", "passed"), [(0, True), (2, True), (3, False)])
def test_the_failed_rule_limit_alone(failed: int, passed: bool) -> None:
    criteria = _only(max_failed_rules=2)
    assert _verdict(criteria, points=0.0, failed=failed, critical=1) == (
        passed,
        () if passed else (PassCriterion.MAX_FAILED_RULES,),
    )


def test_a_zero_failed_rule_limit_allows_none() -> None:
    assert _verdict(_only(max_failed_rules=0), failed=0) == (True, ())
    assert _verdict(_only(max_failed_rules=0), failed=1) == (
        False,
        (PassCriterion.MAX_FAILED_RULES,),
    )


@pytest.mark.parametrize(("critical", "passed"), [(0, True), (1, False), (4, False)])
def test_a_critical_error_alone(critical: int, passed: bool) -> None:
    criteria = _only(fail_on_critical=True)
    assert _verdict(criteria, points=0.0, failed=9, critical=critical) == (
        passed,
        () if passed else (PassCriterion.CRITICAL_ERRORS,),
    )


# -- combined ---------------------------------------------------------------------------------

ALL_ON = PassCriteria(min_score_percent=70, max_failed_rules=2, fail_on_critical=True)


@pytest.mark.parametrize(
    ("points", "failed", "critical", "expected"),
    [
        (80.0, 1, 0, ()),
        (60.0, 1, 0, (PassCriterion.MIN_SCORE_PERCENT,)),
        (80.0, 3, 0, (PassCriterion.MAX_FAILED_RULES,)),
        (80.0, 1, 1, (PassCriterion.CRITICAL_ERRORS,)),
        (
            10.0,
            5,
            2,
            (
                PassCriterion.MIN_SCORE_PERCENT,
                PassCriterion.MAX_FAILED_RULES,
                PassCriterion.CRITICAL_ERRORS,
            ),
        ),
    ],
)
def test_combined_pass_iff_every_enabled_criterion_holds(
    points: float, failed: int, critical: int, expected: tuple[PassCriterion, ...]
) -> None:
    assert _verdict(ALL_ON, points=points, failed=failed, critical=critical) == (
        not expected,
        expected,
    )


def test_the_defaults_combine_the_threshold_and_the_critical_rule() -> None:
    assert _verdict(DEFAULT_PASS_CRITERIA, points=75.0, failed=8) == (True, ())
    assert _verdict(DEFAULT_PASS_CRITERIA, points=75.0, critical=1) == (
        False,
        (PassCriterion.CRITICAL_ERRORS,),
    )


def test_the_verdict_carries_the_numbers_it_read() -> None:
    verdict = pass_verdict(
        ALL_ON, total_points=3.0, total_max_points=4.0, failed_rule_count=1, critical_error_count=0
    )
    assert verdict.criteria == ALL_ON
    assert (verdict.score_percent, verdict.failed_rule_count, verdict.critical_error_count) == (
        75.0,
        1,
        0,
    )


# -- recorded in SESSION_CREATED --------------------------------------------------------------


def _created(pass_criteria: PassCriteria | None) -> dict[str, Any]:
    version = b.scenario_version(role_chain=(RoleType.OPERATOR_112, RoleType.DDS))
    scenario_id, slug = b.scenario_ids()
    _session, events = create_session(
        session_id=b.SESSION_ID,
        incident_id=b.INCIDENT_ID,
        stage_ids=b.stage_ids(2),
        scenario_version=version,
        scenario_id=scenario_id,
        scenario_slug=slug,
        session_mode=SessionMode.MULTI_TRAINEE,
        created_by=b.INSTRUCTOR,
        pass_criteria=pass_criteria,
    )
    validate_payload(EventType.SESSION_CREATED, events[0].payload)
    return dict(events[0].payload)


def test_session_created_records_the_criteria() -> None:
    criteria = PassCriteria(min_score_percent=None, max_failed_rules=3, fail_on_critical=False)
    assert _created(criteria)["pass_criteria"] == {
        "min_score_percent": None,
        "max_failed_rules": 3,
        "fail_on_critical": False,
    }


def test_session_created_records_the_defaults_when_none_are_given() -> None:
    assert _created(None)["pass_criteria"] == {
        "min_score_percent": 70,
        "max_failed_rules": None,
        "fail_on_critical": True,
    }

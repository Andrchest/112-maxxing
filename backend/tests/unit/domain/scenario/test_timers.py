"""The instructor's per-card timer override (I4 E31, HLD 71 §71.8, D34).

`resolve_card_timers(scenario, override)` is scenario ← override, key by key; an absent key keeps
the scenario value; a result that breaks R39 is `422 VALIDATION_ERROR`, never clipped.
"""

from __future__ import annotations

import pytest
from app.domain.dds.card_status import DEFAULT_CARD_TIMERS, CardTimers
from app.domain.lesson.plan import PlanEntry
from app.domain.scenario.timers import (
    CardTimersOverride,
    TimersOverrideError,
    resolve_card_timers,
)
from pydantic import ValidationError

SCENARIO = CardTimers(
    accept_within_ms=20_000, fill_within_ms=120_000, not_completed_after_ms=600_000
)


def test_no_override_keeps_the_scenario_timers() -> None:
    assert resolve_card_timers(SCENARIO, None) == SCENARIO
    assert resolve_card_timers(SCENARIO, CardTimersOverride()) == SCENARIO


def test_an_override_replaces_only_the_keys_it_sets() -> None:
    resolved = resolve_card_timers(SCENARIO, CardTimersOverride(accept_within_ms=45_000))
    assert resolved == CardTimers(
        accept_within_ms=45_000, fill_within_ms=120_000, not_completed_after_ms=600_000
    )


def test_every_key_may_be_overridden() -> None:
    override = CardTimersOverride(
        accept_within_ms=1_000, fill_within_ms=2_000, not_completed_after_ms=3_000
    )
    assert resolve_card_timers(DEFAULT_CARD_TIMERS, override) == CardTimers(
        accept_within_ms=1_000, fill_within_ms=2_000, not_completed_after_ms=3_000
    )


@pytest.mark.parametrize(
    "override",
    [
        CardTimersOverride(accept_within_ms=600_000),
        CardTimersOverride(not_completed_after_ms=20_000),
        CardTimersOverride(accept_within_ms=50_000, not_completed_after_ms=40_000),
    ],
)
def test_a_result_that_breaks_r39_is_refused(override: CardTimersOverride) -> None:
    with pytest.raises(TimersOverrideError) as raised:
        resolve_card_timers(SCENARIO, override)
    assert raised.value.code == "VALIDATION_ERROR"
    assert "R39" in str(raised.value)


@pytest.mark.parametrize(
    "document",
    [{"accept_within_ms": 0}, {"fill_within_ms": -1}, {"accept_within_ms": 1, "extra_ms": 5}],
)
def test_the_override_refuses_a_non_positive_value_or_an_unknown_key(
    document: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        CardTimersOverride.model_validate(document)


def test_a_plan_entry_carries_its_override() -> None:
    entry = PlanEntry.model_validate(
        {
            "position": 1,
            "scenario_version_id": "00000000-0000-0000-0000-000000000001",
            "arrival": {"kind": "AT_OFFSET", "offset_ms": 0},
            "timers": {"accept_within_ms": 60_000},
        }
    )
    assert entry.timers == CardTimersOverride(accept_within_ms=60_000)
    stored = PlanEntry.model_validate(entry.model_dump(mode="json"))
    assert stored == entry, "the plan round-trips through its jsonb document"
    legacy = PlanEntry.model_validate(
        {
            "position": 1,
            "scenario_version_id": "00000000-0000-0000-0000-000000000001",
            "arrival": {"kind": "AT_OFFSET", "offset_ms": 0},
        }
    )
    assert legacy.timers is None, "a plan stored before E31 reads as 'no override'"

"""INV 11 — "Every scoring point/penalty has evidence" (SPEC §42 item 11, §28, D11).

SPEC §28: "Each `ScoreResult` must contain `ScoreEvidence` pointing to concrete events/card
snapshots." D11 adds the enforcement: "a rule that awards or deducts without evidence is a hard
error". Two things have to be true for that promise to mean anything, and both are checked here
over the good run *and* every mutated run:

1. **Enough evidence.** Every result carries at least `max(1, rule.min_evidence)` items, and each
   item sets exactly one of `event_id` / `card_revision_id` / `snapshot_id` — the same "exactly
   one" the `score_evidence` CHECK constraint declares (`20-db-schema.md` §20.7).
2. **Concrete evidence.** Every reference actually resolves inside the log the report was
   computed from. A plausible-looking id that points at nothing would satisfy the first half and
   be worthless: evidence exists so an instructor can click it.

The bite is the last test: an evaluator monkeypatched to award points without evidence makes
`score()` raise, rather than quietly producing a report with an unbacked number in it.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import pytest
from app.domain.enums import EvaluatorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring import evidence as evidence_module
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.engine import ScoringEvidenceError, score
from app.domain.scoring.evaluators import registry
from app.domain.scoring.results import ScoreEvidence, ScoreResult
from app.domain.scoring.rules import ScoringRule

from tests.unit.domain.scoring._event_log_builders import (
    MUTATORS,
    card_revision_ids,
    demo_scenario,
    good_log,
    mutate,
)

ALL_LOGS: dict[str, Sequence[SessionEvent]] = {
    "good": good_log(),
    **{name: builder() for name, builder in MUTATORS.items()},
}


def _snapshot_ids(events: Sequence[SessionEvent]) -> frozenset[UUID]:
    found: set[UUID] = set()
    for event in events:
        if event.event_type is EventType.HANDOFF_CREATED:
            raw = event.payload.get("snapshot_id")
            if isinstance(raw, str):
                found.add(UUID(raw))
    return frozenset(found)


@pytest.mark.parametrize("name", sorted(ALL_LOGS))
def test_every_result_carries_at_least_its_required_evidence(name: str) -> None:
    version = demo_scenario()
    by_rule = {rule.rule_id: rule for rule in version.scoring_rules}

    report = score(version, ALL_LOGS[name])

    assert report.results
    for result in report.results:
        required = max(1, by_rule[result.rule_id].min_evidence)
        assert len(result.evidence) >= required, f"{name}/{result.rule_id}"


@pytest.mark.parametrize("name", sorted(ALL_LOGS))
def test_every_evidence_item_sets_exactly_one_reference(name: str) -> None:
    report = score(demo_scenario(), ALL_LOGS[name])

    for result in report.results:
        for item in result.evidence:
            references = [item.event_id, item.card_revision_id, item.snapshot_id]
            assert sum(1 for ref in references if ref is not None) == 1, f"{name}/{result.rule_id}"
            assert item.note_ru.strip(), f"{name}/{result.rule_id}"


@pytest.mark.parametrize("name", sorted(ALL_LOGS))
def test_every_reference_resolves_inside_the_input_log(name: str) -> None:
    """Concrete means concrete: an instructor can click every one of these."""
    events = ALL_LOGS[name]
    event_ids = {event.id for event in events}
    revision_ids = card_revision_ids(events)
    snapshot_ids = _snapshot_ids(events)
    seq_numbers = {event.seq_no for event in events}

    report = score(demo_scenario(), events)

    for result in report.results:
        for item in result.evidence:
            where = f"{name}/{result.rule_id}: {item.note_ru}"
            if item.event_id is not None:
                assert item.event_id in event_ids, where
            elif item.card_revision_id is not None:
                assert item.card_revision_id in revision_ids, where
            else:
                assert item.snapshot_id in snapshot_ids, where
            if item.seq_no is not None:
                assert item.seq_no in seq_numbers, where


@pytest.mark.parametrize("name", sorted(ALL_LOGS))
def test_no_result_awards_or_deducts_without_evidence(name: str) -> None:
    report = score(demo_scenario(), ALL_LOGS[name])

    moved = [result for result in report.results if result.points_awarded != 0.0]

    assert moved, name
    assert all(result.evidence for result in moved)


def test_the_logs_under_test_really_do_exercise_penalties_and_absences() -> None:
    """A guard: a sweep over logs that all score perfectly would prove nothing."""
    version = demo_scenario()
    reports = {name: score(version, events) for name, events in ALL_LOGS.items()}

    penalties = [
        result
        for report in reports.values()
        for result in report.results
        if result.points_awarded < 0
    ]
    criticals = [result for report in reports.values() for result in report.critical_errors]

    assert len(ALL_LOGS) >= 10
    assert penalties
    assert criticals


# ---------------------------------------------------------------------------------------------
# The bite: an evaluator that awards without evidence must not be able to.
# ---------------------------------------------------------------------------------------------


def test_an_evaluator_that_returns_no_evidence_makes_score_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = demo_scenario()

    def unbacked(rule: ScoringRule, config: object, ctx: ScoringContext) -> ScoreResult:
        """Awards the full points and points at nothing — exactly what D11 forbids."""
        return ScoreResult.model_construct(
            rule_id=rule.rule_id,
            evaluator_type=rule.evaluator_type,
            category=rule.category,
            points_awarded=rule.max_points,
            max_points=rule.max_points,
            passed=True,
            critical_failure=False,
            evidence=(),
        )

    patched = dict(registry.EVALUATORS)
    patched[EvaluatorType.FACT_OBTAINED] = unbacked
    monkeypatch.setattr(registry, "EVALUATORS", patched)
    monkeypatch.setattr("app.domain.scoring.engine.EVALUATORS", patched)

    with pytest.raises(ScoringEvidenceError):
        score(version, good_log())


def test_a_rule_that_demands_more_evidence_than_its_evaluator_produces_raises() -> None:
    version = demo_scenario()
    greedy = version.scoring_rules[0].model_copy(update={"min_evidence": 9})

    with pytest.raises(ScoringEvidenceError):
        score(version.model_copy(update={"scoring_rules": (greedy,)}), good_log())


def test_evidence_cannot_be_built_without_a_real_reference() -> None:
    """The constructors take the object they point at, so a reference cannot be invented."""
    events = good_log()
    handoff = next(e for e in events if e.event_type is EventType.HANDOFF_CREATED)

    from_event = evidence_module.from_event(events[0], "событие")
    from_snapshot = evidence_module.from_snapshot(handoff, "снимок")

    assert from_event.event_id == events[0].id
    assert from_event.seq_no == events[0].seq_no
    assert from_snapshot.snapshot_id == UUID(handoff.payload["snapshot_id"])
    with pytest.raises(ValueError, match="exactly one"):
        ScoreEvidence(note_ru="без ссылки")


def test_absence_evidence_points_at_a_bounding_event() -> None:
    """D11: "'Absence' evidence points at the bounding events"."""
    events = mutate("fact_never_delivered")
    by_id = {event.id: event for event in events}

    report = score(demo_scenario(), events)
    missing = next(r for r in report.results if r.rule_id == "fact_victim_inside")

    referenced = by_id[missing.evidence[0].event_id]

    assert referenced.event_type in {
        EventType.ROLE_STAGE_COMPLETED,
        EventType.SESSION_COMPLETED,
        EventType.HANDOFF_CREATED,
    }

"""`score`, `report_checksum`, `scoring_events` (HLD `10-domain-model.md` §10.14, D11, SPEC §28).

Pure: no I/O, no LLM, no clock, no `uuid4`, no materialized tables (§42 tests 9-11). The whole
input is `(ScenarioVersion, SessionEvents ordered by seq_no)`; nothing else reaches a number, an
evidence list or the checksum, so the same log and the same scenario version always produce the
same report — which is what `rescoreSession` exists to prove.

Order at session end (the unit of work `application/scoring` runs): `SESSION_COMPLETED` is
appended first, `score()` runs over the log up to and including it, and only then is one
`SCORING_RULE_EVALUATED` per rule appended. `SCORING_*` events are the only events allowed to
follow `SESSION_COMPLETED`, and `score()` drops them from its input — so re-scoring the whole
stored log, previous scoring events and all, reproduces the identical report.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType, ScoringCategory
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring import evidence
from app.domain.scoring.context import ScoringContext, build_context
from app.domain.scoring.errors import ScoringEvidenceError
from app.domain.scoring.evaluators.registry import EVALUATORS, parse_rule_config
from app.domain.scoring.results import (
    ScoreCategoryTotal,
    ScoreEvidence,
    ScoreReport,
    ScoreResult,
)
from app.domain.scoring.rules import ScoringRule

__all__ = [
    "ScoringEvidenceError",
    "report_checksum",
    "score",
    "scoring_events",
]

NOT_APPLICABLE_NOTE_RU = "Правило не применяется: роль не участвует в сессии"
"""`note_ru` of the single evidence a non-applicable rule carries (ruling R7)."""

_POINTS_QUANTUM = Decimal("0.01")
"""`score_results.points_awarded` is `numeric(8,2)` (§20.7): the domain rounds to match it."""


def score(
    scenario_version: ScenarioVersion,
    events: Sequence[SessionEvent],
) -> ScoreReport:
    """Deterministically score one session (§10.14, D11, SPEC §28).

    `events` must be ordered by `seq_no`; an unordered or duplicated log raises rather than being
    quietly re-sorted, because that is a caller defect and not a property of the session.
    """
    ctx = build_context(scenario_version, events)
    results = tuple(_one_rule(rule, ctx) for rule in scenario_version.scoring_rules)

    total_points = _round(sum(result.points_awarded for result in results))
    total_max_points = _round(sum(result.max_points for result in results))
    return ScoreReport(
        scenario_version_id=scenario_version.id,
        session_id=_session_id(ctx, events),
        total_points=total_points,
        total_max_points=total_max_points,
        by_category=_by_category(results),
        critical_errors=tuple(result for result in results if result.critical_failure),
        results=results,
        computed_from_event_count=ctx.computed_from_event_count,
    )


def report_checksum(report: ScoreReport) -> str:
    """Canonical-JSON SHA-256 over the numeric results (`openapi.yaml` `ScoreReportView.checksum`).

    Sorted keys, no whitespace, every float rendered as a fixed two-decimal string — the same
    two decimals `numeric(8,2)` stores, so a checksum computed before persisting and one computed
    after reading back cannot differ over a rounding artefact. Results appear in scenario rule
    order; nothing about evidence, notes or timing is in scope, because this is the checksum
    `rescoreSession` compares to answer "are the numbers the same".
    """
    document = {
        "results": [
            {
                "rule_id": result.rule_id,
                "points_awarded": _fixed(result.points_awarded),
                "max_points": _fixed(result.max_points),
                "passed": result.passed,
                "critical_failure": result.critical_failure,
            }
            for result in report.results
        ],
        "total_points": _fixed(report.total_points),
        "total_max_points": _fixed(report.total_max_points),
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def scoring_events(
    report: ScoreReport,
    scenario_version: ScenarioVersion,
    *,
    monotonic_offset_ms: int,
) -> tuple[DomainEvent, ...]:
    """One `SCORING_RULE_EVALUATED` per result, in scenario rule order (§10.13 catalog row).

    Pure, like everything else here: the events are returned, never appended. The unit of work
    that closed the session appends them together with the `score_results` / `score_evidence`
    rows, so a report and its audit trail are written or not written together.

    `critical` in the payload is the *rule's* flag, not `critical_failure`: the catalog row names
    it `critical`, and a reader of the log needs to know that a passed rule was a critical one.
    """
    critical_by_rule = {rule.rule_id: rule.critical for rule in scenario_version.scoring_rules}
    actor = ActorRef(actor_type=ActorType.SYSTEM)
    return tuple(
        DomainEvent(
            event_type=EventType.SCORING_RULE_EVALUATED,
            actor=actor,
            monotonic_offset_ms=monotonic_offset_ms,
            payload={
                "rule_id": result.rule_id,
                "evaluator_type": result.evaluator_type.value,
                "category": result.category.value,
                "points_awarded": result.points_awarded,
                "max_points": result.max_points,
                "passed": result.passed,
                "critical": critical_by_rule.get(result.rule_id, result.critical_failure),
                "evidence": [_evidence_payload(item) for item in result.evidence],
            },
        )
        for result in report.results
    )


# ---------------------------------------------------------------------------------------------
# One rule
# ---------------------------------------------------------------------------------------------


def _one_rule(rule: ScoringRule, ctx: ScoringContext) -> ScoreResult:
    if not _applies(rule, ctx):
        return _not_applicable(rule, ctx)
    config = parse_rule_config(rule)
    result = EVALUATORS[rule.evaluator_type](rule, config, ctx)
    return _finish(rule, result)


def _applies(rule: ScoringRule, ctx: ScoringContext) -> bool:
    """Ruling R7: an empty `applies_to_roles` always applies; otherwise the chain decides.

    The chain is the one the *event log* records (`SESSION_CREATED.role_chain`, falling back to
    the `ROLE_STAGE_STARTED` types), never `scenario_version.role_chain`: a session is scored on
    what happened, and an instructor may run a scenario on a shorter chain than the scenario
    file declares. A log that records no chain at all leaves every rule applicable — refusing to
    score would turn a thin log into a silent zero, which D11 forbids.
    """
    if not rule.applies_to_roles:
        return True
    if not ctx.role_chain:
        return True
    return any(role in ctx.role_chain for role in rule.applies_to_roles)


def _not_applicable(rule: ScoringRule, ctx: ScoringContext) -> ScoreResult:
    """A zero/zero pass that changes neither the total, nor a percentage, nor a critical error."""
    bound = ctx.role_chain_event
    item = (
        evidence.from_event(bound, NOT_APPLICABLE_NOTE_RU)
        if bound is not None
        else evidence.from_event(evidence.bounding_event(ctx), NOT_APPLICABLE_NOTE_RU)
    )
    return ScoreResult(
        rule_id=rule.rule_id,
        evaluator_type=rule.evaluator_type,
        category=rule.category,
        points_awarded=0.0,
        max_points=0.0,
        passed=True,
        critical_failure=False,
        evidence=(item,),
    )


def _finish(rule: ScoringRule, result: ScoreResult) -> ScoreResult:
    """The one place points are rounded and the evidence requirement is enforced (R3, R10)."""
    required = max(1, rule.min_evidence)
    if len(result.evidence) < required:
        raise ScoringEvidenceError(
            f"rule {rule.rule_id!r} ({rule.evaluator_type.value}) produced "
            f"{len(result.evidence)} evidence item(s), but min_evidence is {required}: "
            "a point or a penalty without evidence is a hard error (SPEC §28, §42 test 11)"
        )
    return result.model_copy(
        update={
            "points_awarded": _round(result.points_awarded),
            "max_points": _round(result.max_points),
            "critical_failure": rule.critical and not result.passed,
        }
    )


def _by_category(results: Sequence[ScoreResult]) -> tuple[ScoreCategoryTotal, ...]:
    """Subtotals in `ScoringCategory` declaration order, for the categories that have a rule."""
    present = {result.category for result in results}
    return tuple(
        ScoreCategoryTotal(
            category=category,
            points_awarded=_round(
                sum(result.points_awarded for result in results if result.category is category)
            ),
            max_points=_round(
                sum(result.max_points for result in results if result.category is category)
            ),
        )
        for category in ScoringCategory
        if category in present
    )


def _session_id(ctx: ScoringContext, events: Sequence[SessionEvent]) -> SessionId:
    """The session the log belongs to. Every `SessionEvent` carries it; an empty log cannot."""
    if ctx.events:
        return ctx.events[0].session_id
    if events:
        return events[0].session_id
    raise ScoringEvidenceError(
        "cannot score an empty event log: no session to attribute the report to (D5)"
    )


def _round(value: float) -> float:
    """ROUND_HALF_UP to two decimals — the one place a number is rounded (ruling R10)."""
    return float(Decimal(repr(float(value))).quantize(_POINTS_QUANTUM, rounding=ROUND_HALF_UP))


def _fixed(value: float) -> str:
    return f"{_round(value):.2f}"


def _evidence_payload(item: ScoreEvidence) -> dict[str, object]:
    return {
        "event_id": str(item.event_id) if item.event_id is not None else None,
        "card_revision_id": (
            str(item.card_revision_id) if item.card_revision_id is not None else None
        ),
        "snapshot_id": str(item.snapshot_id) if item.snapshot_id is not None else None,
        "seq_no": item.seq_no,
        "note_ru": item.note_ru,
    }

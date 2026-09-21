"""`reports` schemas — `ScoreReportView`, `RescoreResult` (`openapi.yaml`, SPEC §28, §29, D11).

Property names are copied **literally** from the contract (`backend/tests/api/test_contract.py`).

`ScoreResultView` needs `name_ru` / `description_ru`, which are not on the domain `ScoreResult` —
only `ScoringRule` (the scenario's own rule catalog) carries them, so every mapper here that builds
one takes a `rules_by_id: Mapping[str, ScoringRule]` alongside the result.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.scoring.rescore_session import RescoreOutcome
from app.domain.enums import EvaluatorType, ScoringCategory
from app.domain.scoring.results import ScoreCategoryTotal, ScoreEvidence, ScoreReport, ScoreResult
from app.domain.scoring.rules import ScoringRule

__all__ = [
    "RescoreDifferenceSchema",
    "RescoreRequestSchema",
    "RescoreResultSchema",
    "ScoreCategoryTotalViewSchema",
    "ScoreEvidenceViewSchema",
    "ScoreReportViewSchema",
    "ScoreResultViewSchema",
    "rescore_result_schema",
    "score_report_view_schema",
    "score_result_view_schema",
]


class RescoreRequestSchema(ApiModel):
    """`openapi.yaml`'s `RescoreRequest` — the optional body of `rescoreSession`."""

    persist: bool = Field(default=False)


class ScoreEvidenceViewSchema(ApiModel):
    """`openapi.yaml`'s `ScoreEvidenceView`."""

    event_id: UUID | None
    card_revision_id: UUID | None
    snapshot_id: UUID | None
    seq_no: int | None
    note_ru: str


class ScoreResultViewSchema(ApiModel):
    """`openapi.yaml`'s `ScoreResultView`."""

    rule_id: str
    name_ru: str
    description_ru: str
    evaluator_type: EvaluatorType
    category: ScoringCategory
    points_awarded: float
    max_points: float
    passed: bool
    critical_failure: bool
    evidence: list[ScoreEvidenceViewSchema]


class ScoreCategoryTotalViewSchema(ApiModel):
    """`openapi.yaml`'s `ScoreCategoryTotalView`."""

    category: ScoringCategory
    points_awarded: float
    max_points: float


class ScoreReportViewSchema(ApiModel):
    """`openapi.yaml`'s `ScoreReportView`."""

    scenario_version_id: UUID
    session_id: UUID
    total_points: float
    total_max_points: float
    by_category: list[ScoreCategoryTotalViewSchema]
    critical_errors: list[ScoreResultViewSchema]
    results: list[ScoreResultViewSchema]
    computed_from_event_count: int
    checksum: str


class RescoreDifferenceSchema(ApiModel):
    """One item of `openapi.yaml`'s `RescoreResult.differences`."""

    rule_id: str
    stored_points: float | None
    recomputed_points: float


class RescoreResultSchema(ApiModel):
    """`openapi.yaml`'s `RescoreResult`."""

    session_id: UUID
    identical_to_stored: bool
    recomputed: ScoreReportViewSchema
    stored_checksum: str | None
    recomputed_checksum: str
    differences: list[RescoreDifferenceSchema]
    persisted: bool


def score_evidence_view_schema(evidence: ScoreEvidence) -> ScoreEvidenceViewSchema:
    """`ScoreEvidence` -> the wire model."""
    return ScoreEvidenceViewSchema(
        event_id=UUID(str(evidence.event_id)) if evidence.event_id is not None else None,
        card_revision_id=(
            UUID(str(evidence.card_revision_id)) if evidence.card_revision_id is not None else None
        ),
        snapshot_id=UUID(str(evidence.snapshot_id)) if evidence.snapshot_id is not None else None,
        seq_no=evidence.seq_no,
        note_ru=evidence.note_ru,
    )


def score_result_view_schema(
    result: ScoreResult, rules_by_id: Mapping[str, ScoringRule]
) -> ScoreResultViewSchema:
    """`ScoreResult` + its rule's `name_ru`/`description_ru` -> the wire model."""
    rule = rules_by_id[result.rule_id]
    return ScoreResultViewSchema(
        rule_id=result.rule_id,
        name_ru=rule.name_ru,
        description_ru=rule.description_ru,
        evaluator_type=result.evaluator_type,
        category=result.category,
        points_awarded=result.points_awarded,
        max_points=result.max_points,
        passed=result.passed,
        critical_failure=result.critical_failure,
        evidence=[score_evidence_view_schema(evidence) for evidence in result.evidence],
    )


def score_category_total_view_schema(total: ScoreCategoryTotal) -> ScoreCategoryTotalViewSchema:
    """`ScoreCategoryTotal` -> the wire model."""
    return ScoreCategoryTotalViewSchema(
        category=total.category, points_awarded=total.points_awarded, max_points=total.max_points
    )


def score_report_view_schema(
    report: ScoreReport, rules_by_id: Mapping[str, ScoringRule], *, checksum: str
) -> ScoreReportViewSchema:
    """`ScoreReport` -> the wire model. `checksum` is computed by the caller (`report_checksum`,
    a pure domain function `app.api.schemas` never calls on its own)."""
    return ScoreReportViewSchema(
        scenario_version_id=UUID(str(report.scenario_version_id)),
        session_id=UUID(str(report.session_id)),
        total_points=report.total_points,
        total_max_points=report.total_max_points,
        by_category=[score_category_total_view_schema(total) for total in report.by_category],
        critical_errors=[
            score_result_view_schema(result, rules_by_id) for result in report.critical_errors
        ],
        results=[score_result_view_schema(result, rules_by_id) for result in report.results],
        computed_from_event_count=report.computed_from_event_count,
        checksum=checksum,
    )


def rescore_result_schema(outcome: RescoreOutcome) -> RescoreResultSchema:
    """`RescoreOutcome` -> the wire model."""
    rules_by_id = {rule.rule_id: rule for rule in outcome.scoring_rules}
    return RescoreResultSchema(
        session_id=UUID(str(outcome.session_id)),
        identical_to_stored=outcome.identical_to_stored,
        recomputed=score_report_view_schema(
            outcome.recomputed, rules_by_id, checksum=outcome.recomputed_checksum
        ),
        stored_checksum=outcome.stored_checksum,
        recomputed_checksum=outcome.recomputed_checksum,
        differences=[
            RescoreDifferenceSchema(
                rule_id=difference.rule_id,
                stored_points=difference.stored_points,
                recomputed_points=difference.recomputed_points,
            )
            for difference in outcome.differences
        ],
        persisted=outcome.persisted,
    )

"""Scoring results (HLD `10-domain-model.md` §10.14 "Results", SPEC §28, D11).

The four shapes are copied literally from §10.14. All four are frozen and `extra="forbid"`: a
`ScoreReport` is a value, and the checksum `rescoreSession` compares (`openapi.yaml`
`ScoreReportView.checksum`) is only meaningful over a shape nothing can add a field to.

`ScoreEvidence` carries exactly one of `event_id` / `card_revision_id` / `snapshot_id` — the same
"exactly one of the three refs is non-null" CHECK the `score_evidence` table declares
(`20-db-schema.md` §20.7), enforced here so the domain never builds a row the DB would reject.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.common.ids import (
    CardRevisionId,
    EventId,
    ScenarioVersionId,
    SessionId,
    SnapshotId,
)
from app.domain.enums import EvaluatorType, ScoringCategory

__all__ = [
    "ScoreCategoryTotal",
    "ScoreEvidence",
    "ScoreReport",
    "ScoreResult",
]


class ScoreEvidence(BaseModel):
    """One concrete reference behind a point or a penalty (SPEC §28, §42 test 11)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: EventId | None = None
    card_revision_id: CardRevisionId | None = None
    snapshot_id: SnapshotId | None = None
    seq_no: int | None = None
    note_ru: str

    @model_validator(mode="after")
    def _exactly_one_reference(self) -> ScoreEvidence:
        chosen = sum(
            1
            for value in (self.event_id, self.card_revision_id, self.snapshot_id)
            if value is not None
        )
        if chosen != 1:
            raise ValueError(
                "exactly one of event_id / card_revision_id / snapshot_id must be set "
                "(HLD 10.14, 20-db-schema 20.7)"
            )
        return self


class ScoreResult(BaseModel):
    """One evaluated `ScoringRule` (§10.14). `points_awarded` may be negative (a penalty)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    evaluator_type: EvaluatorType
    category: ScoringCategory
    points_awarded: float
    max_points: float
    passed: bool
    critical_failure: bool
    evidence: tuple[ScoreEvidence, ...]

    @model_validator(mode="after")
    def _at_least_one_evidence(self) -> ScoreResult:
        if not self.evidence:
            raise ValueError(
                f"ScoreResult {self.rule_id!r} has no evidence; every result carries at least one "
                "(SPEC §28, §42 test 11)"
            )
        return self


class ScoreCategoryTotal(BaseModel):
    """Per-`ScoringCategory` subtotal (§10.14, SPEC §29 "score by category")."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: ScoringCategory
    points_awarded: float
    max_points: float


class ScoreReport(BaseModel):
    """The whole deterministic outcome of one `score(...)` call (§10.14, D11)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_version_id: ScenarioVersionId
    session_id: SessionId
    total_points: float
    total_max_points: float
    by_category: tuple[ScoreCategoryTotal, ...]
    critical_errors: tuple[ScoreResult, ...]
    results: tuple[ScoreResult, ...]
    computed_from_event_count: int

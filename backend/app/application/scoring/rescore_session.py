"""`rescoreSession` (`openapi.yaml` `POST /api/v1/reports/{session_id}/rescore`, SPEC §28, §42
test 9, D11).

Re-runs `score()` over the stored log and compares it with what `score_results` holds, without
mutating anything unless the caller asks (`persist: false` is the default, and the check is then
non-destructive). `identical_to_stored` is the checksum comparison (R8); `differences` is the
friendlier per-rule `points_awarded` delta a human reads first.

A session with **no** stored score (never scored, or a `ScoringEvidenceError` at close left none —
CHANGE item 3) is not an error: `stored_checksum` is `null` and every rule is a difference against
`null`, exactly as `RescoreResult`'s schema allows. A session that has not reached `COMPLETED` is
`409 REPORT_NOT_READY` — there is no `SESSION_COMPLETED` in its log for `score()` to bound
"absence" evidence against (R2), so nothing here would be reproducible.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.auth.ownership import require_owner_or_admin
from app.application.ports.audit_changes import NO_AUDIT_CHANGES, AuditChangeCollector
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.scoring.score_session import (
    compute_report,
    persist_score,
    session_completed_offset,
)
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId
from app.domain.enums import ScoringCategory, SessionState
from app.domain.scoring.engine import report_checksum
from app.domain.scoring.results import ScoreCategoryTotal, ScoreReport, ScoreResult
from app.domain.scoring.rules import ScoringRule

__all__ = ["ReportNotReadyError", "RescoreDifference", "RescoreOutcome", "RescoreSession"]


class ReportNotReadyError(DomainError):
    """The session has not reached `COMPLETED`, so it has never been scored (`409 REPORT_NOT_READY`,
    `openapi.yaml`'s `Conflict` response and `getReportExplanation`'s own use of the same code)."""

    code = "REPORT_NOT_READY"

    def __init__(self, session_id: SessionId, state: SessionState) -> None:
        self.session_id = session_id
        self.state = state
        super().__init__(f"session {session_id} is {state.value}, not COMPLETED; nothing to score")


class RescoreDifference(BaseModel):
    """One rule whose stored and recomputed `points_awarded` disagree (`RescoreResult.differences`).

    `stored_points` is `None` when the rule was never stored at all — the "no stored score" case,
    where every rule of the recomputed report is a difference.
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str
    stored_points: float | None
    recomputed_points: float


class RescoreOutcome(BaseModel):
    """`RescoreResult` (`openapi.yaml`), assembled — the API schema mapper renders this as-is."""

    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    identical_to_stored: bool
    recomputed: ScoreReport
    stored_checksum: str | None
    recomputed_checksum: str
    differences: tuple[RescoreDifference, ...]
    persisted: bool
    scoring_rules: tuple[ScoringRule, ...]
    """The scenario's own rule catalog (`rule_id -> name_ru/description_ru`), for the schema
    mapper: `ScoreResultView.name_ru`/`.description_ru` are not on the domain `ScoreResult`."""


class RescoreSession:
    """`rescoreSession`: `INSTRUCTOR`/`ADMIN` only (D8 — the two roles that may command or observe
    any session; a trainee re-scoring, let alone persisting over, their own official result is
    exactly the kind of self-graded outcome SPEC §28's determinism guarantee exists to rule out)."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, changes: AuditChangeCollector = NO_AUDIT_CHANGES
    ) -> None:
        self._unit_of_work = unit_of_work
        #: I7 E43 (ТЗ ¶246): a persisted rescore reports the score «было → стало» — the total and
        #: every rule whose points moved. A dry run changes nothing and reports nothing.
        self._changes = changes

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, *, persist: bool
    ) -> RescoreOutcome:
        if not user.is_instructor_or_admin:
            raise ForbiddenForRoleError(
                f"the caller may not rescore session {session_id}: INSTRUCTOR/ADMIN only"
            )
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if persist:
                # I5 E39 (Q-E9b-4 а): persisting overwrites the official result, so only the
                # instructor who created the session (or an ADMIN); the dry run stays a read.
                require_owner_or_admin(
                    session.created_by_user_id, user, resource=f"the score of session {session_id}"
                )
            if session.state is not SessionState.COMPLETED:
                raise ReportNotReadyError(session_id, session.state)

            recomputed, scenario_version, events = await compute_report(uow, session_id)
            stored_results = await uow.scores.load_report(session_id)
            recomputed_checksum = report_checksum(recomputed)
            stored_checksum = (
                None
                if stored_results is None
                else report_checksum(_stored_report(recomputed, stored_results))
            )
            differences = _differences(stored_results, recomputed.results)

            persisted = False
            if persist:
                completed_at = session_completed_offset(session_id, events)
                await persist_score(
                    uow,
                    session_id,
                    scenario_version,
                    recomputed,
                    monotonic_offset_ms=completed_at,
                )
                persisted = True
            await uow.commit()
        if persisted:
            self._record_score(stored_results, recomputed, differences)

        return RescoreOutcome(
            session_id=session_id,
            identical_to_stored=stored_checksum is not None
            and stored_checksum == recomputed_checksum,
            recomputed=recomputed,
            stored_checksum=stored_checksum,
            recomputed_checksum=recomputed_checksum,
            differences=differences,
            persisted=persisted,
            scoring_rules=scenario_version.scoring_rules,
        )

    def _record_score(
        self,
        stored_results: tuple[ScoreResult, ...] | None,
        recomputed: ScoreReport,
        differences: tuple[RescoreDifference, ...],
    ) -> None:
        stored_total = (
            None
            if stored_results is None
            else sum(result.points_awarded for result in stored_results)
        )
        self._changes.record("score", "total_points", stored_total, recomputed.total_points)
        for difference in differences:
            self._changes.record(
                "score",
                f"rule_points[{difference.rule_id}]",
                difference.stored_points,
                difference.recomputed_points,
            )


def _stored_report(recomputed: ScoreReport, stored_results: tuple[ScoreResult, ...]) -> ScoreReport:
    """Stored `score_results` rows, reshaped into a `ScoreReport` so `report_checksum` can hash
    them with the exact same function the recomputed side uses (R8).

    `computed_from_event_count` is not a `score_results` column (it is a report-level fact, not a
    per-rule one) — it is borrowed from `recomputed` rather than re-derived, which is exact rather
    than approximate: `SCORING_*` events are the only events allowed after `SESSION_COMPLETED`
    (R2) and `score()` ignores them (R2), so the count of events `score()` reads for a `COMPLETED`
    session is a session-wide invariant that cannot have changed between the stored score and now.
    """
    total_points = sum(result.points_awarded for result in stored_results)
    total_max_points = sum(result.max_points for result in stored_results)
    by_category = _category_totals(stored_results)
    critical_errors = tuple(result for result in stored_results if result.critical_failure)
    return ScoreReport(
        scenario_version_id=recomputed.scenario_version_id,
        session_id=recomputed.session_id,
        total_points=total_points,
        total_max_points=total_max_points,
        by_category=by_category,
        critical_errors=critical_errors,
        results=stored_results,
        computed_from_event_count=recomputed.computed_from_event_count,
    )


def _category_totals(results: tuple[ScoreResult, ...]) -> tuple[ScoreCategoryTotal, ...]:
    """Per-category subtotal, in `ScoringCategory`'s own declaration order — the same order
    `app.domain.scoring.engine._CATEGORY_ORDER` uses, so a reconstructed report's `by_category`
    is ordered exactly as the original's was."""
    totals: dict[ScoringCategory, list[float]] = {}
    for result in results:
        bucket = totals.setdefault(result.category, [0.0, 0.0])
        bucket[0] += result.points_awarded
        bucket[1] += result.max_points
    ordered: list[ScoreCategoryTotal] = []
    for category in ScoringCategory:
        found = totals.get(category)
        if found is not None:
            ordered.append(
                ScoreCategoryTotal(category=category, points_awarded=found[0], max_points=found[1])
            )
    return tuple(ordered)


def _differences(
    stored_results: tuple[ScoreResult, ...] | None, recomputed_results: tuple[ScoreResult, ...]
) -> tuple[RescoreDifference, ...]:
    stored_points_by_rule = (
        {result.rule_id: result.points_awarded for result in stored_results}
        if stored_results is not None
        else {}
    )
    differences: list[RescoreDifference] = []
    for result in recomputed_results:
        stored_points = stored_points_by_rule.get(result.rule_id)
        if stored_points is None or stored_points != result.points_awarded:
            differences.append(
                RescoreDifference(
                    rule_id=result.rule_id,
                    stored_points=stored_points,
                    recomputed_points=result.points_awarded,
                )
            )
    return tuple(differences)

"""`generateReportExplanation` (`openapi.yaml` `POST /api/v1/reports/{session_id}/explanation`,
SPEC §2, §29; D11; R8).

Guard order (DO item 2): session `COMPLETED` + stored scores exist (else `409 REPORT_NOT_READY`,
same as the report itself, R1) → report visibility for this viewer (`app.application.reports.
visibility.report_visibility` — the identical gate `getSessionReport` uses) → an explanation
already stored for `(session_id, audience)` and `regenerate` not set (`409
EXPLANATION_ALREADY_EXISTS`) → the LLM call → store → return.

`GenerateExplanation` is constructed with a `ScoreReportReader` (R8's structural guarantee: not
the real `ScoreRepository`, so this class holds nothing with a `replace_for_session` method on
it — see `backend/tests/invariants/test_explanation_cannot_write_scores.py`). Everything else
(`uow.sessions`, `uow.scenarios`, `uow.report_explanations`) comes through the ordinary
`UnitOfWorkFactory`, which this module never uses to reach `uow.scores` at all.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.clock import Clock
from app.application.ports.id_generator import IdGenerator
from app.application.ports.llm import (
    ChatMessage,
    LLMClient,
    LlmTimeoutError,
    LlmUnavailableError,
)
from app.application.ports.report_explanation_repository import (
    ExplanationAudience,
    StoredReportExplanation,
)
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.reports.explanation.errors import (
    ExplanationAlreadyExistsError,
    ExplanationLLMUnavailableError,
    ReportNotReadyError,
)
from app.application.reports.explanation.ports import ScoreReportReader
from app.application.reports.explanation.prompt import build_messages
from app.application.reports.visibility import report_visibility
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import ScenarioVersionId, SessionId
from app.domain.enums import ScoringCategory, SessionState
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.engine import report_checksum
from app.domain.scoring.results import ScoreCategoryTotal, ScoreReport, ScoreResult

__all__ = ["GenerateExplanation"]


class GenerateExplanation:
    """`generateReportExplanation`."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        scores: ScoreReportReader,
        llm: LLMClient,
        clock: Clock,
        ids: IdGenerator,
        *,
        llm_provider: str,
        max_tokens: int,
        temperature: float,
        timeout_ms: int,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._scores = scores
        self._llm = llm
        self._clock = clock
        self._ids = ids
        self._llm_provider = llm_provider
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._timeout_ms = timeout_ms

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        audience: ExplanationAudience,
        regenerate: bool,
    ) -> StoredReportExplanation:
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not user.is_instructor_or_admin:
                # Same order `getSessionReport` uses: a non-participant is refused before they
                # learn anything about the session's state (D8).
                resolve_participant(session, user)
            if session.state is not SessionState.COMPLETED:
                raise ReportNotReadyError(session_id, session.state)

            stored_results = await self._scores.load_report(session_id)
            if stored_results is None:
                raise ReportNotReadyError(session_id, session.state)

            released = await uow.sessions.get_report_release(session_id) is not None
            report_visibility(session, user, released=released)

            existing = await uow.report_explanations.get(session_id, audience)
            if existing is not None and not regenerate:
                raise ExplanationAlreadyExistsError(session_id, audience)

            document = await uow.scenarios.get_version_document(session.scenario_version_id)
            if document is None:  # pragma: no cover - `simulation_sessions` has a FK to it
                raise RuntimeError(
                    f"scenario version {session.scenario_version_id} no longer exists"
                )
            scenario_version = ScenarioVersion.model_validate(dict(document))
            rule_titles = {rule.rule_id: rule.name_ru for rule in scenario_version.scoring_rules}

            report = _score_report(session_id, session.scenario_version_id, stored_results)
            messages: list[ChatMessage] = build_messages(report, rule_titles, audience)

            request_id = str(self._ids.new())
            try:
                completion = await self._llm.complete(
                    messages,
                    request_id=request_id,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    timeout_ms=self._timeout_ms,
                )
            except (LlmTimeoutError, LlmUnavailableError, TimeoutError) as exc:
                raise ExplanationLLMUnavailableError(session_id, str(exc)) from exc

            text_ru = completion.text.strip()
            if not text_ru:
                raise ExplanationLLMUnavailableError(session_id, "the model returned no text")

            stored = StoredReportExplanation(
                id=self._ids.new(),
                session_id=session_id,
                audience=audience,
                text_ru=text_ru,
                generated_at=self._clock.now(),
                llm_provider=self._llm_provider,
                llm_model=self._llm.model_name,
                score_report_checksum=report_checksum(report),
            )
            await uow.report_explanations.upsert(stored)
            await uow.commit()
        return stored


def _score_report(
    session_id: SessionId, scenario_version_id: ScenarioVersionId, results: tuple[ScoreResult, ...]
) -> ScoreReport:
    """The stored `score_results` reshaped into a `ScoreReport` (R8) — enough of one for
    `build_messages` and `report_checksum`, which is all this module ever does with it.

    `computed_from_event_count` has no stored counterpart (`ScoreRepository.load_report` returns
    only the per-rule rows, HLD §20.7) and is not part of `report_checksum`'s document (SPEC §2 —
    the checksum covers only the numeric results) or of anything `build_messages` reads, so `0`
    here is a documented placeholder, never rendered or hashed.
    """
    total_points = sum(result.points_awarded for result in results)
    total_max_points = sum(result.max_points for result in results)
    by_category = _category_totals(results)
    critical_errors = tuple(result for result in results if result.critical_failure)
    return ScoreReport(
        scenario_version_id=scenario_version_id,
        session_id=session_id,
        total_points=total_points,
        total_max_points=total_max_points,
        by_category=by_category,
        critical_errors=critical_errors,
        results=results,
        computed_from_event_count=0,
    )


def _category_totals(results: tuple[ScoreResult, ...]) -> tuple[ScoreCategoryTotal, ...]:
    """Per-category subtotal, in `ScoringCategory`'s own declaration order."""
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

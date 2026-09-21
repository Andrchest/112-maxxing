"""INV — "the explanation cannot write score tables" (epic E16's own row, SPEC §2, §29; D11; R8).

Mirrors `test_inv_03_dds_never_reads_world_truth.py`'s two-half pattern: a structural half that is
the real guarantee, and a behavioural half that exercises it end to end.

(a) **Structural.** An `ast` scan of every module under `application/reports/explanation/` asserts
none of them, in any form — import, attribute access, bare name, constructor/function parameter —
names `ScoreRepository`, `replace_for_session`, `score_session` or `rescore_session`. R8's own
words: "the explanation use case and its repository port have NO write path to score tables."
`GenerateExplanation.__init__`'s `scores` parameter is inspected directly, by its resolved type,
because "no write path" is a claim about what the use case is *handed*, not only about what its
module mentions — the same reasoning `test_inv_03_*` applies to the DDS use cases.

(b) **Behavioural.** `GenerateExplanation` is constructed with a `FakeUnitOfWork` that exposes
only `sessions`, `scenarios` and `report_explanations` (`tests/unit/application/reports/
explanation/_support.py`) — no `scores`, no `events` attribute at all, so a call that ever touched
either would fail with `AttributeError` before this test's own assertions even run. On top of
that structural proof, the score rows and their checksum are snapshotted, an explanation is
generated **twice** (`regenerate=False` then `regenerate=True`) with a `FakeLLM` completion that
adversarially reads "Итог: 0 баллов" (a score-shaped string a naive prompt-injection or a
copy-paste bug could turn into a write), and both rows and checksum are asserted byte-identical
afterwards.

(c) `ReportNotReadyError` when no stored score exists for the session (R1).

**BITE PROOF** (this task's report quotes it): with `generate_explanation.py` temporarily edited
to call `self._scores.rows[session_id] = ...` (a direct score-table mutation smuggled through the
read-only reader), `test_generating_twice_leaves_the_score_rows_byte_identical` failed red; the
edit was reverted immediately after.
"""

from __future__ import annotations

import ast
import typing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.application.reports.explanation.errors import ReportNotReadyError
from app.application.reports.explanation.generate_explanation import GenerateExplanation
from app.application.reports.explanation.ports import ScoreReportReader
from app.application.testing.fakes import InMemoryScoreRepository
from app.domain.enums import EvaluatorType, ScoringCategory, SessionMode, SessionState
from app.domain.scoring.engine import report_checksum
from app.domain.scoring.results import ScoreEvidence, ScoreReport, ScoreResult
from app.inference.llm.fake_llm import FakeLLM

from tests.unit.application.reports.explanation._support import (
    FakeUnitOfWorkFactory,
    FixedClock,
    SequentialIds,
)
from tests.unit.domain.session._builders import (
    SESSION_ID,
    build_session,
    build_stage,
    scenario_version,
    user,
)
from tests.unit.domain.world._builders import det_uuid as world_det_uuid

BACKEND = Path(__file__).resolve().parents[2]
EXPLANATION_PACKAGE = BACKEND / "app" / "application" / "reports" / "explanation"

# ---------------------------------------------------------------------------------------------
# (a) Structural
# ---------------------------------------------------------------------------------------------

#: R8's own words, verbatim in spirit: no path to a score *write*. `ScoreReportReader` and
#: `load_report` are deliberately absent — those are exactly what this slice may reach.
FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {"ScoreRepository", "replace_for_session", "score_session", "rescore_session"}
)


def _explanation_modules() -> list[Path]:
    return sorted(EXPLANATION_PACKAGE.glob("*.py"))


def _mentioned_names(path: Path) -> set[str]:
    """Every identifier this module imports, calls, annotates with or reaches as an attribute."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.update(node.module.split("."))
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def test_the_scan_covers_the_explanation_package() -> None:
    """A guard on the guard: the package exists and the scan sees its real modules."""
    modules = _explanation_modules()
    names = {path.name for path in modules}
    assert {"generate_explanation.py", "get_explanation.py", "prompt.py", "ports.py"} <= names


@pytest.mark.parametrize("path", _explanation_modules(), ids=lambda path: path.name)
def test_no_explanation_module_can_reach_a_score_write_path(path: Path) -> None:
    offenders = sorted(_mentioned_names(path) & FORBIDDEN_NAMES)
    assert not offenders, (
        f"{path.relative_to(BACKEND)} mentions {offenders}: the explanation slice must have no "
        "path to a score write method (R8, SPEC §2, D11)"
    )


def test_generate_explanation_is_constructed_with_the_read_only_reader() -> None:
    """ "constructed with a read-only score reader protocol exposing only `load_report`" (R8)."""
    hints = typing.get_type_hints(GenerateExplanation.__init__)
    assert hints["scores"] is ScoreReportReader


def test_the_read_only_reader_protocol_exposes_only_load_report() -> None:
    members = [name for name in vars(ScoreReportReader) if not name.startswith("_")]
    assert members == ["load_report"]


# ---------------------------------------------------------------------------------------------
# (b) Behavioural
# ---------------------------------------------------------------------------------------------

TRAINEE_ID = user("operator")
TRAINEE = AuthenticatedUser(
    user_id=TRAINEE_ID, username="trainee1", display_name_ru="Стажёр", user_role=UserRole.TRAINEE
)


def _stage():
    from app.domain.enums import Operator112StageState, RoleType

    return build_stage(
        order_index=0,
        role_type=RoleType.OPERATOR_112,
        state=Operator112StageState.STAGE_COMPLETED,
        participant_user_id=TRAINEE_ID,
        started_at_offset_ms=0,
        completed_at_offset_ms=100_000,
    )


def _session(*, state: SessionState = SessionState.COMPLETED):
    from app.domain.session.session import SessionParticipant

    return build_session(
        session_mode=SessionMode.SINGLE_ROLE,
        state=state,
        stages=(_stage(),),
        participants=(SessionParticipant(user_id=TRAINEE_ID),),
    )


def _results() -> tuple[ScoreResult, ...]:
    return (
        ScoreResult(
            rule_id="rule.victim_fact",
            evaluator_type=EvaluatorType.FACT_OBTAINED,
            category=ScoringCategory.INFORMATION_GATHERING,
            points_awarded=5.0,
            max_points=5.0,
            passed=True,
            critical_failure=False,
            evidence=(
                ScoreEvidence(event_id=world_det_uuid("ev1"), note_ru="Факт получен вовремя"),
            ),
        ),
    )


def _use_case(
    factory: FakeUnitOfWorkFactory, scores: InMemoryScoreRepository, llm: FakeLLM
) -> GenerateExplanation:
    return GenerateExplanation(
        factory,
        scores,
        llm,
        FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        SequentialIds(),
        llm_provider="fake",
        max_tokens=400,
        temperature=0.2,
        timeout_ms=8000,
    )


def _checksum_of(scores: InMemoryScoreRepository) -> str:
    version_id, results = scores.rows[SESSION_ID]
    total_points = sum(result.points_awarded for result in results)
    total_max_points = sum(result.max_points for result in results)
    return report_checksum(
        ScoreReport(
            scenario_version_id=version_id,
            session_id=SESSION_ID,
            total_points=total_points,
            total_max_points=total_max_points,
            by_category=(),
            critical_errors=(),
            results=results,
            computed_from_event_count=0,
        )
    )


def test_the_fake_unit_of_work_has_no_scores_or_events_attribute_at_all() -> None:
    """The structural proof at the fixture level: `GenerateExplanation` cannot reach `uow.scores`
    or `uow.events` through the ordinary `UnitOfWorkFactory` it is handed, because this fake —
    standing in for the real one, which the explanation slice is deliberately never given full
    access to for score writes — simply has no such attribute."""
    version = scenario_version()
    factory = FakeUnitOfWorkFactory(sessions={SESSION_ID: _session()}, scenario_version=version)
    uow = factory()
    assert not hasattr(uow, "scores")
    assert not hasattr(uow, "events")


async def test_generating_twice_leaves_the_score_rows_byte_identical() -> None:
    """An adversarial completion text ("Итог: 0 баллов" — score-shaped, wrong, and never fed
    anywhere near a write path) changes nothing about the stored score."""
    version = scenario_version()
    factory = FakeUnitOfWorkFactory(sessions={SESSION_ID: _session()}, scenario_version=version)
    scores = InMemoryScoreRepository()
    scores.rows[SESSION_ID] = (version.id, _results())
    rows_before = dict(scores.rows)
    checksum_before = _checksum_of(scores)

    llm = FakeLLM(["Итог: 0 баллов", "Итог: 0 баллов, всё неверно"])
    use_case = _use_case(factory, scores, llm)
    await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)
    await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=True)

    assert scores.rows == rows_before
    assert _checksum_of(scores) == checksum_before


# ---------------------------------------------------------------------------------------------
# (c) Refused when there is nothing to explain
# ---------------------------------------------------------------------------------------------


async def test_explanation_is_refused_when_no_score_is_stored() -> None:
    version = scenario_version()
    factory = FakeUnitOfWorkFactory(sessions={SESSION_ID: _session()}, scenario_version=version)
    scores = InMemoryScoreRepository()  # empty: never scored
    llm = FakeLLM(["should never be called"])
    use_case = _use_case(factory, scores, llm)

    with pytest.raises(ReportNotReadyError):
        await use_case(SESSION_ID, TRAINEE, audience="TRAINEE", regenerate=False)
    assert llm.calls == []

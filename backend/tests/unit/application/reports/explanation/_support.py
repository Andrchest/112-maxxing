"""Fakes for the explanation use-case tests (epic E16-B).

`FakeUnitOfWork` exposes exactly what `GenerateExplanation`/`GetExplanation` may touch:
`sessions`, `scenarios` and `report_explanations` — never `scores` (that is the injected,
separately-constructed `ScoreReportReader`, per R8). Any other attribute access raises
`AttributeError`, the same discipline `tests/unit/application/scoring/_support.py` uses.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import UUID, uuid5

from app.application.ports.scenario_repository import StoredScenarioVersion
from app.application.ports.session_repository import ReportRelease
from app.application.testing.fakes import InMemoryReportExplanationRepository
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.scenario.version import ScenarioVersion
from app.domain.session.session import SimulationSession

__all__ = [
    "FakeScenarioRepository",
    "FakeSessionRepository",
    "FakeUnitOfWork",
    "FakeUnitOfWorkFactory",
    "FixedClock",
    "SequentialIds",
]

_NAMESPACE = UUID("00000000-0000-4000-8000-000000000000")


class FakeScenarioRepository:
    """An in-memory `ScenarioRepository`: only the one read `generate_explanation` needs."""

    def __init__(self, versions: Mapping[ScenarioVersionId, ScenarioVersion]) -> None:
        self._versions = dict(versions)

    async def get_version(
        self, scenario_version_id: ScenarioVersionId
    ) -> StoredScenarioVersion | None:
        version = self._versions.get(scenario_version_id)
        if version is None:
            return None
        return StoredScenarioVersion(
            scenario_version_id=version.id,
            scenario_id=version.scenario_id,
            version=version.version,
            content_sha256="fake",
            locked_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def get_version_document(
        self, scenario_version_id: ScenarioVersionId
    ) -> Mapping[str, Any] | None:
        version = self._versions.get(scenario_version_id)
        return None if version is None else version.model_dump(mode="json")


class FakeSessionRepository:
    """An in-memory `SessionRepository`: `.get` and `.get_report_release` only."""

    def __init__(
        self,
        sessions: Mapping[SessionId, SimulationSession],
        *,
        releases: Mapping[SessionId, ReportRelease] | None = None,
    ) -> None:
        self._sessions = dict(sessions)
        self._releases = dict(releases or {})

    async def get(self, session_id: SessionId) -> SimulationSession | None:
        return self._sessions.get(session_id)

    async def get_report_release(self, session_id: SessionId) -> ReportRelease | None:
        return self._releases.get(session_id)

    def release(self, session_id: SessionId, *, released_by_user_id: UserId) -> None:
        """Test helper: mark `session_id` released, exactly as `releaseReportToTrainee` would."""
        self._releases[session_id] = ReportRelease(
            session_id=session_id,
            released_at=datetime(2026, 1, 1, tzinfo=UTC),
            released_by_user_id=released_by_user_id,
        )


class FakeUnitOfWork:
    """A `UnitOfWork` exposing `sessions`, `scenarios` and `report_explanations` only."""

    def __init__(
        self,
        *,
        sessions: FakeSessionRepository,
        scenarios: FakeScenarioRepository,
        report_explanations: InMemoryReportExplanationRepository,
    ) -> None:
        self._sessions = sessions
        self._scenarios = scenarios
        self._report_explanations = report_explanations
        self.committed = False
        self.rolled_back = False

    @property
    def sessions(self) -> FakeSessionRepository:
        return self._sessions

    @property
    def scenarios(self) -> FakeScenarioRepository:
        return self._scenarios

    @property
    def report_explanations(self) -> InMemoryReportExplanationRepository:
        return self._report_explanations

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc is None and not self.committed:
            await self.rollback()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeUnitOfWorkFactory:
    """A `UnitOfWorkFactory` over one shared set of stores, so a write in one `async with` block
    is visible to the next (exactly as two committed real transactions would be)."""

    def __init__(
        self,
        *,
        sessions: Mapping[SessionId, SimulationSession],
        scenario_version: ScenarioVersion,
        releases: Mapping[SessionId, ReportRelease] | None = None,
    ) -> None:
        self.session_repo = FakeSessionRepository(sessions, releases=releases)
        self.scenario_repo = FakeScenarioRepository({scenario_version.id: scenario_version})
        self.explanations = InMemoryReportExplanationRepository()

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(
            sessions=self.session_repo,
            scenarios=self.scenario_repo,
            report_explanations=self.explanations,
        )


class SequentialIds:
    """A deterministic `IdGenerator`: `uuid5`-derived, incrementing, never `uuid4` (D7)."""

    def __init__(self) -> None:
        self._count = 0

    def new(self) -> UUID:
        self._count += 1
        return _det_uuid(f"explanation-id-{self._count}")


def _det_uuid(name: str) -> UUID:
    return uuid5(_NAMESPACE, name)


class FixedClock:
    """A `Clock` fixed at one instant, so `generated_at` is assertable."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def monotonic_ms(self) -> int:
        return 0

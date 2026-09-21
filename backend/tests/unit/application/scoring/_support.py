"""Fakes for the `score_session` / `rescore_session` use-case tests (epic E15-B).

`FakeUnitOfWork` exposes only `events`, `scenarios` and `scores` — the three properties
`compute_report`/`score_session` may touch (CHANGE item 3). Any other property access (`.sessions`,
`.handoffs`, ...) raises `AttributeError`, which is what makes "the use case touches only these
three ports" a property the test suite enforces rather than a comment.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import uuid4

from app.application.ports.scenario_repository import StoredScenarioVersion
from app.application.testing.fakes import InMemoryScoreRepository
from app.domain.common.ids import EventId, ScenarioVersionId, SessionId
from app.domain.enums import SessionState
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.scenario.version import ScenarioVersion

from tests.unit.domain.scoring._event_log_builders import demo_scenario

__all__ = [
    "FakeEventStore",
    "FakeScenarioRepository",
    "FakeSessionRepository",
    "FakeUnitOfWork",
    "FakeUnitOfWorkFactory",
    "StubSession",
]


class FakeEventStore:
    """An in-memory `EventStore`: append allocates `seq_no`, read returns in order."""

    def __init__(self, events: Sequence[SessionEvent] = ()) -> None:
        self.events: list[SessionEvent] = list(events)

    async def append(
        self, session_id: SessionId, events: Sequence[DomainEvent]
    ) -> list[SessionEvent]:
        stored: list[SessionEvent] = []
        for event in events:
            seq_no = len(self.events) + 1
            row = SessionEvent(
                id=EventId(uuid4()),
                session_id=session_id,
                seq_no=seq_no,
                event_type=event.event_type,
                timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
                monotonic_offset_ms=event.monotonic_offset_ms,
                actor_type=event.actor.actor_type,
                actor_id=event.actor.actor_id,
                correlation_id=event.correlation_id,
                payload=dict(event.payload),
            )
            self.events.append(row)
            stored.append(row)
        return stored

    async def read(
        self, session_id: SessionId, after_seq_no: int = 0, limit: int | None = None
    ) -> list[SessionEvent]:
        matching = [
            event
            for event in self.events
            if event.session_id == session_id and event.seq_no > after_seq_no
        ]
        return matching if limit is None else matching[:limit]

    async def last_seq_no(self, session_id: SessionId, event_types: Any = None) -> int:
        matching = [event for event in self.events if event.session_id == session_id]
        return matching[-1].seq_no if matching else 0


class FakeScenarioRepository:
    """An in-memory `ScenarioRepository`: only the two reads `compute_report` needs."""

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


@dataclass
class StubSession:
    """The one field `rescore_session`'s state gate reads — not a real `SimulationSession`."""

    state: SessionState


class FakeSessionRepository:
    """An in-memory `SessionRepository`: only the plain `get` `RescoreSession` needs."""

    def __init__(self, sessions: Mapping[SessionId, StubSession]) -> None:
        self._sessions = dict(sessions)

    async def get(self, session_id: SessionId) -> StubSession | None:
        return self._sessions.get(session_id)


class FakeUnitOfWork:
    """A `UnitOfWork` exposing `events`, `scenarios`, `scores` and (if given) `sessions`.

    `score_session`'s own tests construct one directly with fresh stores (see the module
    docstring: no `sessions` means `hasattr(uow, "sessions")` is `False`). `rescore_session`'s
    tests go through `FakeUnitOfWorkFactory` instead, which shares one set of stores across every
    `async with` block — the same way separate committed transactions share one database.
    """

    def __init__(
        self,
        events: FakeEventStore | Sequence[SessionEvent] = (),
        scenario_version: ScenarioVersion | None = None,
        *,
        scenarios: FakeScenarioRepository | None = None,
        scores: InMemoryScoreRepository | None = None,
        sessions: FakeSessionRepository | None = None,
    ) -> None:
        version = scenario_version if scenario_version is not None else demo_scenario()
        self._event_store = events if isinstance(events, FakeEventStore) else FakeEventStore(events)
        self._scenario_repo = (
            scenarios if scenarios is not None else FakeScenarioRepository({version.id: version})
        )
        self._score_repo = scores if scores is not None else InMemoryScoreRepository()
        self._session_repo = sessions
        self.committed = False
        self.rolled_back = False

    @property
    def events(self) -> FakeEventStore:
        return self._event_store

    @property
    def scenarios(self) -> FakeScenarioRepository:
        return self._scenario_repo

    @property
    def scores(self) -> InMemoryScoreRepository:
        return self._score_repo

    @property
    def sessions(self) -> FakeSessionRepository:
        if self._session_repo is None:
            raise AttributeError("this FakeUnitOfWork was not given a sessions repository")
        return self._session_repo

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
    """A `UnitOfWorkFactory`: every call returns a fresh `FakeUnitOfWork` over the same shared
    stores, so a write committed in one `async with` block is visible to the next — exactly as two
    separate, real committed transactions share one database."""

    def __init__(
        self,
        session_id: SessionId,
        *,
        events: Sequence[SessionEvent] = (),
        scenario_version: ScenarioVersion | None = None,
        session_state: SessionState | None = SessionState.COMPLETED,
    ) -> None:
        version = scenario_version if scenario_version is not None else demo_scenario()
        self.event_store = FakeEventStore(events)
        self.scenario_repo = FakeScenarioRepository({version.id: version})
        self.score_repo = InMemoryScoreRepository()
        sessions = {} if session_state is None else {session_id: StubSession(state=session_state)}
        self.session_repo = FakeSessionRepository(sessions)

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(
            events=self.event_store,
            scenarios=self.scenario_repo,
            scores=self.score_repo,
            sessions=self.session_repo,
        )

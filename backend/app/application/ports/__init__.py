"""Application-layer ports — `typing.Protocol` declarations only (D2).

Every technology-facing capability a use case needs is declared here and implemented in
`app.infrastructure`. Nothing in this package may import sqlalchemy, redis, asyncpg or any other
vendor SDK; `backend/tools/check_imports.py` enforces it.
"""

from __future__ import annotations

from app.application.ports.clock import Clock
from app.application.ports.event_publisher import EventEnvelope, EventPublisher, envelope_of
from app.application.ports.event_store import EventStore
from app.application.ports.scenario_repository import (
    ScenarioRepository,
    StoredScenario,
    StoredScenarioVersion,
)
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory

__all__ = [
    "Clock",
    "EventEnvelope",
    "EventPublisher",
    "EventStore",
    "ScenarioRepository",
    "StoredScenario",
    "StoredScenarioVersion",
    "UnitOfWork",
    "UnitOfWorkFactory",
    "envelope_of",
]

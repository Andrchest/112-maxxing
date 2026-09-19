"""PostgreSQL adapters for the application ports (HLD `20-db-schema.md`, D2, D5).

`mappers` converts between the domain types of `10-domain-model.md` and the ORM rows of
`app.db.models`; `event_store`, `unit_of_work` and `scenario_repository` implement
`app.application.ports`. The domain never imports anything here (D2).
"""

from __future__ import annotations

from app.infrastructure.persistence.event_store import SqlAlchemyEventStore
from app.infrastructure.persistence.scenario_repository import SqlAlchemyScenarioRepository
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork, unit_of_work_factory

__all__ = [
    "SqlAlchemyEventStore",
    "SqlAlchemyScenarioRepository",
    "SqlAlchemyUnitOfWork",
    "unit_of_work_factory",
]

"""Fixtures for the voice slice — a real session, with the two §40.6 side effects observable.

`backend/tests/api/operator/conftest.py` already builds an `ACTIVE` session with a 112 stage and
the `OperatorFlow` helper that drives it over real HTTP; those fixtures are re-exported here rather
than rewritten, so the voice tests exercise exactly the same call the operator tests do.

The one difference is the container: `voice_signals` and `call_state_cache` are in-memory, so a
test can assert *that* `voice:join` was published and *when* — the Redis adapters have their own
tests, and a recorded list is a better assertion than a pub/sub race.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.api.container import Container
from app.application.testing.fakes import (
    FakeInferenceReadiness,
    FakePasswordHasher,
    InMemoryCallStateCache,
    InMemoryEventPublisher,
    InMemoryIdempotencyStore,
    InMemoryVoiceSignals,
)
from app.config.settings import Settings
from app.db.session import create_session_factory
from app.infrastructure.clock import SystemClock
from app.infrastructure.persistence.unit_of_work import unit_of_work_factory
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.operator.conftest import (
    OperatorFlow,
    connected,
    flow,
    idempotency,
    interview,
    ringing,
    uow_factory,
)

pytestmark = pytest.mark.integration

__all__ = [
    "OperatorFlow",
    "connected",
    "container",
    "flow",
    "idempotency",
    "interview",
    "ringing",
    "uow_factory",
    "voice_signals",
]


@pytest.fixture
def voice_signals() -> InMemoryVoiceSignals:
    """§40.6's `voice:join` / `voice:cancel:{session_id}`, recorded instead of published."""
    return InMemoryVoiceSignals()


@pytest.fixture
def call_state_cache() -> InMemoryCallStateCache:
    """§40.6's `session:{id}:call_state`, in a dict — `forget()` is a lapsed TTL or a FLUSHALL."""
    return InMemoryCallStateCache()


@pytest.fixture
def container(
    api_settings: Settings,
    migrated_engine: AsyncEngine,
    redis_client: Redis,
    publisher: InMemoryEventPublisher,
    hasher: FakePasswordHasher,
    inference: FakeInferenceReadiness,
    idempotency: InMemoryIdempotencyStore,
    voice_signals: InMemoryVoiceSignals,
    call_state_cache: InMemoryCallStateCache,
) -> Container:
    """The operator container plus the two observable §40.6 side effects."""
    session_factory = create_session_factory(migrated_engine)
    return Container(
        api_settings,
        engine=migrated_engine,
        session_factory=session_factory,
        redis=redis_client,
        publisher=publisher,
        unit_of_work=unit_of_work_factory(session_factory, SystemClock(), publisher),
        hasher=hasher,
        inference=inference,
        idempotency=idempotency,
        voice_signals=voice_signals,
        call_state_cache=call_state_cache,
        owns_engine=False,
        owns_redis=False,
    )


def problem(response: Any) -> dict[str, Any]:
    """The RFC 7807 body of a refusal, asserted on by code rather than by prose."""
    body: dict[str, Any] = response.json()
    return body

"""Fixtures for the Operator 112 API tests — a real session, driven over real HTTP.

`backend/tests/api/conftest.py` already gives a migrated database, a real Redis, the production
container and an `httpx.AsyncClient` over the ASGI app with no port bound. This module adds the
one thing those tests need on top: a session that is `ACTIVE` with a 112 stage, plus the two
things a *trainee* cannot do and the simulation must.

Those two are deliberate, not conveniences:

* `flow.advance_call_flow()` runs `app.application.operator.call_flow`, which is what fires the
  `SIMULATION`-only `ring` and `begin_interview` triggers (§10.8). There is no endpoint for
  either and there must not be — a trainee who could fire `ring` would be starting their own
  call. The runner normally drives it; `SIM_RUNNER_ENABLED=false` in these tests, so the test
  drives it instead and no background task can outlive a test;
* `flow.append_asr_final(...)` appends an `ASR_FINAL` through the event store exactly as the
  voice-agent will (D9, §20.8). It is what makes `guard_first_finalized_turn` true, and it is
  also the lever INV 4 pulls: the ASR path writes *events*, never the card.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.api.container import Container
from app.application.testing.fakes import (
    FakeInferenceReadiness,
    FakePasswordHasher,
    InMemoryEventPublisher,
    InMemoryIdempotencyStore,
)
from app.config.settings import Settings
from app.db.session import create_session_factory
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId, UserId
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.infrastructure.clock import SystemClock
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork, unit_of_work_factory
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth, create_demo_session, participant

pytestmark = pytest.mark.integration


@pytest.fixture
def idempotency() -> InMemoryIdempotencyStore:
    """The `IdempotencyStore` of §40.6, in memory.

    Real Redis would work; a dict makes "the key expired" a one-line `forget()` instead of a
    300-second wait, and the Redis adapter has its own test.
    """
    return InMemoryIdempotencyStore()


@pytest.fixture
def container(
    api_settings: Settings,
    migrated_engine: AsyncEngine,
    redis_client: Redis,
    publisher: InMemoryEventPublisher,
    hasher: FakePasswordHasher,
    inference: FakeInferenceReadiness,
    idempotency: InMemoryIdempotencyStore,
) -> Container:
    """`tests.api.conftest.container` plus the in-memory idempotency store (see above)."""
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
        owns_engine=False,
        owns_redis=False,
    )


@dataclass
class OperatorFlow:
    """One started session with a 112 stage, and the levers a trainee does not have."""

    client: httpx.AsyncClient
    container: Container
    session_id: UUID
    operator_token: str
    dds_token: str
    instructor_token: str
    operator_user_id: UserId
    dds_user_id: UserId

    # -- HTTP ----------------------------------------------------------------------------------

    def url(self, suffix: str) -> str:
        """`/api/v1/sessions/{session_id}{suffix}`."""
        return f"/api/v1/sessions/{self.session_id}{suffix}"

    async def post(
        self, suffix: str, *, token: str | None = None, json: Any = None
    ) -> httpx.Response:
        """POST as the operator trainee unless another token is given."""
        return await self.client.post(
            self.url(suffix), headers=auth(token or self.operator_token), json=json
        )

    async def put(
        self, suffix: str, *, token: str | None = None, json: Any = None
    ) -> httpx.Response:
        """PUT as the operator trainee unless another token is given."""
        return await self.client.put(
            self.url(suffix), headers=auth(token or self.operator_token), json=json
        )

    async def get(
        self, suffix: str, *, token: str | None = None, params: Any = None
    ) -> httpx.Response:
        """GET as the operator trainee unless another token is given."""
        return await self.client.get(
            self.url(suffix), headers=auth(token or self.operator_token), params=params
        )

    # -- commands ------------------------------------------------------------------------------

    async def set_field(self, field_path: str, new_value: Any, **extra: Any) -> httpx.Response:
        """`setCardField`."""
        body: dict[str, Any] = {"field_path": field_path, "new_value": new_value}
        body.update(extra)
        return await self.put("/operator/card/field", json=body)

    async def select(self, service_type: str) -> httpx.Response:
        """`selectRecipientService`."""
        return await self.post("/operator/services/select", json={"service_type": service_type})

    async def deselect(self, service_type: str) -> httpx.Response:
        """`deselectRecipientService`."""
        return await self.post("/operator/services/deselect", json={"service_type": service_type})

    async def snapshot(self, *, token: str | None = None) -> httpx.Response:
        """`getSessionSnapshot`."""
        return await self.get("/snapshot", token=token)

    # -- what only the simulation may do -------------------------------------------------------

    async def advance_call_flow(self) -> bool:
        """Fire whichever of `ring` / `begin_interview` is due (§10.8, `SIMULATION` actor)."""
        return await self.container.advance_call_flow()(SessionId(self.session_id))

    async def append_asr(self, event_type: EventType, text: str, turn_index: int = 0) -> None:
        """Append one ASR event through the event store, as the voice-agent will (D9, §20.8).

        The payload is the §10.13 catalog's, and the actor is `MODEL` — which the database's own
        CHECK on `incident_card_revisions.actor_type` would reject outright, were anything in the
        ASR path ever to try to write a card revision (SPEC §42 test 4).
        """
        payload: dict[str, Any] = {
            "call_id": str(uuid4()),
            "turn_index": turn_index,
            "text": text,
            "start_ms": 0,
            "end_ms": 1000,
            "asr_provider": "test",
            "asr_model": "test-asr",
        }
        if event_type is EventType.ASR_FINAL:
            payload["transcript_segment_id"] = str(uuid4())
            payload["audio_segment_id"] = None
            payload["confidence"] = 0.99
        async with self.container.unit_of_work() as uow:
            await uow.events.append(
                SessionId(self.session_id),
                [
                    DomainEvent(
                        event_type=event_type,
                        actor=ActorRef(actor_type=ActorType.MODEL),
                        monotonic_offset_ms=1000 + turn_index,
                        payload=payload,
                    )
                ],
            )
            await uow.commit()

    # -- assertions' raw material ---------------------------------------------------------------

    async def event_types(self) -> list[str]:
        """Every event type in the session log, in `seq_no` order."""
        async with self.container.unit_of_work() as uow:
            events = await uow.events.read(SessionId(self.session_id))
            await uow.commit()
        return [event.event_type.value for event in events]


async def _start_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: Any,
) -> UUID:
    """`createSession` (112 -> DDS, one trainee per stage) then `startSession`."""
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [
            participant(users["trainee1"], "OPERATOR_112"),
            participant(users["trainee2"], "DDS"),
        ],
    )
    session_id = UUID(detail["id"])
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "ACTIVE"
    return session_id


@pytest.fixture
async def flow(
    client: httpx.AsyncClient,
    container: Container,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: Any,
) -> AsyncIterator[OperatorFlow]:
    """An `ACTIVE` session whose first stage is `OPERATOR_112`, played by `trainee1`."""
    session_id = await _start_session(client, tokens, users, demo_version_id)
    yield OperatorFlow(
        client=client,
        container=container,
        session_id=session_id,
        operator_token=tokens["trainee1"],
        dds_token=tokens["trainee2"],
        instructor_token=tokens["instructor1"],
        operator_user_id=users["trainee1"],
        dds_user_id=users["trainee2"],
    )


@pytest.fixture
async def ringing(flow: OperatorFlow) -> OperatorFlow:
    """`flow`, advanced to `RINGING` by the simulation's `ring` trigger."""
    assert await flow.advance_call_flow() is True
    return flow


@pytest.fixture
async def connected(ringing: OperatorFlow) -> OperatorFlow:
    """`ringing`, with the call answered — stage state `CONNECTED`."""
    response = await ringing.post("/operator/call/answer")
    assert response.status_code == 200, response.text
    return ringing


@pytest.fixture
async def interview(connected: OperatorFlow) -> OperatorFlow:
    """`connected`, with one `ASR_FINAL` appended and `begin_interview` fired — `INTERVIEW`."""
    await connected.append_asr(EventType.ASR_FINAL, "Горит квартира на улице Ленина, дом 5")
    assert await connected.advance_call_flow() is True
    return connected


@pytest.fixture
def uow_factory(container: Container) -> Callable[[], SqlAlchemyUnitOfWork]:
    """The container's Unit of Work factory, for tests that read the tables directly."""

    def make() -> SqlAlchemyUnitOfWork:
        unit = container.unit_of_work()
        assert isinstance(unit, SqlAlchemyUnitOfWork)
        return unit

    return make

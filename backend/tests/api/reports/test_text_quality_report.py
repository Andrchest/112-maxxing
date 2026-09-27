"""`getSessionReport`'s `text_quality` section over real HTTP (I4 E35, HLD 71 §71.12, D35).

The one property the design rests on: **the checker's presence or absence cannot move the score
or the checksum** — `text_quality` is built after both are already fixed
(`assemble_report.GetSessionReport.__call__`). This suite proves it end to end, against the exact
container two identical requests would otherwise share: same database, same stored results, one
with the real `FileTextChecker` wired (the default), one with it forced to `None`.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from app.api.container import Container
from app.api.main import create_app
from app.application.testing.fakes import (
    FakeClock,
    FakeInferenceReadiness,
    FakePasswordHasher,
    InMemoryEventPublisher,
    InMemoryIdempotencyStore,
)
from app.config.settings import Settings
from app.db.session import create_session_factory
from app.infrastructure.persistence.unit_of_work import unit_of_work_factory
from app.infrastructure.reference.text_checker import DEFAULT_LEXICON_DIR, DEFAULT_STREETS_DIR
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.conftest import auth
from tests.api.reports.conftest import OperatorFlow, report

pytestmark = pytest.mark.integration


async def _checkerless_client(
    *,
    api_settings: Settings,
    migrated_engine: AsyncEngine,
    redis_client: Redis,
    publisher: InMemoryEventPublisher,
    hasher: FakePasswordHasher,
    inference: FakeInferenceReadiness,
    idempotency: InMemoryIdempotencyStore,
    clock: FakeClock,
) -> AsyncClient:
    """A second, otherwise identical `Container` over the *same* database and Redis, with
    `text_checker` forced to `None` — the absent-data path, without touching a single file."""
    session_factory = create_session_factory(migrated_engine)
    container = Container(
        api_settings,
        engine=migrated_engine,
        session_factory=session_factory,
        redis=redis_client,
        publisher=publisher,
        clock=clock,
        unit_of_work=unit_of_work_factory(session_factory, clock, publisher),
        hasher=hasher,
        inference=inference,
        idempotency=idempotency,
        owns_engine=False,
        owns_redis=False,
    )
    # `text_checker=None` at construction is indistinguishable from "not given" (the container
    # would just load the real data itself, same as the default `Container`) — the absent-data
    # path is forced by overriding the already-built attribute, not the constructor argument.
    container.text_checker = None
    transport = ASGITransport(app=create_app(container))
    return AsyncClient(transport=transport, base_url="http://api")


async def test_text_quality_is_available_by_default_and_unavailable_without_a_checker(
    completed: OperatorFlow,
    api_settings: Settings,
    migrated_engine: AsyncEngine,
    redis_client: Redis,
    publisher: InMemoryEventPublisher,
    hasher: FakePasswordHasher,
    inference: FakeInferenceReadiness,
    idempotency: InMemoryIdempotencyStore,
    clock: FakeClock,
) -> None:
    with_checker = await report(completed)
    assert with_checker.status_code == 200, with_checker.text
    with_body: dict[str, Any] = with_checker.json()

    async with await _checkerless_client(
        api_settings=api_settings,
        migrated_engine=migrated_engine,
        redis_client=redis_client,
        publisher=publisher,
        hasher=hasher,
        inference=inference,
        idempotency=idempotency,
        clock=clock,
    ) as checkerless:
        without_checker = await checkerless.get(
            f"/api/v1/reports/{completed.session_id}",
            headers=auth(completed.instructor_token),
        )
    assert without_checker.status_code == 200, without_checker.text
    without_body: dict[str, Any] = without_checker.json()

    # §71.12's own acceptance item: the score and the checksum never move.
    assert with_body["score_report"] == without_body["score_report"]
    assert with_body["score_report"]["checksum"]
    assert with_body["score_report"]["checksum"] == without_body["score_report"]["checksum"]

    # The one thing that *does* differ: `text_quality.available`.
    assert with_body["text_quality"]["available"] is True
    assert without_body["text_quality"]["available"] is False
    assert without_body["text_quality"]["fields"] == []
    assert without_body["text_quality"]["dictionary_sha256"] is None
    assert without_body["text_quality"]["street_list_sha256"] is None
    assert without_body["text_quality"]["unavailable_message_ru"] == (
        "Проверка недоступна: словарь/справочник не установлен"
    )

    # §71.12's own acceptance item: the data sha is recorded, and it is the packaged data's own.
    expected_dictionary = hashlib.sha256(
        (DEFAULT_LEXICON_DIR / "ru_RU.aff").read_bytes()
        + (DEFAULT_LEXICON_DIR / "ru_RU.dic").read_bytes()
    ).hexdigest()
    expected_streets = hashlib.sha256(
        (DEFAULT_STREETS_DIR / "osm_moscow_street_names.txt").read_bytes()
        + (DEFAULT_STREETS_DIR / "kladr_moscow_street_names.txt").read_bytes()
    ).hexdigest()
    assert with_body["text_quality"]["dictionary_sha256"] == expected_dictionary
    assert with_body["text_quality"]["street_list_sha256"] == expected_streets

    # The demo card's `address.street` (`tests/api/handoff/conftest.py`'s `CARD_ENTRIES`) is
    # checked, and street-only fields carry a lookup — the description/comment fields do not.
    fields_by_source = {field["source"]: field for field in with_body["text_quality"]["fields"]}
    assert "ADDRESS_STREET" in fields_by_source
    assert fields_by_source["ADDRESS_STREET"]["street"] is not None
    for source, field in fields_by_source.items():
        if source != "ADDRESS_STREET":
            assert field["street"] is None

"""INV 9 — "Scoring is reproducible without an LLM" (SPEC §42 item 9), the integration half.

`backend/tests/invariants/test_inv_09_scoring_reproducible_without_llm.py` (E15-A) proves the pure
half: `score()` called twice over the same `(ScenarioVersion, SessionEvents)` produces byte-
identical reports. This file proves the machine-checkable, over-the-wire form `openapi.yaml`
actually ships: `rescoreSession`'s `identical_to_stored` flag, through the real HTTP endpoint and
real PostgreSQL, against the full 112 -> DDS cycle `test_full_cycle.py` already drives to
`SESSION_COMPLETED` (CHANGE item 7).

Three things are asserted, in one flow:

1. closing the incident persists `score_results` rows and appends one `SCORING_RULE_EVALUATED`
   per demo-scenario rule (epic E15-B's own wiring, already covered by `test_full_cycle.py` — reads
   here as the E2E happy-path baseline `rescoreSession` is then checked against);
2. `rescoreSession` (`persist: false`, the default) against the untouched store answers
   `identical_to_stored: true`, `differences: []`;
3. one stored `points_awarded` is tampered with **directly in the database** — the scenario R8's
   checksum exists to catch — and `rescoreSession` answers `identical_to_stored: false` with that
   rule in `differences`; `persist: true` then repairs the row, and a second, untampered rescore is
   `identical_to_stored: true` again.

The API fixtures live in `tests/api/**/conftest.py` and are re-exported here by name, exactly as
`test_inv_03_dds_never_reads_world_truth.py` does: `pytest_plugins` cannot register a module that
is already loaded as a real conftest. `resolved` is imported directly from `test_full_cycle.py`
itself — the same fixture that test drives its own closure assertions with.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from app.domain.common.ids import SessionId

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------------------------
# Fixtures, re-exported by name (see the module docstring)
# ---------------------------------------------------------------------------------------------

from tests.api import conftest as _api_fixtures  # noqa: E402
from tests.api.dds import conftest as _dds_fixtures  # noqa: E402
from tests.api.dds.test_full_cycle import resolved as resolved  # noqa: E402
from tests.api.handoff import conftest as _handoff_fixtures  # noqa: E402
from tests.api.operator import conftest as _operator_fixtures  # noqa: E402

client = _api_fixtures.client
clean_database = _api_fixtures.clean_database
tokens = _api_fixtures.tokens
users = _api_fixtures.users
hasher = _api_fixtures.hasher
inference = _api_fixtures.inference
publisher = _api_fixtures.publisher
redis_client = _api_fixtures.redis_client
api_settings = _api_fixtures.api_settings
demo_version_id = _api_fixtures.demo_version_id
unit_of_work = _api_fixtures.unit_of_work

flow = _operator_fixtures.flow
ringing = _operator_fixtures.ringing
connected = _operator_fixtures.connected
interview = _operator_fixtures.interview
uow_factory = _operator_fixtures.uow_factory

clock = _handoff_fixtures.clock
container = _handoff_fixtures.container
idempotency = _handoff_fixtures.idempotency
prepared = _handoff_fixtures.prepared
handed_off = _handoff_fixtures.handed_off
in_transition = _handoff_fixtures.in_transition
dds_active = _handoff_fixtures.dds_active

OperatorFlow = _handoff_fixtures.OperatorFlow

auth = _api_fixtures.auth
dds_post = _dds_fixtures.dds_post
events_of = _dds_fixtures.events_of
event_types = _dds_fixtures.event_types

RULE_COUNT = 10
"""The demo scenario's own `scoring_rules` count (`scenarios/examples/apartment-fire/v1.yaml`)."""


async def _rescore(
    client: Any, session_id: UUID, token: str, *, persist: bool = False
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/reports/{session_id}/rescore",
        headers=auth(token),
        json={"persist": persist},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _close(resolved: OperatorFlow) -> None:
    response = await dds_post(resolved, "/dds/close", {"closure_reason": "RESOLVED"})
    assert response.status_code == 200, response.text


async def test_closing_persists_score_rows_and_scoring_events(
    resolved: OperatorFlow, uow_factory: Callable[[], Any]
) -> None:
    """The E15-B baseline: `score_results` rows and `SCORING_RULE_EVALUATED` events both exist."""
    await _close(resolved)

    scoring_events = await events_of(resolved, "SCORING_RULE_EVALUATED")
    assert len(scoring_events) == RULE_COUNT

    async with uow_factory() as uow:
        stored = await uow.scores.load_report(SessionId(resolved.session_id))
        await uow.commit()
    assert stored is not None
    assert len(stored) == RULE_COUNT


async def test_rescore_of_an_untampered_session_is_identical(
    resolved: OperatorFlow,
) -> None:
    await _close(resolved)

    outcome = await _rescore(resolved.client, resolved.session_id, resolved.instructor_token)

    assert outcome["identical_to_stored"] is True
    assert outcome["stored_checksum"] == outcome["recomputed_checksum"]
    assert outcome["differences"] == []
    assert outcome["persisted"] is False


async def test_a_trainee_may_not_rescore(resolved: OperatorFlow) -> None:
    await _close(resolved)

    response = await resolved.client.post(
        f"/api/v1/reports/{resolved.session_id}/rescore",
        headers=auth(resolved.operator_token),
        json={"persist": False},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_rescore_before_completion_is_report_not_ready(
    dds_active: OperatorFlow,
) -> None:
    response = await dds_active.client.post(
        f"/api/v1/reports/{dds_active.session_id}/rescore",
        headers=auth(dds_active.instructor_token),
        json={"persist": False},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "REPORT_NOT_READY"


async def test_a_tampered_row_is_reported_and_persist_repairs_it(
    resolved: OperatorFlow, uow_factory: Callable[[], Any], migrated_engine: Any
) -> None:
    await _close(resolved)

    original = await _rescore(resolved.client, resolved.session_id, resolved.instructor_token)
    assert original["identical_to_stored"] is True
    some_rule = original["recomputed"]["results"][0]

    async with migrated_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "UPDATE score_results SET points_awarded = points_awarded + 999"
                " WHERE session_id = :session_id AND rule_id = :rule_id"
            ),
            {"session_id": resolved.session_id, "rule_id": some_rule["rule_id"]},
        )

    tampered = await _rescore(resolved.client, resolved.session_id, resolved.instructor_token)
    assert tampered["identical_to_stored"] is False
    assert tampered["stored_checksum"] != tampered["recomputed_checksum"]
    difference = next(d for d in tampered["differences"] if d["rule_id"] == some_rule["rule_id"])
    assert difference["stored_points"] == some_rule["points_awarded"] + 999
    assert difference["recomputed_points"] == some_rule["points_awarded"]
    assert tampered["persisted"] is False

    repaired = await _rescore(
        resolved.client, resolved.session_id, resolved.instructor_token, persist=True
    )
    assert repaired["identical_to_stored"] is False  # compared against the still-tampered store
    assert repaired["persisted"] is True

    again = await _rescore(resolved.client, resolved.session_id, resolved.instructor_token)
    assert again["identical_to_stored"] is True
    assert again["differences"] == []

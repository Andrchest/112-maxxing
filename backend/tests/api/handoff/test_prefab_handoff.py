"""The DDS-only chain's prefab handoff (D6, §30.5, §10.10) — materialised at stage start.

A `role_chain` of `[DDS]` has no 112 stage, so the scenario's `expected_response.prefab_handoff`
is what the DDS trainee receives. Two halves:

* **absent prefab ⇒ the session never exists** — `409 PREFAB_HANDOFF_REQUIRED` at *creation*
  (already the domain factory's behaviour; asserted here over HTTP so E9 cannot regress it);
* **present prefab ⇒ the work item is there the moment the session starts** — a
  `HandoffSnapshot`, one `DDSAssignment` leg per recipient service, one `HANDOFF_RECEIVED` per
  leg, and a `SessionSnapshot.work_item` the trainee can act on. No `HANDOFF_CREATED`: §10.13
  types that event `TRAINEE`-only and no trainee made this handoff.

The demo's prefab is deliberately imperfect — `address.floor: 5` is the *caller's* wrong floor —
which is the point: the prefab is scenario data, never world truth (rule R14 checks it against
`CARD_FIELDS` and against nothing else).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from app.application.handoff.prefab_handoff import SERVICES_FIELD_PATH
from app.application.operator.select_service import (
    SERVICES_FIELD_PATH as OPERATOR_SERVICES_FIELD_PATH,
)
from app.application.scenarios.import_scenarios import canonical_content, content_digest
from app.domain.common.ids import ScenarioId, ScenarioVersionId, SessionId, UserId
from app.domain.scenario.version import ScenarioVersion
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.conftest import auth, participant
from tests.fixtures.scenarios import demo_document

pytestmark = pytest.mark.integration


def test_the_recipient_services_path_is_the_operator_s() -> None:
    """`prefab_handoff` spells the constant out to avoid an import cycle; it must not drift."""
    assert SERVICES_FIELD_PATH == OPERATOR_SERVICES_FIELD_PATH


async def test_a_dds_only_scenario_without_a_prefab_cannot_start_a_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    unit_of_work: Any,
) -> None:
    """D6: `409 PREFAB_HANDOFF_REQUIRED` at creation — there is nothing for DDS to receive."""
    document: dict[str, Any] = copy.deepcopy(demo_document())
    document["id"] = str(uuid4())
    document["scenario_id"] = str(uuid4())
    document["role_chain"] = ["DDS"]
    document["expected_response"].pop("prefab_handoff", None)
    version = ScenarioVersion(**document)
    content = canonical_content(version)
    async with unit_of_work() as uow:
        stored = await uow.scenarios.find_scenario_by_slug("dds-only-no-prefab")
        if stored is None:
            await uow.scenarios.add_scenario(
                ScenarioId(UUID(document["scenario_id"])), "dds-only-no-prefab", version.title
            )
            await uow.scenarios.add_version(version, content, content_digest(content))
            version_id: ScenarioVersionId = version.id
        else:
            found = await uow.scenarios.find_version(stored.scenario_id, 1)
            assert found is not None
            version_id = found.scenario_version_id
        await uow.commit()

    response = await client.post(
        "/api/v1/sessions",
        headers=auth(tokens["instructor1"]),
        json={
            "scenario_version_id": str(version_id),
            "session_mode": "SINGLE_ROLE",
            "participants": [participant(users["trainee2"], "DDS")],
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PREFAB_HANDOFF_REQUIRED"


async def test_starting_a_dds_only_session_materialises_the_prefab_handoff(
    dds_only_session: UUID,
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """One snapshot, one leg per recipient service, one `HANDOFF_RECEIVED` each — no
    `HANDOFF_CREATED`."""
    async with uow_factory() as uow:
        events = await uow.events.read(SessionId(dds_only_session))
        snapshots = [
            dict(row._mapping)
            for row in (await uow.session.execute(sa.text("SELECT * FROM handoff_snapshots"))).all()
        ]
        legs = [
            dict(row._mapping)
            for row in (
                await uow.session.execute(
                    sa.text(
                        "SELECT a.* FROM dds_assignments a"
                        " JOIN role_stages s ON s.id = a.role_stage_id"
                        " WHERE s.session_id = :session_id"
                    ),
                    {"session_id": dds_only_session},
                )
            ).all()
        ]
        await uow.commit()

    types = [event.event_type.value for event in events]
    assert types[:2] == ["SESSION_CREATED", "SESSION_STARTED"]
    assert "HANDOFF_CREATED" not in types, "no trainee created this handoff (§10.13)"
    assert types.count("HANDOFF_RECEIVED") == 2
    assert types.index("ROLE_STAGE_STARTED") < types.index("HANDOFF_RECEIVED"), (
        "the DDS stage is started before it is handed anything"
    )

    received = [event for event in events if event.event_type.value == "HANDOFF_RECEIVED"]
    assert {event.actor_type.value for event in received} == {"SIMULATION"}
    assert {event.payload["service_type"] for event in received} == {"FIRE_RESCUE", "AMBULANCE"}

    assert len(snapshots) == 1
    assert snapshots[0]["card_values"]["address.house"] == "27"  # the prefab's own value
    assert len(legs) == 2
    assert {leg["state"] for leg in legs} == {"RECEIVED"}
    assert {str(leg["snapshot_id"]) for leg in legs} == {str(snapshots[0]["id"])}


async def test_the_dds_trainee_sees_the_prefab_work_item_immediately(
    client: httpx.AsyncClient, tokens: dict[str, str], dds_only_session: UUID
) -> None:
    """`SessionSnapshot.work_item` is filled at stage start; `card` never is (D3)."""
    response = await client.get(
        f"/api/v1/sessions/{dds_only_session}/snapshot", headers=auth(tokens["trainee2"])
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active_role_type"] == "DDS"
    assert body["stage_state"] == "RECEIVED"
    assert body["card"] is None, "a DDS viewer never receives the live OperatorCard (D3)"

    work_item = body["work_item"]
    assert work_item is not None
    assert work_item["state"] == "RECEIVED"
    assert work_item["recipient_services"] == ["FIRE_RESCUE", "AMBULANCE"]
    assert work_item["service_type"] == "FIRE_RESCUE"
    assert work_item["card_values"]["address.floor"] == 5, "the caller's wrong floor, verbatim"
    assert work_item["selected_resource_ids"] == []
    assert work_item["dispatched_at_offset_ms"] is None


async def test_the_prefab_card_is_written_by_the_instructor_and_frozen_from_there(
    dds_only_session: UUID, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """The snapshot points at a real `incident_card_revisions` row, authored by a real account."""
    async with uow_factory() as uow:
        revisions = [
            dict(row._mapping)
            for row in (
                await uow.session.execute(
                    sa.text("SELECT * FROM incident_card_revisions ORDER BY revision_no")
                )
            ).all()
        ]
        snapshot = dict(
            (await uow.session.execute(sa.text("SELECT * FROM handoff_snapshots"))).one()._mapping
        )
        await uow.commit()

    assert revisions, "the prefab writes the card it freezes"
    assert {revision["actor_type"] for revision in revisions} == {"INSTRUCTOR"}
    assert str(snapshot["card_revision_id"]) == str(revisions[-1]["id"])
    assert snapshot["recipient_services"] == ["FIRE_RESCUE", "AMBULANCE"]
    assert json.loads(json.dumps(snapshot["card_values"]))[SERVICES_FIELD_PATH] == [
        "FIRE_RESCUE",
        "AMBULANCE",
    ]

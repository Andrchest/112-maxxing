"""`createHandoff` over real HTTP — SPEC §10's six steps, and what must not happen (E9).

The frozen snapshot is the whole point of the operation, so the assertions are about identity and
immutability rather than about happy-path shape alone: the events in `x-emits` order, one
`HANDOFF_CREATED` however many services were chosen, one `HANDOFF_RECEIVED` per leg, and a
snapshot whose bytes and `content_sha256` do not move when the card is edited afterwards.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from app.domain.common.ids import SessionId
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api.handoff.conftest import OperatorFlow, fill_card, prepare_handoff, read_assignments

pytestmark = pytest.mark.integration


async def _snapshot_row(uow_factory: Callable[[], SqlAlchemyUnitOfWork]) -> dict[str, Any]:
    async with uow_factory() as uow:
        result = await uow.session.execute(sa.text("SELECT * FROM handoff_snapshots"))
        rows = [dict(row._mapping) for row in result.all()]
        await uow.commit()
    assert len(rows) == 1, f"expected exactly one handoff snapshot, found {len(rows)}"
    return rows[0]


async def test_the_handoff_answers_with_the_snapshot_and_its_assignment_ids(
    prepared: OperatorFlow,
) -> None:
    """`201 HandoffCreatedView`: the frozen snapshot, one assignment id per recipient service."""
    response = await prepared.post("/operator/handoff", json={})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["stage_state"] == "HANDED_OFF"
    assert body["session_state"] == "ACTIVE"
    assert body["snapshot"]["recipient_services"] == ["FIRE_RESCUE", "AMBULANCE"]
    assert body["snapshot"]["card_values"]["address.house"] == "72"
    assert len(body["assignment_ids"]) == 2
    assert len(set(body["assignment_ids"])) == 2


async def test_the_events_are_exactly_the_x_emits_list_in_order(prepared: OperatorFlow) -> None:
    """`x-emits: [HANDOFF_CREATED, STAGE_STATE_CHANGED, HANDOFF_RECEIVED]`, fanned out N-fold.

    One `HANDOFF_CREATED` for two recipient services: one trainee action is one trainee event,
    whatever the operator ticked (E9 analyst R5). Only `HANDOFF_RECEIVED` is per leg.
    """
    before = await prepared.event_types()
    assert (await prepared.post("/operator/handoff", json={})).status_code == 201

    new = (await prepared.event_types())[len(before) :]
    assert new == [
        "HANDOFF_CREATED",
        "STAGE_STATE_CHANGED",
        "HANDOFF_RECEIVED",
        "HANDOFF_RECEIVED",
        # I3 E4a (HLD 70 §70.4.6): the card is handed off — REGISTERED → WORKED, one SIMULATION
        # event after the command's own, in the same Unit of Work (flush-before-append).
        "DDS_CARD_STATUS_CHANGED",
    ]


async def test_handoff_received_maps_each_leg_to_its_service(
    prepared: OperatorFlow, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """The N `HANDOFF_RECEIVED` events are the log's only `assignment -> service` map (D5)."""
    response = await prepared.post("/operator/handoff", json={})
    assert response.status_code == 201, response.text

    async with uow_factory() as uow:
        result = await uow.session.execute(
            sa.text(
                "SELECT payload, actor_type FROM session_events "
                "WHERE event_type = 'HANDOFF_RECEIVED' ORDER BY seq_no"
            )
        )
        rows = [dict(row._mapping) for row in result.all()]
        await uow.commit()

    assert [row["actor_type"] for row in rows] == ["SIMULATION", "SIMULATION"]
    assert [row["payload"]["service_type"] for row in rows] == ["FIRE_RESCUE", "AMBULANCE"]

    legs = await read_assignments(uow_factory, prepared.session_id)
    assert {leg["service_type"] for leg in legs} == {"FIRE_RESCUE", "AMBULANCE"}
    assert {str(leg["id"]) for leg in legs} == {row["payload"]["assignment_id"] for row in rows}
    assert {leg["state"] for leg in legs} == {"RECEIVED"}


async def test_every_leg_points_at_the_dds_stage_and_the_one_snapshot(
    prepared: OperatorFlow, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """One work item, N legs: same `role_stage_id`, same `snapshot_id`, different services."""
    assert (await prepared.post("/operator/handoff", json={})).status_code == 201

    legs = await read_assignments(uow_factory, prepared.session_id)
    assert len({leg["role_stage_id"] for leg in legs}) == 1
    assert len({leg["snapshot_id"] for leg in legs}) == 1
    assert len({leg["service_type"] for leg in legs}) == 2

    snapshot = await _snapshot_row(uow_factory)
    assert str(snapshot["id"]) == str(legs[0]["snapshot_id"])
    assert str(snapshot["incident_id"]) == str(legs[0]["incident_id"])


async def test_the_optional_comment_becomes_a_card_field_before_the_freeze(
    prepared: OperatorFlow,
) -> None:
    """The comment is "part of the snapshot rather than a side channel around it" (openapi)."""
    before = await prepared.event_types()
    response = await prepared.post(
        "/operator/handoff", json={"comment_ru": "Сильное задымление, подъезд 3"}
    )
    assert response.status_code == 201, response.text

    new = (await prepared.event_types())[len(before) :]
    assert new[0] == "CARD_FIELD_CHANGED", "the comment is written before anything is frozen"
    assert new[1:] == [
        "HANDOFF_CREATED",
        "STAGE_STATE_CHANGED",
        "HANDOFF_RECEIVED",
        "HANDOFF_RECEIVED",
        "DDS_CARD_STATUS_CHANGED",  # I3 E4a: REGISTERED → WORKED
    ]

    snapshot = response.json()["snapshot"]
    assert snapshot["card_values"]["recipients.comment"] == "Сильное задымление, подъезд 3"

    card = (await prepared.get("/operator/card")).json()
    assert card["values"]["recipients.comment"] == "Сильное задымление, подъезд 3"
    revisions = (await prepared.get("/operator/card/revisions")).json()
    assert revisions["items"][-1]["field_path"] == "recipients.comment"


async def test_without_a_comment_nothing_extra_is_written(prepared: OperatorFlow) -> None:
    """No comment, no card write: the snapshot then points at the card's latest revision."""
    revisions_before = (await prepared.get("/operator/card/revisions")).json()["total"]
    response = await prepared.post("/operator/handoff", json={})
    assert response.status_code == 201, response.text

    revisions_after = (await prepared.get("/operator/card/revisions")).json()
    assert revisions_after["total"] == revisions_before
    assert "recipients.comment" not in response.json()["snapshot"]["card_values"]
    assert response.json()["snapshot"]["card_revision_id"] == str(
        UUID(revisions_after["items"][-1]["revision_id"])
    )


async def test_editing_the_card_afterwards_never_changes_the_snapshot(
    prepared: OperatorFlow, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """SPEC §10 step 3, on the bytes: the snapshot is a by-value copy, not a view of the card.

    The card is moved to the *world's* "27" through the repository rather than through
    `setCardField`, because `edit_card` leaves `available_actions` at `HANDED_OFF` (§10.9) — and
    because writing the card behind the endpoint's back is the strongest form of the claim: even
    then the snapshot does not follow.
    """
    assert (await prepared.post("/operator/handoff", json={})).status_code == 201
    before = await _snapshot_row(uow_factory)

    async with uow_factory() as uow:
        session = await uow.sessions.get(SessionId(prepared.session_id))
        assert session is not None
        card = await uow.operator_cards.get(session.incident.incident_id)
        assert card is not None
        await uow.operator_cards.save(
            card.model_copy(update={"values": {**card.values, "address.house": "27"}})
        )
        await uow.commit()

    after = await _snapshot_row(uow_factory)
    assert after["card_values"] == before["card_values"]
    assert after["card_values"]["address.house"] == "72"
    assert after["content_sha256"] == before["content_sha256"]
    assert json.dumps(after["card_values"], sort_keys=True) == json.dumps(
        before["card_values"], sort_keys=True
    )


async def test_the_content_sha256_is_over_the_frozen_values_and_the_services(
    prepared: OperatorFlow,
) -> None:
    """§10.7: canonical JSON of `card_values` + `recipient_services`, recomputable by a client."""
    body = (await prepared.post("/operator/handoff", json={})).json()["snapshot"]
    payload = json.dumps(
        {
            "card_values": body["card_values"],
            "recipient_services": body["recipient_services"],
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert body["content_sha256"] == hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def test_a_second_handoff_is_refused_with_its_own_code(prepared: OperatorFlow) -> None:
    """`409 HANDOFF_ALREADY_CREATED` — "that has already happened", not "you may not now"."""
    assert (await prepared.post("/operator/handoff", json={})).status_code == 201
    before = await prepared.event_types()

    second = await prepared.post("/operator/handoff", json={})

    assert second.status_code == 409, second.text
    assert second.json()["code"] == "HANDOFF_ALREADY_CREATED"
    assert await prepared.event_types() == before, "a refused handoff appends nothing"


async def test_no_recipient_service_is_refused_with_its_own_code(
    interview: OperatorFlow, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """`409 RECIPIENT_SERVICES_EMPTY`, not the guard's generic `INVALID_TRANSITION`."""
    await fill_card(interview)
    await prepare_handoff(interview)  # no service selected
    before = await interview.event_types()

    response = await interview.post("/operator/handoff", json={})

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "RECIPIENT_SERVICES_EMPTY"
    assert await interview.event_types() == before
    assert await read_assignments(uow_factory, interview.session_id) == []


async def test_the_handoff_is_not_available_before_the_preparation_screen(
    interview: OperatorFlow,
) -> None:
    """D8's second gate: `create_handoff` is not an `INTERVIEW` action (§10.9)."""
    await fill_card(interview)
    assert (await interview.select("FIRE_RESCUE")).status_code == 200

    response = await interview.post("/operator/handoff", json={})

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


async def test_only_the_stage_trainee_may_hand_off(prepared: OperatorFlow) -> None:
    """SPEC §7: the instructor observes and intervenes; they never complete a trainee action."""
    for token in (prepared.instructor_token, prepared.dds_token):
        response = await prepared.post("/operator/handoff", token=token, json={})
        assert response.status_code == 403, response.text

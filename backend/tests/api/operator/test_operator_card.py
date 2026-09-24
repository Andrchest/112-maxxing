"""The incident card: one field per command, every mutation recorded (SPEC §9; §10.6, §40.6).

SPEC §9 is the requirement this file exists for: *"every mutation is stored with its previous
value and actor"* and *"the final card is NOT enough"*. So the assertions are about the audit
trail as much as about the card — a revision row per real change, ordered, paged, immutable, and
none at all for a write that changed nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.application.ports.idempotency_store import idempotency_key
from app.application.testing.fakes import InMemoryIdempotencyStore
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy.exc import DBAPIError

from tests.api.operator.conftest import OperatorFlow

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------------------------


async def test_a_change_produces_one_revision_and_one_event(interview: OperatorFlow) -> None:
    """The happy case: card updated, `revision_no` 1, one `CARD_FIELD_CHANGED`."""
    before = await interview.event_types()
    response = await interview.set_field("address.house", "5")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["card"]["values"]["address.house"] == "5"
    assert body["card"]["revision_counter"] == 1
    assert body["revision"]["revision_no"] == 1
    assert body["revision"]["previous_value"] is None
    assert body["revision"]["new_value"] == "5"
    assert body["revision"]["actor"]["actor_type"] == "TRAINEE"
    assert body["revision"]["actor"]["actor_id"] == str(interview.operator_user_id)
    assert (await interview.event_types())[len(before) :] == ["CARD_FIELD_CHANGED"]


async def test_writing_the_same_value_again_is_a_no_op(interview: OperatorFlow) -> None:
    """§10.6: "no revision, no event". `200`, `revision: null`, the card unchanged."""
    assert (await interview.set_field("address.house", "5")).status_code == 200
    before = await interview.event_types()
    repeat = await interview.set_field("address.house", "5")
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["revision"] is None
    assert repeat.json()["card"]["revision_counter"] == 1
    assert await interview.event_types() == before
    page = await interview.get("/operator/card/revisions")
    assert page.json()["total"] == 1


async def test_the_previous_value_of_a_second_write_is_the_first(interview: OperatorFlow) -> None:
    """SPEC §9's "with its previous value" — the property the report's diff is built on."""
    await interview.set_field("address.house", "5")
    second = await interview.set_field("address.house", "7")
    assert second.json()["revision"]["previous_value"] == "5"
    assert second.json()["revision"]["new_value"] == "7"
    assert second.json()["revision"]["revision_no"] == 2


@pytest.mark.parametrize(
    "field_path,new_value,code",
    [
        ("address.nonexistent", "5", "CARD_FIELD_UNKNOWN"),
        ("", "5", "CARD_FIELD_UNKNOWN"),
        ("address.floor", "not an integer", "CARD_VALUE_TYPE_MISMATCH"),
        ("flags.threat_to_life", "yes", "CARD_VALUE_TYPE_MISMATCH"),
        ("incident.type", "NOT_A_MEMBER", "CARD_VALUE_TYPE_MISMATCH"),
        ("recipients.services", ["POLICE"], "VALIDATION_ERROR"),
    ],
)
async def test_a_rejected_write_uses_the_documented_code_and_writes_nothing(
    interview: OperatorFlow, field_path: str, new_value: Any, code: str
) -> None:
    """Every 422 `openapi.yaml` documents for `setCardField`, and no trace of the attempt."""
    before = await interview.event_types()
    response = await interview.set_field(field_path, new_value)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == code
    assert await interview.event_types() == before
    assert (await interview.get("/operator/card/revisions")).json()["total"] == 0


async def test_a_boolean_is_not_an_integer_field(interview: OperatorFlow) -> None:
    """`True` is an `int` in Python and must not satisfy an `INTEGER` card field."""
    response = await interview.set_field("address.floor", True)
    assert response.status_code == 422
    assert response.json()["code"] == "CARD_VALUE_TYPE_MISMATCH"


# ---------------------------------------------------------------------------------------------
# Reading the history
# ---------------------------------------------------------------------------------------------


async def test_revisions_are_ordered_and_paged(interview: OperatorFlow) -> None:
    """Ascending by `revision_no`, `limit`/`offset` page it, `total` is the unpaged count."""
    for house in ("1", "2", "3", "4", "5"):
        assert (await interview.set_field("address.house", house)).status_code == 200

    everything = await interview.get("/operator/card/revisions")
    assert everything.status_code == 200, everything.text
    assert everything.json()["total"] == 5
    assert [item["revision_no"] for item in everything.json()["items"]] == [1, 2, 3, 4, 5]
    assert [item["new_value"] for item in everything.json()["items"]] == ["1", "2", "3", "4", "5"]

    page = await interview.get("/operator/card/revisions", params={"limit": 2, "offset": 2})
    assert page.json()["total"] == 5, "the total is the unpaged count"
    assert [item["revision_no"] for item in page.json()["items"]] == [3, 4]


async def test_revisions_can_be_filtered_to_one_field(interview: OperatorFlow) -> None:
    """The filter narrows the `total` too: one field's history says nothing about the card's."""
    await interview.set_field("address.house", "5")
    await interview.set_field("address.street", "Ленина")
    await interview.set_field("address.house", "7")

    filtered = await interview.get(
        "/operator/card/revisions", params={"field_path": "address.house"}
    )
    assert filtered.json()["total"] == 2
    assert [item["new_value"] for item in filtered.json()["items"]] == ["5", "7"]


async def test_a_revision_row_cannot_be_updated(
    interview: OperatorFlow, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
) -> None:
    """§20.9's `incident_card_revisions_append_only` trigger rejects UPDATE — the audit is real."""
    response = await interview.set_field("address.house", "5")
    revision_id = response.json()["revision"]["revision_id"]
    with pytest.raises(DBAPIError) as rejected:
        async with uow_factory() as uow:
            await uow.session.execute(
                sa.text(
                    "UPDATE incident_card_revisions SET new_value = '\"999\"'::jsonb WHERE id = :id"
                ),
                {"id": revision_id},
            )
            await uow.commit()
    assert "immutable" in str(rejected.value).lower() or "reject" in str(rejected.value).lower()


# ---------------------------------------------------------------------------------------------
# Idempotency (§40.6)
# ---------------------------------------------------------------------------------------------


async def test_a_repeat_with_the_same_client_command_id_appends_nothing(
    interview: OperatorFlow, idempotency: InMemoryIdempotencyStore
) -> None:
    """§40.6: a retried `setCardField` returns the first response body and writes nothing more."""
    command_id = str(uuid4())
    first = await interview.set_field("address.house", "5", client_command_id=command_id)
    assert first.status_code == 200, first.text
    before = await interview.event_types()

    second = await interview.set_field("address.house", "9", client_command_id=command_id)
    assert second.status_code == 200, second.text
    assert second.json() == first.json(), "the *first* response body, not a new one"
    assert await interview.event_types() == before
    assert (await interview.get("/operator/card/revisions")).json()["total"] == 1
    assert (await interview.get("/operator/card")).json()["values"]["address.house"] == "5"

    assert idempotency_key(interview.operator_user_id, command_id) in idempotency.values


async def test_losing_the_key_only_re_evaluates_the_command(
    interview: OperatorFlow, idempotency: InMemoryIdempotencyStore
) -> None:
    """§40.6's documented loss behaviour: Redis is never authoritative, only a de-duplicator."""
    command_id = str(uuid4())
    await interview.set_field("address.house", "5", client_command_id=command_id)
    idempotency.forget(idempotency_key(interview.operator_user_id, command_id))

    again = await interview.set_field("address.house", "9", client_command_id=command_id)
    assert again.status_code == 200, again.text
    assert again.json()["revision"]["new_value"] == "9", "re-evaluated, not replayed"
    assert (await interview.get("/operator/card/revisions")).json()["total"] == 2


async def test_two_clients_cannot_collide_on_one_client_command_id(
    interview: OperatorFlow,
) -> None:
    """The key is `idempotency:{user_id}:{client_command_id}`, so it is scoped to one caller."""
    command_id = str(uuid4())
    await interview.set_field("address.house", "5", client_command_id=command_id)
    # The same id from the DDS trainee is a different key; the command is refused for its own
    # reason (the wrong stage), never answered out of the operator's stored body.
    other = await interview.client.put(
        interview.url("/operator/card/field"),
        headers={"Authorization": f"Bearer {interview.dds_token}"},
        json={
            "field_path": "address.house",
            "new_value": "5",
            "client_command_id": command_id,
        },
    )
    assert other.status_code == 403


# ---------------------------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------------------------


async def test_two_concurrent_set_field_commands_both_land(interview: OperatorFlow) -> None:
    """The §20.8 row lock serialises them: two events, two revisions, distinct numbers.

    This is the property that makes the audit trail trustworthy under a double-click: neither
    command is lost and neither overwrites the other's `seq_no` or `revision_no`.
    """
    first, second = await asyncio.gather(
        interview.set_field("address.house", "5"),
        interview.set_field("address.street", "Ленина"),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    revisions = (await interview.get("/operator/card/revisions")).json()
    assert revisions["total"] == 2
    assert sorted(item["revision_no"] for item in revisions["items"]) == [1, 2]

    card = (await interview.get("/operator/card")).json()
    assert card["values"]["address.house"] == "5"
    assert card["values"]["address.street"] == "Ленина"
    assert card["revision_counter"] == 2

    types = await interview.event_types()
    assert types.count("CARD_FIELD_CHANGED") == 2


# ---------------------------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------------------------


async def test_selecting_a_service_writes_the_card_field_too(interview: OperatorFlow) -> None:
    """`recipients.services` *is* a card field, so the selection is in the card's history (D5)."""
    response = await interview.select("FIRE_RESCUE")
    assert response.status_code == 200, response.text
    assert response.json()["card"]["values"]["recipients.services"] == ["FIRE_RESCUE"]
    revisions = (await interview.get("/operator/card/revisions")).json()
    assert revisions["total"] == 1
    assert revisions["items"][0]["field_path"] == "recipients.services"
    assert revisions["items"][0]["new_value"] == ["FIRE_RESCUE"]


async def test_selecting_an_already_selected_service_is_a_no_op(interview: OperatorFlow) -> None:
    """`openapi.yaml`: "Selecting an already selected service is a no-op"."""
    await interview.select("FIRE_RESCUE")
    before = await interview.event_types()
    repeat = await interview.select("FIRE_RESCUE")
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["selected_services"] == ["FIRE_RESCUE"]
    assert await interview.event_types() == before
    assert (await interview.get("/operator/card/revisions")).json()["total"] == 1


async def test_deselecting_a_service_that_was_not_selected_is_a_no_op(
    interview: OperatorFlow,
) -> None:
    before = await interview.event_types()
    response = await interview.deselect("POLICE")
    assert response.status_code == 200, response.text
    assert response.json()["selected_services"] == []
    assert await interview.event_types() == before


async def test_every_service_type_is_offered_including_the_wrong_ones(
    interview: OperatorFlow,
) -> None:
    """SPEC §10: the trainee must be able to pick the wrong service, so the UI offers them all."""
    from app.domain.enums import LEGACY_SERVICE_IDS

    response = await interview.select("FIRE_RESCUE")
    assert response.json()["available_services"] == list(LEGACY_SERVICE_IDS)


async def test_a_service_is_a_catalog_id_and_an_unknown_one_is_422(
    interview: OperatorFlow,
) -> None:
    """I3 E2a (D18): any id of the session's service catalog is accepted — here one beyond the six
    legacy ids — and an id the catalog does not have is `422 SERVICE_UNKNOWN`, writing nothing."""
    selected = await interview.select("MOSVODOKANAL")
    assert selected.status_code == 200, selected.text
    assert selected.json()["selected_services"] == ["MOSVODOKANAL"]

    before = await interview.event_types()
    for response in (
        await interview.select("NOT_A_SERVICE"),
        await interview.deselect("NOT_A_SERVICE"),
    ):
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "SERVICE_UNKNOWN"
    assert await interview.event_types() == before


# ---------------------------------------------------------------------------------------------
# Reading the card
# ---------------------------------------------------------------------------------------------


async def test_the_instructor_may_read_the_card_but_the_dds_trainee_may_not(
    interview: OperatorFlow,
) -> None:
    """D3: `OPERATOR_CARD` is a source of the 112 policy and the console, never of DDS's."""
    await interview.set_field("address.house", "5")

    as_instructor = await interview.get("/operator/card", token=interview.instructor_token)
    assert as_instructor.status_code == 200, as_instructor.text
    assert as_instructor.json()["values"]["address.house"] == "5"

    as_dds = await interview.get("/operator/card", token=interview.dds_token)
    assert as_dds.status_code == 403, as_dds.text
    assert as_dds.json()["code"] == "FORBIDDEN_FOR_ROLE"

    revisions = await interview.get("/operator/card/revisions", token=interview.dds_token)
    assert revisions.status_code == 403


async def test_the_card_carries_the_field_specs_the_ui_renders_from(
    interview: OperatorFlow,
) -> None:
    """`field_specs` is `CARD_FIELDS` — the UI renders the form from it, not from its own list."""
    from app.domain.layers.operator_card import CARD_FIELDS

    card = (await interview.get("/operator/card")).json()
    assert [spec["field_path"] for spec in card["field_specs"]] == [
        spec.field_path for spec in CARD_FIELDS
    ]

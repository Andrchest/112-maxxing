"""The idempotency note of §40.6: its key, and the round trip that makes replay honest.

`setCardField` stores "the first response body of that command" and replays it on a retry. That
only works if the stored body *is* the response — so the mechanism rests on
`SetCardFieldResult` round-tripping through JSON unchanged, which is exactly what these tests
assert. No database and no container: the property is about serialisation and a key format.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.application.operator.set_card_field import SetCardFieldResult
from app.application.operator.views import (
    ActorRefView,
    CardRevisionView,
    OperatorCardView,
    card_view,
    revision_view,
)
from app.application.ports.idempotency_store import idempotency_key
from app.application.testing.fakes import InMemoryIdempotencyStore
from app.domain.common.actors import ActorRef
from app.domain.common.ids import CardId, CardRevisionId, IncidentId, UserId
from app.domain.enums import ActorType
from app.domain.layers.operator_card import CardRevision, OperatorCard

USER = UserId(UUID("00000000-0000-4000-8000-00000000000f"))
COMMAND = UUID("11111111-2222-4333-8444-555555555555")


def test_the_key_is_the_one_the_protocol_document_names() -> None:
    """§40.6's table: `idempotency:{user_id}:{client_command_id}`, lowercase, no braces."""
    key = idempotency_key(USER, COMMAND)
    assert key == f"idempotency:{USER}:{COMMAND}"
    assert "{" not in key and "}" not in key
    assert key == key.lower()


def test_the_key_is_scoped_to_one_user() -> None:
    """Two clients that draw the same UUID must not be handed each other's response body."""
    other = UserId(uuid4())
    assert idempotency_key(USER, COMMAND) != idempotency_key(other, COMMAND)


def _card() -> OperatorCard:
    return OperatorCard(
        card_id=CardId(UUID("00000000-0000-4000-8000-0000000000c1")),
        incident_id=IncidentId(UUID("00000000-0000-4000-8000-0000000000c2")),
        values={"address.house": "5", "recipients.services": ["FIRE_RESCUE"]},
        revision_counter=2,
    )


def _revision() -> CardRevision:
    return CardRevision(
        revision_id=CardRevisionId(UUID("00000000-0000-4000-8000-0000000000d1")),
        card_id=CardId(UUID("00000000-0000-4000-8000-0000000000c1")),
        revision_no=2,
        field_path="address.house",
        previous_value=None,
        new_value="5",
        actor=ActorRef(actor_type=ActorType.TRAINEE, actor_id=USER),
        at_offset_ms=4_200,
    )


@pytest.mark.parametrize("with_revision", [True, False], ids=["changed", "no-op"])
def test_the_stored_response_round_trips_unchanged(with_revision: bool) -> None:
    """A replayed retry must be byte-identical to the first answer, no-op case included."""
    result = SetCardFieldResult(
        card=card_view(_card()),
        revision=revision_view(_revision()) if with_revision else None,
    )
    replayed = SetCardFieldResult.model_validate_json(result.model_dump_json())
    assert replayed == result
    assert replayed.model_dump_json() == result.model_dump_json()


async def test_the_fake_store_replays_what_it_was_given() -> None:
    """The in-memory store is the production adapter's contract, minus the TTL."""
    store = InMemoryIdempotencyStore()
    key = idempotency_key(USER, COMMAND)
    assert await store.get(key) is None

    result = SetCardFieldResult(card=card_view(_card()), revision=revision_view(_revision()))
    await store.put(key, result.model_dump_json())
    cached = await store.get(key)
    assert cached is not None
    assert SetCardFieldResult.model_validate_json(cached) == result


async def test_forgetting_the_key_is_a_miss_not_an_error() -> None:
    """§40.6's loss behaviour: the command re-evaluates; nothing raises."""
    store = InMemoryIdempotencyStore()
    key = idempotency_key(USER, COMMAND)
    await store.put(key, "{}")
    store.forget(key)
    assert await store.get(key) is None


def test_the_card_view_carries_every_field_spec_and_only_the_set_values() -> None:
    """`values` holds only the paths the trainee set; `field_specs` is all of `CARD_FIELDS`."""
    from app.domain.layers.operator_card import CARD_FIELDS

    view = card_view(_card())
    assert set(view.values) == {"address.house", "recipients.services"}
    assert len(view.field_specs) == len(CARD_FIELDS)
    assert isinstance(view, OperatorCardView)


def test_the_revision_view_keeps_the_actor_who_made_the_change() -> None:
    """SPEC §9: every mutation is stored with its actor, and the view must not drop it."""
    view = revision_view(_revision())
    assert isinstance(view, CardRevisionView)
    assert view.actor == ActorRefView(actor_type="TRAINEE", actor_id=USER)
    assert view.previous_value is None
    assert view.new_value == "5"

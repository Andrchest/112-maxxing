"""Revealed-fact bookkeeping (HLD `10-domain-model.md` §10.12, D10, SPEC §42 test 10).

`facts_delivered` answers "what would this utterance reveal"; `fold_revealed` answers "what does
the event log say has been revealed". Together they are the only writers of `revealed_fact_ids` —
the gate is not one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.domain.common.actors import ActorRef
from app.domain.common.ids import EventId, SessionId
from app.domain.enums import ActorType, DisclosurePolicy
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.facts.gate import FactRequest, GateConditionContext, evaluate_fact_access
from app.domain.facts.revealed import facts_delivered, fold_revealed

from tests.unit.domain.facts._support import belief, definition, definitions

SESSION_ID = SessionId(UUID("99999999-8888-7777-6666-555555555555"))


def _package(requests: list[FactRequest], revealed: frozenset[str] = frozenset()):  # type: ignore[no-untyped-def]
    defs = definitions(
        definition("asked"),
        definition("also_asked"),
        definition("spont", policy=DisclosurePolicy.SPONTANEOUS),
        definition("secret", policy=DisclosurePolicy.NEVER_DISCLOSE),
    )
    package, _ = evaluate_fact_access(
        requests, defs, belief(defs, revealed=revealed), revealed, 0, GateConditionContext()
    )
    return package


def _session_event(seq_no: int, event_type: EventType, payload: dict[str, object]) -> SessionEvent:
    return SessionEvent(
        id=EventId(UUID(int=seq_no)),
        session_id=SESSION_ID,
        seq_no=seq_no,
        event_type=event_type,
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        monotonic_offset_ms=seq_no * 1000,
        actor_type=ActorType.SIMULATION,
        payload=payload,
    )


# ---------------------------------------------------------------------------------------------
# facts_delivered
# ---------------------------------------------------------------------------------------------


def test_a_completed_utterance_reveals_every_allowed_fact_including_the_spontaneous_ones() -> None:
    package = _package([FactRequest(fact_id="asked", explicit=True)])

    assert [fact.fact_id for fact in package.allowed] == ["asked", "spont"]
    assert facts_delivered(package, completed=True) == ("asked", "spont")


def test_an_interrupted_utterance_reveals_nothing() -> None:
    """D10: "Interrupted reveals nothing" — however much of it the trainee actually heard."""
    package = _package([FactRequest(fact_id="asked", explicit=True)])

    assert facts_delivered(package, completed=False) == ()


def test_unavailable_and_withheld_facts_are_never_delivered() -> None:
    package = _package([FactRequest(fact_id="secret", explicit=True)])

    assert package.unavailable[0].fact_id == "secret"
    assert "secret" not in facts_delivered(package, completed=True)


def test_delivery_follows_package_order_and_repeats_no_id() -> None:
    package = _package(
        [
            FactRequest(fact_id="also_asked", explicit=True),
            FactRequest(fact_id="asked", explicit=True),
            FactRequest(fact_id="asked", explicit=True),
        ]
    )

    delivered = facts_delivered(package, completed=True)

    assert delivered == ("also_asked", "asked", "spont")
    assert len(set(delivered)) == len(delivered)


def test_an_empty_package_delivers_nothing() -> None:
    package = _package([FactRequest(fact_id="unknown.id", explicit=True)], frozenset({"spont"}))

    assert package.allowed == ()
    assert facts_delivered(package, completed=True) == ()


# ---------------------------------------------------------------------------------------------
# fold_revealed
# ---------------------------------------------------------------------------------------------


def test_the_fold_collects_every_facts_delivered_id() -> None:
    events = [
        _session_event(1, EventType.FACTS_DELIVERED, {"fact_ids": ["a", "b"]}),
        _session_event(2, EventType.CALLER_TTS_ENDED, {"completed": True}),
        _session_event(3, EventType.FACTS_DELIVERED, {"fact_ids": ["b", "c"]}),
    ]

    assert fold_revealed(events) == frozenset({"a", "b", "c"})


def test_the_fold_ignores_every_other_event_type() -> None:
    events = [
        _session_event(1, EventType.CALLER_TTS_STARTED, {"fact_ids": ["leak"]}),
        _session_event(2, EventType.CALLER_UTTERANCE_INTERRUPTED, {"fact_ids": ["leak"]}),
    ]

    assert fold_revealed(events) == frozenset()


def test_the_fold_is_total_on_a_malformed_payload() -> None:
    events = [
        _session_event(1, EventType.FACTS_DELIVERED, {}),
        _session_event(2, EventType.FACTS_DELIVERED, {"fact_ids": None}),
        _session_event(3, EventType.FACTS_DELIVERED, {"fact_ids": ["ok", 27]}),
    ]

    assert fold_revealed(events) == frozenset({"ok"})


def test_the_fold_accepts_a_domain_event_too() -> None:
    """`DomainEvent` has no `seq_no` yet and must fold exactly like the persisted row."""
    event = DomainEvent(
        event_type=EventType.FACTS_DELIVERED,
        actor=ActorRef(actor_type=ActorType.SIMULATION),
        monotonic_offset_ms=0,
        payload={"fact_ids": ["a"]},
    )

    assert fold_revealed([event]) == frozenset({"a"})


def test_the_fold_is_empty_for_an_empty_log() -> None:
    assert fold_revealed([]) == frozenset()


@pytest.mark.parametrize("completed", [True, False])
def test_the_round_trip_from_a_package_to_the_folded_set(completed: bool) -> None:
    """The two functions compose: what the gate allowed is what the log then says was revealed."""
    package = _package([FactRequest(fact_id="asked", explicit=True)])
    delivered = facts_delivered(package, completed=completed)
    event = _session_event(1, EventType.FACTS_DELIVERED, {"fact_ids": list(delivered)})

    assert fold_revealed([event]) == frozenset(delivered)

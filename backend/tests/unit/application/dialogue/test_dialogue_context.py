"""`DialogueContextLoader` — one read-only unit of work per turn (R4, D3, §5.2, §10.12).

Two properties carry the weight here. First, the loader **never returns a `WorldTruth`**: the
`DialogueTurnInputs` type has no field for one, and the loader holds no repository that could
reach one. Second, `previously_allowed` is rebuilt from the persisted `gate_output`, not from the
`FactDefinition`s — the difference is invisible for a `KNOWN` fact and decisive for the demo's
`INCORRECT_BELIEF` floor (world 4, caller 5).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from app.application.dialogue.dialogue_context import (
    DialogueContextLoader,
    DialogueContextUnavailableError,
    DialogueTurnInputs,
    allowed_facts_from_gate_output,
    gate_output_document,
)
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.application.testing.fakes import FakeClock
from app.domain.common.ids import EventId, SessionId
from app.domain.enums import ActorType, GateReason
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.facts.gate import FactRequest, evaluate_fact_access
from app.domain.scenario.validation import build_fact_definitions, validate_scenario_document
from app.domain.scenario.version import ScenarioVersion
from app.domain.world.conditions import evaluate_condition

from tests.fixtures.scenarios import CONDITION_GATED_FACT_ID, condition_gated_document
from tests.unit.application.dialogue._support import gate_package
from tests.unit.application.dialogue.conftest import (
    DialogueStore,
    InMemoryDialogueUnitOfWork,
    seed_turn_row,
    transcribed_turn,
)


def loader(
    uow_factory: Callable[[], InMemoryDialogueUnitOfWork], clock: FakeClock, turns: int = 6
) -> DialogueContextLoader:
    return DialogueContextLoader(uow_factory, clock, window_turns=turns)  # type: ignore[arg-type]


def _event(store: DialogueStore, event_type: EventType, payload: dict) -> None:
    store.events.append(
        SessionEvent(
            id=EventId(uuid.uuid4()),
            session_id=store.session.id,
            seq_no=store.next_seq_no,
            event_type=event_type,
            timestamp_utc=store.session.started_at,
            monotonic_offset_ms=0,
            actor_type=ActorType.SIMULATION,
            actor_id=None,
            correlation_id=None,
            payload=payload,
        )
    )
    store.next_seq_no += 1


async def test_the_loader_never_returns_world_truth(
    store: DialogueStore, clock: FakeClock, uow_factory: Callable[[], InMemoryDialogueUnitOfWork]
) -> None:
    """D3, R4: the type has no field for one and nothing it holds could reach one."""
    assert "world_truth" not in DialogueTurnInputs.__dataclass_fields__

    inputs = await loader(uow_factory, clock).load(store.session.id)

    assert not hasattr(inputs, "world_truth")


async def test_it_loads_the_definitions_catalog_profile_and_live_belief(
    store: DialogueStore, clock: FakeClock, uow_factory: Callable[[], InMemoryDialogueUnitOfWork]
) -> None:
    inputs = await loader(uow_factory, clock).load(store.session.id)

    assert "address.street" in inputs.definitions
    assert [entry.fact_id for entry in inputs.catalog] == list(inputs.definitions)
    assert inputs.caller_profile.identity_ru.startswith("Соседка")
    assert inputs.caller_belief is store.caller_belief
    assert inputs.emotion == store.caller_belief.emotion


async def test_revealed_fact_ids_come_from_the_event_log(
    store: DialogueStore, clock: FakeClock, uow_factory: Callable[[], InMemoryDialogueUnitOfWork]
) -> None:
    """R4: `fold_revealed` over `FACTS_DELIVERED`, E13-A's function — not re-implemented."""
    _event(
        store,
        EventType.FACTS_DELIVERED,
        {
            "turn_index": 0,
            "fact_ids": ["address.street"],
            "delivered_via": "TTS_COMPLETED",
            "at_offset_ms": 0,
        },
    )

    inputs = await loader(uow_factory, clock).load(store.session.id)

    assert inputs.revealed_fact_ids == frozenset({"address.street"})


async def test_fired_world_events_come_from_the_event_log(
    store: DialogueStore, clock: FakeClock, uow_factory: Callable[[], InMemoryDialogueUnitOfWork]
) -> None:
    _event(
        store,
        EventType.WORLD_EVENT_TRIGGERED,
        {
            "world_event_id": "gas_cylinder_hazard",
            "kind": "SCHEDULED",
            "occurrence": 1,
            "title_ru": "Баллон",
            "caller_observable": True,
            "trigger_reason": "SCHEDULE",
            "effect_kinds": [],
            "at_offset_ms": 0,
        },
    )

    inputs = await loader(uow_factory, clock).load(store.session.id)

    assert inputs.fired_world_event_ids == frozenset({"gas_cylinder_hazard"})
    assert inputs.condition_ctx.fired_world_event_ids == inputs.fired_world_event_ids
    # E17 R3: the gate's condition context is built from the log — and from no `WorldTruth`.
    conditions = inputs.condition_ctx.conditions
    assert conditions is not None
    assert conditions.world_truth is None
    assert conditions.event_index.count(EventType.WORLD_EVENT_TRIGGERED) == 1


async def test_previously_allowed_is_rebuilt_from_the_persisted_gate_output(
    store: DialogueStore, clock: FakeClock, uow_factory: Callable[[], InMemoryDialogueUnitOfWork]
) -> None:
    """R3/R4: the caller value of a revealed fact, never the definition's world value."""
    turn = transcribed_turn("Какой этаж?", turn_index=0)
    seed_turn_row(store, turn)
    package, decisions = gate_package(("address.floor",))
    await store.turns.set_dialogue_outcome(
        store.session.id,
        0,
        interpretation={},
        gate_output=gate_output_document(package, decisions),
        planned_text="Пятый этаж.",
        fallback_used=False,
    )
    _event(
        store,
        EventType.FACTS_DELIVERED,
        {
            "turn_index": 0,
            "fact_ids": ["address.floor"],
            "delivered_via": "TTS_COMPLETED",
            "at_offset_ms": 0,
        },
    )

    inputs = await loader(uow_factory, clock).load(store.session.id)

    revealed = inputs.already_revealed
    assert [fact.fact_id for fact in revealed] == ["address.floor"]
    # The caller believes the fifth floor; the world says the fourth. The caller's value wins.
    assert revealed[0].value == 5
    assert inputs.definitions["address.floor"].world_value == 4
    assert inputs.revealed_values == ("5",)


async def test_the_window_pairs_operator_transcripts_with_planned_caller_text(
    store: DialogueStore, clock: FakeClock, uow_factory: Callable[[], InMemoryDialogueUnitOfWork]
) -> None:
    """R4: the caller side is `planned_text` until E14 records what was delivered."""
    turn = transcribed_turn("Назовите адрес", turn_index=0)
    seed_turn_row(store, turn)
    store.transcripts.append(
        StoredTranscriptSegment(
            id=turn.transcript_segment_id,
            session_id=store.session.id,
            audio_segment_id=None,
            speaker="TRAINEE",
            start_ms=0,
            end_ms=640,
            text="Назовите адрес",
            is_final=True,
            confidence=0.9,
            asr_provider="fake",
            asr_model="fake-1",
            turn_index=0,
        )
    )
    await store.turns.set_dialogue_outcome(
        store.session.id,
        0,
        interpretation={},
        gate_output={},
        planned_text="Улица Николаева, дом 27.",
        fallback_used=False,
    )

    inputs = await loader(uow_factory, clock).load(store.session.id)

    assert [(turn.speaker, turn.text) for turn in inputs.window] == [
        ("OPERATOR", "Назовите адрес"),
        ("CALLER", "Улица Николаева, дом 27."),
    ]
    assert inputs.operator_utterances == ("Назовите адрес",)


async def test_the_window_keeps_only_the_configured_number_of_turns(
    store: DialogueStore, clock: FakeClock, uow_factory: Callable[[], InMemoryDialogueUnitOfWork]
) -> None:
    for index in range(8):
        turn = transcribed_turn(f"Вопрос {index}", turn_index=index)
        seed_turn_row(store, turn)
        store.transcripts.append(
            StoredTranscriptSegment(
                id=turn.transcript_segment_id,
                session_id=store.session.id,
                audio_segment_id=None,
                speaker="TRAINEE",
                start_ms=index * 2000,
                end_ms=index * 2000 + 640,
                text=f"Вопрос {index}",
                is_final=True,
                confidence=0.9,
                asr_provider="fake",
                asr_model="fake-1",
                turn_index=index,
            )
        )

    inputs = await loader(uow_factory, clock, turns=4).load(store.session.id)

    assert [turn.text for turn in inputs.window] == [f"Вопрос {index}" for index in range(4, 8)]


async def test_now_ms_comes_from_the_clock_and_the_sessions_start(
    store: DialogueStore, clock: FakeClock, uow_factory: Callable[[], InMemoryDialogueUnitOfWork]
) -> None:
    clock.advance_ms(2_500)

    inputs = await loader(uow_factory, clock).load(store.session.id)

    assert inputs.now_ms == 2_500


async def test_a_missing_session_is_an_explicit_error(
    clock: FakeClock, uow_factory: Callable[[], InMemoryDialogueUnitOfWork]
) -> None:
    with pytest.raises(DialogueContextUnavailableError):
        await loader(uow_factory, clock).load(SessionId(uuid.uuid4()))


def test_gate_output_round_trips_losslessly() -> None:
    package, decisions = gate_package(("address.street", "address.landmark"))

    document = gate_output_document(package, decisions)
    facts = allowed_facts_from_gate_output(document)

    assert facts == list(package.allowed)


def test_an_unreadable_gate_output_yields_nothing_rather_than_raising() -> None:
    """Total on purpose: a turn from an older shape must not fail the current turn."""
    assert allowed_facts_from_gate_output(None) == []
    assert allowed_facts_from_gate_output("not json") == []
    assert allowed_facts_from_gate_output({"allowed": "nonsense"}) == []
    assert allowed_facts_from_gate_output({"allowed": [{"fact_id": "x"}]}) == []


# ---------------------------------------------------------------------------------------------
# Condition-gated facts (E17 ruling R3)
# ---------------------------------------------------------------------------------------------


async def test_a_condition_gated_fact_opens_from_the_event_log_alone(
    store: DialogueStore, clock: FakeClock, uow_factory: Callable[[], InMemoryDialogueUnitOfWork]
) -> None:
    """R3: `available_after: {condition: …}` is evaluated, and evaluated without any world truth.

    Before E17 the loader passed `conditions=None`, so a condition-shaped `available_after` was
    unmet for ever and the fact was unreachable however the exercise went (the old
    E17 marker at this spot). The gating condition here is an `action` leaf — the folded session
    event log — which is exactly the material D3 allows a dialogue turn to see.
    """
    store.document = condition_gated_document()
    definitions = build_fact_definitions(ScenarioVersion(**store.document))
    gated = definitions[CONDITION_GATED_FACT_ID].available_after
    assert gated is not None and gated.condition is not None

    before = await loader(uow_factory, clock).load(store.session.id)
    assert before.condition_ctx.conditions is not None
    assert evaluate_condition(gated.condition, before.condition_ctx.conditions) is False

    _event(
        store,
        EventType.CARD_FIELD_CHANGED,
        {
            "card_id": str(uuid.uuid4()),
            "field_path": "address.house",
            "previous_value": None,
            "new_value": "72",
            "revision": 1,
            "source": "MANUAL",
        },
    )

    after = await loader(uow_factory, clock).load(store.session.id)
    assert after.condition_ctx.conditions is not None
    assert evaluate_condition(gated.condition, after.condition_ctx.conditions) is True

    # …and the gate itself flips the fact from NOT_YET to released, which is the point of R3.
    assert _gate_outcome(before) == (False, GateReason.NOT_YET_AVAILABLE)
    assert _gate_outcome(after) == (True, GateReason.OK)


def _gate_outcome(inputs: DialogueTurnInputs) -> tuple[bool, GateReason]:
    """Ask the gate for the gated fact: `(is it allowed, what it said about it)`."""
    package, decisions = evaluate_fact_access(
        requests=[FactRequest(fact_id=CONDITION_GATED_FACT_ID, explicit=True)],
        definitions=inputs.definitions,
        caller_belief=inputs.caller_belief,
        revealed_fact_ids=frozenset(),
        now_ms=inputs.now_ms,
        condition_ctx=inputs.condition_ctx,
    )
    allowed = any(fact.fact_id == CONDITION_GATED_FACT_ID for fact in package.allowed)
    reason = next(
        decision.reason for decision in decisions if decision.fact_id == CONDITION_GATED_FACT_ID
    )
    return allowed, reason


def test_the_condition_gated_fixture_is_a_valid_scenario() -> None:
    """§30.8 rule 31 accepts an `action` leaf: it is answerable from the log (E17 R3)."""
    assert validate_scenario_document(condition_gated_document()) == []

"""INV 12 — a barge-in never reveals an undelivered fact, and never loses the record.

> A fact is revealed when, and only when, the trainee has *heard* it. An interrupted caller
> utterance reveals nothing; and the utterance that was cut off is still fully recorded — what was
> planned, what was delivered, and how much audio reached the wire.

The invariant is structural, not a flag: `FACTS_DELIVERED` is appended only behind an
uninterrupted `CALLER_TTS_ENDED` (D10, `50-voice-pipeline.md` §6.4), and `fold_revealed` — the
one function the Fact Access Gate's `ALREADY_REVEALED` decision reads (E13-A) — reads exactly
those events. So "the facts stay unrevealed" and "no `FACTS_DELIVERED` was appended for that
turn" are the same statement, and this file asserts it over the event log a real `TurnPipeline`
wrote against fakes.

Two halves, both required by the invariant's wording:

* **nothing is revealed** — no `FACTS_DELIVERED`, no `CALLER_TTS_ENDED`, and the gate's own fold
  still counts the interrupted facts as unrevealed on the next turn;
* **nothing is lost** — `CALLER_UTTERANCE_INTERRUPTED` carries `planned_text`, `delivered_text`,
  both audio figures and every `fact_id` that did *not* get through, and the transcript and turn
  rows of §6.4 are written.
"""

from __future__ import annotations

import asyncio

import pytest
from app.application.voice.config import VoiceTurnConfig
from app.domain.events.types import EventType
from app.domain.facts.revealed import fold_revealed

from tests.unit.application.voice.conftest import VoiceStore
from tests.unit.application.voice.test_barge_in import (
    CALLER_TEXT_RU,
    build,
    payload_of,
    two_turns,
    types_of,
)

FACTS = ("incident.address", "incident.floor")


@pytest.fixture
def config() -> VoiceTurnConfig:
    return VoiceTurnConfig()


async def a_barged_in_call(config: VoiceTurnConfig) -> VoiceStore:
    pipeline, _transport, store, _responder, _clock = build(
        config, frames=two_turns(config), fact_ids=FACTS
    )
    await asyncio.wait_for(pipeline.run(), timeout=10)
    return store


# ---------------------------------------------------------------------------------------------
# Half 1: nothing is revealed
# ---------------------------------------------------------------------------------------------


async def test_an_interrupted_utterance_appends_no_facts_delivered(
    config: VoiceTurnConfig,
) -> None:
    """D10: the interrupted turn reveals nothing, whatever its text says."""
    store = await a_barged_in_call(config)

    interrupted = payload_of(store, EventType.CALLER_UTTERANCE_INTERRUPTED)["turn_id"]
    assert not [
        event
        for event in store.events
        if event.event_type is EventType.FACTS_DELIVERED and event.payload["turn_id"] == interrupted
    ]


async def test_an_interrupted_utterance_appends_no_tts_ended(config: VoiceTurnConfig) -> None:
    """§6.4: "an interrupted playback has no natural end" — the event simply is not there."""
    store = await a_barged_in_call(config)

    interrupted = payload_of(store, EventType.CALLER_UTTERANCE_INTERRUPTED)["turn_id"]
    assert not [
        event
        for event in store.events
        if event.event_type is EventType.CALLER_TTS_ENDED
        and event.payload["turn_id"] == interrupted
    ]


async def test_the_gate_still_sees_the_interrupted_facts_as_unrevealed(
    config: VoiceTurnConfig,
) -> None:
    """The invariant as the Fact Access Gate itself reads it (E13-A's `fold_revealed`)."""
    store = await a_barged_in_call(config)

    interrupted_turn = payload_of(store, EventType.CALLER_UTTERANCE_INTERRUPTED)["turn_id"]
    of_that_turn = [
        event for event in store.events if event.payload.get("turn_id") == interrupted_turn
    ]
    revealed_by_that_turn = fold_revealed(of_that_turn)

    assert revealed_by_that_turn == frozenset(), (
        f"a fact the trainee never heard was folded as revealed: {sorted(revealed_by_that_turn)}"
    )

    # And, in log order: nothing was revealed at any point before the interruption either.
    interrupted_at = next(
        index
        for index, event in enumerate(store.events)
        if event.event_type is EventType.CALLER_UTTERANCE_INTERRUPTED
    )
    assert fold_revealed(store.events[: interrupted_at + 1]) == frozenset()


async def test_the_facts_may_be_offered_again_and_then_really_are_revealed(
    config: VoiceTurnConfig,
) -> None:
    """The other side of the same coin: the second, uninterrupted turn does reveal them."""
    store = await a_barged_in_call(config)

    assert fold_revealed(store.events) == frozenset(FACTS)


# ---------------------------------------------------------------------------------------------
# Half 2: nothing is lost
# ---------------------------------------------------------------------------------------------


async def test_the_interrupted_utterance_is_fully_recorded(config: VoiceTurnConfig) -> None:
    """§6.3's payload and §6.4's rows — the audit record of an utterance nobody finished."""
    store = await a_barged_in_call(config)

    payload = payload_of(store, EventType.CALLER_UTTERANCE_INTERRUPTED)
    assert payload["planned_text"] == CALLER_TEXT_RU
    assert sorted(payload["fact_ids_not_revealed"]) == sorted(FACTS)
    assert payload["delivered_audio_ms"] <= payload["total_audio_ms_generated"]
    assert payload["total_audio_ms_generated"] > 0
    assert CALLER_TEXT_RU.startswith(payload["delivered_text"])

    turn_index = payload["turn_index"]
    caller_rows = [
        row for row in store.transcripts if row.speaker == "CALLER" and row.turn_index == turn_index
    ]
    assert len(caller_rows) == 1, "the interrupted utterance lost its transcript row"
    assert caller_rows[0].text == payload["delivered_text"]
    outcome = next(row for row in store.caller_outcomes if row.turn_index == turn_index)
    assert outcome.interrupted is True


async def test_every_fact_the_utterance_would_have_revealed_is_named(
    config: VoiceTurnConfig,
) -> None:
    """Not "the ones the prefix missed": all of them (D10).

    A partial reading would be worse than none — the caller's sentence may name a fact in its
    first three words and be cut off before the words that make it *mean* anything, and a reader
    who trusted a prefix-derived list would never offer it again.
    """
    store = await a_barged_in_call(config)

    payload = payload_of(store, EventType.CALLER_UTTERANCE_INTERRUPTED)
    assert set(payload["fact_ids_not_revealed"]) == set(FACTS)


async def test_the_interruption_is_visible_in_the_log_at_all(config: VoiceTurnConfig) -> None:
    """The guard against the whole file passing vacuously: a barge-in really happened."""
    store = await a_barged_in_call(config)

    kinds = types_of(store)
    assert EventType.CALLER_TTS_STARTED in kinds
    assert EventType.CALLER_UTTERANCE_INTERRUPTED in kinds

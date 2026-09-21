"""INV 10 — "Rewording caller dialogue does not modify factual scoring" (SPEC §42 item 10, D10).

D10 states the mechanism: "fact delivery is decided by code, not text". A fact becomes revealed
only when its response finished playback uninterrupted, which produces `FACTS_DELIVERED
{fact_ids}` — and "`FACT_OBTAINED` scoring reads `FACTS_DELIVERED` only, so rewording caller text
cannot change a score".

The test has two halves and both are needed.

**The invariant.** Two logs identical except that *every* caller-text-bearing payload is reworded
— `CALLER_TTS_STARTED.planned_text`, `CALLER_TTS_ENDED.delivered_text`, and any transcript or
dialogue payload — score to the same checksum. Rewording is done by rewriting the payloads of the
committed good log, so the test cannot pass by accident of the builder producing the same text.

**The bite.** Removing one id from one `FACTS_DELIVERED` *does* change the `FACT_OBTAINED` result.
Without this half, an evaluator that ignored the input entirely would pass the first half
trivially.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring.engine import report_checksum, score

from tests.unit.domain.scoring._event_log_builders import demo_scenario, good_log, mutate

#: Every payload key that carries words a human wrote or a model generated.
TEXT_KEYS: frozenset[str] = frozenset(
    {
        "planned_text",
        "delivered_text",
        "text_ru",
        "transcript",
        "text",
        "caller_display_ru",
        "title_ru",
        "body_ru",
    }
)

#: Every event type whose payload is caller dialogue in some form.
TEXT_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.CALLER_TTS_STARTED,
        EventType.CALLER_TTS_ENDED,
        EventType.CALLER_UTTERANCE_INTERRUPTED,
        EventType.CALLER_RESPONSE_PLANNED,
        EventType.CALLER_RESPONSE_GENERATED,
        EventType.ASR_PARTIAL,
        EventType.ASR_FINAL,
        EventType.DIALOGUE_INTERPRETED,
        EventType.CALL_RINGING,
    }
)

REWORDING = "СОВЕРШЕННО ДРУГОЙ ТЕКСТ, НИ ОДНОГО ОБЩЕГО СЛОВА С ИСХОДНЫМ"


def reword(events: Sequence[SessionEvent]) -> tuple[SessionEvent, ...]:
    """Rewrite every text-bearing payload value, leaving ids, offsets and facts untouched."""
    out: list[SessionEvent] = []
    for event in events:
        payload = dict(event.payload)
        touched = False
        for key in list(payload):
            if key in TEXT_KEYS and isinstance(payload[key], str):
                payload[key] = f"{REWORDING} [{key}]"
                touched = True
        out.append(event.model_copy(update={"payload": payload}) if touched else event)
    return tuple(out)


def test_the_rewording_helper_actually_rewords_something() -> None:
    """A guard: an invariant that rewords nothing proves nothing."""
    events = good_log()
    reworded = reword(events)

    changed = [
        (before.event_type, after.payload)
        for before, after in zip(events, reworded, strict=True)
        if before.payload != after.payload
    ]

    assert changed
    assert {event_type for event_type, _ in changed} & TEXT_EVENT_TYPES
    assert all(REWORDING in str(payload) for _, payload in changed)


def test_rewording_every_caller_payload_leaves_the_checksum_identical() -> None:
    version = demo_scenario()
    events = good_log()
    reworded = reword(events)

    assert reworded != events
    assert report_checksum(score(version, reworded)) == report_checksum(score(version, events))


def test_rewording_leaves_every_single_result_identical() -> None:
    version = demo_scenario()

    original = score(version, good_log())
    reworded = score(version, reword(good_log()))

    assert original.results == reworded.results
    assert original.total_points == reworded.total_points


def test_a_differently_worded_builder_run_scores_identically() -> None:
    """The same fact plan, entirely different caller prose, from the builder's own knob."""
    version = demo_scenario()

    wordy = score(version, good_log(caller_text="Умоляю, приезжайте, всё в дыму!!!"))
    terse = score(version, good_log(caller_text="Пожар."))

    assert report_checksum(wordy) == report_checksum(terse)


def test_facts_delivered_are_untouched_by_rewording() -> None:
    events = good_log()
    reworded = reword(events)

    def delivered(log: Sequence[SessionEvent]) -> list[list[str]]:
        return [
            list(event.payload["fact_ids"])
            for event in log
            if event.event_type is EventType.FACTS_DELIVERED
        ]

    assert delivered(reworded) == delivered(events)


# ---------------------------------------------------------------------------------------------
# The bite: the evaluator is not simply ignoring its input.
# ---------------------------------------------------------------------------------------------


def test_removing_a_delivered_fact_id_does_change_the_fact_obtained_result() -> None:
    version = demo_scenario()

    original = score(version, good_log())
    without = score(version, mutate("fact_never_delivered"))

    by_rule = {result.rule_id: result for result in original.results}
    changed = {result.rule_id: result for result in without.results}

    assert by_rule["fact_victim_inside"].points_awarded == 10.0
    assert changed["fact_victim_inside"].points_awarded == 0.0
    assert changed["fact_victim_inside"].critical_failure
    assert report_checksum(original) != report_checksum(without)


def test_delivering_the_fact_too_late_also_changes_it() -> None:
    version = demo_scenario()

    late = score(version, mutate("fact_delivered_late"))

    assert {r.rule_id: r.passed for r in late.results}["fact_victim_inside"] is False

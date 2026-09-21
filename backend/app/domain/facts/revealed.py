"""Revealed-fact bookkeeping (HLD `10-domain-model.md` §10.12, D10, SPEC §21, §42 test 10).

"Fact delivery is decided by code, not by text" (D10). A fact becomes revealed only when the
caller's response finished playback uninterrupted: `CALLER_TTS_ENDED {completed: true}` produces
`FACTS_DELIVERED {fact_ids}`, and that event is the sole writer of `CallerBelief.revealed_fact_ids`
and the sole input of the `FACT_OBTAINED` evaluator. An interrupted utterance reveals nothing at
all, however much of it was actually heard.

The two functions here are the pure bookkeeping half of that rule: what an utterance would reveal
(`facts_delivered`) and what the event log says has been revealed so far (`fold_revealed`).
Emitting `FACTS_DELIVERED` from the real playback path is E14's job — this module never appends an
event, never mutates a `CallerBelief` and never reads a clock.

HLD gap — `ALLOWED_REPEAT` inside the package. §10.12's `AllowedFact` carries no outcome field, so
a repeat of an already-revealed fact is indistinguishable from a first release once the package is
built. `facts_delivered` therefore reports every allowed id once, in package order; folding an id
that is already in `revealed_fact_ids` is idempotent (`fold_revealed` returns a `frozenset`), and
`FACT_OBTAINED` reads "was it ever delivered", so the repeat changes no outcome.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

from app.domain.events.types import EventType
from app.domain.facts.gate import AllowedFactsPackage

__all__ = ["FactsDeliveredEvent", "facts_delivered", "fold_revealed"]


@runtime_checkable
class FactsDeliveredEvent(Protocol):
    """The two attributes `fold_revealed` reads off an event.

    A `Protocol` rather than `SessionEvent` because `DomainEvent` (what a pure domain method
    returns, before `seq_no` exists) has to fold exactly the same way — both satisfy it
    structurally, and neither import is needed here.
    """

    @property
    def event_type(self) -> EventType: ...

    @property
    def payload(self) -> Mapping[str, Any]: ...


def facts_delivered(package: AllowedFactsPackage, *, completed: bool) -> tuple[str, ...]:
    """The `fact_ids` an utterance built from `package` reveals, in package order (D10).

    `completed` is `CALLER_TTS_ENDED.completed`: `False` — the utterance was interrupted, or never
    finished — reveals nothing, whatever was already audible. Nothing outside `package.allowed`
    can ever appear here: `unavailable` facts were never in the prompt, and `withheld_count` is a
    count, not a list.
    """
    if not completed:
        return ()
    seen: list[str] = []
    for fact in package.allowed:
        if fact.fact_id not in seen:
            seen.append(fact.fact_id)
    return tuple(seen)


def fold_revealed(events: Iterable[FactsDeliveredEvent]) -> frozenset[str]:
    """Rebuild `revealed_fact_ids` from the event log — every `FACTS_DELIVERED` id, deduplicated.

    The fold is the definition: `CallerBelief.revealed_fact_ids` is a cache of it (D5's "the event
    log is the source of truth"), so a session that is replayed, resumed or restarted arrives at
    the same set. Events of any other type are ignored, and a `FACTS_DELIVERED` payload whose
    `fact_ids` is missing or is not a list of strings contributes nothing rather than raising —
    the fold is total, like every other domain fold.
    """
    revealed: set[str] = set()
    for event in events:
        if event.event_type is not EventType.FACTS_DELIVERED:
            continue
        fact_ids = event.payload.get("fact_ids")
        if not isinstance(fact_ids, list | tuple):
            continue
        revealed.update(fact_id for fact_id in fact_ids if isinstance(fact_id, str))
    return frozenset(revealed)

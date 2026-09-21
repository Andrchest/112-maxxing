"""`DialogueContextLoader` — one read-only unit of work per turn (R4, D3, §5.3, §10.12).

`DialogueResponder` needs eight different things to answer one turn, and every one of them lives in
a different place: the locked `ScenarioVersion` (fact definitions, the persona), the **live**
`CallerBelief` (caller values, knowledge, emotion), the event log (`revealed_fact_ids`, fired world
events), and `dialogue_turns` + `transcript_segments` (the 4–6 turn window). Assembling them in one
place, once per turn, is what keeps the responder a sequencer instead of a second repository.

**It never returns a `WorldTruth`.** That is the point of it existing beside
`app.application.simulation.world_state_loader`, which does hold both layer repositories: this
loader holds `caller_beliefs` and `scenarios` and nothing that could reach world truth, so the
dialogue chain cannot get there even by accident (D3). It is one of the three modules of this
package allowed to see a `FactDefinition` at all (R3) — the gate needs them, and the gate is what
turns them into the caller-value-only package the prompt builder sees.

`previously_allowed` is rebuilt from the **persisted `gate_output`** of earlier turns, never from
the definitions: the `ALREADY_REVEALED` prompt block must show what the caller actually said, and
re-deriving it from a `FactDefinition` would silently substitute a world value for a caller one on
an `INCORRECT_BELIEF` fact.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.application.dialogue.catalog import build_fact_catalog
from app.application.dialogue.interpreter import DialogueTurn
from app.application.ports.clock import Clock
from app.application.ports.dialogue_turn_repository import StoredDialogueTurn
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.timebase import session_offset_ms
from app.domain.caller.emotion import EmotionState
from app.domain.caller.profile import CallerProfile
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.domain.facts.definitions import FactCatalog, FactDefinition
from app.domain.facts.gate import (
    AllowedFact,
    AllowedFactsPackage,
    GateConditionContext,
    GateDecision,
)
from app.domain.facts.revealed import fold_revealed
from app.domain.layers.caller_belief import CallerBelief
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion

__all__ = [
    "DialogueContextLoader",
    "DialogueContextUnavailableError",
    "DialogueTurnInputs",
    "allowed_facts_from_gate_output",
    "gate_output_document",
]


class DialogueContextUnavailableError(DomainError):
    """A row the dialogue chain needs is missing — the same shape `load_world_state` raises."""

    code = "CONFLICT"


@dataclass(frozen=True, slots=True)
class DialogueTurnInputs:
    """Everything one dialogue turn reads, loaded once. Frozen: a turn reads a snapshot."""

    definitions: Mapping[str, FactDefinition]
    catalog: FactCatalog
    caller_profile: CallerProfile
    caller_belief: CallerBelief
    emotion: EmotionState
    revealed_fact_ids: frozenset[str]
    previously_allowed: Mapping[str, AllowedFact]
    fired_world_event_ids: frozenset[str]
    condition_ctx: GateConditionContext
    window: tuple[DialogueTurn, ...]
    operator_utterances: tuple[str, ...]
    now_ms: int

    @property
    def already_revealed(self) -> tuple[AllowedFact, ...]:
        """The `ALREADY_REVEALED` block's rows: caller values of facts already delivered."""
        return tuple(
            fact
            for fact_id, fact in self.previously_allowed.items()
            if fact_id in self.revealed_fact_ids
        )

    @property
    def revealed_values(self) -> tuple[str, ...]:
        """§7.5's "tokens(already revealed caller values)" source."""
        return tuple(fact.value_ru for fact in self.already_revealed if fact.value is not None)


def gate_output_document(
    package: AllowedFactsPackage, decisions: Sequence[GateDecision]
) -> dict[str, Any]:
    """`dialogue_turns.gate_output` (§20.6) — the package, losslessly, caller values included.

    Caller values, never world values: an `AllowedFactsPackage` structurally cannot hold one
    (INV 1). Lossless because `previously_allowed` is rebuilt from exactly this column on later
    turns, and a lossy copy would silently change what the `ALREADY_REVEALED` block says.
    """
    return {
        "allowed": [fact.model_dump(mode="json") for fact in package.allowed],
        "unavailable": [fact.model_dump(mode="json") for fact in package.unavailable],
        "withheld_count": package.withheld_count,
        "metadata": package.metadata.model_dump(mode="json"),
        "decisions": [decision.model_dump(mode="json") for decision in decisions],
    }


def allowed_facts_from_gate_output(document: Mapping[str, Any] | str | None) -> list[AllowedFact]:
    """The `allowed` rows of one persisted `gate_output`, or `[]` for anything unreadable.

    Total on purpose: a turn whose `gate_output` predates this column's shape must degrade to an
    empty `ALREADY_REVEALED` block, not fail the current turn.
    """
    if document is None:
        return []
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except ValueError:
            return []
    if not isinstance(document, Mapping):
        return []
    rows = document.get("allowed")
    if not isinstance(rows, list | tuple):
        return []
    facts: list[AllowedFact] = []
    for row in rows:
        if isinstance(row, Mapping) and "value_ru" not in row:
            # E13-B4 item 0: `gate_output` persisted before `AllowedFact.value_ru` existed has no
            # such key. `str(value)` is not `render_value_ru` (no `value_type`/`enum_name` survive
            # in a bare `gate_output` row either) — there is no production data behind this column
            # yet, only tests that persist packages, so a plain string default is enough to load.
            row = {**row, "value_ru": str(row.get("value"))}
        try:
            facts.append(AllowedFact.model_validate(row))
        except Exception:
            continue
    return facts


class DialogueContextLoader:
    """`load(session_id)` — one read-only transaction per turn (R4)."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        *,
        window_turns: int = 6,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._window_turns = window_turns

    async def load(self, session_id: SessionId) -> DialogueTurnInputs:
        """Assemble `DialogueTurnInputs` for the next turn of `session_id`."""
        async with self._uow_factory() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise DialogueContextUnavailableError(f"session {session_id} does not exist")
            version = await _scenario_version(uow, session.scenario_version_id)
            belief = await uow.caller_beliefs.get(session.incident.incident_id)
            if belief is None:
                raise DialogueContextUnavailableError(
                    f"incident {session.incident.incident_id} has no incident_caller_beliefs row"
                )
            events = await uow.events.read(session_id)
            turns = await uow.dialogue_turns.list_for_session(session_id)
            transcripts = await uow.transcript_segments.list_for_session(session_id)

        definitions = build_fact_definitions(version)
        window, operator_utterances = _window(turns, transcripts, self._window_turns)
        fired = frozenset(
            str(event.payload.get("world_event_id"))
            for event in events
            if event.event_type is EventType.WORLD_EVENT_TRIGGERED
            and isinstance(event.payload.get("world_event_id"), str)
        )
        previously_allowed: dict[str, AllowedFact] = {}
        for turn in turns:
            for fact in allowed_facts_from_gate_output(turn.gate_output):
                previously_allowed[fact.fact_id] = fact

        return DialogueTurnInputs(
            definitions=definitions,
            catalog=build_fact_catalog(definitions),
            caller_profile=version.caller_profile,
            caller_belief=belief,
            emotion=belief.emotion,
            revealed_fact_ids=fold_revealed(events),
            previously_allowed=previously_allowed,
            fired_world_event_ids=fired,
            # `conditions` stays `None`: a `ConditionContext` carries a `WorldTruth` (§10.11) and
            # this loader must not return one (D3, R4). The gate is total — a condition-shaped
            # `available_after` is then simply unmet (E13-A §3). TODO(E17): a world-truth-free
            # projection of `ConditionContext` would let condition-gated facts open here too; no
            # scenario in the repository uses one for a fact.
            condition_ctx=GateConditionContext(fired_world_event_ids=fired, conditions=None),
            window=window,
            operator_utterances=operator_utterances,
            now_ms=session_offset_ms(self._clock.now(), session.started_at),
        )


async def _scenario_version(uow: UnitOfWork, scenario_version_id: Any) -> ScenarioVersion:
    document = await uow.scenarios.get_version_document(scenario_version_id)
    if document is None:
        raise DialogueContextUnavailableError(
            f"scenario version {scenario_version_id} has no stored content"
        )
    return ScenarioVersion.model_validate(dict(document))


def _window(
    turns: Sequence[StoredDialogueTurn],
    transcripts: Sequence[Any],
    window_turns: int,
) -> tuple[tuple[DialogueTurn, ...], tuple[str, ...]]:
    """The last `window_turns` operator/caller pairs, oldest first (§5.2's turn-window policy)."""
    texts = {segment.id: segment.text for segment in transcripts}
    rendered: list[DialogueTurn] = []
    operator_texts: list[str] = []
    for turn in sorted(turns, key=lambda row: row.turn_index)[-window_turns:]:
        operator = texts.get(turn.operator_transcript_segment_id, "")
        if operator:
            rendered.append(DialogueTurn(speaker="OPERATOR", text=operator))
            operator_texts.append(operator)
        # E14: the caller side of the window is what the trainee actually **heard**. An
        # interrupted utterance's `delivered_text` is a prefix of `planned_text` (§6.3), and a
        # caller who then "continues" from the full planned wording would be answering a
        # conversation that did not happen. `planned_text` is the fallback only for a turn that
        # has no delivered text yet — one still being spoken, or one E13 planned before the sink
        # ever ran.
        caller = (
            texts.get(turn.caller_transcript_segment_id) or turn.delivered_text or turn.planned_text
        )
        if caller:
            rendered.append(DialogueTurn(speaker="CALLER", text=caller))
    return tuple(rendered), tuple(operator_texts)

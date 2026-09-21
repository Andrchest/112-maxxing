"""Builders shared by the E13-B2 dialogue tests (HLD `50-voice-pipeline.md` §3.5-§3.7, §5, §7).

Everything here is deterministic and modelless (D13): the demo scenario's own definitions, the
`CallerBelief` they instantiate to, and small helpers for building an `AllowedFactsPackage` by
running the **real** Fact Access Gate rather than by hand — a package a test invented could not
prove anything about the boundary the gate is supposed to enforce.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from app.application.dialogue.interpreter import (
    InterpretedUtterance,
    RequestedFact,
)
from app.domain.caller.emotion import EmotionState
from app.domain.caller.profile import CallerProfile
from app.domain.common.ids import IncidentId
from app.domain.enums import EmotionLabel, SpeechAct
from app.domain.facts.definitions import FactDefinition
from app.domain.facts.gate import (
    AllowedFactsPackage,
    FactRequest,
    GateConditionContext,
    GateDecision,
    evaluate_fact_access,
)
from app.domain.layers.caller_belief import CallerBelief
from app.domain.scenario.validation import build_fact_definitions
from app.domain.scenario.version import ScenarioVersion

from tests.fixtures.scenarios import demo_document

INCIDENT_ID = IncidentId(UUID("11111111-2222-3333-4444-555555555555"))


def demo_version() -> ScenarioVersion:
    """The demo scenario, parsed by the one parser (`app.domain.scenario`)."""
    return ScenarioVersion.model_validate(demo_document())


def demo_definitions() -> dict[str, FactDefinition]:
    """`fact_id -> FactDefinition` for the demo scenario, in declaration order."""
    return dict(build_fact_definitions(demo_version()))


def demo_profile() -> CallerProfile:
    """The demo scenario's caller persona (a `CallerProfileSection`, which *is* a profile)."""
    return demo_version().caller_profile


def demo_belief(
    definitions: Mapping[str, FactDefinition] | None = None,
    *,
    revealed: frozenset[str] = frozenset(),
    emotion: EmotionState | None = None,
) -> CallerBelief:
    """What `instantiate_caller_belief` produces for `definitions` — caller values only."""
    facts = definitions if definitions is not None else demo_definitions()
    return CallerBelief(
        incident_id=INCIDENT_ID,
        revision=0,
        facts={fact_id: item.caller_value for fact_id, item in facts.items()},
        knowledge={fact_id: item.knowledge for fact_id, item in facts.items()},
        certainty={fact_id: item.certainty for fact_id, item in facts.items()},
        emotion=emotion or EmotionState(emotion=EmotionLabel.FRIGHTENED, stress_level=0.6),
        revealed_fact_ids=revealed,
    )


def gate_package(
    fact_ids: Sequence[str],
    *,
    explicit: bool = True,
    definitions: Mapping[str, FactDefinition] | None = None,
    belief: CallerBelief | None = None,
    revealed: frozenset[str] = frozenset(),
    now_ms: int = 0,
    max_spontaneous_per_turn: int = 0,
) -> tuple[AllowedFactsPackage, tuple[GateDecision, ...]]:
    """Run the **real** gate for `fact_ids` and return what it decided.

    `max_spontaneous_per_turn` defaults to 0 here so a test that asks about one fact gets a
    package about that one fact; the responder's own tests use the production default.
    """
    facts = definitions if definitions is not None else demo_definitions()
    return evaluate_fact_access(
        [FactRequest(fact_id=fact_id, explicit=explicit) for fact_id in fact_ids],
        facts,
        belief or demo_belief(facts, revealed=revealed),
        revealed,
        now_ms,
        GateConditionContext(),
        max_spontaneous_per_turn,
    )


def interpreted(
    *fact_ids: str,
    speech_act: SpeechAct = SpeechAct.QUESTION,
    explicit: bool = True,
    confidence: float = 0.9,
) -> InterpretedUtterance:
    """A minimal `InterpretedUtterance` asking about `fact_ids`."""
    return InterpretedUtterance(
        speech_act=speech_act,
        requested_facts=tuple(
            RequestedFact(fact_id=fact_id, explicit=explicit) for fact_id in fact_ids
        ),
        operator_assertions=(),
        confirmation_targets=(),
        semantic_confidence=confidence,
    )


def scenario_values(definitions: Mapping[str, FactDefinition]) -> tuple[str, ...]:
    """Every world and caller value of `definitions`, rendered — the leak-scan haystack needles."""
    values: list[str] = []
    for definition in definitions.values():
        for value in (definition.world_value, definition.caller_value):
            if value is None or isinstance(value, bool):
                continue
            rendered = str(value).strip()
            if len(rendered) >= 2:
                values.append(rendered)
    return tuple(dict.fromkeys(values))

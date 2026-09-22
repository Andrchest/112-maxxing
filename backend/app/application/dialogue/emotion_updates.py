"""Dialogue-side emotion updates (HLD `10-domain-model.md` §10.5, SPEC §6, §23, D4, R7).

**The model never sets the emotion.** SPEC §23 has the caller "speak as the persona"; §10.5 and D4
make `current_emotion`/`stress_level` simulation state that changes only through deterministic
`EmotionRule`s. The caller prompt therefore *renders* the live `EmotionState` and the generator has
no way to write one back; this module is the only dialogue-side writer, and every trigger it takes
is built by code from a fact the engine or the pipeline observed.

It is the transactional twin of `app.domain.world.apply`'s `_run_emotion_rules`, and it deliberately
reuses that function's storage rather than inventing a second counter: `max_applications` is bounded
by `world_engine_states.emotion_applications`, the same mapping the world engine's tick reads and
writes (`WorldEngineState.emotion_applications`). Two counters would mean a rule capped at one
application could fire twice — once per code path — which is exactly the determinism §10.5 promises.

E13 called this for **no trigger yet**; E14's `app.application.voice.tts_speech_sink.TtsSpeechSink`
fires both dialogue-side triggers of §10.5 — `FACT_REVEALED` once per fact behind an uninterrupted
`FACTS_DELIVERED`, and `INTERRUPTION_COUNT` (folded from the log) behind
`CALLER_UTTERANCE_INTERRUPTED`. The function is unit-tested directly as well.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.simulation.sim_time import running_ms
from app.domain.caller.emotion import EmotionRule, EmotionState, EmotionTrigger, apply_emotion_rules
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion
from app.domain.session.session import SimulationSession

__all__ = ["EmotionChange", "apply_dialogue_emotion_trigger", "caller_emotion_changed_payload"]

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)


@dataclass(frozen=True, slots=True)
class EmotionChange:
    """What one applied rule changed. `None` is returned when no rule matched."""

    previous: EmotionState
    new: EmotionState
    emotion_rule_id: str
    trigger_kind: str


def caller_emotion_changed_payload(
    previous: EmotionState, new: EmotionState, rule_id: str | None, trigger_kind: str, now_ms: int
) -> dict[str, object]:
    """`CALLER_EMOTION_CHANGED` (§10.13) — the payload shape `world/apply.py` emits, verbatim."""
    return {
        "previous_emotion": previous.emotion.value,
        "new_emotion": new.emotion.value,
        "previous_stress_level": previous.stress_level,
        "new_stress_level": new.stress_level,
        "emotion_rule_id": rule_id,
        "trigger_kind": trigger_kind,
        "at_offset_ms": now_ms,
    }


async def apply_dialogue_emotion_trigger(
    uow_factory: UnitOfWorkFactory,
    session_id: SessionId,
    trigger: EmotionTrigger,
    *,
    clock: Clock,
    trigger_kind: str,
    offset_ms: int | None = None,
) -> EmotionChange | None:
    """Apply the first matching `EmotionRule` for `trigger`, in one transaction (§10.5, R7).

    Load the belief and the engine's `emotion_applications` → `apply_emotion_rules` (the existing
    pure function) → save both → append `CALLER_EMOTION_CHANGED`. Nothing is written when no rule
    matches, and nothing here decides a session state (D7): an emotion is a caller-belief fact.
    """
    async with uow_factory() as uow:
        session = await uow.sessions.get(session_id)
        if session is None:
            return None
        incident_id = session.incident.incident_id
        belief = await uow.caller_beliefs.get(incident_id)
        engine_state = await uow.world_engine_states.get(incident_id)
        if belief is None or engine_state is None:
            return None
        rules = await _emotion_rules(uow, session)
        if not rules:
            return None

        previous = belief.emotion
        applied_counts = dict(engine_state.emotion_applications)
        new_emotion, rule_id = apply_emotion_rules(previous, rules, trigger, applied_counts)
        if rule_id is None:
            return None

        applied_counts[rule_id] = applied_counts.get(rule_id, 0) + 1
        await uow.caller_beliefs.save(belief.model_copy(update={"emotion": new_emotion}))
        await uow.world_engine_states.save(
            engine_state.model_copy(update={"emotion_applications": applied_counts})
        )

        now_ms = offset_ms if offset_ms is not None else running_ms(session, clock.now())
        payload = caller_emotion_changed_payload(
            previous, new_emotion, rule_id, trigger_kind, now_ms
        )
        validate_payload(EventType.CALLER_EMOTION_CHANGED, payload)
        await uow.events.append(
            session_id,
            [
                DomainEvent(
                    event_type=EventType.CALLER_EMOTION_CHANGED,
                    actor=_SIMULATION,
                    monotonic_offset_ms=now_ms,
                    payload=dict(payload),
                )
            ],
        )
        await uow.commit()

    return EmotionChange(
        previous=previous,
        new=new_emotion,
        emotion_rule_id=rule_id,
        trigger_kind=trigger_kind,
    )


async def _emotion_rules(uow: UnitOfWork, session: SimulationSession) -> tuple[EmotionRule, ...]:
    """The session's locked scenario version's `caller_profile.emotion_rules` (D4)."""
    document = await uow.scenarios.get_version_document(session.scenario_version_id)
    if document is None:
        return ()
    version = ScenarioVersion.model_validate(dict(document))
    return version.caller_profile.emotion_rules

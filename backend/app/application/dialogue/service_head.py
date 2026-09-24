"""`ServiceHeadResponder` — the service head's side of a ДДС call (HLD `80-telephony.md` §80.4,
§80.3.3, D24; I3 E6c).

The `TranscribedTurnResponder` the voice agent puts behind ASR for a `SERVICE_HEAD` call, in place
of the frozen caller chain. One trainee turn, in this fixed order:

1. `ResponderContextLoader.load` — the head's knowledge now: script + snapshot, nothing else
   (INV 1/3; no WorldTruth or CallerBelief repository exists anywhere on this path);
2. the existing `DialogueInterpreter` against `RESPONDER_SLOT_CATALOG` →
   `DIALOGUE_INTERPRETED` (+ `MODEL_FALLBACK_USED` when its ladder fell);
3. `ResponderTemplates.plan` — the line, the due steps it reports and the card facts the trainee
   stated, all decided by code; one `DDS_CALL_ASSERTION` (MODEL) per stated fact;
4. `Settings.responder_dialogue = llm` only: the model rewords the line
   (`ResponderPromptBuilder`), the words are checked by code (`responder_line_violations`: no
   number outside the knowledge and the trainee's words, no scenario value outside the knowledge)
   and any failure — a timeout, an invalid answer, a leak — is the template line with
   `MODEL_FALLBACK_USED` (INV 14: the head never goes silent);
5. the line is spoken through the call's speech sink (the persona's voice), **last**;
6. only once it has been heard to its end — not on a barge-in — one `DDS_CALL_STATUS_PROPOSED`
   (SIMULATION) per reported step, carrying the step's due offset (INV 7) and `at_offset_ms`, the
   moment it was said. A proposal changes no leg: the trainee commits it with `setDdsServiceStatus
   {proposed_by_call_id}` (INV 4, D24).

The first reply of a call opens with the persona's greeting («Начальник караула, слушаю.»).

**The AI 112 operator (I3 E6d, HLD 80 §80.3.4).** A call to 112 (`call_kind: OPERATOR_112`) runs
this same responder: the loader hands it the operator's knowledge (the snapshot only), the
templates follow REQ-5332's checklist — one `DDS_CALL_ASSERTION` per item the ДДС covered, the
next missing item asked for — and nothing is ever proposed (the operator reports no status).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.application.dialogue.events import (
    dialogue_interpreted_payload,
    model_fallback_used_payload,
)
from app.application.dialogue.interpreter import (
    RESPONDER_SLOT_CATALOG,
    DialogueInterpreter,
    DialogueTurn,
    InterpretationOutcome,
)
from app.application.dialogue.responder_context import (
    DueStep,
    ResponderContextLoader,
    ResponderKnowledge,
)
from app.application.dialogue.responder_prompt_builder import (
    RESPONDER_JSON_SCHEMA,
    RESPONDER_SCHEMA_NAME,
    ResponderPromptBuilder,
    responder_line_violations,
)
from app.application.dialogue.responder_templates import (
    ResponderAssertion,
    ResponderPlan,
    ResponderTemplates,
)
from app.application.dialogue.speech_sink import (
    CallerSpeechSink,
    PlannedCallerUtterance,
    UtteranceSource,
)
from app.application.ports.llm import JsonSchemaSpec, LLMClient
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.voice.turn_pipeline import TranscribedTurn, TurnContext
from app.domain.caller.emotion import EmotionState
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType, EmotionLabel
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = [
    "RESPONDER_DIALOGUE_MODES",
    "LeakValuesProbe",
    "ResponderDialogue",
    "ResponderTurnOutcome",
    "ServiceHeadResponder",
    "known_facts_of",
]

logger = logging.getLogger(__name__)

type ResponderDialogue = Literal["template", "llm"]
RESPONDER_DIALOGUE_MODES: tuple[ResponderDialogue, ...] = ("template", "llm")

type LeakValuesProbe = Callable[[SessionId], Awaitable[Sequence[str]]]
"""Every scenario value of the session (world and caller), for the `llm` leak check only — the
check is code and may see them (D10); nothing of it ever reaches the prompt."""

_MODEL = ActorRef(actor_type=ActorType.MODEL)
_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)
_SYSTEM = ActorRef(actor_type=ActorType.SYSTEM)
_NEUTRAL = EmotionState(emotion=EmotionLabel.CALM, stress_level=0.0)
"""A service head is on duty: one calm voice, whatever the incident."""

_INTERPRETER_COMPONENT = "INTERPRETER"
_GENERATOR_COMPONENT = "GENERATOR"


@dataclass(frozen=True, slots=True)
class ResponderTurnOutcome:
    """What one head turn decided — returned for tests."""

    knowledge: ResponderKnowledge
    interpretation: InterpretationOutcome
    plan: ResponderPlan
    text: str
    source: UtteranceSource
    proposed: tuple[DueStep, ...]


def known_facts_of(knowledge: ResponderKnowledge) -> list[str]:
    """`KNOWN_FACTS` of the paraphrase prompt: the snapshot checklist and the due steps."""
    templates = ResponderTemplates()
    facts = [f"{item.label_ru}: {item.value}" for item in knowledge.checklist]
    facts.extend(templates.status_line(knowledge.persona, due) for due in knowledge.steps_due)
    if knowledge.leg_order_number:
        facts.append(f"Номер наряда: {knowledge.leg_order_number}")
    return facts


class ServiceHeadResponder:
    """`TranscribedTurnResponder` for a `SERVICE_HEAD` call (see the module docstring)."""

    def __init__(
        self,
        *,
        loader: ResponderContextLoader,
        interpreter: DialogueInterpreter,
        sink: CallerSpeechSink,
        uow_factory: UnitOfWorkFactory,
        templates: ResponderTemplates | None = None,
        mode: ResponderDialogue = "template",
        llm: LLMClient | None = None,
        prompt_builder: ResponderPromptBuilder | None = None,
        leak_values: LeakValuesProbe | None = None,
        llm_timeout_ms: int = 4000,
        llm_max_tokens: int = 160,
    ) -> None:
        if mode not in RESPONDER_DIALOGUE_MODES:
            raise ValueError(f"responder_dialogue must be one of {RESPONDER_DIALOGUE_MODES}")
        self._loader = loader
        self._interpreter = interpreter
        self._sink = sink
        self._uow_factory = uow_factory
        self._templates = templates or ResponderTemplates()
        self._mode: ResponderDialogue = mode
        self._llm = llm
        self._builder = prompt_builder or ResponderPromptBuilder()
        self._leak_values = leak_values
        self._llm_timeout_ms = llm_timeout_ms
        self._llm_max_tokens = llm_max_tokens
        #: Calls whose first reply (with the greeting) has been spoken.
        self._greeted: set[uuid.UUID] = set()
        #: This call's recent turns, for the interpreter and the paraphrase prompt.
        self._windows: dict[uuid.UUID, list[DialogueTurn]] = {}

    @property
    def mode(self) -> ResponderDialogue:
        return self._mode

    async def respond_transcribed(self, transcribed: TranscribedTurn, context: TurnContext) -> None:
        await self.run_turn(transcribed, context)

    async def run_turn(
        self, transcribed: TranscribedTurn, context: TurnContext
    ) -> ResponderTurnOutcome:
        """One trainee turn on the call (the module docstring's order)."""
        turn_id = transcribed.turn.turn_id
        knowledge = await self._loader.load(context.session_id, context.call_id)
        window = self._windows.setdefault(context.call_id, [])

        outcome = await self._interpreter.interpret(
            transcribed.text,
            tuple(window),
            RESPONDER_SLOT_CATALOG,
            request_id=f"{turn_id}:interpret",
            turn_index=transcribed.turn_index,
            session_id=uuid.UUID(str(context.session_id)),
            turn_id=turn_id,
        )
        await self._append(
            context,
            EventType.DIALOGUE_INTERPRETED,
            _MODEL,
            {
                **dialogue_interpreted_payload(turn_index=transcribed.turn_index, outcome=outcome),
                "call_id": context.call_id,
            },
            turn_id,
        )
        if outcome.fallback_used:
            await self._fallback_event(
                context,
                transcribed,
                component=_INTERPRETER_COMPONENT,
                reason=outcome.failure_reason or "UNKNOWN",
                fallback_kind="UNINTELLIGIBLE_FALLBACK",
            )

        greeted = context.call_id in self._greeted
        plan = self._templates.plan(
            knowledge, outcome.interpretation, transcribed.text, greeted=greeted
        )
        for assertion in plan.assertions:
            await self._assert(context, turn_id, assertion)

        text, source = await self._wording(context, transcribed, knowledge, plan, window)
        await self._persist(context, transcribed, outcome, plan, text, source)
        self._greeted.add(context.call_id)
        window.extend(
            (DialogueTurn(speaker="OPERATOR", text=transcribed.text), DialogueTurn("CALLER", text))
        )
        del window[:-8]

        await self._sink.speak(
            PlannedCallerUtterance(
                turn_id=turn_id,
                turn_index=transcribed.turn_index,
                text=text,
                fact_ids=(),
                emotion=_NEUTRAL,
                source=source,
            ),
            context,
        )
        # Heard to the end (a barge-in cancels `speak` and skips this): the head has now said it.
        for due in plan.proposals:
            await self._propose(context, knowledge, due)
        return ResponderTurnOutcome(
            knowledge=knowledge,
            interpretation=outcome,
            plan=plan,
            text=text,
            source=source,
            proposed=plan.proposals,
        )

    # -- the words -----------------------------------------------------------------------------

    async def _wording(
        self,
        context: TurnContext,
        transcribed: TranscribedTurn,
        knowledge: ResponderKnowledge,
        plan: ResponderPlan,
        window: Sequence[DialogueTurn],
    ) -> tuple[str, UtteranceSource]:
        """The template line, or — `llm` mode — its checked paraphrase (else the template)."""
        if self._mode != "llm" or self._llm is None:
            return plan.text, "FALLBACK"
        known = known_facts_of(knowledge)
        try:
            completion = await self._llm.complete(
                self._builder.build(knowledge.persona, known, window, transcribed.text, plan.text),
                request_id=f"{transcribed.turn.turn_id}:responder",
                max_tokens=self._llm_max_tokens,
                temperature=0.3,
                response_format=JsonSchemaSpec(
                    name=RESPONDER_SCHEMA_NAME, schema=RESPONDER_JSON_SCHEMA, strict=True
                ),
                timeout_ms=self._llm_timeout_ms,
            )
            utterance = str(json.loads(completion.text)["utterance"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # INV 14: any model failure is the template line
            await self._fallback_event(
                context,
                transcribed,
                component=_GENERATOR_COMPONENT,
                reason=type(exc).__name__,
                fallback_kind="DETERMINISTIC_TEMPLATE",
            )
            return plan.text, "FALLBACK"
        forbidden = (
            await self._leak_values(context.session_id) if self._leak_values is not None else ()
        )
        persona_words = (
            ()
            if knowledge.persona is None
            else (knowledge.persona.title_ru, knowledge.persona.greeting_ru)
        )
        allowed = [plan.text, *known, transcribed.text, *persona_words]
        allowed.extend(turn.text for turn in window if turn.speaker == "OPERATOR")
        problems = responder_line_violations(utterance, allowed, forbidden)
        if problems:
            await self._fallback_event(
                context,
                transcribed,
                component=_GENERATOR_COMPONENT,
                reason=",".join(problems),
                fallback_kind="DETERMINISTIC_TEMPLATE",
            )
            return plan.text, "FALLBACK"
        return utterance.strip(), "LLM"

    # -- events and rows -----------------------------------------------------------------------

    async def _assert(
        self, context: TurnContext, turn_id: uuid.UUID, assertion: ResponderAssertion
    ) -> None:
        await self._append(
            context,
            EventType.DDS_CALL_ASSERTION,
            _MODEL,
            {
                "call_id": context.call_id,
                "turn_id": turn_id,
                "field_path": assertion.field_path,
                "value_ru": assertion.value_ru,
                "matches_snapshot": assertion.matches_snapshot,
                "at_offset_ms": context.appender.offset_ms(),
            },
            turn_id,
        )

    async def _propose(
        self, context: TurnContext, knowledge: ResponderKnowledge, due: DueStep
    ) -> None:
        await self._append(
            context,
            EventType.DDS_CALL_STATUS_PROPOSED,
            _SIMULATION,
            {
                "call_id": context.call_id,
                "assignment_id": knowledge.assignment_id,
                "service_type": knowledge.service_type,
                "status": due.step.status.value,
                "order_number": due.step.order_number,
                "comment_ru": due.step.comment_ru,
                "script_after_ms": due.step.after_ms,
                "due_offset_ms": due.due_offset_ms,
                "at_offset_ms": context.appender.offset_ms(),
            },
            None,
        )

    async def _fallback_event(
        self,
        context: TurnContext,
        transcribed: TranscribedTurn,
        *,
        component: str,
        reason: str,
        fallback_kind: str,
    ) -> None:
        await self._append(
            context,
            EventType.MODEL_FALLBACK_USED,
            _SYSTEM,
            {
                **model_fallback_used_payload(
                    component=component,  # type: ignore[arg-type]
                    reason=reason,
                    attempt=1,
                    fallback_kind=fallback_kind,
                    turn_index=transcribed.turn_index,
                ),
                "turn_id": str(transcribed.turn.turn_id),
                "stage": component,
                "call_id": str(context.call_id),
            },
            transcribed.turn.turn_id,
        )

    async def _persist(
        self,
        context: TurnContext,
        transcribed: TranscribedTurn,
        outcome: InterpretationOutcome,
        plan: ResponderPlan,
        text: str,
        source: UtteranceSource,
    ) -> None:
        """`dialogue_turns.{interpretation, gate_output, planned_text, fallback_used}` (§20.6);
        `gate_output` records the responder's own decision (no Fact Access Gate on this call)."""
        try:
            async with self._uow_factory() as uow:
                await uow.dialogue_turns.set_dialogue_outcome(
                    context.session_id,
                    transcribed.turn_index,
                    interpretation=dialogue_interpreted_payload(
                        turn_index=transcribed.turn_index, outcome=outcome
                    ),
                    gate_output={
                        "responder": {
                            "template_row": plan.template_row,
                            "slots": list(plan.slots),
                            "proposed": [
                                {
                                    "status": due.step.status.value,
                                    "due_offset_ms": due.due_offset_ms,
                                }
                                for due in plan.proposals
                            ],
                        }
                    },
                    planned_text=text,
                    fallback_used=source == "FALLBACK" and self._mode == "llm",
                )
                await uow.commit()
        except Exception:  # a read-model row must never cost the head its answer
            logger.exception("could not record the responder turn %s", transcribed.turn_index)

    async def _append(
        self,
        context: TurnContext,
        event_type: EventType,
        actor: ActorRef,
        payload: dict[str, object],
        turn_id: uuid.UUID | None,
    ) -> None:
        validate_payload(event_type, payload)
        await context.appender.append(
            [
                DomainEvent(
                    event_type=event_type,
                    actor=actor,
                    monotonic_offset_ms=context.appender.offset_ms(),
                    correlation_id=turn_id,
                    payload=dict(payload),
                )
            ]
        )

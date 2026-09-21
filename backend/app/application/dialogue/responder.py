"""`DialogueResponder` — the chain behind ASR (§3.3–§3.6, §3.7, SPEC §16, §21, §24, §42 item 14).

One class, one job: run the fixed stage order of SPEC §16 and append the events of §3.7, in that
order, exactly once each. It decides nothing itself — the interpreter, the Fact Access Gate, the
generator, the validator and §7.8's table each own one decision, and this class is the sequencer
that puts them in the documented order and writes down what happened.

The order (R8, §3.7's "per-turn event order for a normal turn"):

```
DIALOGUE_INTERPRETED            (+ MODEL_FALLBACK_USED{stage: INTERPRETER} when B1's ladder fell)
FACT_GATE_EVALUATED
CALLER_RESPONSE_PLANNED         — before any generation call, from gate output alone
CALLER_RESPONSE_GENERATED       — only for a validated model answer
MODEL_ERROR / MODEL_FALLBACK_USED{stage: GENERATOR|VALIDATOR}  — when it was not
```

Each event is appended in **its own short unit of work**, mirroring `AsrTurnResponder._persist`:
the plan must survive a generation failure, so a single long transaction around the whole turn
would be exactly the wrong shape (SPEC §42 item 14, INV 14).

**The caller never goes silent.** A timeout, a transport error, a prompt that does not fit §5.3's
budget, an invalid answer twice over — every one of them ends in §7.8's deterministic template, and
`dialogue_turns.fallback_used` records it. The one exception is `asyncio.CancelledError`: a
cancelled turn is a barge-in (a newer turn arrived), so nothing is spoken, no fallback is produced
and the cancellation is re-raised after the generator's metric is recorded as `CANCELLED`.

**E13 emits no `CALLER_TTS_*` and no `FACTS_DELIVERED`** (the shared ruling 5). The decided
utterance goes to a `CallerSpeechSink`, last, after every event and row of the turn is committed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from app.application.dialogue.dialogue_context import (
    DialogueContextLoader,
    DialogueTurnInputs,
    gate_output_document,
)
from app.application.dialogue.events import (
    ModelFallbackComponent,
    caller_response_generated_payload,
    caller_response_planned_payload,
    dialogue_interpreted_payload,
    fact_gate_evaluated_payload,
    model_fallback_used_payload,
)
from app.application.dialogue.fallbacks import FallbackChoice, FallbackTemplates
from app.application.dialogue.forbidden_values import forbidden_values
from app.application.dialogue.generator import (
    GENERATOR_COMPONENT,
    PROMPT_BUDGET_REASON,
    CallerResponseGenerator,
    GeneratedResponse,
    ValidationInputs,
)
from app.application.dialogue.interpreter import (
    DialogueInterpreter,
    InterpretationOutcome,
    InterpretedUtterance,
)
from app.application.dialogue.prompt_builder import PromptBudgetExceededError
from app.application.dialogue.speech_sink import (
    CallerSpeechSink,
    PlannedCallerUtterance,
    UtteranceSource,
)
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.voice.events import model_error_event
from app.application.voice.turn_pipeline import TranscribedTurn, TurnContext
from app.domain.common.actors import ActorRef
from app.domain.enums import ActorType
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.facts.gate import (
    AllowedFactsPackage,
    FactRequest,
    GateDecision,
    evaluate_fact_access,
)
from app.domain.facts.revealed import facts_delivered

__all__ = ["DialogueResponder", "TurnOutcome"]

logger = logging.getLogger(__name__)

_MODEL = ActorRef(actor_type=ActorType.MODEL)
_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)

#: `MODEL_FALLBACK_USED.component` values this responder emits (§10.13).
INTERPRETER_COMPONENT: ModelFallbackComponent = "INTERPRETER"
#: `MODEL_FALLBACK_USED.fallback_kind` values (§5.1, §7.8).
INTERPRETER_FALLBACK_KIND = "UNINTELLIGIBLE_FALLBACK"
GENERATOR_FALLBACK_KIND = "DETERMINISTIC_TEMPLATE"


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """What one dialogue turn decided — returned for tests and for E14's future call sites."""

    interpretation: InterpretedUtterance
    package: AllowedFactsPackage
    decisions: tuple[GateDecision, ...]
    planned: PlannedCallerUtterance
    fallback_used: bool
    generated: GeneratedResponse | None


class DialogueResponder:
    """`TranscribedTurnResponder` for the interpret → gate → generate → validate chain (R1, R8)."""

    def __init__(
        self,
        *,
        loader: DialogueContextLoader,
        interpreter: DialogueInterpreter,
        generator: CallerResponseGenerator,
        fallbacks: FallbackTemplates,
        sink: CallerSpeechSink,
        uow_factory: UnitOfWorkFactory,
        max_spontaneous_per_turn: int = 2,
    ) -> None:
        self._loader = loader
        self._interpreter = interpreter
        self._generator = generator
        self._fallbacks = fallbacks
        self._sink = sink
        self._uow_factory = uow_factory
        self._max_spontaneous_per_turn = max_spontaneous_per_turn

    async def respond_transcribed(self, transcribed: TranscribedTurn, context: TurnContext) -> None:
        """Run the whole chain for one finalized, non-empty trainee turn (R8's fixed order)."""
        await self.run_turn(transcribed, context)

    async def run_turn(
        self, transcribed: TranscribedTurn, context: TurnContext
    ) -> TurnOutcome | None:
        """`respond_transcribed`, returning what it decided; the seam method just discards it."""
        inputs = await self._loader.load(context.session_id)
        turn_id = transcribed.turn.turn_id
        turn_index = transcribed.turn_index

        # 2. interpret ------------------------------------------------------------------------
        outcome = await self._interpret(transcribed, context, inputs)
        await self._append(
            context,
            EventType.DIALOGUE_INTERPRETED,
            _MODEL,
            dialogue_interpreted_payload(turn_index=turn_index, outcome=outcome),
            turn_id,
        )
        if outcome.fallback_used:
            await self._append(
                context,
                EventType.MODEL_FALLBACK_USED,
                ActorRef(actor_type=ActorType.SYSTEM),
                {
                    **model_fallback_used_payload(
                        component=INTERPRETER_COMPONENT,
                        reason=outcome.failure_reason or "UNKNOWN",
                        attempt=1 if outcome.repair_retry_used else 0,
                        fallback_kind=INTERPRETER_FALLBACK_KIND,
                        turn_index=turn_index,
                    ),
                    "turn_id": str(turn_id),
                    "stage": INTERPRETER_COMPONENT,
                },
                turn_id,
            )

        # 3. gate -----------------------------------------------------------------------------
        package, decisions = evaluate_fact_access(
            [
                FactRequest(fact_id=fact.fact_id, explicit=fact.explicit)
                for fact in outcome.interpretation.requested_facts
            ],
            inputs.definitions,
            inputs.caller_belief,
            inputs.revealed_fact_ids,
            inputs.now_ms,
            inputs.condition_ctx,
            self._max_spontaneous_per_turn,
        )
        # The gate's signature (§10.12) carries no turn index, so the turn pipeline — which owns
        # the turn counter — stamps it here. This is the stamp `gate.py`'s docstring defers to.
        package = package.model_copy(
            update={"metadata": package.metadata.model_copy(update={"turn_index": turn_index})}
        )
        await self._append(
            context,
            EventType.FACT_GATE_EVALUATED,
            _SIMULATION,
            fact_gate_evaluated_payload(
                turn_id=turn_id,
                turn_index=turn_index,
                package=package,
                decisions=decisions,
                at_offset_ms=context.appender.offset_ms(),
            ),
            turn_id,
        )

        # 4. plan -----------------------------------------------------------------------------
        await self._append(
            context,
            EventType.CALLER_RESPONSE_PLANNED,
            _SIMULATION,
            caller_response_planned_payload(
                call_id=context.call_id,
                turn_id=turn_id,
                turn_index=turn_index,
                package=package,
                emotion=inputs.emotion,
            ),
            turn_id,
        )

        # 5. generate -> validate -> (regenerate) -> fallback ----------------------------------
        generated, fallback = await self._answer(
            transcribed, context, inputs, package, outcome.interpretation
        )
        if generated is not None and generated.validated:
            text = generated.utterance
            fact_ids = facts_delivered(package, completed=True)
            source: UtteranceSource = "LLM"
            template_row = None
            await self._append(
                context,
                EventType.CALLER_RESPONSE_GENERATED,
                _MODEL,
                caller_response_generated_payload(
                    call_id=context.call_id,
                    turn_id=turn_id,
                    turn_index=turn_index,
                    text=text,
                    attempt=generated.attempt,
                    prompt_tokens=generated.usage.prompt_tokens if generated.usage else None,
                    completion_tokens=(
                        generated.usage.completion_tokens if generated.usage else None
                    ),
                    llm_provider=self._generator.model_name,
                    llm_model=self._generator.model_name,
                    regeneration_count=generated.regeneration_count,
                ),
                turn_id,
            )
        else:
            assert fallback is not None
            text = fallback.text
            fact_ids = fallback.fact_ids
            source = "FALLBACK"
            template_row = fallback.template_row

        planned = PlannedCallerUtterance(
            turn_id=turn_id,
            turn_index=turn_index,
            text=text,
            fact_ids=fact_ids,
            emotion=inputs.emotion,
            source=source,
            template_row=template_row,
        )

        # 6. the turn row ---------------------------------------------------------------------
        await self._persist_outcome(context, transcribed, outcome, package, decisions, planned)

        # 7. the sink, last -------------------------------------------------------------------
        await self._sink.speak(planned, context)

        return TurnOutcome(
            interpretation=outcome.interpretation,
            package=package,
            decisions=decisions,
            planned=planned,
            fallback_used=source == "FALLBACK",
            generated=generated,
        )

    # -- stages -------------------------------------------------------------------------------

    async def _interpret(
        self, transcribed: TranscribedTurn, context: TurnContext, inputs: DialogueTurnInputs
    ) -> InterpretationOutcome:
        """B1's interpreter, with the **real** session and turn ids for its metric row (R6)."""
        return await self._interpreter.interpret(
            transcribed.text,
            inputs.window,
            inputs.catalog,
            request_id=f"{transcribed.turn.turn_id}:interpret",
            turn_index=transcribed.turn_index,
            session_id=uuid.UUID(str(context.session_id)),
            turn_id=transcribed.turn.turn_id,
        )

    async def _answer(
        self,
        transcribed: TranscribedTurn,
        context: TurnContext,
        inputs: DialogueTurnInputs,
        package: AllowedFactsPackage,
        interpreted: InterpretedUtterance,
    ) -> tuple[GeneratedResponse | None, FallbackChoice | None]:
        """§7.7's flow, then §7.8's table. `asyncio.CancelledError` is never swallowed."""
        turn_id = transcribed.turn.turn_id
        try:
            generated = await self._generator.generate(
                package,
                inputs.caller_profile,
                inputs.emotion,
                inputs.already_revealed,
                inputs.window,
                transcribed.text,
                inputs=ValidationInputs(
                    revealed_values=inputs.revealed_values,
                    operator_utterances=inputs.operator_utterances,
                    persona_whitelist=tuple(inputs.caller_profile.persona_whitelist_ru),
                    forbidden_values=forbidden_values(
                        inputs.definitions, package, inputs.revealed_fact_ids
                    ),
                ),
                session_id=uuid.UUID(str(context.session_id)),
                turn_id=turn_id,
                request_id=f"{turn_id}:generate",
            )
        except asyncio.CancelledError:
            # A newer turn arrived (§3.7). Nothing is spoken and no fallback is produced.
            raise
        except PromptBudgetExceededError as exc:
            logger.warning("caller prompt over budget for turn %s: %s", turn_id, exc)
            await self._fallback_events(
                context,
                transcribed,
                reason=PROMPT_BUDGET_REASON,
                failure_codes=(),
                model_error=None,
            )
            return None, self._fallbacks.select(package, interpreted)

        if generated.validated:
            return generated, None

        await self._fallback_events(
            context,
            transcribed,
            reason=generated.fallback_reason,
            failure_codes=generated.failure_codes,
            model_error=generated.error_kind,
        )
        return generated, self._fallbacks.select(package, interpreted)

    async def _fallback_events(
        self,
        context: TurnContext,
        transcribed: TranscribedTurn,
        *,
        reason: str,
        failure_codes: Sequence[str],
        model_error: str | None,
    ) -> None:
        """`MODEL_ERROR` (when the call itself failed) and always `MODEL_FALLBACK_USED`."""
        turn_id = transcribed.turn.turn_id
        if model_error is not None:
            await context.appender.append(
                [
                    model_error_event(
                        offset_ms=context.appender.offset_ms(),
                        component=GENERATOR_COMPONENT,
                        provider=self._generator.model_name,
                        model=self._generator.model_name,
                        error_code=model_error,
                        message=f"the caller generator failed: {model_error}",
                        recoverable=True,
                        turn_index=transcribed.turn_index,
                        turn_id=turn_id,
                    )
                ]
            )
        await self._append(
            context,
            EventType.MODEL_FALLBACK_USED,
            ActorRef(actor_type=ActorType.SYSTEM),
            {
                **model_fallback_used_payload(
                    component=GENERATOR_COMPONENT,
                    reason=reason,
                    attempt=1,
                    fallback_kind=GENERATOR_FALLBACK_KIND,
                    turn_index=transcribed.turn_index,
                ),
                "turn_id": str(turn_id),
                "stage": GENERATOR_COMPONENT,
                "failure_codes": list(failure_codes),
            },
            turn_id,
        )

    async def _persist_outcome(
        self,
        context: TurnContext,
        transcribed: TranscribedTurn,
        outcome: InterpretationOutcome,
        package: AllowedFactsPackage,
        decisions: Sequence[GateDecision],
        planned: PlannedCallerUtterance,
    ) -> None:
        """`dialogue_turns.{interpretation, gate_output, planned_text, fallback_used}` (§20.6)."""
        async with self._uow_factory() as uow:
            await uow.dialogue_turns.set_dialogue_outcome(
                context.session_id,
                transcribed.turn_index,
                interpretation=dialogue_interpreted_payload(
                    turn_index=transcribed.turn_index, outcome=outcome
                ),
                gate_output=gate_output_document(package, decisions),
                planned_text=planned.text,
                fallback_used=planned.source == "FALLBACK",
            )
            await uow.commit()

    # -- the one append path -------------------------------------------------------------------

    async def _append(
        self,
        context: TurnContext,
        event_type: EventType,
        actor: ActorRef,
        payload: dict[str, object],
        turn_id: uuid.UUID,
    ) -> None:
        """One event, one short unit of work (§3.7, D5) — the shape `_persist` uses in E12."""
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

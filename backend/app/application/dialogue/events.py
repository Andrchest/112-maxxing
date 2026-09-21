"""Pure payload builders for `DIALOGUE_INTERPRETED` and `MODEL_FALLBACK_USED` (HLD `10-domain-
model.md` §10.13 event-payload catalog, `50-voice-pipeline.md` §3.3).

Builders only — nothing here appends a `SessionEvent`. `TurnPipeline` (E13-B2's responder) is the
only place that appends voice-path events, under the D5 `seq_no` row lock; this module just turns
an `InterpretationOutcome` into the dict shape the catalog fixes, byte-for-byte the same keys a
test can compare against `app.domain.events.catalog.EVENT_PAYLOAD_CATALOG`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Literal

from app.application.dialogue.interpreter import InterpretationOutcome
from app.domain.caller.emotion import EmotionState
from app.domain.facts.gate import AllowedFactsPackage, GateDecision

__all__ = [
    "ModelFallbackComponent",
    "caller_response_generated_payload",
    "caller_response_planned_payload",
    "dialogue_interpreted_payload",
    "fact_gate_evaluated_payload",
    "model_fallback_used_payload",
]

#: `MODEL_FALLBACK_USED.component` (§10.13). Only `"INTERPRETER"` is ever produced by this epic's
#: slice; the rest belong to the generator/validator/ASR/TTS stages of other epics.
ModelFallbackComponent = Literal["INTERPRETER", "GENERATOR", "VALIDATOR", "ASR", "TTS"]


def dialogue_interpreted_payload(
    *, turn_index: int, outcome: InterpretationOutcome
) -> dict[str, Any]:
    """`DIALOGUE_INTERPRETED` (§10.13): `{turn_index, speech_act, requested_facts,
    operator_assertions, confirmation_targets, semantic_confidence, repair_retry_used}`.

    Built from `outcome.interpretation` even when `outcome.fallback_used` is true — the fallback
    *is* an `InterpretedUtterance` (SPEC §20/§5.1), so the event still carries the shape the
    catalog fixes; a caller that also wants a `MODEL_FALLBACK_USED` row appends one separately via
    `model_fallback_used_payload`.
    """
    interpretation = outcome.interpretation
    return {
        "turn_index": turn_index,
        "speech_act": interpretation.speech_act.value,
        "requested_facts": [
            {"fact_id": fact.fact_id, "explicit": fact.explicit}
            for fact in interpretation.requested_facts
        ],
        "operator_assertions": [
            {"fact_id": assertion.fact_id, "asserted_value": assertion.asserted_value}
            for assertion in interpretation.operator_assertions
        ],
        "confirmation_targets": list(interpretation.confirmation_targets),
        "semantic_confidence": interpretation.semantic_confidence,
        "repair_retry_used": outcome.repair_retry_used,
    }


def model_fallback_used_payload(
    *,
    component: ModelFallbackComponent,
    reason: str,
    attempt: int,
    fallback_kind: str,
    turn_index: int | None,
) -> dict[str, Any]:
    """`MODEL_FALLBACK_USED` (§10.13): `{component, reason, attempt, fallback_kind, turn_index}`.

    For the interpreter's own fallback ladder (D10, §5.1), a caller builds this from an
    `InterpretationOutcome` with `outcome.fallback_used` true: `reason = outcome.failure_reason`,
    `attempt = 1` if `outcome.repair_retry_used` else `0`, `fallback_kind =
    "UNINTELLIGIBLE_FALLBACK"`, `component = "INTERPRETER"`.
    """
    return {
        "component": component,
        "reason": reason,
        "attempt": attempt,
        "fallback_kind": fallback_kind,
        "turn_index": turn_index,
    }


# ---------------------------------------------------------------------------------------------
# E13-B2: the gate, plan and generation payloads (§10.13, `50-voice-pipeline.md` §3.4-§3.6)
# ---------------------------------------------------------------------------------------------
#
# Builders only, like everything above: `DialogueResponder` appends them, one event per short
# unit of work, mirroring `AsrTurnResponder._persist`. Every payload carries the §10.13 catalog's
# required keys, and the extra keys `50-voice-pipeline.md` §3.4-§3.6 names ride *beside* them —
# the same convention `app.application.voice.events` established for `turn_id`.


def fact_gate_evaluated_payload(
    *,
    turn_id: uuid.UUID,
    turn_index: int,
    package: AllowedFactsPackage,
    decisions: Sequence[GateDecision],
    at_offset_ms: int,
) -> dict[str, Any]:
    """`FACT_GATE_EVALUATED` (§10.13, INSTRUCTOR only).

    **Caller values may appear here; world values never can** — the payload is built from the
    `AllowedFactsPackage`, which structurally cannot carry one (INV 1, `gate.py`). `unavailable`
    rows carry a `fact_id`, a `label_ru` and a reason and no value at all (INV 2).
    """
    return {
        "turn_index": turn_index,
        "decisions": [
            {
                "fact_id": decision.fact_id,
                "outcome": decision.outcome.value,
                "reason": decision.reason.value,
            }
            for decision in decisions
        ],
        "allowed_fact_ids": [fact.fact_id for fact in package.allowed],
        "spontaneous_attached": list(package.metadata.spontaneous_attached),
        "withheld_count": package.withheld_count,
        "at_offset_ms": at_offset_ms,
        # Beside the catalogued keys (§3.4's "requested, allowed, unavailable, withheld_count"):
        "turn_id": str(turn_id),
        "unavailable": [
            {"fact_id": fact.fact_id, "label_ru": fact.label_ru, "reason": fact.reason.value}
            for fact in package.unavailable
        ],
        "metadata": {
            "turn_index": package.metadata.turn_index,
            "evaluated_at_offset_ms": package.metadata.evaluated_at_offset_ms,
            "spontaneous_attached": list(package.metadata.spontaneous_attached),
            "max_spontaneous_per_turn": package.metadata.max_spontaneous_per_turn,
        },
    }


def caller_response_planned_payload(
    *,
    call_id: uuid.UUID,
    turn_id: uuid.UUID,
    turn_index: int,
    package: AllowedFactsPackage,
    emotion: EmotionState,
) -> dict[str, Any]:
    """`CALLER_RESPONSE_PLANNED` (§3.5): emitted **before** the generation call, from gate output
    alone, "so the plan is auditable even if generation fails"."""
    return {
        "call_id": call_id,
        "turn_index": turn_index,
        "allowed_fact_ids": [fact.fact_id for fact in package.allowed],
        "spontaneous_fact_ids": list(package.metadata.spontaneous_attached),
        "unavailable_fact_ids": [fact.fact_id for fact in package.unavailable],
        "withheld_count": package.withheld_count,
        "emotion": emotion.emotion.value,
        "stress_level": emotion.stress_level,
        "turn_id": str(turn_id),
    }


def caller_response_generated_payload(
    *,
    call_id: uuid.UUID,
    turn_id: uuid.UUID,
    turn_index: int,
    text: str,
    attempt: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    llm_provider: str,
    llm_model: str,
    regeneration_count: int,
) -> dict[str, Any]:
    """`CALLER_RESPONSE_GENERATED` — only for an answer that **passed** `ResponseValidator` (§3.5).

    `validator_verdict` is `"PASS"` on the first attempt and `"REGENERATED"` after the single
    repair retry; a `"FALLBACK"` turn produces no `CALLER_RESPONSE_GENERATED` at all, only
    `MODEL_FALLBACK_USED` (§7.7, §7.8).
    """
    return {
        "call_id": call_id,
        "turn_index": turn_index,
        "utterance_ru": text,
        "output_token_count": completion_tokens or 0,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "validator_verdict": "REGENERATED" if regeneration_count else "PASS",
        "regeneration_count": regeneration_count,
        # Beside the catalogued keys (§3.5's own key list):
        "turn_id": str(turn_id),
        "text": text,
        "attempt": attempt,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "validated": True,
    }

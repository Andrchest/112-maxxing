"""`DialogueInterpreter` — the first LLM call of a turn (HLD `50-voice-pipeline.md` §3.3, §5.1,
D10, SPEC §20).

Turns one operator utterance into the constrained `InterpretedUtterance` structure of SPEC §20. It
is deliberately narrow: its only scenario-shaped input is the value-free `FactCatalog` (D10) — no
`FactDefinition`, no layer type, nothing that could carry a caller or world value ever reaches this
module (checked by an import/signature scan in this task's tests, mirroring `test_inv_01_gate_
never_releases_world_truth.py`'s structural half for the gate).

Failure handling (SPEC §20, §39): a schema/catalog validation failure gets exactly one repair
retry, carrying the previous raw output and the validation error; a second failure, a timeout or a
transport error goes straight to the deterministic fallback (`speech_act = UNINTELLIGIBLE`, every
list empty, `semantic_confidence = 0.0`) with `fallback_used = True`. Nothing here ever fills in a
guessed value for a field the model omitted or got wrong.

**The responder slot catalog (I3 E6c, HLD 80 §80.4.3).** On a ДДС call to a service head the same
interpreter reads the ДДС trainee's utterance against `RESPONDER_SLOT_CATALOG` instead of a
scenario's facts — five value-free slots (`status`, `order_number`, `address`, `victims`, `eta`):
`requested_facts` are what the trainee asks the head, `operator_assertions` what they state to it.
Like every catalog it carries labels and aliases, never a value.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application.dialogue.grammar import build_interpretation_grammar
from app.application.dialogue.prompts import (
    INTERPRETER_REPAIR_PROMPT_RU,
    INTERPRETER_SYSTEM_PROMPT_RU,
    INTERPRETER_USER_TEMPLATE_RU,
    few_shot_messages_ru,
    render_fact_catalog_ru,
    render_turn_window_ru,
    speech_act_help_ru,
)
from app.application.ports.llm import (
    ChatMessage,
    JsonSchemaSpec,
    LLMClient,
    LlmCompletion,
    LlmTimeoutError,
)
from app.application.ports.metrics_recorder import InferenceMetric, InferenceStage, MetricsRecorder
from app.config.settings import Settings
from app.domain.enums import SpeechAct
from app.domain.facts.definitions import FactCatalog, FactCatalogEntry

__all__ = [
    "INTERPRETER_GRAMMAR",
    "INTERPRETER_JSON_SCHEMA",
    "RESPONDER_SLOTS",
    "RESPONDER_SLOT_CATALOG",
    "DialogueInterpreter",
    "DialogueTurn",
    "InterpretationOutcome",
    "InterpretedUtterance",
    "InterpreterConfig",
    "OperatorAssertion",
    "RequestedFact",
    "build_interpretation_schema",
    "interpreter_config_from_settings",
]

_CHARS_PER_TOKEN = 3
_MAX_ITEMS = 8

_RESPONDER_CATEGORY = ("RESPONDER",)

RESPONDER_SLOT_CATALOG: FactCatalog = FactCatalog(
    (
        FactCatalogEntry(
            fact_id="status",
            label_ru="Статус бригады: выехали, прибыли, работают, завершили",
            aliases_ru=("доехали", "выехали", "прибыли", "где вы", "обстановка", "как дела"),
            categories=_RESPONDER_CATEGORY,
        ),
        FactCatalogEntry(
            fact_id="order_number",
            label_ru="Номер наряда",
            aliases_ru=("наряд", "номер наряда", "какой наряд"),
            categories=_RESPONDER_CATEGORY,
        ),
        FactCatalogEntry(
            fact_id="address",
            label_ru="Адрес происшествия",
            aliases_ru=("адрес", "улица", "дом", "куда ехать"),
            categories=_RESPONDER_CATEGORY,
        ),
        FactCatalogEntry(
            fact_id="victims",
            label_ru="Пострадавшие",
            aliases_ru=("пострадавшие", "раненые", "есть ли люди"),
            categories=_RESPONDER_CATEGORY,
        ),
        FactCatalogEntry(
            fact_id="eta",
            label_ru="Время прибытия",
            aliases_ru=("когда будете", "сколько ехать", "время прибытия"),
            categories=_RESPONDER_CATEGORY,
        ),
    )
)
"""The value-free catalog a service head's call is interpreted against (§80.4.3, I3 E6c)."""

RESPONDER_SLOTS: tuple[str, ...] = tuple(entry.fact_id for entry in RESPONDER_SLOT_CATALOG)


def _estimate_tokens(text: str) -> int:
    """`ceil(len(text) / 3)` — the fixed, deterministic estimator this task's brief specifies.

    No tokenizer dependency: the same estimate for the same text on every machine, which is what
    makes the prompt-budget tests deterministic (SPEC §22's "do not fake or hard-code" is about
    *measured* numbers; a prompt-fitting decision is not one — it just needs to be reproducible).
    """
    if not text:
        return 0
    return -(-len(text) // _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------------------------
# InterpretedUtterance (SPEC §20/§10, verbatim field list) and the schema generated from it
# ---------------------------------------------------------------------------------------------


class RequestedFact(BaseModel):
    """One fact the operator asked about, and how directly (SPEC §20, D10)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    explicit: bool


class OperatorAssertion(BaseModel):
    """One value the operator asserted, in their own words (SPEC §20)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    asserted_value: str


class InterpretedUtterance(BaseModel):
    """The interpreter's output (SPEC §20/§10, D10). `extra="forbid"`; every field required — the
    model must always emit all five, an empty list rather than an absent key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    speech_act: SpeechAct
    requested_facts: tuple[RequestedFact, ...] = Field(max_length=_MAX_ITEMS)
    operator_assertions: tuple[OperatorAssertion, ...] = Field(max_length=_MAX_ITEMS)
    confirmation_targets: tuple[str, ...] = Field(max_length=_MAX_ITEMS)
    semantic_confidence: float = Field(ge=0.0, le=1.0)


def build_interpretation_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The llama.cpp `response_format.json_schema.schema` for `model` (§5.1).

    A thin, named wrapper around `model.model_json_schema()` — not a hand-copied literal — so
    that the `speech_act` enum in the wire schema is always exactly `SpeechAct`'s members: a test
    can build an unrelated Pydantic model with a differently-sized string enum, call this same
    function, and see the schema's enum list follow it (see `backend/tests/unit/application/
    dialogue/test_interpreter.py`).
    """
    return model.model_json_schema()


#: Generated, not hand-copied (this task's brief, CHANGE item 4).
INTERPRETER_JSON_SCHEMA: dict[str, Any] = build_interpretation_schema(InterpretedUtterance)

#: Whitespace-free GBNF, generated from the same model as `INTERPRETER_JSON_SCHEMA` above (E13-B3
#: CHANGE item 1) — sent as llama-server's `grammar` request field when
#: `InterpreterConfig.use_grammar` is true (the default); `response_format=json_schema` is the
#: fallback when it is false. See `app.application.dialogue.grammar`.
INTERPRETER_GRAMMAR: str = build_interpretation_grammar(InterpretedUtterance)


# ---------------------------------------------------------------------------------------------
# InterpreterConfig (§5.1/§5.3 params, no literals in the call path)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InterpreterConfig:
    """Every literal the interpreter's LLM call needs, frozen and built once (§5.1, §5.3)."""

    max_tokens: int = 200
    temperature: float = 0.0
    top_p: float = 1.0
    timeout_ms: int = 2500
    #: E13-B3 CHANGE item 1: `grammar` (GBNF, `INTERPRETER_GRAMMAR`) when true (the default),
    #: `response_format=json_schema` (`INTERPRETER_JSON_SCHEMA`) when false — never both in the
    #: same request body.
    use_grammar: bool = True
    #: §5.3: "`fact_catalog` is capped at 60 facts".
    catalog_cap: int = 60
    #: §5.3: "system + catalog ≤ 1800".
    catalog_token_budget: int = 1800
    #: §5.1/§5.3: the last 4-6 turns, ≤ 1200 tokens.
    window_token_budget: int = 1200
    #: §5.3: the current operator utterance, ≤ 200 tokens.
    utterance_token_budget: int = 200
    #: §5.1: "the same 4-6 turn window as §5.3" — the ceiling on turns considered before budgeting.
    max_window_turns: int = 6
    min_window_turns: int = 4


def interpreter_config_from_settings(settings: Settings) -> InterpreterConfig:
    """`SIM_LLM_INTERPRETER_MAX_TOKENS` / `SIM_LLM_INTERPRETER_TIMEOUT_MS` /
    `SIM_LLM_INTERPRETER_USE_GRAMMAR`; the rest are §5.1/§5.3 fixed budgets, not per-deployment
    settings."""
    return InterpreterConfig(
        max_tokens=settings.llm_interpreter_max_tokens,
        timeout_ms=settings.llm_interpreter_timeout_ms,
        use_grammar=settings.llm_interpreter_use_grammar,
    )


# ---------------------------------------------------------------------------------------------
# DialogueTurn — the window the interpreter (and, later, the generator) renders (§5.1, §5.3)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DialogueTurn:
    """One prior turn for the `{recent_turns}` window. Text only — no fact ids, no values."""

    speaker: Literal["OPERATOR", "CALLER"]
    text: str


@dataclass(frozen=True, slots=True)
class InterpretationOutcome:
    """What `DialogueInterpreter.interpret()` returns."""

    interpretation: InterpretedUtterance
    repair_retry_used: bool
    fallback_used: bool
    failure_reason: str | None


#: SPEC §20/§5.1: the fallback when the repair retry also fails, or the call itself errors/times
#: out. Never guesses a field; every collection is empty and the confidence is honest (0.0).
_FALLBACK_INTERPRETATION = InterpretedUtterance(
    speech_act=SpeechAct.UNINTELLIGIBLE,
    requested_facts=(),
    operator_assertions=(),
    confirmation_targets=(),
    semantic_confidence=0.0,
)


# ---------------------------------------------------------------------------------------------
# Prompt rendering, budgeted (§5.1, §5.3)
# ---------------------------------------------------------------------------------------------


def _catalog_tuple(entry: FactCatalogEntry) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    return (entry.fact_id, entry.label_ru, entry.aliases_ru, entry.categories)


#: A one-time estimate of the system template's own token cost with an empty catalog, used to
#: leave the catalog block its share of the combined "system + catalog ≤ 1800" budget (§5.3). An
#: estimate, not a measurement — the same deterministic `_estimate_tokens` the rest of this module
#: budgets with, so the split is reproducible even though it is approximate.
_SYSTEM_TEMPLATE_TOKENS = _estimate_tokens(
    INTERPRETER_SYSTEM_PROMPT_RU.format(speech_act_help=speech_act_help_ru(), fact_catalog="")
)


def _render_catalog(catalog: FactCatalog, config: InterpreterConfig) -> str:
    """Cap at `catalog_cap` facts, then deterministically drop the lowest-priority (last) entries
    until the combined system+catalog estimate fits `catalog_token_budget` (§5.3)."""
    entries = list(catalog)[: config.catalog_cap]
    budget = max(config.catalog_token_budget - _SYSTEM_TEMPLATE_TOKENS, 0)
    while entries:
        rendered = render_fact_catalog_ru([_catalog_tuple(entry) for entry in entries])
        if _estimate_tokens(rendered) <= budget:
            return rendered
        entries = entries[:-1]
    return render_fact_catalog_ru([])


def _render_window(window: Sequence[DialogueTurn], config: InterpreterConfig) -> str:
    """The last `max_window_turns` turns, oldest dropped first while over budget (§5.1, §5.3)."""
    turns = list(window)[-config.max_window_turns :]
    while turns:
        rendered = render_turn_window_ru([(turn.speaker, turn.text) for turn in turns])
        if _estimate_tokens(rendered) <= config.window_token_budget:
            return rendered
        turns = turns[1:]
    return render_turn_window_ru([])


def _fit_utterance(text: str, config: InterpreterConfig) -> str:
    """Deterministic cropping to `utterance_token_budget` (§5.3): keep the start, drop the tail."""
    max_chars = config.utterance_token_budget * _CHARS_PER_TOKEN
    return text if len(text) <= max_chars else text[:max_chars]


def _system_prompt(catalog: FactCatalog, config: InterpreterConfig) -> str:
    return INTERPRETER_SYSTEM_PROMPT_RU.format(
        speech_act_help=speech_act_help_ru(), fact_catalog=_render_catalog(catalog, config)
    )


def _user_prompt(window: Sequence[DialogueTurn], utterance: str, config: InterpreterConfig) -> str:
    return INTERPRETER_USER_TEMPLATE_RU.format(
        recent_turns=_render_window(window, config),
        operator_utterance=_fit_utterance(utterance, config),
    )


def _few_shot_messages(catalog: FactCatalog) -> list[ChatMessage]:
    """CHANGE item 2/3: the few-shot pairs, converted to `ChatMessage`s. A function of `catalog`
    alone (never a per-call value), so — together with `_system_prompt`, equally catalog-only —
    it is byte-identical across every turn of one session, which is what makes "system + few-shot
    + catalog" one stable prefix for llama-server's `cache_prompt` (CHANGE item 3)."""
    return [
        ChatMessage(role=role, content=content)  # type: ignore[arg-type]
        for role, content in few_shot_messages_ru([_catalog_tuple(entry) for entry in catalog])
    ]


# ---------------------------------------------------------------------------------------------
# Parsing and post-schema validation (SPEC §20 last line: unknown ids are a validation failure)
# ---------------------------------------------------------------------------------------------


def _parse_and_validate(
    raw_text: str, catalog_ids: frozenset[str]
) -> tuple[InterpretedUtterance | None, str | None]:
    try:
        parsed = InterpretedUtterance.model_validate_json(raw_text)
    except (ValidationError, ValueError) as exc:
        return None, f"invalid JSON/schema: {exc}"

    unknown: set[str] = set()
    unknown.update(
        fact.fact_id for fact in parsed.requested_facts if fact.fact_id not in catalog_ids
    )
    unknown.update(
        assertion.fact_id
        for assertion in parsed.operator_assertions
        if assertion.fact_id not in catalog_ids
    )
    unknown.update(target for target in parsed.confirmation_targets if target not in catalog_ids)
    if unknown:
        return None, f"unknown fact_id(s) not in the catalog: {sorted(unknown)}"
    return parsed, None


# ---------------------------------------------------------------------------------------------
# DialogueInterpreter
# ---------------------------------------------------------------------------------------------


class DialogueInterpreter:
    """`interpret()` — one operator utterance to one `InterpretedUtterance` (§3.3, D10)."""

    def __init__(
        self, llm: LLMClient, metrics: MetricsRecorder, *, config: InterpreterConfig
    ) -> None:
        self._llm = llm
        self._metrics = metrics
        self._config = config

    async def interpret(
        self,
        utterance: str,
        window: Sequence[DialogueTurn],
        catalog: FactCatalog,
        *,
        request_id: str,
        turn_index: int,
        session_id: uuid.UUID | None = None,
        turn_id: uuid.UUID | None = None,
    ) -> InterpretationOutcome:
        """E13-B2 (R6): `session_id`/`turn_id` are optional so every existing caller keeps
        working; when the turn pipeline supplies them, the `InferenceMetric` rows of this call
        carry the **real** ids instead of the uuid5 stand-ins `_call` derives."""
        catalog_ids = frozenset(entry.fact_id for entry in catalog)
        system_prompt = _system_prompt(catalog, self._config)
        user_prompt = _user_prompt(window, utterance, self._config)
        # CHANGE item 3: the fixed prefix (system + few-shot + catalog) first, the variable part
        # (turn window + utterance, both folded into `user_prompt`) last.
        messages = [
            ChatMessage(role="system", content=system_prompt),
            *_few_shot_messages(catalog),
            ChatMessage(role="user", content=user_prompt),
        ]

        completion, error = await self._call(
            messages, request_id=request_id, attempt=0, session_id=session_id, turn_id=turn_id
        )
        if completion is None:
            return InterpretationOutcome(
                _FALLBACK_INTERPRETATION,
                repair_retry_used=False,
                fallback_used=True,
                failure_reason=str(error),
            )

        parsed, validation_error = _parse_and_validate(completion.text, catalog_ids)
        if parsed is not None:
            return InterpretationOutcome(
                parsed, repair_retry_used=False, fallback_used=False, failure_reason=None
            )

        repair_messages = [
            *messages,
            ChatMessage(
                role="assistant",
                content=completion.text,
            ),
            ChatMessage(
                role="user",
                content=INTERPRETER_REPAIR_PROMPT_RU.format(
                    previous_raw_output=completion.text, validation_error=validation_error
                ),
            ),
        ]
        repair_completion, repair_error = await self._call(
            repair_messages,
            request_id=f"{request_id}:repair",
            attempt=1,
            session_id=session_id,
            turn_id=turn_id,
        )
        if repair_completion is None:
            return InterpretationOutcome(
                _FALLBACK_INTERPRETATION,
                repair_retry_used=True,
                fallback_used=True,
                failure_reason=str(repair_error),
            )

        parsed_repair, repair_validation_error = _parse_and_validate(
            repair_completion.text, catalog_ids
        )
        if parsed_repair is not None:
            return InterpretationOutcome(
                parsed_repair, repair_retry_used=True, fallback_used=False, failure_reason=None
            )
        return InterpretationOutcome(
            _FALLBACK_INTERPRETATION,
            repair_retry_used=True,
            fallback_used=True,
            failure_reason=repair_validation_error,
        )

    async def _call(
        self,
        messages: list[ChatMessage],
        *,
        request_id: str,
        attempt: int,
        session_id: uuid.UUID | None = None,
        turn_id: uuid.UUID | None = None,
    ) -> tuple[LlmCompletion | None, Exception | None]:
        """One LLM call, timed and recorded as one `InferenceMetric` (SPEC §27).

        Returns `(completion, None)` on success or `(None, exception)` on failure — never raises,
        so `interpret()` reads as a straight-line fallback ladder.
        """
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        # HLD gap: `interpret()`'s signature (this task's brief, CHANGE item 4) carries no
        # session/turn id, only a `request_id: str` and a `turn_index: int`; `InferenceMetric`
        # requires a real `session_id: uuid.UUID`. Absent a caller-supplied one, a deterministic
        # id is derived from `request_id` so the metric row is still emitted and reproducible;
        # whichever epic wires this interpreter into the `TurnPipeline` should pass the real
        # session/turn ids through once it has them. See this task's report ("HLD gaps").
        metric_session_id = session_id or uuid.uuid5(
            uuid.NAMESPACE_URL, f"sim-112:interpret:{request_id}"
        )
        metric_turn_id = turn_id or uuid.uuid5(
            uuid.NAMESPACE_URL, f"sim-112:interpret:{request_id}:turn"
        )

        status: Literal["OK", "TIMEOUT", "ERROR"] = "OK"
        error_kind: str | None = None
        completion: LlmCompletion | None = None
        error: Exception | None = None
        # CHANGE item 1: `grammar` XOR `response_format`, never both in one body.
        # CHANGE item 3: `cache_prompt=true` always; `id_slot=0` pins every interpreter call to
        # one llama-server slot, so a session's fixed prefix (system + few-shot + catalog) is
        # reused by the *same* slot's KV cache turn over turn rather than racing another caller
        # for whichever slot answers first. Sent via `extra_body` — the port's HLD-gap note
        # (`app.application.ports.llm`) already makes it a generic pass-through, so no port change
        # was needed (this task's brief, FILES: "prefer extra_body").
        response_format: JsonSchemaSpec | None = None
        extra_body: dict[str, Any] = {"cache_prompt": True, "id_slot": 0}
        if self._config.use_grammar:
            extra_body["grammar"] = INTERPRETER_GRAMMAR
        else:
            response_format = JsonSchemaSpec(
                name="operator_utterance_interpretation",
                schema=INTERPRETER_JSON_SCHEMA,
                strict=True,
            )
        try:
            completion = await self._llm.complete(
                messages,
                request_id=request_id,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                top_p=self._config.top_p,
                response_format=response_format,
                extra_body=extra_body,
                timeout_ms=self._config.timeout_ms,
            )
        except (LlmTimeoutError, TimeoutError) as exc:
            status = "TIMEOUT"
            error_kind = type(exc).__name__
            error = exc
        except Exception as exc:
            status = "ERROR"
            error_kind = type(exc).__name__
            error = exc

        finished_at = datetime.now(UTC)
        total_latency_ms = int((time.monotonic() - started_monotonic) * 1000)
        await self._metrics.record(
            InferenceMetric(
                id=uuid.uuid4(),
                session_id=metric_session_id,
                turn_id=metric_turn_id,
                request_id=request_id,
                stage=InferenceStage.LLM_INTERPRET,
                provider=self._llm.model_name,
                model_version=self._llm.model_name,
                input_tokens=completion.usage.prompt_tokens if completion else None,
                input_audio_ms=None,
                output_tokens=completion.usage.completion_tokens if completion else None,
                output_audio_ms=None,
                started_at=started_at,
                first_output_at=finished_at if completion is not None else None,
                finished_at=finished_at,
                ttft_ms=None,  # non-streaming call (§2.6): no time-to-first-token to measure
                total_latency_ms=total_latency_ms,
                tokens_per_second=None,
                realtime_factor=None,
                gpu_memory_used_mb=None,
                fallback_count=0,
                retry_count=attempt,
                status=status,
                error_kind=error_kind,
            )
        )
        return completion, error

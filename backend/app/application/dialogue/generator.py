"""`CallerResponseGenerator` — Russian caller wording from allowed facts only (§3.5, §5.2, §7.7).

It owns §7.7's retry-once flow and nothing else:

```
attempt 1: generate -> validate
  ok    -> GeneratedResponse(validated=True, attempt=1)
  fail  -> attempt 2 (same prompt + a correction message, temperature 0.3)
attempt 2: ok -> GeneratedResponse(validated=True, attempt=2)
           fail -> GeneratedResponse(validated=False) — the responder uses §7.8's fallback
```

"There is exactly one retry (SPEC §24). A second failure never leads to a third call." — so this
class makes **at most two** LLM calls per turn, which the unit tests assert on the `FakeLLM`'s call
count rather than on a comment.

The correction message names the *category* of the failure and never the offending value (§7.7):
re-showing the model the value it just leaked would put that value straight back into its context,
which is the one thing the whole §7 machinery exists to prevent. For the same reason the rejected
answer itself is **not** echoed back as an assistant turn.

Like `prompt_builder.py`, this module has no route to a scenario value: it takes an
`AllowedFactsPackage` and a persona, and `forbidden_values` only passes *through* it into the
validator — which is code, and may see them (D10). An import scan enforces that this module never
imports `app.domain.layers.world_truth`, `app.domain.facts.definitions`, `app.domain.scenario`,
`app.application.dialogue.forbidden_values` or `app.application.dialogue.dialogue_context`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.application.dialogue.grammar import build_caller_response_grammar
from app.application.dialogue.interpreter import DialogueTurn
from app.application.dialogue.prompt_builder import CallerPromptBuilder
from app.application.dialogue.prompts.caller import CALLER_REPAIR_PROMPT_RU, FAILURE_REASON_RU
from app.application.dialogue.validator import (
    CallerUtterance,
    ResponseValidator,
    ValidationFailure,
    ValidationVerdict,
)
from app.application.ports.llm import (
    ChatMessage,
    JsonSchemaSpec,
    LLMClient,
    LlmCompletion,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
)
from app.application.ports.metrics_recorder import (
    InferenceMetric,
    InferenceStage,
    MetricsRecorder,
    MetricStatus,
)
from app.config.settings import Settings
from app.domain.caller.emotion import EmotionState
from app.domain.caller.profile import CallerProfile
from app.domain.facts.gate import AllowedFact, AllowedFactsPackage

__all__ = [
    "CALLER_JSON_SCHEMA",
    "CallerResponseGenerator",
    "GeneratedResponse",
    "GeneratorConfig",
    "ValidationInputs",
    "generator_config_from_settings",
]

#: §5.2 verbatim — the caller's whole output schema. `extra="forbid"` is the wire's
#: `additionalProperties: false`, and `CallerUtterance` (validator.py) is its Pydantic twin.
CALLER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["utterance"],
    "properties": {"utterance": {"type": "string", "maxLength": 400}},
}

#: E13-B4, CHANGE item 3 — the same "one source, two renderings" the interpreter's
#: `INTERPRETER_GRAMMAR` is: generated from `CallerUtterance` (`validator.py`), the schema's own
#: pydantic twin, not hand-copied from `CALLER_JSON_SCHEMA` above. Sent as llama-server's `grammar`
#: request field when `GeneratorConfig.use_grammar` is true (the default); `response_format=
#: json_schema` (`CALLER_JSON_SCHEMA`) is the fallback when it is false.
CALLER_GRAMMAR: str = build_caller_response_grammar(CallerUtterance)

#: E13-B4, CHANGE item 3: a different `id_slot` than the interpreter's (`interpreter.py` pins `0`)
#: so the two stages never contend for the same llama-server prompt-cache slot when both are
#: warm — requires the server to be launched with `--parallel 2` (see `docs/hld/60-inference-ops.
#: md`'s launch-flags row and this task's report for the `ctx-size = n_ctx * slots` consequence).
GENERATOR_ID_SLOT = 1

#: `MODEL_ERROR.component` / `MODEL_FALLBACK_USED.component` for this stage (§10.13).
GENERATOR_COMPONENT: Literal["GENERATOR"] = "GENERATOR"
#: `MODEL_FALLBACK_USED.reason` when the prompt did not fit §5.3's budget (R3).
PROMPT_BUDGET_REASON = "PROMPT_BUDGET"


@dataclass(frozen=True, slots=True)
class GeneratorConfig:
    """§5.2's call parameters plus §7.7's repair temperature — never literals in the call path."""

    max_tokens: int = 80
    temperature: float = 0.7
    top_p: float = 0.9
    timeout_ms: int = 3000
    #: §7.7: "regenerate … temperature 0.3".
    repair_temperature: float = 0.3
    #: E13-B4, CHANGE item 3: `grammar` (GBNF, `CALLER_GRAMMAR`) when true (the default),
    #: `response_format=json_schema` (`CALLER_JSON_SCHEMA`) when false — never both in one body,
    #: the same lever B3 built for the interpreter.
    use_grammar: bool = True


def generator_config_from_settings(settings: Settings) -> GeneratorConfig:
    """`SIM_LLM_GENERATOR_*`. §7.7's repair temperature is a documented constant, not a setting."""
    return GeneratorConfig(
        max_tokens=settings.llm_generator_max_tokens,
        temperature=settings.llm_generator_temperature,
        top_p=settings.llm_generator_top_p,
        timeout_ms=settings.llm_generator_timeout_ms,
        use_grammar=settings.llm_generator_use_grammar,
    )


@dataclass(frozen=True, slots=True)
class ValidationInputs:
    """Everything §7.3–§7.6 needs beyond the package — assembled by the responder, not here."""

    revealed_values: tuple[str, ...] = ()
    operator_utterances: tuple[str, ...] = ()
    persona_whitelist: tuple[str, ...] = ()
    forbidden_values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GeneratedResponse:
    """§3.5's `GeneratedResponse {utterance, attempt, usage, request_id}` plus what §7.8 needs."""

    utterance: str
    attempt: int
    usage: LlmUsage | None
    request_id: str
    validated: bool = False
    failures: tuple[ValidationFailure, ...] = ()
    regeneration_count: int = 0
    error_kind: str | None = None
    """`LlmTimeoutError`, `LlmUnavailableError` or another exception type name; `None` when every
    attempt actually produced text."""
    verdicts: tuple[ValidationVerdict, ...] = field(default_factory=tuple)
    """One verdict per attempt that produced text, in attempt order."""

    @property
    def failure_codes(self) -> tuple[str, ...]:
        """`MODEL_FALLBACK_USED.failure_codes` — the last attempt's codes, in check order."""
        return tuple(failure.code.value for failure in self.failures)

    @property
    def fallback_reason(self) -> str:
        """Why §7.8 has to answer instead: the model error, or the validator's verdict."""
        if self.error_kind is not None:
            return self.error_kind
        if self.failures:
            return self.failures[0].code.value
        return "NO_RESPONSE"


class CallerResponseGenerator:
    """The second LLM call of a turn, and the only one that produces trainee-audible words."""

    def __init__(
        self,
        llm: LLMClient,
        metrics: MetricsRecorder,
        builder: CallerPromptBuilder,
        validator: ResponseValidator,
        *,
        config: GeneratorConfig,
    ) -> None:
        self._llm = llm
        self._metrics = metrics
        self._builder = builder
        self._validator = validator
        self._config = config

    @property
    def model_name(self) -> str:
        """The model every call of this generator goes to (`CALLER_RESPONSE_GENERATED`)."""
        return self._llm.model_name

    async def generate(
        self,
        package: AllowedFactsPackage,
        profile: CallerProfile,
        emotion: EmotionState,
        already_revealed: Sequence[AllowedFact],
        window: Sequence[DialogueTurn],
        utterance: str,
        *,
        inputs: ValidationInputs,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        request_id: str,
    ) -> GeneratedResponse:
        """§7.7's flow: one call, one validation, at most one repair call. Never a third."""
        messages = self._builder.build(
            package, profile, emotion, already_revealed, window, utterance
        )

        first, error = await self._call(
            messages,
            request_id=request_id,
            temperature=self._config.temperature,
            session_id=session_id,
            turn_id=turn_id,
            retry_count=0,
            fallback_count=0,
        )
        if first is None:
            return GeneratedResponse(
                utterance="",
                attempt=0,
                usage=None,
                request_id=request_id,
                error_kind=type(error).__name__ if error is not None else "NO_RESPONSE",
            )

        verdict = self._validate(first.text, package, inputs)
        if verdict.ok:
            return GeneratedResponse(
                utterance=verdict.utterance,
                attempt=1,
                usage=first.usage,
                request_id=request_id,
                validated=True,
                verdicts=(verdict,),
            )

        repair_request_id = f"{request_id}:repair"
        repair_messages = [
            *messages,
            ChatMessage(role="user", content=_repair_message(verdict.failures)),
        ]
        second, repair_error = await self._call(
            repair_messages,
            request_id=repair_request_id,
            temperature=self._config.repair_temperature,
            session_id=session_id,
            turn_id=turn_id,
            retry_count=1,
            fallback_count=0,
        )
        if second is None:
            return GeneratedResponse(
                utterance="",
                attempt=1,
                usage=first.usage,
                request_id=repair_request_id,
                failures=verdict.failures,
                regeneration_count=1,
                error_kind=(
                    type(repair_error).__name__ if repair_error is not None else "NO_RESPONSE"
                ),
                verdicts=(verdict,),
            )

        repair_verdict = self._validate(second.text, package, inputs)
        return GeneratedResponse(
            utterance=repair_verdict.utterance if repair_verdict.ok else "",
            attempt=2,
            usage=second.usage,
            request_id=repair_request_id,
            validated=repair_verdict.ok,
            failures=() if repair_verdict.ok else repair_verdict.failures,
            regeneration_count=1,
            verdicts=(verdict, repair_verdict),
        )

    # -- internals ----------------------------------------------------------------------------

    def _validate(
        self, raw: str, package: AllowedFactsPackage, inputs: ValidationInputs
    ) -> ValidationVerdict:
        return self._validator.validate(
            raw,
            package=package,
            revealed_values=inputs.revealed_values,
            operator_utterances=inputs.operator_utterances,
            persona_whitelist=inputs.persona_whitelist,
            forbidden_values=inputs.forbidden_values,
        )

    async def _call(
        self,
        messages: list[ChatMessage],
        *,
        request_id: str,
        temperature: float,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        retry_count: int,
        fallback_count: int,
    ) -> tuple[LlmCompletion | None, BaseException | None]:
        """One LLM call, timed and recorded as one `InferenceMetric` (SPEC §27).

        Never raises except for `asyncio.CancelledError`, which is the pipeline's barge-in
        signal: the metric is recorded as `CANCELLED` and the cancellation is re-raised, because
        a cancelled response must actually stop and must not be replaced by a fallback.
        """
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        status: MetricStatus = "OK"
        error_kind: str | None = None
        completion: LlmCompletion | None = None
        error: BaseException | None = None
        # E13-B4, CHANGE item 3: `grammar` XOR `response_format`, never both in one body (same
        # rule the interpreter's `_call` follows). `cache_prompt=true` always; `id_slot=1` pins
        # every generator call to its own llama-server slot, distinct from the interpreter's `0`,
        # so a warm interpreter call never evicts the generator's cached prefix or vice versa —
        # sent via `extra_body`, exactly like B3's interpreter change.
        response_format: JsonSchemaSpec | None = None
        extra_body: dict[str, Any] = {"cache_prompt": True, "id_slot": GENERATOR_ID_SLOT}
        if self._config.use_grammar:
            extra_body["grammar"] = CALLER_GRAMMAR
        else:
            response_format = JsonSchemaSpec(
                name="caller_utterance", schema=CALLER_JSON_SCHEMA, strict=True
            )
        try:
            completion = await self._llm.complete(
                messages,
                request_id=request_id,
                max_tokens=self._config.max_tokens,
                temperature=temperature,
                top_p=self._config.top_p,
                response_format=response_format,
                extra_body=extra_body,
                timeout_ms=self._config.timeout_ms,
            )
        except asyncio.CancelledError:
            await self._record(
                session_id=session_id,
                turn_id=turn_id,
                request_id=request_id,
                started_at=started_at,
                started_monotonic=started_monotonic,
                completion=None,
                status="CANCELLED",
                error_kind="BARGE_IN",
                retry_count=retry_count,
                fallback_count=fallback_count,
            )
            raise
        except (LlmTimeoutError, TimeoutError) as exc:
            status, error_kind, error = "TIMEOUT", type(exc).__name__, exc
        except LlmUnavailableError as exc:
            status, error_kind, error = "ERROR", type(exc).__name__, exc
        except Exception as exc:
            status, error_kind, error = "ERROR", type(exc).__name__, exc

        await self._record(
            session_id=session_id,
            turn_id=turn_id,
            request_id=request_id,
            started_at=started_at,
            started_monotonic=started_monotonic,
            completion=completion,
            status=status,
            error_kind=error_kind,
            retry_count=retry_count,
            fallback_count=fallback_count,
        )
        return completion, error

    async def _record(
        self,
        *,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        request_id: str,
        started_at: datetime,
        started_monotonic: float,
        completion: LlmCompletion | None,
        status: MetricStatus,
        error_kind: str | None,
        retry_count: int,
        fallback_count: int,
    ) -> None:
        finished_at = datetime.now(UTC)
        total_latency_ms = int((time.monotonic() - started_monotonic) * 1000)
        metric = InferenceMetric(
            id=uuid.uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            request_id=request_id,
            stage=InferenceStage.LLM_GENERATE,
            provider=self._llm.model_name,
            model_version=self._llm.model_name,
            input_tokens=completion.usage.prompt_tokens if completion else None,
            input_audio_ms=None,
            output_tokens=completion.usage.completion_tokens if completion else None,
            output_audio_ms=None,
            started_at=started_at,
            first_output_at=finished_at if completion is not None else None,
            finished_at=finished_at,
            ttft_ms=None,  # non-streaming call (§2.6)
            total_latency_ms=total_latency_ms,
            tokens_per_second=None,
            realtime_factor=None,
            gpu_memory_used_mb=None,
            fallback_count=fallback_count,
            retry_count=retry_count,
            status=status,
            error_kind=error_kind,
        )
        # §2.6: a metrics failure is swallowed; telemetry never fails a turn.
        with contextlib.suppress(Exception):
            await self._metrics.record(metric)


def _repair_message(failures: Sequence[ValidationFailure]) -> str:
    """§7.7's correction message: the category, in Russian, and never the offending value."""
    reason = FAILURE_REASON_RU[failures[0].code] if failures else "ответ не прошёл проверку"
    return CALLER_REPAIR_PROMPT_RU.format(failure_reason_ru=reason)

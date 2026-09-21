"""`CallerResponseGenerator` — §7.7's retry-once flow (HLD §3.5, §5.2, §7.7, SPEC §24, §27).

"There is exactly one retry (SPEC §24). A second failure never leads to a third call." — asserted
on the `FakeLLM`'s call count, because a comment saying so is not a guarantee.

The correction message is checked twice over: it must name the failure *category* in Russian, and
it must **not** contain the offending value. Re-showing the model what it just leaked would put the
leaked value back into the very context §7 exists to keep it out of.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from app.application.dialogue.generator import (
    CALLER_GRAMMAR,
    CALLER_JSON_SCHEMA,
    GENERATOR_ID_SLOT,
    CallerResponseGenerator,
    GeneratorConfig,
    ValidationInputs,
    generator_config_from_settings,
)
from app.application.dialogue.prompt_builder import CallerPromptBuilder, CallerPromptConfig
from app.application.dialogue.prompts.caller import FAILURE_REASON_RU
from app.application.dialogue.validator import (
    ResponseValidator,
    ValidationFailureCode,
    ValidatorConfig,
)
from app.application.ports.llm import LlmTimeoutError, LlmUnavailableError
from app.application.ports.metrics_recorder import InferenceStage, NullMetricsRecorder
from app.config.settings import Settings
from app.domain.caller.emotion import EmotionState
from app.domain.enums import EmotionLabel
from app.inference.llm.fake_llm import FakeLLM

from tests.unit.application.dialogue._support import demo_profile, gate_package

SESSION_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TURN_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
EMOTION = EmotionState(emotion=EmotionLabel.FRIGHTENED, stress_level=0.6)
GOOD = json.dumps({"utterance": "Улица Николаева, дом 27."}, ensure_ascii=False)
LEAK = json.dumps({"utterance": "Тут ещё 47 человек."}, ensure_ascii=False)


def make(
    script: list, *, config: GeneratorConfig | None = None
) -> tuple[CallerResponseGenerator, FakeLLM, NullMetricsRecorder]:
    llm = FakeLLM(script)
    metrics = NullMetricsRecorder()
    generator = CallerResponseGenerator(
        llm,
        metrics,
        CallerPromptBuilder(CallerPromptConfig()),
        ResponseValidator(ValidatorConfig(small_count_allowlist=frozenset())),
        config=config or GeneratorConfig(),
    )
    return generator, llm, metrics


async def run(generator: CallerResponseGenerator, *, operator: str = "Назовите адрес"):
    package, _ = gate_package(("address.street", "address.house"))
    return await generator.generate(
        package,
        demo_profile(),
        EMOTION,
        (),
        (),
        operator,
        inputs=ValidationInputs(
            operator_utterances=(operator,),
            persona_whitelist=demo_profile().persona_whitelist_ru,
        ),
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        request_id=f"{TURN_ID}:generate",
    )


# ---------------------------------------------------------------------------------------------
# §7.7's ladder
# ---------------------------------------------------------------------------------------------


async def test_a_valid_first_attempt_is_returned_after_one_call() -> None:
    generator, llm, _ = make([GOOD])

    response = await run(generator)

    assert response.validated is True
    assert response.attempt == 1
    assert response.regeneration_count == 0
    assert response.utterance == "Улица Николаева, дом 27."
    assert len(llm.calls) == 1


async def test_an_invalid_first_attempt_is_regenerated_once_and_can_succeed() -> None:
    generator, llm, _ = make([LEAK, GOOD])

    response = await run(generator)

    assert response.validated is True
    assert response.attempt == 2
    assert response.regeneration_count == 1
    assert len(llm.calls) == 2


async def test_the_regeneration_runs_at_temperature_0_3() -> None:
    """§7.7: "regenerate with the same prompt plus a correction message, temperature 0.3"."""
    generator, llm, _ = make([LEAK, GOOD])

    await run(generator)

    assert llm.calls[0].temperature == GeneratorConfig().temperature
    assert llm.calls[1].temperature == 0.3


async def test_the_correction_message_names_the_category_and_not_the_value() -> None:
    generator, llm, _ = make([LEAK, GOOD])

    await run(generator)

    correction = llm.calls[1].messages[-1]
    assert correction.role == "user"
    assert FAILURE_REASON_RU[ValidationFailureCode.NEW_NUMBER] in correction.content
    assert "47" not in correction.content
    # The rejected answer itself is never echoed back as an assistant turn, for the same reason.
    assert all("47" not in message.content for message in llm.calls[1].messages)


async def test_two_failures_end_in_no_validated_answer_and_exactly_two_calls() -> None:
    """SPEC §24: "A second failure never leads to a third call"."""
    generator, llm, _ = make([LEAK, LEAK])

    response = await run(generator)

    assert response.validated is False
    assert response.attempt == 2
    assert ValidationFailureCode.NEW_NUMBER.value in response.failure_codes
    assert len(llm.calls) == 2


async def test_the_correction_message_carries_the_whole_prompt_again() -> None:
    """§7.7: "the same prompt plus a correction message" — the persona and facts stay."""
    generator, llm, _ = make([LEAK, GOOD])

    await run(generator)

    assert len(llm.calls[1].messages) == len(llm.calls[0].messages) + 1
    assert llm.calls[1].messages[: len(llm.calls[0].messages)] == llm.calls[0].messages


# ---------------------------------------------------------------------------------------------
# §5.2's call parameters and §27's metric
# ---------------------------------------------------------------------------------------------


async def test_the_call_uses_the_documented_schema_and_parameters() -> None:
    """`use_grammar=False` here: the documented `CALLER_JSON_SCHEMA` is what `response_format`
    carries when it is sent at all — see the grammar-vs-schema tests below for the default."""
    generator, llm, _ = make([GOOD], config=GeneratorConfig(use_grammar=False))

    await run(generator)

    call = llm.calls[0]
    assert call.max_tokens == 80
    assert call.response_format is not None
    assert call.response_format.schema == CALLER_JSON_SCHEMA


# ---------------------------------------------------------------------------------------------
# E13-B4 item 3: grammar XOR response_format, cache_prompt/id_slot
# ---------------------------------------------------------------------------------------------


async def test_grammar_is_sent_and_response_format_is_omitted_when_use_grammar_is_true() -> None:
    generator, llm, _ = make([GOOD], config=GeneratorConfig(use_grammar=True))

    await run(generator)

    call = llm.calls[0]
    assert call.response_format is None
    assert call.extra_body["grammar"] == CALLER_GRAMMAR


async def test_response_format_is_sent_and_grammar_is_omitted_when_use_grammar_is_false() -> None:
    generator, llm, _ = make([GOOD], config=GeneratorConfig(use_grammar=False))

    await run(generator)

    call = llm.calls[0]
    assert call.response_format is not None
    assert call.response_format.schema == CALLER_JSON_SCHEMA
    assert "grammar" not in call.extra_body


async def test_cache_prompt_and_a_distinct_id_slot_are_always_sent() -> None:
    """A different `id_slot` than the interpreter's `0` (E13-B4 item 3)."""
    assert GENERATOR_ID_SLOT != 0
    for use_grammar in (True, False):
        generator, llm, _ = make([GOOD], config=GeneratorConfig(use_grammar=use_grammar))

        await run(generator)

        call = llm.calls[0]
        assert call.extra_body["cache_prompt"] is True
        assert call.extra_body["id_slot"] == GENERATOR_ID_SLOT


async def test_the_repair_call_also_carries_cache_prompt_and_id_slot() -> None:
    generator, llm, _ = make([LEAK, GOOD])

    await run(generator)

    assert len(llm.calls) == 2
    for call in llm.calls:
        assert call.extra_body["cache_prompt"] is True
        assert call.extra_body["id_slot"] == GENERATOR_ID_SLOT


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        "redis_url": "redis://localhost:56379/0",
        "jwt_secret": "test-only-secret",
        "livekit_url": "ws://localhost:7880",
        "livekit_api_key": "devkey",
        "livekit_api_secret": "devsecret1234567890",
        "llm_base_url": "http://localhost:8080/v1",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_generator_config_from_settings_reads_use_grammar() -> None:
    config = generator_config_from_settings(_settings(llm_generator_use_grammar=False))
    assert config.use_grammar is False


def test_generator_config_from_settings_defaults_use_grammar_to_true() -> None:
    config = generator_config_from_settings(_settings())
    assert config.use_grammar is True


async def test_every_call_records_one_llm_generate_metric() -> None:
    """SPEC §27: one `InferenceMetric` per model call, whatever the outcome."""
    generator, _, metrics = make([LEAK, GOOD])

    await run(generator)

    assert [metric.stage for metric in metrics.metrics] == [
        InferenceStage.LLM_GENERATE,
        InferenceStage.LLM_GENERATE,
    ]
    assert [metric.status for metric in metrics.metrics] == ["OK", "OK"]
    assert [metric.retry_count for metric in metrics.metrics] == [0, 1]
    assert all(metric.session_id == SESSION_ID for metric in metrics.metrics)
    assert all(metric.turn_id == TURN_ID for metric in metrics.metrics)


# ---------------------------------------------------------------------------------------------
# Model failures (INV 14's generator half)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (LlmTimeoutError("too slow"), "TIMEOUT"),
        (LlmUnavailableError("no server"), "ERROR"),
        (RuntimeError("cuda is sulking"), "ERROR"),
    ],
)
async def test_a_failing_call_is_recorded_and_returns_no_answer(
    error: Exception, status: str
) -> None:
    generator, _, metrics = make([error])

    response = await run(generator)

    assert response.validated is False
    assert response.error_kind == type(error).__name__
    assert response.fallback_reason == type(error).__name__
    assert metrics.metrics[0].status == status


async def test_a_cancelled_call_is_recorded_as_cancelled_and_re_raised() -> None:
    """A barge-in must actually stop the turn — nothing is spoken and no fallback is produced."""
    generator, _, metrics = make([asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        await run(generator)

    assert [metric.status for metric in metrics.metrics] == ["CANCELLED"]
    assert metrics.metrics[0].error_kind == "BARGE_IN"


async def test_a_failing_repair_call_keeps_the_first_attempts_failures() -> None:
    generator, llm, _ = make([LEAK, LlmTimeoutError("too slow")])

    response = await run(generator)

    assert response.validated is False
    assert response.error_kind == "LlmTimeoutError"
    assert ValidationFailureCode.NEW_NUMBER.value in response.failure_codes
    assert len(llm.calls) == 2

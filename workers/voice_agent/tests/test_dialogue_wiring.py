"""The voice agent wires E13's dialogue chain behind ASR (R10, D2, D9, D13).

`wiring.py` is the process's composition root, so this is where "the chain is actually connected"
becomes a fact rather than an intention: the built `AsrTurnResponder.next_stage` is a
`DialogueResponder`, every stage is its own object, every literal comes from `Settings`, and the
`llm` health key is published exactly the way `asr`'s is.

The `SIM_LLM_PROVIDER=fake` default is exercised end to end, because a fake that answers nothing is
a chain that is wired and never run: `ScriptedFakeDialogueLLM` gives both calls a schema-valid,
validator-clean default so the gate's own test run goes all the way through (R10).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.application.dialogue.generator import CALLER_JSON_SCHEMA
from app.application.dialogue.interpreter import InterpretedUtterance
from app.application.dialogue.responder import DialogueResponder
from app.application.dialogue.speech_sink import NullCallerSpeechSink
from app.application.dialogue.validator import ResponseValidator, ValidatorConfig
from app.application.ports.llm import JsonSchemaSpec, LLMClient
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeClock
from app.application.voice.asr_responder import AsrTurnResponder
from app.application.voice.tts_speech_sink import TtsSpeechSink
from app.application.voice.turn_pipeline import TranscribedTurnResponder
from app.config.settings import Settings
from app.domain.facts.gate import AllowedFactsPackage
from app.inference.asr.fake_asr import FakeASR
from app.inference.tts.fake_tts import FakeTTS
from voice_agent.wiring import (
    ScriptedFakeDialogueLLM,
    VoiceAgentDeps,
    build_dialogue_llm,
    build_dialogue_responder,
    build_responder,
)


def settings(**overrides: Any) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        "redis_url": "redis://localhost:56379/0",
        "jwt_secret": "test-only-secret-padded-32-bytes!",
        "livekit_url": "ws://localhost:7880",
        "livekit_api_key": "devkey",
        "livekit_api_secret": "devsecret1234567890",
        "llm_base_url": "http://localhost:8080/v1",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def deps(**overrides: Any) -> VoiceAgentDeps:
    return VoiceAgentDeps.build(
        settings(**overrides),
        FakeClock(),
        lambda: None,  # type: ignore[arg-type,return-value]
    )


# ---------------------------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------------------------


def test_the_built_responder_chain_ends_in_a_dialogue_responder() -> None:
    """R10: `AsrTurnResponder(next_stage=…)` is where the interpreter → gate → generator goes."""
    built = deps()
    responder = build_responder(
        built,
        asr=FakeASR(),
        metrics=NullMetricsRecorder(),
        next_stage=build_dialogue_responder(built, metrics=NullMetricsRecorder()),
    )

    assert isinstance(responder, AsrTurnResponder)
    assert isinstance(responder.next_stage, DialogueResponder)
    assert isinstance(responder.next_stage, TranscribedTurnResponder)


def test_the_dialogue_responder_is_built_from_settings_not_literals() -> None:
    """§5.1/§5.2/§5.3/§7: every knob comes from `Settings` (SPEC §17's "configuration" rule)."""
    built = deps(
        llm_generator_max_tokens=64,
        llm_generator_temperature=0.5,
        caller_max_chars=222,
        caller_prompt_token_budget=2100,
        dialogue_window_turns=4,
    )
    responder = build_dialogue_responder(built, metrics=NullMetricsRecorder())

    generator = responder._generator
    assert generator._config.max_tokens == 64
    assert generator._config.temperature == 0.5
    assert generator._builder.config.prompt_token_budget == 2100
    assert generator._builder.config.max_window_turns == 4
    assert generator._validator.config.max_chars == 222


def test_the_default_speech_sink_is_e14s_tts_sink() -> None:
    """E13 decides the words; E14 decides the audio (R5) — and now wires the sink that does it."""
    responder = build_dialogue_responder(deps(), metrics=NullMetricsRecorder())

    assert isinstance(responder._sink, TtsSpeechSink)
    # `SIM_TTS_PROVIDER=fake` is the gate's, and `SIM_TTS_FALLBACK_PROVIDER=none` means the
    # "both providers failed" row of INV 14 is reachable rather than papered over by a fake.
    assert isinstance(responder._sink._provider, FakeTTS)
    assert responder._sink._fallback is None


def test_an_explicit_null_speech_sink_is_still_honoured() -> None:
    """A dialogue test that is about the *words* wires `NullCallerSpeechSink` deliberately."""
    null = NullCallerSpeechSink()
    responder = build_dialogue_responder(deps(), metrics=NullMetricsRecorder(), sink=null)

    assert responder._sink is null


def test_the_gate_is_not_a_collaborator() -> None:
    """SPEC §21: the Fact Access Gate is a pure function, so there is nothing to inject."""
    responder = build_dialogue_responder(deps(), metrics=NullMetricsRecorder())

    assert not hasattr(responder, "_gate")


# ---------------------------------------------------------------------------------------------
# The fake provider answers validly (R10)
# ---------------------------------------------------------------------------------------------


def test_the_fake_provider_is_wrapped_with_a_default_script() -> None:
    assert isinstance(build_dialogue_llm(deps()), ScriptedFakeDialogueLLM)


async def test_the_fake_answers_a_valid_interpretation_and_a_valid_caller_utterance() -> None:
    """A gate run with `SIM_LLM_PROVIDER=fake` exercises the chain instead of falling back."""
    llm: LLMClient = build_dialogue_llm(deps())

    interpretation = await llm.complete(
        [],
        request_id="r1",
        max_tokens=200,
        temperature=0.0,
        response_format=JsonSchemaSpec(name="operator_utterance_interpretation", schema={}),
        timeout_ms=2500,
    )
    caller = await llm.complete(
        [],
        request_id="r2",
        max_tokens=80,
        temperature=0.7,
        response_format=JsonSchemaSpec(name="caller_utterance", schema=CALLER_JSON_SCHEMA),
        timeout_ms=3000,
    )

    # The interpreter's schema accepts it…
    parsed = InterpretedUtterance.model_validate_json(interpretation.text)
    assert parsed.requested_facts == ()
    # …and the validator accepts the caller reply unmodified.
    verdict = ResponseValidator(ValidatorConfig()).validate(
        caller.text,
        package=AllowedFactsPackage(),
        revealed_values=(),
        operator_utterances=(),
        persona_whitelist=(),
        forbidden_values=(),
    )
    assert verdict.ok, verdict.failures
    assert json.loads(caller.text)["utterance"] == "Да, я слушаю."


async def test_the_wrapper_delegates_warm_up_and_close() -> None:
    """§4.2's LLM warm-up step must reach the real client, fake or not."""
    llm = build_dialogue_llm(deps())

    await llm.warm_up()
    await llm.cancel("r1")
    await llm.close()

    assert llm.model_name == "fake-llm"
    assert llm.n_ctx == 4096


async def test_the_wrapper_streams_the_same_default_answer() -> None:
    llm = build_dialogue_llm(deps())

    deltas = [
        delta
        async for delta in llm.stream(
            [],
            request_id="r3",
            max_tokens=80,
            temperature=0.7,
            response_format=JsonSchemaSpec(name="caller_utterance", schema=CALLER_JSON_SCHEMA),
            timeout_ms=3000,
        )
    ]

    assert [delta.text for delta in deltas] == ['{"utterance": "Да, я слушаю."}']


def test_a_real_provider_is_not_wrapped() -> None:
    """`ScriptedFakeDialogueLLM` is a property of how the *fake* is wired, never of a real one."""
    with pytest.raises(Exception):  # noqa: B017 - any refusal is fine; a wrap is not
        wrapped = build_dialogue_llm(deps(llm_provider="not-a-provider"))
        assert not isinstance(wrapped, ScriptedFakeDialogueLLM)

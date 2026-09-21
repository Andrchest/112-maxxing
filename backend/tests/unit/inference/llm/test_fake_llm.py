"""`FakeLLM` — determinism and port conformance (D13, HLD `50-voice-pipeline.md` §2.5).

`FakeLLM` is what the gate and every non-`requires_models` interpreter test runs against; its own
determinism is a property everything above it inherits, exactly as `test_fake_asr.py` argues for
`FakeASR`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.application.ports.llm import ChatMessage, JsonSchemaSpec, LLMClient, LlmStreamDelta
from app.inference.llm.fake_llm import FakeLLM

_MESSAGES = [ChatMessage(role="system", content="сис"), ChatMessage(role="user", content="привет")]


def test_fake_llm_is_an_llm_client() -> None:
    assert isinstance(FakeLLM(), LLMClient)


def test_the_identity_is_fixed() -> None:
    llm = FakeLLM()
    assert llm.model_name == "fake-llm"
    assert llm.n_ctx == 4096


async def test_a_string_entry_is_returned_as_the_completion_text() -> None:
    llm = FakeLLM(["привет, чем помочь?"])
    completion = await llm.complete(
        _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
    )
    assert completion.text == "привет, чем помочь?"
    assert completion.finish_reason == "stop"
    assert completion.request_id == "r1"
    assert completion.model == "fake-llm"


async def test_a_dict_entry_is_json_dumped() -> None:
    llm = FakeLLM([{"utterance": "алло"}])
    completion = await llm.complete(
        _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
    )
    assert completion.text == '{"utterance": "алло"}'


async def test_an_exception_instance_is_raised() -> None:
    llm = FakeLLM([ValueError("bad json")])
    try:
        await llm.complete(
            _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
        )
    except ValueError as exc:
        assert str(exc) == "bad json"
    else:
        raise AssertionError("expected the scripted exception to be raised")


async def test_a_plain_timeout_error_is_allowed_and_raised() -> None:
    llm = FakeLLM([TimeoutError("slow")])
    raised = False
    try:
        await llm.complete(
            _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
        )
    except TimeoutError:
        raised = True
    assert raised


async def test_the_script_advances_in_order_across_complete_and_stream() -> None:
    llm = FakeLLM(["first", "second"])
    first = await llm.complete(
        _MESSAGES, request_id="a", max_tokens=80, temperature=0.0, timeout_ms=1000
    )
    deltas = [
        d
        async for d in llm.stream(
            _MESSAGES, request_id="b", max_tokens=80, temperature=0.0, timeout_ms=1000
        )
    ]
    assert first.text == "first"
    assert "".join(d.text for d in deltas) == "second"


async def test_an_exhausted_script_returns_an_empty_completion() -> None:
    llm = FakeLLM()
    completion = await llm.complete(
        _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
    )
    assert completion.text == ""


async def test_stream_yields_deterministic_8_char_deltas_and_flags_the_first() -> None:
    llm = FakeLLM(["0123456789ABCDEFG"])
    deltas: list[LlmStreamDelta] = [
        d
        async for d in llm.stream(
            _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
        )
    ]
    assert [d.text for d in deltas] == ["01234567", "89ABCDEF", "G"]
    assert [d.index for d in deltas] == [0, 1, 2]
    assert [d.is_first for d in deltas] == [True, False, False]


async def test_stream_is_a_generator_and_two_iterations_are_independent_of_completes() -> None:
    """Two `stream()` calls over the fake share the one cursor, like `complete()` does."""
    llm = FakeLLM(["aaaaaaaa", "bbbbbbbb"])

    async def drain(iterator: AsyncIterator[LlmStreamDelta]) -> str:
        return "".join([chunk.text async for chunk in iterator])

    first = await drain(
        llm.stream(_MESSAGES, request_id="a", max_tokens=80, temperature=0.0, timeout_ms=1000)
    )
    second = await drain(
        llm.stream(_MESSAGES, request_id="b", max_tokens=80, temperature=0.0, timeout_ms=1000)
    )
    assert (first, second) == ("aaaaaaaa", "bbbbbbbb")


async def test_every_call_is_recorded_for_assertions() -> None:
    llm = FakeLLM(["ok"])
    schema = JsonSchemaSpec(name="s", schema={"type": "object"})
    await llm.complete(
        _MESSAGES,
        request_id="r1",
        max_tokens=42,
        temperature=0.5,
        response_format=schema,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        timeout_ms=1000,
    )
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call.kind == "complete"
    assert call.messages == _MESSAGES
    assert call.response_format is schema
    assert call.max_tokens == 42
    assert call.temperature == 0.5
    assert call.request_id == "r1"
    assert call.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


async def test_cancel_marks_the_request_id_and_never_raises() -> None:
    llm = FakeLLM()
    await llm.cancel("some-request")
    assert llm.cancelled == ["some-request"]


async def test_warm_up_and_close_are_counted() -> None:
    llm = FakeLLM()
    await llm.warm_up()
    await llm.warm_up()
    await llm.close()
    assert llm.warm_ups == 2
    assert llm.closed is True


async def test_no_randomness_two_runs_of_the_same_script_agree() -> None:
    async def run() -> list[str]:
        llm = FakeLLM(["алло", "да"])
        texts = []
        for i in range(2):
            completion = await llm.complete(
                _MESSAGES, request_id=f"r{i}", max_tokens=80, temperature=0.0, timeout_ms=1000
            )
            texts.append(completion.text)
        return texts

    first_calls = await run()
    second_calls = await run()
    assert first_calls == second_calls == ["алло", "да"]

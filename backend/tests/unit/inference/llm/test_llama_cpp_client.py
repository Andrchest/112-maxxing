"""`LlamaCppClient` — the base-url guard and the request/response shape (SPEC §22, §41).

No real server anywhere in this file: `httpx.MockTransport` stands in for llama-server, so these
tests run under plain `make gate` (D13). The real server is only in
`backend/tests/models/test_llama_cpp_contract.py` (marker `requires_models`).
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.application.ports.llm import (
    ChatMessage,
    JsonSchemaSpec,
    LlmTimeoutError,
    LlmUnavailableError,
)
from app.inference.errors import InferenceOutOfMemoryError
from app.inference.llm.errors import ExternalInferenceEndpointError
from app.inference.llm.llama_cpp_client import LlamaCppClient, validate_llm_base_url

# ---------------------------------------------------------------------------------------------
# base_url guard (SPEC §41): >= 12 cases, both directions
# ---------------------------------------------------------------------------------------------

_VALID_URLS = [
    "http://127.0.0.1:8080/v1",
    "http://127.5.5.5:8080/v1",  # 127.0.0.0/8, not just 127.0.0.1
    "http://localhost:8080/v1",
    "http://llama-server:8080/v1",  # default compose-internal allow-list entry
    "http://[::1]:8080/v1",
]

_INVALID_URLS = [
    "http://localhost.evil.com:8080/v1",  # looks like localhost, is not
    "http://127.0.0.1.nip.io:8080/v1",  # wildcard-DNS trick; no resolution is ever performed
    "https://api.openai.com/v1",
    "http://8.8.8.8:8080/v1",  # a real public IP
    "http://example.com/v1",
    "http://192.168.1.5:8080/v1",  # private, but not loopback and not allow-listed
    "http://0.0.0.0:8080/v1",  # unspecified, not loopback
    "http:///v1",  # no host at all
]


@pytest.mark.parametrize("url", _VALID_URLS)
def test_loopback_and_compose_internal_hosts_are_accepted(url: str) -> None:
    validate_llm_base_url(url)  # must not raise


@pytest.mark.parametrize("url", _INVALID_URLS)
def test_everything_else_is_rejected(url: str) -> None:
    with pytest.raises(ExternalInferenceEndpointError):
        validate_llm_base_url(url)


def test_the_guard_bites_at_client_construction_not_just_as_a_free_function() -> None:
    """The proof it bites: constructing the real client with a bad host must fail immediately."""
    with pytest.raises(ExternalInferenceEndpointError):
        LlamaCppClient(
            base_url="https://api.openai.com/v1",
            model_name="whatever",
            n_ctx=4096,
            default_timeout_ms=1000,
        )


def test_a_configured_internal_host_beyond_the_default_is_accepted() -> None:
    validate_llm_base_url(
        "http://my-llm-service:8080/v1", allowed_internal_hosts=("my-llm-service",)
    )


def test_no_dns_resolution_is_ever_attempted() -> None:
    """A host that cannot possibly resolve (`.invalid` TLD) is rejected the same, fast way."""
    with pytest.raises(ExternalInferenceEndpointError):
        validate_llm_base_url("http://definitely-does-not-exist.invalid:8080/v1")


# ---------------------------------------------------------------------------------------------
# Request/response shape, over `httpx.MockTransport`
# ---------------------------------------------------------------------------------------------

_MESSAGES = [
    ChatMessage(role="system", content="Ты — анализатор."),
    ChatMessage(role="user", content="Какой у вас адрес?"),
]


def _completion_response(text: str, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "id": "cmpl-1",
            "object": "chat.completion",
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
        },
    )


def _client(handler) -> LlamaCppClient:
    transport = httpx.MockTransport(handler)
    return LlamaCppClient(
        base_url="http://127.0.0.1:9/v1",
        model_name="test-model",
        n_ctx=4096,
        default_timeout_ms=1000,
        client=httpx.AsyncClient(transport=transport),
    )


async def test_thinking_is_always_disabled_with_no_caller_extra_body() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _completion_response("ок")

    llm = _client(handler)
    await llm.complete(_MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000)

    body = captured[0]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"][0]["content"].startswith("/no_think")
    assert body["messages"][-1]["content"].startswith("/no_think")


async def test_thinking_is_forced_off_even_if_the_caller_asks_for_it() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _completion_response("ок")

    llm = _client(handler)
    await llm.complete(
        _MESSAGES,
        request_id="r1",
        max_tokens=80,
        temperature=0.0,
        extra_body={"chat_template_kwargs": {"enable_thinking": True, "custom": 1}},
        timeout_ms=1000,
    )

    body = captured[0]
    assert body["chat_template_kwargs"] == {"enable_thinking": False, "custom": 1}


async def test_a_json_schema_response_format_is_sent_as_llama_cpp_expects() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _completion_response("{}")

    llm = _client(handler)
    schema = JsonSchemaSpec(name="thing", schema={"type": "object"}, strict=True)
    await llm.complete(
        _MESSAGES,
        request_id="r1",
        max_tokens=80,
        temperature=0.0,
        response_format=schema,
        timeout_ms=1000,
    )

    assert captured[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "thing", "schema": {"type": "object"}, "strict": True},
    }


async def test_a_think_block_is_stripped_and_flagged() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _completion_response("<think>рассуждение</think>Улица Ленина, дом 5")

    llm = _client(handler)
    completion = await llm.complete(
        _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
    )

    assert completion.text == "Улица Ленина, дом 5"
    assert llm.think_leaks == ["r1"]


async def test_no_think_block_means_nothing_is_flagged() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _completion_response("Улица Ленина, дом 5")

    llm = _client(handler)
    await llm.complete(_MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000)

    assert llm.think_leaks == []


async def test_usage_is_read_from_the_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _completion_response("ок")

    llm = _client(handler)
    completion = await llm.complete(
        _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
    )
    assert (completion.usage.prompt_tokens, completion.usage.completion_tokens) == (11, 4)


async def test_a_500_raises_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    llm = _client(handler)
    with pytest.raises(LlmUnavailableError):
        await llm.complete(
            _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
        )


async def test_an_allocation_failure_body_raises_out_of_memory_not_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text='{"error": "failed to allocate compute buffer"}')

    llm = _client(handler)
    with pytest.raises(InferenceOutOfMemoryError):
        await llm.complete(
            _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
        )


async def test_a_timeout_raises_llm_timeout_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=_request)

    llm = _client(handler)
    with pytest.raises(LlmTimeoutError):
        await llm.complete(
            _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
        )


def _sse_body(deltas: list[str]) -> bytes:
    lines = []
    for text in deltas:
        payload = json.dumps({"choices": [{"index": 0, "delta": {"content": text}}]})
        lines.append(f"data: {payload}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


async def test_stream_parses_sse_deltas_in_order() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse_body(["Улица ", "Ленина"]),
            headers={"content-type": "text/event-stream"},
        )

    llm = _client(handler)
    deltas = [
        d
        async for d in llm.stream(
            _MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000
        )
    ]
    assert [d.text for d in deltas] == ["Улица ", "Ленина"]
    assert deltas[0].is_first is True
    assert deltas[1].is_first is False


async def test_stream_first_delta_arrives_before_the_stream_is_drained() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse_body(["первый", "второй", "третий"]))

    llm = _client(handler)
    stream = llm.stream(_MESSAGES, request_id="r1", max_tokens=80, temperature=0.0, timeout_ms=1000)
    first = await stream.__anext__()
    assert first.text == "первый"


async def test_cancel_of_an_unknown_request_id_is_a_harmless_no_op() -> None:
    llm = _client(lambda request: _completion_response("ок"))
    await llm.cancel("no-such-request")  # must not raise

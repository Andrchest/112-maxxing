"""`FakeLLM` — the scripted `LLMClient` every non-`requires_models` test runs against (D1, D13).

Like `FakeASR` (`app.inference.asr.fake_asr`), it is a *script reader*: the caller hands it the
sequence of outcomes a test needs and it returns them in order, one per `complete()` / `stream()`
call, sharing one cursor across both. A `str` entry is the completion text; a `dict` entry is
`json.dumps`-ed first (the shape a schema-constrained interpreter call actually receives); an
`Exception` **instance** (including a plain `TimeoutError`) is raised. Nothing here reads the wall
clock, a random source or any global state, so the same script always produces the same calls.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.application.ports.llm import (
    ChatMessage,
    JsonSchemaSpec,
    LlmCompletion,
    LlmStreamDelta,
    LlmUsage,
)

__all__ = ["FakeLLM", "FakeLlmCall"]

#: `LLMClient.model_name` / `n_ctx` this fake reports (D13; the interpreter's `InterpreterConfig`
#: budgets against a real `n_ctx = 4096`, so the fake reports the same number).
_MODEL_NAME = "fake-llm"
_N_CTX = 4096
#: `stream()` yields the scripted text in fixed-size character chunks — deterministic and
#: independent of any tokenizer, which is what makes "the first delta arrived" assertable without
#: a real model.
_STREAM_CHUNK_CHARS = 8
#: `ceil(len(text) / 3)` — the same simple, deterministic token estimator the interpreter and
#: generator budget prompts with (no tokenizer dependency in the gate's test path).
_CHARS_PER_TOKEN = 3


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return -(-len(text) // _CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class FakeLlmCall:
    """One recorded `complete()`/`stream()` invocation, for a test's assertions."""

    kind: str
    """`"complete"` or `"stream"`."""

    messages: list[ChatMessage]
    response_format: JsonSchemaSpec | None
    max_tokens: int
    temperature: float
    request_id: str
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Scripted:
    text: str | None
    error: BaseException | None


def _resolve(entry: str | dict[str, Any] | BaseException) -> _Scripted:
    if isinstance(entry, BaseException):
        return _Scripted(text=None, error=entry)
    if isinstance(entry, dict):
        return _Scripted(text=json.dumps(entry, ensure_ascii=False), error=None)
    return _Scripted(text=entry, error=None)


class FakeLLM:
    """A deterministic `LLMClient` driven by a script (D13)."""

    def __init__(self, script: Sequence[str | dict[str, Any] | BaseException] = ()) -> None:
        self._script: list[_Scripted] = [_resolve(entry) for entry in script]
        self._cursor = 0
        #: Every `complete()`/`stream()` call, in call order.
        self.calls: list[FakeLlmCall] = []
        #: Every `request_id` passed to `cancel()`, in call order.
        self.cancelled: list[str] = []
        self.warm_ups = 0
        self.closed = False

    # -- port properties ----------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        return _MODEL_NAME

    @property
    def n_ctx(self) -> int:
        return _N_CTX

    # -- the port -----------------------------------------------------------------------------

    async def warm_up(self) -> None:
        self.warm_ups += 1

    async def close(self) -> None:
        self.closed = True

    async def cancel(self, request_id: str) -> None:
        self.cancelled.append(request_id)

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        request_id: str,
        max_tokens: int,
        temperature: float,
        top_p: float = 0.95,
        response_format: JsonSchemaSpec | None = None,
        stop: Sequence[str] = (),
        extra_body: dict[str, Any] | None = None,
        timeout_ms: int,
    ) -> LlmCompletion:
        self.calls.append(
            FakeLlmCall(
                kind="complete",
                messages=list(messages),
                response_format=response_format,
                max_tokens=max_tokens,
                temperature=temperature,
                request_id=request_id,
                extra_body=dict(extra_body or {}),
            )
        )
        text = self._next()
        prompt_tokens = sum(_estimate_tokens(message.content) for message in messages)
        return LlmCompletion(
            text=text,
            finish_reason="stop",
            usage=LlmUsage(prompt_tokens=prompt_tokens, completion_tokens=_estimate_tokens(text)),
            model=_MODEL_NAME,
            request_id=request_id,
        )

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        request_id: str,
        max_tokens: int,
        temperature: float,
        top_p: float = 0.95,
        response_format: JsonSchemaSpec | None = None,
        stop: Sequence[str] = (),
        extra_body: dict[str, Any] | None = None,
        timeout_ms: int,
    ) -> AsyncIterator[LlmStreamDelta]:
        return self._stream(
            messages,
            request_id=request_id,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
            extra_body=extra_body,
        )

    async def _stream(
        self,
        messages: list[ChatMessage],
        *,
        request_id: str,
        max_tokens: int,
        temperature: float,
        response_format: JsonSchemaSpec | None,
        extra_body: dict[str, Any] | None,
    ) -> AsyncIterator[LlmStreamDelta]:
        self.calls.append(
            FakeLlmCall(
                kind="stream",
                messages=list(messages),
                response_format=response_format,
                max_tokens=max_tokens,
                temperature=temperature,
                request_id=request_id,
                extra_body=dict(extra_body or {}),
            )
        )
        text = self._next()
        starts = range(0, len(text), _STREAM_CHUNK_CHARS)
        for index, start in enumerate(starts):
            chunk = text[start : start + _STREAM_CHUNK_CHARS]
            yield LlmStreamDelta(text=chunk, index=index, is_first=index == 0)

    # -- internals ----------------------------------------------------------------------------

    def _next(self) -> str:
        if self._cursor >= len(self._script):
            return ""
        entry = self._script[self._cursor]
        self._cursor += 1
        if entry.error is not None:
            raise entry.error
        return entry.text or ""

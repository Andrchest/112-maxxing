"""`LLMClient` port (HLD `50-voice-pipeline.md` §2.5, D10, SPEC §20-§22, §41).

Every model call in the dialogue chain — the interpreter (E13-B1) and, later, the caller
generator (E13-B2) — goes through this one Protocol. `FakeLLM` (`app.inference.llm.fake_llm`) is
what the gate and every non-`requires_models` test run against (D13); `LlamaCppClient`
(`app.inference.llm.llama_cpp_client`) is the only adapter that ever leaves the loopback/
compose-internal network (SPEC §41).

`LlmTimeoutError` and `LlmUnavailableError` live here, not in `app.inference`, because both a
caller in `app.application` (the interpreter, which classifies a failure into
`InferenceMetric.status`) and an adapter in `app.inference` (which raises them) need the same
type, and `app.application` may not import `app.inference` (D2). `app.inference` has no such
restriction the other way, so the adapter importing its own port module is the normal direction.

HLD gap: §2.5's snippet types `stop: list[str] = ()` and `extra_body: dict[str, Any] =
field(default_factory=dict)` as Protocol *method* defaults. Both are mypy-strict violations (a
mutable-typed parameter with an immutable default; `dataclasses.field()` used outside a
`@dataclass` body evaluates to a `Field` sentinel, not a `dict`) and neither is ever actually
invoked — a `Protocol` method body is `...`. The names, order and every other type are copied
verbatim; `stop` is typed `Sequence[str]` (a tuple literal satisfies it) and `extra_body` is typed
`dict[str, Any] | None` with `None` meaning "no extra body", which is what every caller in this
epic passes. See this task's report ("HLD gaps").
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

__all__ = [
    "ChatMessage",
    "JsonSchemaSpec",
    "LLMClient",
    "LlmCompletion",
    "LlmStreamDelta",
    "LlmTimeoutError",
    "LlmUnavailableError",
    "LlmUsage",
]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One chat-completion message (§2.5)."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class JsonSchemaSpec:
    """Rendered into llama.cpp's OpenAI-compatible
    `response_format={"type": "json_schema", "json_schema": {...}}`."""

    name: str
    schema: dict[str, Any]
    strict: bool = True


@dataclass(frozen=True, slots=True)
class LlmUsage:
    """Token accounting for one completion (SPEC §27)."""

    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True, slots=True)
class LlmCompletion:
    """One non-streaming (or fully drained) chat completion (§2.5)."""

    text: str
    finish_reason: Literal["stop", "length", "cancelled", "error"]
    usage: LlmUsage
    model: str
    request_id: str


@dataclass(frozen=True, slots=True)
class LlmStreamDelta:
    """One streamed token/chunk (§2.5)."""

    text: str
    index: int
    is_first: bool


class LlmTimeoutError(RuntimeError):
    """The call exceeded `timeout_ms` (SPEC §22, §27 `status = "TIMEOUT"`)."""


class LlmUnavailableError(RuntimeError):
    """The server could not be reached, or answered with a transport/HTTP failure that is not an
    out-of-memory condition (`app.inference.errors.InferenceOutOfMemoryError` is that one; SPEC
    §27 `status = "ERROR"`)."""


@runtime_checkable
class LLMClient(Protocol):
    """One local LLM endpoint, used for both the interpreter and the caller generator (D10)."""

    @property
    def model_name(self) -> str: ...

    @property
    def n_ctx(self) -> int: ...

    async def warm_up(self) -> None: ...

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
        """One non-streaming chat completion. Cancelled by cancelling the awaiting asyncio task,
        which must abort the underlying HTTP request rather than let it run to completion."""
        ...

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
        """Token stream. Closing the iterator (`aclose`) must cancel generation server-side."""
        ...

    async def cancel(self, request_id: str) -> None:
        """Best-effort out-of-band cancellation for a request issued from another task."""
        ...

    async def close(self) -> None: ...

"""`LlamaCppClient` — the real `LLMClient` over a local llama.cpp server (HLD `50-voice-pipeline.md`
§2.5, D10, SPEC §22, §27, §41).

Plain `httpx.AsyncClient` against llama.cpp's OpenAI-compatible `/chat/completions` endpoint — no
`openai`/`anthropic` SDK anywhere in this repository (`backend/tools/check_imports.py`). Three
things this adapter is responsible for that the port itself cannot enforce:

* **`base_url` never leaves the local machine (SPEC §41).** `validate_llm_base_url` runs at
  construction, not at call time, and does no DNS resolution — it is a pure string/`ipaddress`
  check against loopback addresses and a configured allow-list of compose-internal service names
  (default `("llama-server",)`). A host that merely *looks* loopback (`localhost.evil.com`,
  `127.0.0.1.nip.io`) is rejected exactly because no resolution happens.
* **Thinking is off, belt and braces (D10, "Thinking must be disabled").** Every request carries
  `chat_template_kwargs: {"enable_thinking": false}` in the body. HLD §2.5/§5.2 additionally say
  the client "prefixes the **last user** message with `/no_think`"; this task's brief says it
  prefixes the **system** message. The two disagree and neither is flagged as a ruling that
  overrides the other, so this adapter does both — every request gets a `/no_think`-prefixed
  system message *and* a `/no_think`-prefixed last user message — which satisfies both texts
  and is strictly more defensive than either alone. See this task's report ("HLD gaps").
  Any `<think>...</think>` block that still appears in a response is stripped defensively and the
  affected `request_id` is recorded on `self.think_leaks`, since the frozen `LlmCompletion` (§2.5)
  has no field to carry a per-call protocol-violation flag — a metrics/event home for this belongs
  to whichever epic wires `MetricsRecorder`/`MODEL_ERROR` to this client.
* **Failures map onto the port's vocabulary.** A timeout raises `LlmTimeoutError`; a connection or
  non-2xx HTTP failure raises `LlmUnavailableError`; a response body that looks like a llama.cpp
  allocation failure raises `app.inference.errors.InferenceOutOfMemoryError` instead of the plain
  "unavailable" — the one distinction `app.inference` callers actually branch on (§4.4 OOM path).
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import re
from collections.abc import AsyncIterator, Sequence
from types import TracebackType
from typing import Any
from urllib.parse import urlparse

import httpx

from app.application.ports.llm import (
    ChatMessage,
    JsonSchemaSpec,
    LlmCompletion,
    LlmStreamDelta,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
)
from app.inference.errors import InferenceOutOfMemoryError
from app.inference.llm.errors import ExternalInferenceEndpointError

__all__ = ["LlamaCppClient", "validate_llm_base_url"]

#: The compose-internal service name every model profile uses (`60-inference-ops.md` §1).
DEFAULT_ALLOWED_INTERNAL_HOSTS: tuple[str, ...] = ("llama-server",)

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_OOM_MARKERS: tuple[str, ...] = (
    "out of memory",
    "failed to allocate",
    "cudamalloc failed",
    "insufficient memory",
    "alloc_tensor",
)


def validate_llm_base_url(
    base_url: str, *, allowed_internal_hosts: Sequence[str] = DEFAULT_ALLOWED_INTERNAL_HOSTS
) -> None:
    """SPEC §41: `base_url`'s host must be loopback or a configured compose-internal name.

    Pure string/`ipaddress` check — **no DNS resolution** — so a host that would *resolve* to a
    loopback address (`127.0.0.1.nip.io`) or merely contains the word `localhost`
    (`localhost.evil.com`) is rejected rather than trusted.
    """
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        raise ExternalInferenceEndpointError(
            f"SIM_LLM_BASE_URL={base_url!r} has no host (SPEC §41)"
        )
    if host in allowed_internal_hosts:
        return
    if host == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ExternalInferenceEndpointError(
            f"SIM_LLM_BASE_URL host {host!r} is not loopback, not 'localhost' and not one of "
            f"the configured compose-internal hosts {tuple(allowed_internal_hosts)!r} (SPEC §41)"
        ) from exc
    if not address.is_loopback:
        raise ExternalInferenceEndpointError(
            f"SIM_LLM_BASE_URL host {host!r} ({address}) is not a loopback address (SPEC §41)"
        )


def _looks_like_oom(body_text: str) -> bool:
    lowered = body_text.lower()
    return any(marker in lowered for marker in _OOM_MARKERS)


def _no_think(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Prefix both the system message and the last user message with `/no_think` (see the module
    docstring's "HLD gaps" note: the brief and the HLD disagree about which one, so this does
    both)."""
    result = list(messages)
    for index, message in enumerate(result):
        if message.role == "system" and not message.content.startswith("/no_think"):
            result[index] = ChatMessage(role="system", content=f"/no_think\n{message.content}")
            break
    for index in range(len(result) - 1, -1, -1):
        if result[index].role == "user":
            if not result[index].content.startswith("/no_think"):
                result[index] = ChatMessage(
                    role="user", content=f"/no_think\n{result[index].content}"
                )
            break
    return result


def _message_dict(message: ChatMessage) -> dict[str, str]:
    return {"role": message.role, "content": message.content}


class LlamaCppClient:
    """`LLMClient` over llama.cpp's OpenAI-compatible HTTP endpoint (SPEC §22, §41)."""

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        n_ctx: int,
        default_timeout_ms: int,
        allowed_internal_hosts: Sequence[str] = DEFAULT_ALLOWED_INTERNAL_HOSTS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        validate_llm_base_url(base_url, allowed_internal_hosts=allowed_internal_hosts)
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._n_ctx = n_ctx
        self._default_timeout_ms = default_timeout_ms
        self._client = client if client is not None else httpx.AsyncClient()
        self._owns_client = client is None
        #: `request_id -> the open streaming response`, so `cancel()` can close it out of band.
        self._streams: dict[str, httpx.Response] = {}
        #: Every `request_id` whose response text contained a `<think>` block that was stripped
        #: (see the module docstring — `LlmCompletion` has no field for this).
        self.think_leaks: list[str] = []

    # -- port properties ----------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def n_ctx(self) -> int:
        return self._n_ctx

    # -- the port -----------------------------------------------------------------------------

    async def warm_up(self) -> None:
        """Best-effort: poll `/models` once. The full warm-up state machine is E18's."""
        with contextlib.suppress(httpx.HTTPError):
            await self._client.get(
                f"{self._base_url}/models", timeout=self._default_timeout_ms / 1000
            )

    async def close(self) -> None:
        for response in list(self._streams.values()):
            await response.aclose()
        self._streams.clear()
        if self._owns_client:
            await self._client.aclose()

    async def cancel(self, request_id: str) -> None:
        response = self._streams.pop(request_id, None)
        if response is not None:
            await response.aclose()

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
        body = self._build_body(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            response_format=response_format,
            stop=stop,
            extra_body=extra_body,
            stream=False,
        )
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions", json=body, timeout=timeout_ms / 1000
            )
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError(f"llama-server timed out after {timeout_ms}ms") from exc
        except httpx.HTTPError as exc:
            raise LlmUnavailableError(f"llama-server request failed: {exc}") from exc

        if response.status_code != 200:
            self._raise_for_status(response.status_code, response.text)

        payload = response.json()
        choice = payload["choices"][0]
        text = choice.get("message", {}).get("content") or ""
        text = self._strip_think(text, request_id).strip()
        usage = payload.get("usage", {})
        finish_reason = choice.get("finish_reason") or "stop"
        if finish_reason not in ("stop", "length", "cancelled", "error"):
            finish_reason = "stop"
        return LlmCompletion(
            text=text,
            finish_reason=finish_reason,  # type: ignore[arg-type]
            usage=LlmUsage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
            model=payload.get("model", self._model_name),
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
            top_p=top_p,
            response_format=response_format,
            stop=stop,
            extra_body=extra_body,
            timeout_ms=timeout_ms,
        )

    async def _stream(
        self,
        messages: list[ChatMessage],
        *,
        request_id: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        response_format: JsonSchemaSpec | None,
        stop: Sequence[str],
        extra_body: dict[str, Any] | None,
        timeout_ms: int,
    ) -> AsyncIterator[LlmStreamDelta]:
        body = self._build_body(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            response_format=response_format,
            stop=stop,
            extra_body=extra_body,
            stream=True,
        )
        index = 0
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=body,
                timeout=timeout_ms / 1000,
            ) as response:
                self._streams[request_id] = response
                try:
                    if response.status_code != 200:
                        raw = await response.aread()
                        self._raise_for_status(
                            response.status_code, raw.decode("utf-8", errors="replace")
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if not data or data == "[DONE]":
                            continue
                        chunk = json.loads(data)
                        choices = chunk.get("choices") or [{}]
                        delta_text = choices[0].get("delta", {}).get("content") or ""
                        delta_text = self._strip_think(delta_text, request_id)
                        if not delta_text:
                            continue
                        yield LlmStreamDelta(text=delta_text, index=index, is_first=index == 0)
                        index += 1
                finally:
                    self._streams.pop(request_id, None)
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError(f"llama-server stream timed out after {timeout_ms}ms") from exc
        except httpx.HTTPError as exc:
            raise LlmUnavailableError(f"llama-server stream failed: {exc}") from exc

    # -- internals ----------------------------------------------------------------------------

    def _build_body(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        response_format: JsonSchemaSpec | None,
        stop: Sequence[str],
        extra_body: dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        prefixed = _no_think(messages)
        body: dict[str, Any] = {
            "model": self._model_name,
            "messages": [_message_dict(message) for message in prefixed],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": stream,
        }
        if stop:
            body["stop"] = list(stop)
        if response_format is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_format.name,
                    "schema": response_format.schema,
                    "strict": response_format.strict,
                },
            }
        merged_extra = dict(extra_body or {})
        chat_template_kwargs = dict(merged_extra.pop("chat_template_kwargs", {}))
        # Always sent, regardless of what the caller asked for (D10, "belt and braces").
        chat_template_kwargs["enable_thinking"] = False
        body.update(merged_extra)
        body["chat_template_kwargs"] = chat_template_kwargs
        return body

    def _strip_think(self, text: str, request_id: str) -> str:
        if "<think>" in text.lower():
            text = _THINK_BLOCK_RE.sub("", text).strip()
            self.think_leaks.append(request_id)
        return text

    def _raise_for_status(self, status_code: int, body_text: str) -> None:
        if _looks_like_oom(body_text):
            raise InferenceOutOfMemoryError(
                f"llama-server allocation failure (HTTP {status_code}): {body_text[:500]}"
            )
        raise LlmUnavailableError(f"llama-server returned HTTP {status_code}: {body_text[:500]}")

    async def __aenter__(self) -> LlamaCppClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

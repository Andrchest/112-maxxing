"""Inference health: the pure state machine of HLD 60 §4.1 and the OOM guard of §4.4 (SPEC §39).

Three things live here, and the split between them is the point of the module:

1. **`ServiceHealth`** — one service's state machine (`llm`, `asr`, `tts`, `vad`). Pure: no Redis,
   no clock of its own, no logging that matters, no I/O at all. Every method answers with a
   `HealthTransition` (or `None` when the event changed nothing), so §4.1's transition table can be
   unit-tested row by row without a process. `InferenceHealth` is the four of them together.
2. **`InferenceHealthGuard`** — the `app.application.ports.inference_guard.InferenceGuard`
   implementation, i.e. §4.4's `guard_inference(stage)`. It wraps a model call, routes the outcome
   into the state machine, publishes whatever transition came out, and then lets the stage's own
   deterministic fallback ladder run (or returns the fallback the caller supplied). It never calls
   a session use case, never appends an event of its own, never touches
   `simulation_sessions.state`: **an OOM changes health, never simulation state** (§4.4 rule 3).
3. **`GuardedLLMClient`** — one adapter-shaped wrapper, because the LLM is the one stage whose two
   call sites (the interpreter and the caller generator, `app.application.dialogue`) are not in the
   voice-agent's own reach: wrapping the `LLMClient` port object itself puts *both* behind the guard
   without the dialogue package knowing a guard exists. The other three stages take an
   `InferenceGuard` at their own seam (`TurnPipeline` for VAD, `AsrTurnResponder` for ASR,
   `TtsSpeechSink` for TTS).

§4.1's table, implemented literally:

| From | Event | To |
|:--|:--|:--|
| NOT_READY | warm-up started | WARMING |
| WARMING | warm-up succeeded | READY |
| WARMING | warm-up failed, recoverable | NOT_READY |
| WARMING | warm-up failed, unrecoverable (OOM, missing model, no CUDA) | FATAL |
| READY | `failure_threshold` consecutive runtime failures | NOT_READY |
| READY | GPU OOM at runtime | FATAL |
| NOT_READY | periodic re-warm (`rewarm_interval_s`) | WARMING |
| FATAL | — | nothing; only a process restart leaves FATAL |

FATAL is terminal **in this process**: `due_for_rewarm()` answers `False` for it forever, so the
re-warm loop never retries it, and `voice:health:fatal` (written without an expiry by the publisher
in `voice_agent.main`) is what stops a restart loop from making a fatal condition look transient.
Only `clearInferenceFatal` (ADMIN) or a clean warm-up after a manual restart clears it.

`torch.cuda.empty_cache()` is called once after a transition to FATAL — and only if `torch` is
importable, because the gate runs on fake providers in a venv that has no torch (D13). No model is
ever reloaded: "reloading into a fragmented, contended 8 GB card is how one OOM becomes a loop"
(§4.4 rule 4).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from app.application.ports.inference_guard import SERVICE_FOR_STAGE
from app.application.ports.llm import ChatMessage, JsonSchemaSpec, LlmCompletion, LlmStreamDelta
from app.inference.errors import InferenceOutOfMemoryError

__all__ = [
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_REWARM_INTERVAL_S",
    "HEALTH_SERVICES",
    "STATE_FATAL",
    "STATE_NOT_READY",
    "STATE_READY",
    "STATE_WARMING",
    "GuardedLLMClient",
    "HealthTransition",
    "InferenceHealth",
    "InferenceHealthGuard",
    "ServiceHealth",
    "empty_cuda_cache",
]

logger = logging.getLogger(__name__)

#: Cancellation is not a failure. `asyncio.CancelledError` is a `BaseException`, and E12/E13/E14 all
#: treat it as "the trainee is talking again"; `GeneratorExit` is the same story for a stream being
#: torn down. Neither ever counts toward `failure_threshold`.
_CANCELLED_TYPES: tuple[type[BaseException], ...] = (asyncio.CancelledError, GeneratorExit)

#: §4.1's four states. Plain strings, not an enum, because they are a *wire* vocabulary: the
#: `voice:health:{service}` payload's `state` field and the backend's `HealthStatus` share these
#: spellings and `10-domain-model.md` §10.2's "member name is its wire value" rule applies.
STATE_NOT_READY = "NOT_READY"
STATE_WARMING = "WARMING"
STATE_READY = "READY"
STATE_FATAL = "FATAL"

#: The four services one voice-agent process owns a state for (§4.1; `postgres`/`redis`/`livekit`
#: are the backend's, D8). Warm-up order, which is §4.2's order.
HEALTH_SERVICES: tuple[str, ...] = ("vad", "asr", "llm", "tts")

#: §4.1's `health.failure_threshold` / `health.rewarm_interval_s` defaults. A profile's `health`
#: block (`app.config.profile.HealthProfile`) overrides them.
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_REWARM_INTERVAL_S = 30


@dataclass(frozen=True, slots=True)
class HealthTransition:
    """One state change, as the publisher and the pub/sub channel need it (§4.3).

    `at` is deliberately absent: a pure state machine has no clock. The publisher stamps the
    instant from the injected `Clock` when it turns this into a Redis payload.
    """

    service: str
    from_state: str
    to_state: str
    detail: str | None = None

    @property
    def is_fatal(self) -> bool:
        """True when this transition latches FATAL, i.e. `voice:health:fatal` must be written."""
        return self.to_state == STATE_FATAL


class ServiceHealth:
    """One service's §4.1 state machine. Pure — every method is a total function of its state."""

    def __init__(
        self,
        service: str,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        rewarm_interval_s: int = DEFAULT_REWARM_INTERVAL_S,
        state: str = STATE_NOT_READY,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("health.failure_threshold must be at least 1")
        if rewarm_interval_s < 1:
            raise ValueError("health.rewarm_interval_s must be at least 1 second")
        self._service = service
        self._failure_threshold = failure_threshold
        self._rewarm_interval_s = rewarm_interval_s
        self._state = state
        self._consecutive_failures = 0
        self._detail: str | None = None
        #: The monotonic second the service last *left* WARMING, i.e. when the re-warm clock for a
        #: NOT_READY service started. `None` means "never warmed", which is due immediately.
        self._not_ready_since_s: float | None = None

    # -- read-only view ------------------------------------------------------------------------

    @property
    def service(self) -> str:
        """The `voice:health:{service}` name."""
        return self._service

    @property
    def state(self) -> str:
        """The current §4.1 state."""
        return self._state

    @property
    def detail(self) -> str | None:
        """Why the service is in this state, for the payload's `detail` field."""
        return self._detail

    @property
    def consecutive_failures(self) -> int:
        """Runtime failures since the last success — §4.1's `failure_threshold` counter."""
        return self._consecutive_failures

    @property
    def failure_threshold(self) -> int:
        """`health.failure_threshold`."""
        return self._failure_threshold

    @property
    def rewarm_interval_s(self) -> int:
        """`health.rewarm_interval_s`."""
        return self._rewarm_interval_s

    # -- the transition table ------------------------------------------------------------------

    def warm_started(self) -> HealthTransition | None:
        """NOT_READY → WARMING. FATAL never restarts a warm-up; READY needs none."""
        if self._state in (STATE_FATAL, STATE_WARMING, STATE_READY):
            return None
        return self._to(STATE_WARMING, None)

    def warm_succeeded(self, *, detail: str | None = None) -> HealthTransition | None:
        """WARMING → READY. Clears the failure counter and any latched detail."""
        if self._state == STATE_FATAL:
            return None
        self._consecutive_failures = 0
        if self._state == STATE_READY:
            return None
        return self._to(STATE_READY, detail)

    def warm_failed(
        self, *, recoverable: bool, detail: str | None = None, now_s: float | None = None
    ) -> HealthTransition | None:
        """WARMING → NOT_READY (recoverable) or → FATAL (OOM, missing model, no CUDA)."""
        if self._state == STATE_FATAL:
            return None
        if not recoverable:
            return self._to(STATE_FATAL, detail)
        self._not_ready_since_s = now_s
        return self._to(STATE_NOT_READY, detail)

    def runtime_success(self) -> None:
        """A model call succeeded: the consecutive-failure counter resets. No transition (§4.1)."""
        self._consecutive_failures = 0

    def runtime_failure(
        self, *, detail: str | None = None, now_s: float | None = None
    ) -> HealthTransition | None:
        """One ordinary runtime failure; the `failure_threshold`-th in a row demotes to NOT_READY.

        A service that is already NOT_READY stays NOT_READY (and keeps counting, so the log shows
        how bad it is); FATAL is untouched, because FATAL is terminal.
        """
        if self._state == STATE_FATAL:
            return None
        self._consecutive_failures += 1
        if self._consecutive_failures < self._failure_threshold:
            return None
        if self._state == STATE_NOT_READY:
            return None
        self._not_ready_since_s = now_s
        return self._to(
            STATE_NOT_READY,
            detail
            or f"{self._consecutive_failures} consecutive failures "
            f"(health.failure_threshold {self._failure_threshold})",
        )

    def out_of_memory(self, *, detail: str | None = None) -> HealthTransition | None:
        """Any state → FATAL. §4.4: an OOM is never recoverable and never auto-retried."""
        if self._state == STATE_FATAL:
            return None
        return self._to(STATE_FATAL, detail)

    def due_for_rewarm(self, now_s: float) -> bool:
        """§4.1's periodic re-warm: NOT_READY and `rewarm_interval_s` elapsed.

        FATAL answers `False` forever — "only a process restart leaves FATAL".
        """
        if self._state != STATE_NOT_READY:
            return False
        if self._not_ready_since_s is None:
            return True
        return (now_s - self._not_ready_since_s) >= self._rewarm_interval_s

    def _to(self, state: str, detail: str | None) -> HealthTransition:
        transition = HealthTransition(
            service=self._service, from_state=self._state, to_state=state, detail=detail
        )
        self._state = state
        self._detail = detail
        return transition


class InferenceHealth:
    """The four `ServiceHealth` machines of one voice-agent process (§4.1)."""

    def __init__(
        self,
        *,
        services: Sequence[str] = HEALTH_SERVICES,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        rewarm_interval_s: int = DEFAULT_REWARM_INTERVAL_S,
    ) -> None:
        self._services = {
            service: ServiceHealth(
                service,
                failure_threshold=failure_threshold,
                rewarm_interval_s=rewarm_interval_s,
            )
            for service in services
        }

    def __getitem__(self, service: str) -> ServiceHealth:
        """The named service's machine."""
        return self._services[service]

    def __contains__(self, service: object) -> bool:
        """Whether this process owns a state for `service`."""
        return service in self._services

    @property
    def services(self) -> tuple[str, ...]:
        """Every service name, in warm-up order."""
        return tuple(self._services)

    @property
    def any_fatal(self) -> bool:
        """True while at least one service is FATAL — what `voice:health:fatal` mirrors (§4.3)."""
        return any(machine.state == STATE_FATAL for machine in self._services.values())

    @property
    def all_ready(self) -> bool:
        """True when every service is READY (the backend's `is_ready()` answer, R4)."""
        return all(machine.state == STATE_READY for machine in self._services.values())

    def machine_or_none(self, service: str) -> ServiceHealth | None:
        """The named service's machine, or `None` for a service this process does not own."""
        return self._services.get(service)

    def state(self, service: str) -> str:
        """One service's state, or NOT_READY for a service this process does not own."""
        machine = self._services.get(service)
        return machine.state if machine is not None else STATE_NOT_READY

    def due_for_rewarm(self, now_s: float) -> tuple[str, ...]:
        """Every NOT_READY service whose `rewarm_interval_s` has elapsed (§4.1)."""
        return tuple(
            service for service, machine in self._services.items() if machine.due_for_rewarm(now_s)
        )


def empty_cuda_cache() -> bool:
    """`torch.cuda.empty_cache()` if — and only if — torch is importable (§4.4 rule 4).

    The gate runs entirely on fake providers in a venv with no torch (D13), so this must be a
    no-op there rather than an ImportError. Returns whether the cache was actually emptied, which
    is what a unit test asserts instead of monkey-patching a module that may not exist.
    """
    try:  # pragma: no cover - the gate venv has no torch; the real path is E19's
        import torch
    except Exception:
        return False
    try:  # pragma: no cover - same
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            return True
    except Exception:
        logger.warning("torch.cuda.empty_cache() failed after a FATAL transition", exc_info=True)
    return False


#: How a transition reaches Redis. Injected rather than imported, so the state machine and the
#: guard stay testable with a list-appending fake (`voice_agent.main.VoiceAgent` supplies the real
#: one, which writes `voice:health:{service}`, publishes on `voice:health` and latches
#: `voice:health:fatal`).
PublishTransition = Callable[[HealthTransition], Awaitable[None]]

T = TypeVar("T")


class InferenceHealthGuard:
    """§4.4's `guard_inference(stage)` as an `InferenceGuard` (R5).

    One instance per process, shared by every call: it holds no session, no turn and no appender,
    which is *why* it cannot touch simulation state even by accident.
    """

    def __init__(
        self,
        health: InferenceHealth,
        publish: PublishTransition,
        *,
        monotonic_s: Callable[[], float] | None = None,
        empty_cache: Callable[[], bool] = empty_cuda_cache,
    ) -> None:
        self._health = health
        self._publish = publish
        self._monotonic_s = monotonic_s if monotonic_s is not None else _default_monotonic_s
        self._empty_cache = empty_cache

    @property
    def health(self) -> InferenceHealth:
        """The state machines this guard feeds — read-only for a caller, asserted by tests."""
        return self._health

    async def run(
        self,
        stage: str,
        call: Callable[[], Awaitable[T]],
        *,
        fallback: Callable[[], Awaitable[T]] | None = None,
    ) -> T:
        """Await `call()`, routing its outcome into `stage`'s health (§4.4 steps 1-4)."""
        service = SERVICE_FOR_STAGE.get(stage, stage.lower())
        machine = self._health.machine_or_none(service)
        try:
            result = await call()
        except BaseException as exc:
            # A cancellation is a barge-in, not a model failure (§6.1): it must never count
            # toward `failure_threshold` and never demote a healthy service.
            if isinstance(exc, _CANCELLED_TYPES):
                raise
            if machine is not None:
                await self._on_failure(machine, exc)
            if fallback is None:
                raise
            return await fallback()
        if machine is not None:
            machine.runtime_success()
        return result

    async def _on_failure(self, machine: ServiceHealth, exc: BaseException) -> None:
        detail = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, InferenceOutOfMemoryError):
            transition = machine.out_of_memory(detail=detail)
            logger.error("%s reported OOM; it is FATAL and will not be re-warmed", machine.service)
            if transition is not None:
                await self._publish(transition)
                # Once, after the transition, and no model is ever reloaded (§4.4 rule 4).
                self._empty_cache()
            return
        transition = machine.runtime_failure(detail=detail, now_s=self._monotonic_s())
        if transition is not None:
            logger.warning(
                "%s demoted to %s after %d consecutive failures",
                machine.service,
                transition.to_state,
                machine.consecutive_failures,
            )
            await self._publish(transition)


def _default_monotonic_s() -> float:
    return time.monotonic()


class GuardedLLMClient:
    """An `LLMClient` whose `complete()`/`stream()` go through an `InferenceGuard` (R5).

    The LLM is the one guarded stage with two call sites the voice-agent cannot reach directly:
    `DialogueInterpreter` and `CallerResponseGenerator` live in `app.application.dialogue`, which
    knows nothing about health and must keep knowing nothing (D2/D3). Wrapping the port object
    itself — once, in `voice_agent.main`, around the single client both stages share — puts both
    behind the guard without a line of dialogue code changing.

    No `fallback` is supplied: both stages already own §4.1/§7.8's deterministic ladders (the
    interpreter answers `UNINTELLIGIBLE` + `MODEL_FALLBACK_USED`, the generator falls back to the
    gate-outcome template), so the guard records the health transition and re-raises, and the
    existing ladder produces the caller's line exactly as it does today.
    """

    def __init__(self, inner: Any, guard: Any) -> None:
        self._inner = inner
        self._guard = guard

    @property
    def inner(self) -> Any:
        """The wrapped client — what a test asserts the wiring kept."""
        return self._inner

    @property
    def model_name(self) -> str:
        """The wrapped client's model name."""
        name: str = self._inner.model_name
        return name

    @property
    def n_ctx(self) -> int:
        """The wrapped client's context size."""
        size: int = self._inner.n_ctx
        return size

    async def warm_up(self) -> None:
        """Warm the wrapped client up. Warm-up health is `VoiceAgent._warm_component`'s job."""
        await self._inner.warm_up()

    async def cancel(self, request_id: str) -> None:
        """Cancel on the wrapped client — never a guarded call (a cancel is not inference)."""
        await self._inner.cancel(request_id)

    async def close(self) -> None:
        """Close the wrapped client."""
        await self._inner.close()

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
        """`complete()` under the guard: both dialogue stages reach the LLM through here."""

        async def _call() -> LlmCompletion:
            completion: LlmCompletion = await self._inner.complete(
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
            return completion

        result: LlmCompletion = await self._guard.run("LLM", _call)
        return result

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
    ) -> Any:
        """`stream()` under the guard, reported when the **first** delta is pulled.

        A streaming OOM surfaces on the first `__anext__`, which is where llama-server's
        allocation failure arrives, so the guard wraps that pull rather than the (synchronous)
        call that merely builds the iterator.
        """
        inner = self._inner

        async def _guarded() -> Any:
            iterator = inner.stream(
                messages,
                request_id=request_id,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                response_format=response_format,
                stop=stop,
                extra_body=extra_body,
                timeout_ms=timeout_ms,
            ).__aiter__()

            async def _first() -> LlmStreamDelta:
                delta: LlmStreamDelta = await iterator.__anext__()
                return delta

            first = await self._guard.run("LLM", _first)
            yield first
            async for delta in iterator:
                yield delta

        return _guarded()

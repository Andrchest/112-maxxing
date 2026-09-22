"""`InferenceGuard` — the seam between a model call and the inference health state machine.

`docs/hld/60-inference-ops.md` §4.4 puts the rule plainly: **an OOM changes health, never
simulation state.** The mechanism it names is `guard_inference(stage)`, a wrapper around every
model call, living in `workers/voice_agent/voice_agent/health.py` — the voice-agent process, which
is the only process that owns a model.

`app.application` may not import `voice_agent` (D2, enforced by `backend/tools/check_imports.py`),
so the pipeline reaches that state machine through this port. The real implementation is
`voice_agent.health.InferenceHealthGuard`; the default everywhere else — every existing unit test,
the backend container, a process with no health registry at all — is `NoOpInferenceGuard`, which
awaits the call and changes nothing. A guard is therefore never required to run the pipeline; it is
required only to make a failure *visible* as health.

What the guard does and does not do:

* it **observes**: a success resets that service's consecutive-failure counter, an ordinary failure
  increments it (`health.failure_threshold` consecutive failures take a READY service to
  NOT_READY), and an `app.inference.errors.InferenceOutOfMemoryError` takes it straight to FATAL;
* it **never invents a fallback of its own**. The deterministic fallback of a stage belongs to that
  stage — `AsrTurnResponder` writes `MODEL_ERROR` and no transcript, `TtsSpeechSink` retries on the
  configured fallback provider and otherwise ends the turn silent-but-complete, the interpreter
  answers `UNINTELLIGIBLE` and the generator falls back to a template. So `run()` re-raises by
  default and the stage's own ladder runs, exactly as it does today. `fallback` is for the one
  stage that has no ladder of its own (VAD, whose frame score has a safe deterministic value);
* it **never touches session state**. It has no session use case, no repository and no appender.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar, runtime_checkable

__all__ = [
    "OUT_OF_MEMORY_ERROR_NAME",
    "SERVICE_FOR_STAGE",
    "STAGE_ASR",
    "STAGE_LLM",
    "STAGE_TTS",
    "STAGE_VAD",
    "InferenceGuard",
    "NoOpInferenceGuard",
    "is_out_of_memory",
]

T = TypeVar("T")

#: `app.inference.errors.InferenceOutOfMemoryError`, by name.
#:
#: D2 forbids `app.application` from importing `app.inference`, and
#: `backend/tools/check_imports.py` enforces it — yet the stages in `app.application.voice` must be
#: able to tell an allocation failure from an ordinary provider error, because §4.4 gives it a
#: different `MODEL_ERROR.error_code` (`OOM`) and a different `recoverable` flag (`false`). The
#: established precedent for a type that must cross this boundary is `app.application.ports.tts`,
#: which *defines* `TtsTimeoutError` in the port so both sides can name it. The OOM error already
#: exists in the adapter package and is raised by three providers, so rather than move it
#: (and churn every adapter), the application side recognises it by class name over the whole MRO.
#: `app.inference.errors`'s own docstring names this guard as its intended consumer.
OUT_OF_MEMORY_ERROR_NAME = "InferenceOutOfMemoryError"


def is_out_of_memory(exc: BaseException) -> bool:
    """True for `app.inference.errors.InferenceOutOfMemoryError` and any subclass of it."""
    return any(base.__name__ == OUT_OF_MEMORY_ERROR_NAME for base in type(exc).__mro__)


#: The four stage labels the guard understands. They are the `MODEL_ERROR.component` spelling of
#: `10-domain-model.md` §10.13 (upper case), not the health-key spelling.
STAGE_VAD = "VAD"
STAGE_ASR = "ASR"
STAGE_LLM = "LLM"
STAGE_TTS = "TTS"

#: `stage -> voice:health:{service}` (§4.3's four services, lower case).
SERVICE_FOR_STAGE: dict[str, str] = {
    STAGE_VAD: "vad",
    STAGE_ASR: "asr",
    STAGE_LLM: "llm",
    STAGE_TTS: "tts",
}


@runtime_checkable
class InferenceGuard(Protocol):
    """Wraps one model call so its outcome reaches the health state machine (§4.4)."""

    async def run(
        self,
        stage: str,
        call: Callable[[], Awaitable[T]],
        *,
        fallback: Callable[[], Awaitable[T]] | None = None,
    ) -> T:
        """Await `call()`, recording the outcome against `stage`'s health.

        On failure: the health transition happens first, then either `fallback()` is awaited and
        its value returned (when the stage has a deterministic fallback the guard can produce) or
        the original exception is re-raised so the stage's own fallback ladder runs.
        """
        ...


class NoOpInferenceGuard:
    """The default: call through, observe nothing (D13).

    Every seam that takes a guard defaults to this one, so the whole voice path keeps behaving
    exactly as it did before this epic in any process — every existing test included — that does
    not deliberately wire a health registry.
    """

    async def run(
        self,
        stage: str,
        call: Callable[[], Awaitable[T]],
        *,
        fallback: Callable[[], Awaitable[T]] | None = None,
    ) -> T:
        """Await `call()` and let every exception propagate untouched."""
        return await call()

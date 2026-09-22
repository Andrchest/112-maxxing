"""`voice_agent.health` — HLD 60 §4.1's transition table, row by row, and §4.4's guard (E18-C).

The state machine is pure, so every row of §4.1's table is a two-line test with no process, no
Redis, no clock and no model. The guard gets a fake publisher (a list) and a fake `empty_cache`
(a counter), which is why "`torch.cuda.empty_cache()` is called once, and no model is reloaded" is
assertable in a gate venv that has no torch at all (D13).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.application.ports.inference_guard import STAGE_ASR, STAGE_LLM, STAGE_TTS, STAGE_VAD
from app.inference.errors import InferenceOutOfMemoryError, ModelNotAvailableError
from voice_agent.health import (
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_REWARM_INTERVAL_S,
    STATE_FATAL,
    STATE_NOT_READY,
    STATE_READY,
    STATE_WARMING,
    GuardedLLMClient,
    HealthTransition,
    InferenceHealth,
    InferenceHealthGuard,
    ServiceHealth,
)

# -- §4.1's transition table -------------------------------------------------------------------


def test_the_documented_defaults_are_the_hld_s() -> None:
    """§4.1: `health.failure_threshold` 3, `health.rewarm_interval_s` 30."""
    assert DEFAULT_FAILURE_THRESHOLD == 3
    assert DEFAULT_REWARM_INTERVAL_S == 30
    assert ServiceHealth("llm").state == STATE_NOT_READY


def test_not_ready_to_warming_to_ready() -> None:
    """Rows 1 and 2: a warm-up that starts and succeeds."""
    machine = ServiceHealth("asr")
    started = machine.warm_started()
    assert started == HealthTransition("asr", STATE_NOT_READY, STATE_WARMING, None)
    assert machine.state == STATE_WARMING
    succeeded = machine.warm_succeeded()
    assert succeeded is not None and succeeded.to_state == STATE_READY
    assert machine.state == STATE_READY


def test_a_recoverable_warm_up_failure_is_not_ready_not_fatal() -> None:
    """Row 3: "warm-up failed, recoverable (timeout, connection refused)" → NOT_READY."""
    machine = ServiceHealth("llm")
    machine.warm_started()
    transition = machine.warm_failed(recoverable=True, detail="connection refused", now_s=0.0)
    assert transition is not None
    assert (transition.from_state, transition.to_state) == (STATE_WARMING, STATE_NOT_READY)
    assert machine.detail == "connection refused"


def test_an_unrecoverable_warm_up_failure_is_fatal() -> None:
    """Row 4: "warm-up failed, unrecoverable (OOM, missing model, no CUDA)" → FATAL."""
    machine = ServiceHealth("tts")
    machine.warm_started()
    transition = machine.warm_failed(recoverable=False, detail="no CUDA device", now_s=0.0)
    assert transition is not None and transition.to_state == STATE_FATAL
    assert transition.is_fatal is True


def test_three_consecutive_runtime_failures_demote_a_ready_service() -> None:
    """Row 5: `failure_threshold` consecutive runtime failures, READY → NOT_READY — and not one
    failure earlier."""
    machine = ServiceHealth("asr", failure_threshold=3)
    machine.warm_started()
    machine.warm_succeeded()
    assert machine.runtime_failure(now_s=0.0) is None
    assert machine.state == STATE_READY
    assert machine.runtime_failure(now_s=0.0) is None
    assert machine.state == STATE_READY
    third = machine.runtime_failure(now_s=0.0)
    assert third is not None and third.to_state == STATE_NOT_READY
    assert machine.consecutive_failures == 3


def test_a_success_resets_the_consecutive_failure_counter() -> None:
    """Row 5 says *consecutive*: two failures and a success in between is not three failures."""
    machine = ServiceHealth("asr", failure_threshold=3)
    machine.warm_started()
    machine.warm_succeeded()
    machine.runtime_failure(now_s=0.0)
    machine.runtime_failure(now_s=0.0)
    machine.runtime_success()
    assert machine.consecutive_failures == 0
    assert machine.runtime_failure(now_s=0.0) is None
    assert machine.state == STATE_READY


def test_a_runtime_oom_takes_a_ready_service_straight_to_fatal() -> None:
    """Row 6: "GPU OOM at runtime" — no threshold, no counting, no second chance."""
    machine = ServiceHealth("tts")
    machine.warm_started()
    machine.warm_succeeded()
    transition = machine.out_of_memory(detail="CUDA out of memory")
    assert transition is not None
    assert (transition.from_state, transition.to_state) == (STATE_READY, STATE_FATAL)


def test_a_not_ready_service_becomes_due_for_a_rewarm_after_the_interval() -> None:
    """Row 7: NOT_READY → WARMING on the periodic re-warm, `rewarm_interval_s` later."""
    machine = ServiceHealth("llm", rewarm_interval_s=30)
    machine.warm_started()
    machine.warm_failed(recoverable=True, now_s=100.0)
    assert machine.due_for_rewarm(100.0) is False
    assert machine.due_for_rewarm(129.0) is False
    assert machine.due_for_rewarm(130.0) is True


def test_fatal_is_terminal_and_never_due_for_a_rewarm() -> None:
    """Row 8: "nothing; only a process restart leaves FATAL"."""
    machine = ServiceHealth("tts")
    machine.out_of_memory(detail="OOM")
    assert machine.due_for_rewarm(10_000.0) is False
    assert machine.warm_started() is None
    assert machine.warm_succeeded() is None
    assert machine.runtime_failure(now_s=10_000.0) is None
    assert machine.out_of_memory() is None
    assert machine.state == STATE_FATAL


def test_a_never_warmed_service_is_due_immediately() -> None:
    """A process that has not warmed anything yet must not wait 30 s before its first attempt."""
    assert ServiceHealth("vad").due_for_rewarm(0.0) is True


@pytest.mark.parametrize(
    ("threshold", "interval"),
    [(0, 30), (3, 0), (-1, 30)],
    ids=["threshold", "interval", "negative"],
)
def test_nonsense_health_config_is_refused_at_construction(threshold: int, interval: int) -> None:
    """A zero threshold would demote on every call; a zero interval would re-warm in a hot loop."""
    with pytest.raises(ValueError):
        ServiceHealth("llm", failure_threshold=threshold, rewarm_interval_s=interval)


def test_the_four_services_are_the_documented_ones() -> None:
    """§4.1: one state per service, `llm`/`asr`/`tts`/`vad` (postgres/redis/livekit are D8's)."""
    health = InferenceHealth()
    assert set(health.services) == {"llm", "asr", "tts", "vad"}
    assert health.all_ready is False
    assert health.any_fatal is False
    assert health.state("postgres") == STATE_NOT_READY  # not ours, and never claimed READY
    assert health.machine_or_none("postgres") is None


def test_all_ready_and_any_fatal_fold_the_four() -> None:
    health = InferenceHealth()
    for service in health.services:
        health[service].warm_started()
        health[service].warm_succeeded()
    assert health.all_ready is True
    health["tts"].out_of_memory(detail="OOM")
    assert health.any_fatal is True
    assert health.all_ready is False
    assert health.due_for_rewarm(10_000.0) == ()  # FATAL is not due; the rest are READY


# -- §4.4's guard ------------------------------------------------------------------------------


class _Recorder:
    """A publisher that records, and an `empty_cache` that counts."""

    def __init__(self) -> None:
        self.published: list[HealthTransition] = []
        self.cache_emptied = 0

    async def publish(self, transition: HealthTransition) -> None:
        self.published.append(transition)

    def empty_cache(self) -> bool:
        self.cache_emptied += 1
        return True


def _guard(recorder: _Recorder, **kwargs: Any) -> InferenceHealthGuard:
    return InferenceHealthGuard(
        InferenceHealth(**kwargs),
        recorder.publish,
        monotonic_s=lambda: 0.0,
        empty_cache=recorder.empty_cache,
    )


async def test_a_successful_call_is_returned_untouched() -> None:
    recorder = _Recorder()
    guard = _guard(recorder)

    async def _call() -> str:
        return "ok"

    assert await guard.run(STAGE_ASR, _call) == "ok"
    assert recorder.published == []


@pytest.mark.parametrize("stage", [STAGE_VAD, STAGE_ASR, STAGE_LLM, STAGE_TTS])
async def test_an_oom_in_any_stage_is_fatal_published_and_empties_the_cache_once(
    stage: str,
) -> None:
    """§4.4 steps 1-4, for every stage: FATAL, published, cache emptied once, nothing reloaded."""
    recorder = _Recorder()
    guard = _guard(recorder)

    async def _call() -> str:
        raise InferenceOutOfMemoryError("CUDA out of memory")

    with pytest.raises(InferenceOutOfMemoryError):
        await guard.run(stage, _call)

    assert len(recorder.published) == 1
    assert recorder.published[0].to_state == STATE_FATAL
    assert recorder.published[0].is_fatal is True
    assert recorder.cache_emptied == 1
    assert guard.health.any_fatal is True

    # A second OOM on an already-FATAL service publishes nothing more and reloads nothing.
    with pytest.raises(InferenceOutOfMemoryError):
        await guard.run(stage, _call)
    assert len(recorder.published) == 1
    assert recorder.cache_emptied == 1


async def test_an_ordinary_failure_publishes_only_at_the_threshold() -> None:
    """§4.1 row 5 through the guard: three failures, one transition."""
    recorder = _Recorder()
    guard = _guard(recorder, failure_threshold=3)
    guard.health["asr"].warm_started()
    guard.health["asr"].warm_succeeded()

    async def _call() -> str:
        raise RuntimeError("the worker hiccuped")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await guard.run(STAGE_ASR, _call)

    assert [t.to_state for t in recorder.published] == [STATE_NOT_READY]
    assert recorder.cache_emptied == 0  # an ordinary failure never touches the allocator


async def test_a_fallback_is_returned_instead_of_raising_when_one_is_supplied() -> None:
    """The VAD stage's shape: it has no fallback ladder of its own, so the guard produces one."""
    recorder = _Recorder()
    guard = _guard(recorder)

    async def _call() -> str:
        raise InferenceOutOfMemoryError("CUDA out of memory")

    async def _fallback() -> str:
        return "silence"

    assert await guard.run(STAGE_VAD, _call, fallback=_fallback) == "silence"
    assert recorder.published[0].to_state == STATE_FATAL


async def test_a_cancellation_is_a_barge_in_not_a_failure() -> None:
    """§6.1: a newer turn cancels the response. That must never demote a healthy service."""
    import asyncio

    recorder = _Recorder()
    guard = _guard(recorder, failure_threshold=1)
    guard.health["tts"].warm_started()
    guard.health["tts"].warm_succeeded()

    async def _call() -> str:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await guard.run(STAGE_TTS, _call)
    assert recorder.published == []
    assert guard.health.state("tts") == STATE_READY
    assert guard.health["tts"].consecutive_failures == 0


async def test_a_missing_model_file_during_a_call_is_an_ordinary_failure_not_an_oom() -> None:
    """Only an allocation failure is FATAL at *runtime*; §4.1 row 4 is about the warm-up."""
    recorder = _Recorder()
    guard = _guard(recorder, failure_threshold=1)
    guard.health["asr"].warm_started()
    guard.health["asr"].warm_succeeded()

    async def _call() -> str:
        raise ModelNotAvailableError("models/gigaam is missing")

    with pytest.raises(ModelNotAvailableError):
        await guard.run(STAGE_ASR, _call)
    assert recorder.published[0].to_state == STATE_NOT_READY


# -- the LLM wrapper ---------------------------------------------------------------------------


class _FakeLlm:
    model_name = "qwen3.5-2b"
    n_ctx = 4096

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls = 0

    async def complete(self, messages: Any, **kwargs: Any) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return "completion"

    def stream(self, messages: Any, **kwargs: Any) -> Any:
        error = self.error

        async def _iter() -> Any:
            if error is not None:
                raise error
            yield "delta"

        return _iter()

    async def warm_up(self) -> None:
        return None

    async def cancel(self, request_id: str) -> None:
        return None

    async def close(self) -> None:
        return None


def _llm_kwargs() -> dict[str, Any]:
    return {"request_id": "r1", "max_tokens": 8, "temperature": 0.1, "timeout_ms": 1000}


async def test_the_guarded_llm_client_routes_complete_through_the_guard() -> None:
    """Both dialogue stages share one client, so wrapping it guards interpreter *and* generator."""
    recorder = _Recorder()
    guard = _guard(recorder)
    inner = _FakeLlm(InferenceOutOfMemoryError("CUDA out of memory"))
    client = GuardedLLMClient(inner, guard)

    assert client.model_name == "qwen3.5-2b"
    assert client.n_ctx == 4096
    assert client.inner is inner

    with pytest.raises(InferenceOutOfMemoryError):
        await client.complete([], **_llm_kwargs())
    assert guard.health.state("llm") == STATE_FATAL
    assert recorder.published[0].service == "llm"


async def test_the_guarded_llm_client_guards_the_first_stream_delta() -> None:
    """A streaming allocation failure surfaces on the first pull, which is what the guard wraps."""
    recorder = _Recorder()
    guard = _guard(recorder)
    client = GuardedLLMClient(_FakeLlm(InferenceOutOfMemoryError("oom")), guard)

    with pytest.raises(InferenceOutOfMemoryError):
        async for _ in client.stream([], **_llm_kwargs()):
            pass
    assert guard.health.state("llm") == STATE_FATAL


async def test_a_healthy_stream_still_yields_every_delta() -> None:
    recorder = _Recorder()
    client = GuardedLLMClient(_FakeLlm(), _guard(recorder))
    assert [delta async for delta in client.stream([], **_llm_kwargs())] == ["delta"]
    assert recorder.published == []

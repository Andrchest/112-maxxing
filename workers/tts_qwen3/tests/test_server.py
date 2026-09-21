"""`tts_qwen3.server` — request/response shape, locking and error-mapping, over a FAKE model
factory (this task's brief, item 1).

No `torch`, no `qwen_tts` anywhere in this file: every test constructs `create_app(model_factory=
...)` with `_FakeModel`/`_FailingModel` below, so this suite proves the FastAPI plumbing (locks,
disconnect-drop, headers, stable error body) without ever needing a GPU or the pinned weights.
Runs in this package's own venv (`make test-tts-qwen3`); a narrower copy of the same shape
assertions also runs under the main backend gate
(`backend/tests/unit/inference/tts/test_qwen3_worker_shape.py`).
"""

from __future__ import annotations

import asyncio
import struct

import httpx
import pytest
from tts_qwen3.server import SAMPLE_RATE, VENDOR_SPEAKERS, WorkerState, create_app


class _FakeModel:
    """`generate_custom_voice` returns 0.5s of a fixed tone — deterministic, no randomness."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def generate_custom_voice(
        self, *, text: str, language: str, speaker: str, instruct: str
    ) -> tuple[list, int]:
        self.calls.append(
            {"text": text, "language": language, "speaker": speaker, "instruct": instruct}
        )
        n_samples = SAMPLE_RATE // 2  # 500 ms
        wav = [0.1 * ((i % 100) / 100.0) for i in range(n_samples)]
        return [wav], SAMPLE_RATE


class _FailingModel:
    def generate_custom_voice(self, **_kwargs: object) -> tuple[list, int]:
        raise RuntimeError("boom: some internal CUDA detail nobody outside should see")


async def _client_for(model_factory) -> httpx.AsyncClient:
    app = create_app(model_factory=lambda _model_dir: model_factory())
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_health_shape_before_load() -> None:
    async with await _client_for(_FakeModel) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "model", "revision", "device", "loaded"}
    assert body["loaded"] is False


async def test_warm_up_loads_the_model_and_health_reflects_it() -> None:
    async with await _client_for(_FakeModel) as client:
        response = await client.post("/warm_up")
        assert response.status_code == 200
        health = (await client.get("/health")).json()
    assert health["loaded"] is True


async def test_synthesize_returns_pcm_with_expected_headers() -> None:
    async with await _client_for(_FakeModel) as client:
        response = await client.post(
            "/synthesize",
            json={
                "text": "Здравствуйте, это проверка.",
                "speaker": "Serena",
                "language": "Russian",
                "instruct": "Speak in a calm and composed manner.",
                "request_id": "r1",
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/L16"
    assert int(response.headers["X-Sample-Rate"]) == SAMPLE_RATE
    assert int(response.headers["X-Audio-Ms"]) == pytest.approx(500, abs=5)
    assert int(response.headers["X-Gen-Ms"]) >= 0
    # s16le mono: an even byte count, and it parses.
    assert len(response.content) % 2 == 0
    struct.unpack(f"<{len(response.content) // 2}h", response.content)


async def test_synthesize_lazily_loads_the_model() -> None:
    """No explicit `/warm_up` call — `/synthesize` must load it itself."""
    async with await _client_for(_FakeModel) as client:
        response = await client.post(
            "/synthesize",
            json={"text": "Алло.", "speaker": "Ryan", "request_id": "r2"},
        )
    assert response.status_code == 200


async def test_unknown_speaker_is_rejected_without_calling_the_model() -> None:
    model = _FakeModel()
    async with await _client_for(lambda: model) as client:
        response = await client.post(
            "/synthesize",
            json={"text": "тест", "speaker": "NotARealSpeaker", "request_id": "r3"},
        )
    assert response.status_code == 503
    assert model.calls == []
    body = response.json()
    assert body["error"] == "tts_qwen3_unavailable"
    assert "NotARealSpeaker" not in body["message"]


async def test_vendor_speakers_are_exactly_four() -> None:
    assert VENDOR_SPEAKERS == ("Serena", "Ryan", "Vivian", "Aiden")


async def test_generation_failure_maps_to_a_stable_503_body_never_echoing_the_exception() -> None:
    async with await _client_for(_FailingModel) as client:
        response = await client.post(
            "/synthesize",
            json={"text": "тест", "speaker": "Serena", "request_id": "r4"},
        )
    assert response.status_code == 503
    body = response.json()
    assert body == {
        "error": "tts_qwen3_unavailable",
        "message": "Qwen3-TTS worker is unavailable; retry or use the configured TTS fallback.",
    }
    assert "CUDA" not in response.text
    assert "boom" not in response.text


async def test_warm_up_failure_also_maps_to_the_stable_503_body() -> None:
    """A load-time failure (the factory itself raises), not a generation-time one — `_FailingModel`
    above only fails inside `generate_custom_voice`, which `ensure_loaded()` never calls."""

    def _raising_factory(_model_dir) -> None:
        raise RuntimeError("could not allocate a CUDA context")

    app = create_app(model_factory=_raising_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/warm_up")
    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "tts_qwen3_unavailable"
    assert "CUDA" not in response.text


async def test_inference_lock_serialises_two_concurrent_synthesize_calls() -> None:
    """Two concurrent requests must not run `generate_custom_voice` at the same time — the
    worker-side half of the owner's own reference worker's `_INFERENCE_LOCK` (recon §1.1)."""

    class _TrackingModel:
        def __init__(self) -> None:
            self.concurrent = 0
            self.max_concurrent = 0

        def generate_custom_voice(self, **_kwargs: object) -> tuple[list, int]:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
            # No real sleep needed: the lock is what this test is asserting on, and the fake
            # model's own call is synchronous CPU work already serialised by GIL + the lock.
            self.concurrent -= 1
            return [[0.0] * 100], SAMPLE_RATE

    model = _TrackingModel()
    async with await _client_for(lambda: model) as client:

        async def _one(index: int) -> httpx.Response:
            return await client.post(
                "/synthesize",
                json={"text": f"t{index}", "speaker": "Serena", "request_id": f"c{index}"},
            )

        await asyncio.gather(*(_one(i) for i in range(3)))

    assert model.max_concurrent == 1


async def test_disconnected_client_is_dropped_without_generating(monkeypatch) -> None:
    """A request whose `is_disconnected()` is True right after the lock is acquired must never
    reach `generate_custom_voice` (this task's brief, item 1)."""
    from fastapi import Request

    model = _FakeModel()
    app = create_app(model_factory=lambda _model_dir: model)
    state: WorkerState = app.state.worker

    async def _always_disconnected(self: Request) -> bool:
        return True

    monkeypatch.setattr(Request, "is_disconnected", _always_disconnected)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/synthesize",
            json={"text": "тест", "speaker": "Serena", "request_id": "r5"},
        )
    assert response.status_code == 499
    assert model.calls == []
    assert state.loaded is True  # the model still loads; only generation is skipped

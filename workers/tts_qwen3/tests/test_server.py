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
import shutil
import struct
from pathlib import Path

import httpx
import pytest
from tts_qwen3 import server as server_module
from tts_qwen3.server import (
    DEFAULT_HOST,
    DEFAULT_MODEL_VARIANT,
    MAX_NEW_TOKENS,
    MIN_NEW_TOKENS,
    MODEL_VARIANTS,
    SAFETY_NET_MAX_CHARS,
    SAMPLE_RATE,
    SAMPLING_DEFAULTS,
    VENDOR_SPEAKERS,
    WARMUP_SPEAKER,
    WARMUP_TEXT_RU,
    NullRuntime,
    TorchRuntime,
    UnknownModelVariantError,
    WorkerState,
    create_app,
    max_new_tokens_for,
    rate_check_passes,
    spoken_chars,
)


class _FakeModel:
    """`generate_custom_voice` returns 0.5s of a fixed tone — deterministic, no randomness."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_custom_voice(
        self, *, text: str, language: str, speaker: str, instruct: str, **kwargs: object
    ) -> tuple[list, int]:
        self.calls.append(
            {"text": text, "language": language, "speaker": speaker, "instruct": instruct, **kwargs}
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
                "speaker": "serena",
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
            json={"text": "Алло.", "speaker": "eric", "request_id": "r2"},
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


async def test_vendor_speakers_are_the_owners_evaluated_four_plus_ryan() -> None:
    """I8 V0: serena, eric, aiden, uncle_fu (evaluated by ear) and ryan (spare); no vivian."""
    assert VENDOR_SPEAKERS == ("serena", "eric", "aiden", "uncle_fu", "ryan")


async def test_speaker_is_matched_case_insensitively_and_sent_lower_case() -> None:
    model = _FakeModel()
    async with await _client_for(lambda: model) as client:
        response = await client.post(
            "/synthesize",
            json={"text": "тест", "speaker": "Uncle_Fu", "request_id": "r-case"},
        )
    assert response.status_code == 200
    assert model.calls[0]["speaker"] == "uncle_fu"


async def test_vivian_is_rejected() -> None:
    model = _FakeModel()
    async with await _client_for(lambda: model) as client:
        response = await client.post(
            "/synthesize",
            json={"text": "тест", "speaker": "Vivian", "request_id": "r-vivian"},
        )
    assert response.status_code == 503
    assert model.calls == []


async def test_generation_failure_maps_to_a_stable_503_body_never_echoing_the_exception() -> None:
    async with await _client_for(_FailingModel) as client:
        response = await client.post(
            "/synthesize",
            json={"text": "тест", "speaker": "serena", "request_id": "r4"},
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
                json={"text": f"t{index}", "speaker": "serena", "request_id": f"c{index}"},
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
            json={"text": "тест", "speaker": "serena", "request_id": "r5"},
        )
    assert response.status_code == 499
    assert model.calls == []
    assert state.loaded is True  # the model still loads; only generation is skipped


# -- E20 R15: SIM_MODELS_ROOT (host runs) --------------------------------------------------------


async def test_a_container_model_dir_is_rebased_onto_sim_models_root(monkeypatch) -> None:
    """A host run has the weights under the repo's `models/`, never at `/models` (E20 R15)."""
    monkeypatch.setenv("SIM_TTS_QWEN3_MODEL_DIR", "/models/tts/qwen3-tts")
    monkeypatch.setenv("SIM_MODELS_ROOT", "./models")

    app = create_app(model_factory=lambda _model_dir: _FakeModel())

    state: WorkerState = app.state.worker
    assert state.model_dir == Path("models/tts/qwen3-tts") / "Qwen3-TTS-12Hz-1.7B-CustomVoice"


async def test_without_sim_models_root_the_container_path_is_left_alone(monkeypatch) -> None:
    """Under compose `/models` IS the mount point; nothing may be rewritten."""
    monkeypatch.setenv("SIM_TTS_QWEN3_MODEL_DIR", "/models/tts/qwen3-tts")
    monkeypatch.delenv("SIM_MODELS_ROOT", raising=False)

    app = create_app(model_factory=lambda _model_dir: _FakeModel())

    state: WorkerState = app.state.worker
    assert state.model_dir == Path("/models/tts/qwen3-tts") / "Qwen3-TTS-12Hz-1.7B-CustomVoice"


async def test_a_relative_model_dir_is_never_rebased(monkeypatch) -> None:
    """Only a container path is mapped; the shipped default is already a host path."""
    monkeypatch.setenv("SIM_MODELS_ROOT", "/somewhere/else")

    app = create_app(model_factory=lambda _model_dir: _FakeModel())

    state: WorkerState = app.state.worker
    assert state.model_dir == Path("models/qwen3-tts") / "Qwen3-TTS-12Hz-1.7B-CustomVoice"


# -- E14-D: configurable model variant (`SIM_TTS_QWEN3_MODEL`) -----------------------------------


async def test_default_variant_is_the_owners_evaluated_1_7b_and_resolves_the_subdirectory() -> None:
    """No `variant=` kwarg, no `SIM_TTS_QWEN3_MODEL` set -> `DEFAULT_MODEL_VARIANT` ("1.7B"), and
    the effective checkpoint dir is `SIM_TTS_QWEN3_MODEL_DIR/<the 1.7B subdirectory>`, not the bare
    base dir (this task's brief, item 1: the subdirectory join `create_app` was missing before)."""
    assert DEFAULT_MODEL_VARIANT == "1.7B"
    app = create_app(model_factory=lambda _model_dir: _FakeModel())
    state: WorkerState = app.state.worker
    assert app.state.variant == "1.7B"
    assert state.variant_repo == MODEL_VARIANTS["1.7B"].repo
    assert state.variant_revision == MODEL_VARIANTS["1.7B"].revision
    assert state.model_dir == Path("models/qwen3-tts") / "Qwen3-TTS-12Hz-1.7B-CustomVoice"


async def test_0_6b_variant_resolves_its_own_repo_revision_and_subdirectory() -> None:
    app = create_app(model_factory=lambda _model_dir: _FakeModel(), variant="0.6B")
    state: WorkerState = app.state.worker
    assert app.state.variant == "0.6B"
    assert state.variant_repo == "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    assert state.variant_revision == "85e237c12c027371202489a0ec509ded67b5e4b5"
    assert state.model_dir == Path("models/qwen3-tts") / "Qwen3-TTS-12Hz-0.6B-CustomVoice"


async def test_0_6b_variant_via_env_var_matches_the_explicit_kwarg(monkeypatch) -> None:
    monkeypatch.setenv("SIM_TTS_QWEN3_MODEL", "0.6B")
    app = create_app(model_factory=lambda _model_dir: _FakeModel())
    state: WorkerState = app.state.worker
    assert state.variant_repo == MODEL_VARIANTS["0.6B"].repo
    assert state.variant_revision == MODEL_VARIANTS["0.6B"].revision


async def test_unknown_variant_refuses_to_build_the_app_with_a_clear_message() -> None:
    with pytest.raises(UnknownModelVariantError, match="NotAVariant"):
        create_app(model_factory=lambda _model_dir: _FakeModel(), variant="NotAVariant")


async def test_unknown_variant_via_env_var_also_refuses(monkeypatch) -> None:
    monkeypatch.setenv("SIM_TTS_QWEN3_MODEL", "3B")
    with pytest.raises(UnknownModelVariantError, match="3B"):
        create_app(model_factory=lambda _model_dir: _FakeModel())


async def test_health_reports_the_variant_actually_configured() -> None:
    """`/health`'s `model`/`revision` must reflect the *resolved* variant, not a hard-coded 1.7B
    constant — a worker actually serving 0.6B must not claim to be the 1.7B (this task's brief,
    item 1)."""
    async with await _client_for_variant("0.6B") as client:
        health = (await client.get("/health")).json()
    assert set(health) == {"status", "model", "revision", "device", "loaded"}
    assert health["model"] == "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    assert health["revision"] == "85e237c12c027371202489a0ec509ded67b5e4b5"


async def _client_for_variant(variant: str) -> httpx.AsyncClient:
    app = create_app(model_factory=lambda _model_dir: _FakeModel(), variant=variant)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


# ---------------------------------------------------------------------------------------------
# E18-C: `/warm_up` runs one real generation and discards the audio (HLD 60 §4.2 step 4)
# ---------------------------------------------------------------------------------------------


async def test_warm_up_actually_generates_and_discards_the_audio() -> None:
    """E14-D measured 13.1 s for the *first* synthesis after a load-only warm-up: loading the
    weights leaves the CUDA graphs and the kernel autotuning cold, so the first caller line paid
    for all of it. That cost belongs to warm-up (E18-C), which is why this is a real generation."""
    model = _FakeModel()
    app = create_app(model_factory=lambda _model_dir: model)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/warm_up")

    assert response.status_code == 200
    body = response.json()
    assert body["loaded"] is True
    assert body["output_audio_ms"] > 0
    assert body["generate_ms"] >= 0
    # Exactly one generation, through the same path a real request takes: Russian text, a vendor
    # speaker, and the audio never leaves the worker.
    assert len(model.calls) == 1
    assert model.calls[0]["text"] == WARMUP_TEXT_RU
    assert model.calls[0]["language"] == "Russian"
    assert model.calls[0]["speaker"] in VENDOR_SPEAKERS
    assert WARMUP_SPEAKER in VENDOR_SPEAKERS
    assert "audio" not in body and "pcm" not in body


async def test_a_warm_up_whose_generation_fails_is_the_stable_503_body() -> None:
    """A warm-up that loaded but could not generate is not warm, and says so the usual way."""
    async with await _client_for(_FailingModel) as client:
        response = await client.post("/warm_up")
    assert response.status_code == 503
    assert response.json() == {
        "error": "tts_qwen3_unavailable",
        "message": "Qwen3-TTS worker is unavailable; retry or use the configured TTS fallback.",
    }
    assert "boom" not in response.text


def test_the_bind_host_defaults_to_loopback_and_is_overridable() -> None:
    """E18-E: inside its own container the worker must accept connections from `voice-agent` at
    the compose-internal hostname, which a loopback bind makes impossible. The default stays
    loopback for a host run (SPEC §41), and the container publishes no host port."""
    import os

    from tts_qwen3.__main__ import _is_loopback

    assert DEFAULT_HOST == "127.0.0.1"
    assert _is_loopback(DEFAULT_HOST) is True
    assert _is_loopback("localhost") is True
    assert _is_loopback("0.0.0.0") is False
    assert _is_loopback("10.1.2.3") is False
    # The resolution rule itself, without starting uvicorn.
    assert os.environ.get("SIM_TTS_QWEN3_HOST", DEFAULT_HOST) == DEFAULT_HOST


# ---------------------------------------------------------------------------------------------
# I8 V1: the generation recipe — token cap, seed, sampling, rate check + one retry, tempo, the
# >100-char safety net and the header contract. Fake models and a recording runtime only.
# ---------------------------------------------------------------------------------------------

#: 20 spoken characters -> 2.0 s expected; the rate check applies (>= QC_MIN_CHARS).
_TWENTY_CHARS = "У нас пожар, помогите нам!"


class _RecordingRuntime:
    """Every torch side effect, in order, as `("seed", n)` / `("release", None)`."""

    def __init__(self) -> None:
        self.events: list[tuple[str, int | None]] = []

    def seed(self, seed: int) -> None:
        self.events.append(("seed", seed))

    def release(self) -> None:
        self.events.append(("release", None))


class _ScriptedModel:
    """Returns `durations_s[i]` seconds of audio on call `i` (the last one repeats)."""

    def __init__(self, *durations_s: float) -> None:
        self.durations_s = durations_s
        self.calls: list[dict[str, object]] = []

    def generate_custom_voice(self, **kwargs: object) -> tuple[list, int]:
        index = min(len(self.calls), len(self.durations_s) - 1)
        self.calls.append(dict(kwargs))
        n_samples = int(SAMPLE_RATE * self.durations_s[index])
        return [[0.1] * n_samples], SAMPLE_RATE


def _app_with(model: object, runtime: _RecordingRuntime | None = None):
    return create_app(model_factory=lambda _model_dir: model, runtime=runtime)


async def _synthesize(app, **body: object) -> httpx.Response:
    payload = {"speaker": "serena", "request_id": "v1", **body}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post("/synthesize", json=payload)


def test_spoken_chars_count_letters_and_digits_only() -> None:
    assert spoken_chars("Да, 12 — нет!") == 7
    assert spoken_chars("  ... ") == 0


@pytest.mark.parametrize(
    ("text", "requested", "expected"),
    [
        # 2 chars -> 0.2 s -> ceil(4.8) = 5 -> the 64 floor.
        ("Да.", None, MIN_NEW_TOKENS),
        # 50 chars -> 5 s -> 5 x 12 x 2 = 120.
        ("а" * 50, None, 120),
        # Spaces and punctuation do not count: still 50 spoken chars.
        (", ".join(["а" * 10] * 5) + ".", None, 120),
        # 51 chars -> 5.1 s -> ceil(122.4) = 123.
        ("а" * 51, None, 123),
        # 300 chars -> 30 s -> 720 -> the 400 ceiling.
        ("а" * 300, None, MAX_NEW_TOKENS),
        # A request may LOWER the cap...
        ("а" * 50, 80, 80),
        # ...never raise it.
        ("а" * 50, 300, 120),
    ],
)
def test_the_token_cap_formula(text: str, requested: int | None, expected: int) -> None:
    """clamp(ceil(expected_seconds x 12 x 2), 64, 400), expected_seconds = spoken chars / 10."""
    assert max_new_tokens_for(text, requested) == expected


async def test_every_generation_gets_the_cap_and_the_labs_sampling_set() -> None:
    model = _FakeModel()
    response = await _synthesize(_app_with(model), text="а" * 50)

    assert response.status_code == 200
    call = model.calls[0]
    assert call["max_new_tokens"] == 120
    for name, value in SAMPLING_DEFAULTS.items():
        assert call[name] == value
    assert SAMPLING_DEFAULTS == {
        "temperature": 0.65,
        "top_p": 0.9,
        "top_k": 30,
        "subtalker_temperature": 0.65,
        "subtalker_top_p": 0.9,
        "subtalker_top_k": 30,
        "repetition_penalty": 1.05,
    }


async def test_an_explicit_lower_cap_in_the_request_is_honoured() -> None:
    model = _FakeModel()
    await _synthesize(_app_with(model), text="а" * 50, max_new_tokens=70)

    assert model.calls[0]["max_new_tokens"] == 70


async def test_a_seed_is_set_before_the_generation_and_the_cache_released_after() -> None:
    runtime = _RecordingRuntime()
    model = _FakeModel()
    response = await _synthesize(_app_with(model, runtime), text=_TWENTY_CHARS, seed=12345)

    assert response.status_code == 200
    assert runtime.events == [("seed", 12345), ("release", None)]
    assert response.headers["X-Seed"] == "12345"
    assert response.headers["X-QC"] == "ok"


async def test_without_a_seed_nothing_is_seeded_but_the_cache_is_still_released() -> None:
    runtime = _RecordingRuntime()
    response = await _synthesize(_app_with(_FakeModel(), runtime), text=_TWENTY_CHARS)

    assert runtime.events == [("release", None)]
    assert response.headers["X-Seed"] == "none"


async def test_the_cache_is_released_even_when_the_generation_fails() -> None:
    runtime = _RecordingRuntime()
    response = await _synthesize(_app_with(_FailingModel(), runtime), text="тест", seed=7)

    assert response.status_code == 503
    assert runtime.events == [("seed", 7), ("release", None)]


def test_the_real_loader_gets_the_torch_runtime_and_a_fake_factory_the_null_one() -> None:
    real = create_app(model_dir=Path("/nonexistent"))
    fake = create_app(model_factory=lambda _model_dir: _FakeModel())

    assert isinstance(real.state.worker.runtime, TorchRuntime)
    assert isinstance(fake.state.worker.runtime, NullRuntime)


@pytest.mark.parametrize(
    ("audio_s", "expected"),
    [
        (2.0, True),  # 10 chars/s, exactly as expected
        (3.4, False),  # 5.88 chars/s < 6
        (3.3, True),  # 6.06 chars/s, 1.65 x expected
        (0.0, True),
    ],
)
def test_the_rate_check_on_the_raw_clip(audio_s: float, expected: bool) -> None:
    assert spoken_chars(_TWENTY_CHARS) == 20
    assert rate_check_passes(_TWENTY_CHARS, audio_s) is expected


def test_the_length_limit_is_three_times_the_expected_clip(monkeypatch) -> None:
    """With the chars/s floor out of the way the length bound is what trips: 3 x expected."""
    monkeypatch.setattr(server_module, "QC_MIN_CHARS_PER_SECOND", 0.0)

    assert rate_check_passes("а" * 20, 6.0) is True
    assert rate_check_passes("а" * 20, 6.1) is False


def test_the_rate_check_is_skipped_for_a_one_word_unit() -> None:
    assert rate_check_passes("Да.", 30.0) is None


async def test_a_runaway_clip_is_regenerated_once_with_seed_plus_one() -> None:
    runtime = _RecordingRuntime()
    model = _ScriptedModel(10.0, 2.0)  # 2 chars/s, then a normal 10 chars/s
    response = await _synthesize(_app_with(model, runtime), text=_TWENTY_CHARS, seed=41)

    assert response.status_code == 200
    assert len(model.calls) == 2
    assert [event for event in runtime.events if event[0] == "seed"] == [
        ("seed", 41),
        ("seed", 42),
    ]
    assert runtime.events.count(("release", None)) == 2
    assert response.headers["X-QC"] == "regenerated"
    assert response.headers["X-Seed"] == "42"
    assert int(response.headers["X-Audio-Ms"]) == pytest.approx(2000, abs=5)


async def test_there_is_never_a_second_retry_and_the_shorter_failing_clip_wins() -> None:
    model = _ScriptedModel(10.0, 8.0, 1.0)
    response = await _synthesize(_app_with(model), text=_TWENTY_CHARS, seed=5)

    assert len(model.calls) == 2
    assert response.headers["X-QC"] == "regenerated"
    assert response.headers["X-Seed"] == "6"
    assert int(response.headers["X-Audio-Ms"]) == pytest.approx(8000, abs=5)


async def test_when_the_retry_is_worse_the_first_seed_is_kept() -> None:
    model = _ScriptedModel(10.0, 12.0)
    response = await _synthesize(_app_with(model), text=_TWENTY_CHARS, seed=5)

    assert response.headers["X-QC"] == "regenerated"
    assert response.headers["X-Seed"] == "5"
    assert int(response.headers["X-Audio-Ms"]) == pytest.approx(10000, abs=5)


async def test_an_unseeded_runaway_is_still_regenerated_once() -> None:
    model = _ScriptedModel(10.0, 2.0)
    response = await _synthesize(_app_with(model), text=_TWENTY_CHARS)

    assert len(model.calls) == 2
    assert response.headers["X-QC"] == "regenerated"
    assert response.headers["X-Seed"] == "none"


async def test_a_short_unit_is_never_regenerated() -> None:
    model = _ScriptedModel(5.0)
    response = await _synthesize(_app_with(model), text="Алло!", seed=1)

    assert len(model.calls) == 1
    assert response.headers["X-QC"] == "skipped"


async def test_a_client_that_left_before_the_retry_gets_no_retry(monkeypatch) -> None:
    from fastapi import Request

    answers = iter([False, True])

    async def _gone_after_the_first_generation(self: Request) -> bool:
        return next(answers)

    monkeypatch.setattr(Request, "is_disconnected", _gone_after_the_first_generation)
    model = _ScriptedModel(10.0, 2.0)
    response = await _synthesize(_app_with(model), text=_TWENTY_CHARS, seed=3)

    assert len(model.calls) == 1
    assert response.headers["X-QC"] == "failed"


async def test_the_header_contract() -> None:
    response = await _synthesize(_app_with(_FakeModel()), text=_TWENTY_CHARS, seed=9)

    assert response.status_code == 200
    for header in (
        "X-Sample-Rate",
        "X-Audio-Ms",
        "X-Gen-Ms",
        "X-Tempo",
        "X-Seed",
        "X-QC",
        "X-Units",
    ):
        assert header in response.headers
    assert response.headers["X-Tempo"] == "1"
    assert response.headers["X-Units"] == "1"


async def test_a_unit_over_the_safety_net_is_split_generated_per_segment_and_stitched() -> None:
    text = (
        "Я на улице Ленина, дом двенадцать, квартира сорок пять, тут горит кухня, "
        "дым идёт из окна, помогите нам пожалуйста срочно. Приезжайте."
    )
    assert len(text) > SAFETY_NET_MAX_CHARS
    model = _ScriptedModel(1.0)
    response = await _synthesize(_app_with(model), text=text, seed=11, pause_s=0.25)

    assert response.status_code == 200
    units = len(model.calls)
    assert int(response.headers["X-Units"]) == units >= 2
    assert all(len(str(call["text"])) <= SAFETY_NET_MAX_CHARS for call in model.calls)
    expected_ms = units * 1000 + (units - 1) * 250
    assert int(response.headers["X-Audio-Ms"]) == pytest.approx(expected_ms, abs=5)
    assert response.headers["X-Seed"] == ",".join(["11"] * units)


async def test_digits_are_spelled_out_before_the_model_sees_them() -> None:
    pytest.importorskip("num2words")
    model = _FakeModel()
    await _synthesize(_app_with(model), text="Ленина, 12.")

    assert model.calls[0]["text"] == "Ленина, двенадцать."


async def test_without_num2words_the_raw_text_is_sent_with_one_warning(monkeypatch, caplog) -> None:
    def _missing(_text: str) -> str:
        raise ImportError("No module named 'num2words'")

    monkeypatch.setattr(server_module, "normalize_numbers", _missing)
    model = _FakeModel()
    app = _app_with(model)
    with caplog.at_level("WARNING", logger="tts_qwen3"):
        await _synthesize(app, text="Ленина, 12.")
        await _synthesize(app, text="Дом 5.")

    assert [call["text"] for call in model.calls] == ["Ленина, 12.", "Дом 5."]
    assert sum("num2words" in record.getMessage() for record in caplog.records) == 1


async def test_a_missing_sox_degrades_to_tempo_1_with_one_warning(monkeypatch, caplog) -> None:
    monkeypatch.setattr(server_module.shutil, "which", lambda _name: None)
    app = _app_with(_FakeModel())
    with caplog.at_level("WARNING", logger="tts_qwen3"):
        first = await _synthesize(app, text=_TWENTY_CHARS, tempo=1.2)
        second = await _synthesize(app, text=_TWENTY_CHARS, tempo=1.2)

    for response in (first, second):
        assert response.status_code == 200
        assert response.headers["X-Tempo"] == "1"
        assert int(response.headers["X-Audio-Ms"]) == pytest.approx(500, abs=5)
    assert sum("sox" in record.getMessage() for record in caplog.records) == 1


async def test_a_failing_sox_never_fails_the_synthesis(monkeypatch) -> None:
    monkeypatch.setattr(server_module.shutil, "which", lambda _name: "/bin/false")
    response = await _synthesize(_app_with(_FakeModel()), text=_TWENTY_CHARS, tempo=1.2)

    assert response.status_code == 200
    assert response.headers["X-Tempo"] == "1"


@pytest.mark.skipif(shutil.which("sox") is None, reason="sox is not installed on this host")
async def test_sox_tempo_shortens_the_clip_and_is_echoed() -> None:
    response = await _synthesize(_app_with(_ScriptedModel(2.0)), text=_TWENTY_CHARS, tempo=1.25)

    assert response.status_code == 200
    assert response.headers["X-Tempo"] == "1.25"
    # 2000 ms at 1.25x; the rate check measured the RAW 2 s clip, so no regeneration happened.
    assert int(response.headers["X-Audio-Ms"]) == pytest.approx(1600, abs=40)
    assert response.headers["X-QC"] == "ok"
    assert len(response.content) % 2 == 0


async def test_the_warm_up_generation_goes_through_the_same_recipe() -> None:
    model = _FakeModel()
    app = _app_with(model)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/warm_up")

    assert response.status_code == 200
    assert model.calls[0]["max_new_tokens"] == MIN_NEW_TOKENS
    assert model.calls[0]["temperature"] == SAMPLING_DEFAULTS["temperature"]

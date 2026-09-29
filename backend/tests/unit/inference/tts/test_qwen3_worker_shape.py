"""A torch-free smoke test of `workers/tts_qwen3/tts_qwen3/server.py`'s request/response shape,
run under the **main backend gate** venv (this task's brief, item 1: "keep a torch-free test
module that the main gate can run").

`workers/tts_qwen3` is a standalone package, not a `sim112-workspace` member and not installed
into this venv (see `workers/tts_qwen3/README.md`) — but `server.py` itself imports nothing heavier
than `fastapi`/`pydantic` at module scope (every `torch`/`qwen_tts` import is deferred inside
`_default_model_factory`, only reached when a real model factory is used), and this venv already
has `fastapi` as a hard `sim-backend` dependency. So the module is loaded directly from its file
path with `importlib.util` — no `sys.path` mutation, no risk of shadowing the already-imported
`tests` top-level package this repository's own `backend/tests/**` uses
(`backend/tests/models/conftest.py`'s `from tests.models.conftest import ...`) — and exercised the
same way `workers/tts_qwen3/tests/test_server.py`'s fuller suite does, with a fake model factory.

This is the fuller suite's narrower sibling: it proves the wire shape holds in the venv `make gate`
actually runs, not every lock/concurrency edge case (those stay in `workers/tts_qwen3/tests/
test_server.py`, which needs this package's own venv — see that module's docstring, and this
task's report for which alternative of the brief's item 1 was chosen and why).
"""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path
from types import ModuleType

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SERVER_PATH = _REPO_ROOT / "workers" / "tts_qwen3" / "tts_qwen3" / "server.py"


def _load_server_module() -> ModuleType:
    if not _SERVER_PATH.is_file():  # pragma: no cover - repository layout invariant
        pytest.skip(f"workers/tts_qwen3/tts_qwen3/server.py not found at {_SERVER_PATH}")
    spec = importlib.util.spec_from_file_location("tts_qwen3_server_shape_test", _SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


server = _load_server_module()


class _FakeModel:
    def generate_custom_voice(
        self, *, text: str, language: str, speaker: str, instruct: str
    ) -> tuple[list, int]:
        n_samples = server.SAMPLE_RATE // 4  # 250 ms
        return [[0.05] * n_samples], server.SAMPLE_RATE


async def _client() -> httpx.AsyncClient:
    app = server.create_app(model_factory=lambda _model_dir: _FakeModel())
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_health_has_the_documented_fields() -> None:
    async with await _client() as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert set(response.json()) == {"status", "model", "revision", "device", "loaded"}


async def test_synthesize_returns_audio_l16_with_the_documented_headers() -> None:
    async with await _client() as client:
        response = await client.post(
            "/synthesize",
            json={
                "text": "Проверка.",
                "speaker": "serena",
                "language": "Russian",
                "instruct": "Speak in a calm and composed manner.",
                "request_id": "shape-1",
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/L16"
    for header in ("X-Sample-Rate", "X-Audio-Ms", "X-Gen-Ms"):
        assert header in response.headers
    assert len(response.content) % 2 == 0
    struct.unpack(f"<{len(response.content) // 2}h", response.content)


async def test_unknown_speaker_maps_to_the_stable_503_body() -> None:
    async with await _client() as client:
        response = await client.post(
            "/synthesize",
            json={"text": "тест", "speaker": "Nope", "request_id": "shape-2"},
        )
    assert response.status_code == 503
    assert response.json()["error"] == "tts_qwen3_unavailable"


async def test_default_port_and_vendor_speakers_match_the_brief() -> None:
    assert server.DEFAULT_PORT == 8112
    assert server.DEFAULT_PORT not in (8000, 8001, 8012, 8016)
    assert server.VENDOR_SPEAKERS == ("serena", "eric", "aiden", "uncle_fu", "ryan")


def test_the_two_vendor_speaker_copies_are_equal() -> None:
    """I8 V0: the worker's and the adapter's `VENDOR_SPEAKERS` are two copies by design (separate
    venvs) — they must never drift."""
    from app.inference.tts.qwen3_tts import VENDOR_SPEAKERS

    assert server.VENDOR_SPEAKERS == VENDOR_SPEAKERS
    assert "vivian" not in VENDOR_SPEAKERS


def test_every_qwen_profile_casts_only_vendor_speakers() -> None:
    """I8 V0: every `voice_map` value, `default_voice` and `voice_id` of every Qwen3-TTS profile
    is one of `VENDOR_SPEAKERS` (an unknown one would be a 503 per utterance, then Piper)."""
    from app.config.profile import PROFILES_DIR, load_profile

    checked = 0
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        tts = load_profile(path.stem).tts
        if tts.provider != "qwen3_tts":
            continue
        checked += 1
        speakers = {tts.voice_id, *tts.voice_map.values()}
        if tts.default_voice is not None:
            speakers.add(tts.default_voice)
        assert speakers <= set(server.VENDOR_SPEAKERS), path.name
    assert checked >= 2  # DEV_3060TI, DEV_3060TI_VOICE (and the FINAL Qwen profile)


async def test_speaker_is_matched_case_insensitively() -> None:
    async with await _client() as client:
        response = await client.post(
            "/synthesize",
            json={"text": "тест", "speaker": "Serena", "request_id": "shape-case"},
        )
    assert response.status_code == 200


async def test_warm_up_generates_once_and_reports_the_audio_it_threw_away() -> None:
    """E18-C, HLD 60 §4.2 step 4: `/warm_up` runs one **real** generation and discards the audio.

    The gate's copy of the assertion (the fuller one, with call-argument inspection, is in
    `workers/tts_qwen3/tests/test_server.py`): what matters here is that the shape `Qwen3TTS.
    warm_up` relies on — HTTP 200 — now also carries proof that synthesis actually ran, so a
    regression to a load-only warm-up fails under plain `make gate`.
    """
    async with await _client() as client:
        response = await client.post("/warm_up")
        health = (await client.get("/health")).json()
    assert response.status_code == 200
    body = response.json()
    assert body["loaded"] is True
    assert body["output_audio_ms"] > 0
    assert health["loaded"] is True
    assert server.WARMUP_TEXT_RU and server.WARMUP_SPEAKER in server.VENDOR_SPEAKERS


def test_the_bind_host_default_is_loopback() -> None:
    """SPEC §41: the host run stays loopback; only a container (no published port) overrides it."""
    assert server.DEFAULT_HOST == "127.0.0.1"

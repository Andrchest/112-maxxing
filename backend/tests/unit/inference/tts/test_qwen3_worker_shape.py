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
                "speaker": "Serena",
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
    assert server.VENDOR_SPEAKERS == ("Serena", "Ryan", "Vivian", "Aiden")

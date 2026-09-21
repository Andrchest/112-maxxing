"""The Qwen3-TTS GPU worker's FastAPI app (E14-B; see `README.md`).

Loopback only (enforced by how `make run-tts-qwen3`/`scripts/run.py`-equivalent launches uvicorn
with `--host 127.0.0.1`, never by this module binding a socket itself — this module only builds
the `FastAPI` app). One model instance per process, guarded by two `asyncio.Lock`s:

* `_load_lock` serialises the (once-only) model load, so two concurrent requests that both find
  the model unloaded do not both try to load it;
* `_inference_lock` serialises `generate_custom_voice()` calls — the owner's own reference worker
  has exactly this shape (recon §1.1: "`_INFERENCE_LOCK` serializing every synthesis call ... no
  concurrency inside one worker process, requests queue").

A request whose client already disconnected by the time it acquires `_inference_lock` is dropped
without ever calling into the model (`await request.is_disconnected()` checked immediately after
acquiring the lock, not before — the check must observe the state at the moment this request is
about to actually spend GPU time, not at enqueue time). This is the worker-side half of
`TtsStream.cancel()` (`app.inference.tts.qwen3_tts`): the client closes the HTTP connection, and
the worker who has not yet started generating drops the request instead of generating audio nobody
will play — SPEC §18/§27, ruling 3.

Every failure — model load, generation, a client that vanished mid-response-write — is `503` with
a **stable** JSON body that never echoes the underlying exception's text (this task's brief, item
1; mirrors the owner's own worker's `{"error": "qwen3_tts_unavailable", ...}` contract, recon
§1.1). The real model load (`_default_model_factory`) imports `torch`/`qwen_tts` **inside the
function**, never at module import time, so this module — and therefore `create_app()` with a fake
factory — is importable without either package installed (this is what lets
`backend/tests/unit/inference/tts/test_qwen3_worker_shape.py` run under the plain backend gate
venv, which has neither).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

__all__ = [
    "DEFAULT_PORT",
    "MODEL_REPO",
    "MODEL_REVISION",
    "SAMPLE_RATE",
    "TOKENIZER_REPO",
    "TOKENIZER_REVISION",
    "VENDOR_SPEAKERS",
    "ModelFactory",
    "ModelHandle",
    "SynthesizeRequest",
    "WorkerState",
    "create_app",
]

log = logging.getLogger("tts_qwen3")

#: Never 8012 (the owner's own qwen3-tts experiment) or 8016 (the owner's resident Higgs-TTS
#: worker, PID 1082982 — never touched by anything in this repository). `SIM_TTS_QWEN3_PORT`
#: overrides it.
DEFAULT_PORT = 8112
#: The one output shape `Qwen3TTS.output_sample_rate` (`app.inference.tts.qwen3_tts`) is pinned
#: to — measured by the owner (recon §1.1), not a guess.
SAMPLE_RATE = 24000
BYTES_PER_SAMPLE = 2

#: Pinned exactly (recon §1.1 / `docs/QWEN3_TTS_EXPERIMENT.md:25-30`) — immutable SHA revisions,
#: not "latest", so a re-run of `make models-tts-qwen3` a year from now still fetches the same
#: weights the owner evaluated.
MODEL_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
MODEL_REVISION = "0c0e3051f131929182e2c023b9537f8b1c68adfe"
TOKENIZER_REPO = "Qwen/Qwen3-TTS-Tokenizer-12Hz"
TOKENIZER_REVISION = "7dd38ad4e9bad454aae9cd937d0cd577604fe229"

#: CustomVoice's closed speaker set (recon §1.1: "13 profile ids ... map to only 4 vendor speaker
#: names"). `Qwen3TTS` (the backend adapter) validates `TtsVoiceSpec.voice_id` against this same
#: set before ever dialling the worker; the worker re-validates it too, because a worker that
#: trusts its one known client is a worker that breaks silently the day a second one exists.
VENDOR_SPEAKERS: tuple[str, ...] = ("Serena", "Ryan", "Vivian", "Aiden")

#: Never echoed with exception text (this task's brief, item 1) — one stable body for every
#: failure mode, so a client never has to parse free text to classify a failure.
_ERROR_BODY: dict[str, str] = {
    "error": "tts_qwen3_unavailable",
    "message": "Qwen3-TTS worker is unavailable; retry or use the configured TTS fallback.",
}


class ModelHandle(Protocol):
    """What `WorkerState` needs from a loaded model — real (`qwen_tts.Qwen3TTSModel`) or fake."""

    def generate_custom_voice(
        self, *, text: str, language: str, speaker: str, instruct: str
    ) -> tuple[Any, int]:
        """Returns `(wavs, sample_rate)` — `wavs` a sequence of float32 arrays (recon §1.1)."""
        ...


#: A factory takes the model directory and returns a loaded `ModelHandle`. Swapped for a fake in
#: tests so no test process ever imports `torch`/`qwen_tts` (this task's brief, item 1).
ModelFactory = Callable[[Path], ModelHandle]


def _default_model_factory(model_dir: Path) -> ModelHandle:
    """The real loader. Every heavy import happens here, not at module scope (see module
    docstring). Mirrors the owner's own load call exactly (recon §1.1)."""
    import torch
    from qwen_tts import Qwen3TTSModel

    model: ModelHandle = Qwen3TTSModel.from_pretrained(
        str(model_dir),
        device_map="cuda:0",
        dtype=torch.bfloat16,
        local_files_only=True,
    )
    return model


class SynthesizeRequest(BaseModel):
    text: str
    speaker: str
    language: str = "Russian"
    instruct: str = ""
    request_id: str


class WorkerState:
    """One model instance, a load lock and an inference lock (this task's brief, item 1)."""

    def __init__(
        self,
        *,
        model_dir: Path,
        model_factory: ModelFactory,
        device: str = "cuda:0",
    ) -> None:
        self.model_dir = model_dir
        self.model_factory = model_factory
        self.device = device
        self.model: ModelHandle | None = None
        self.load_lock = asyncio.Lock()
        self.inference_lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self.model is not None

    async def ensure_loaded(self) -> None:
        """Idempotent, concurrency-safe load: the double-checked lock is what stops two
        concurrent first requests from both loading the model."""
        if self.model is not None:
            return
        async with self.load_lock:
            if self.model is not None:
                return
            self.model = await asyncio.to_thread(self.model_factory, self.model_dir)


def _pcm_audio_ms(pcm: bytes, sample_rate: int) -> int:
    if sample_rate <= 0:  # pragma: no cover - defensive, never true for a real model
        return 0
    samples = len(pcm) // BYTES_PER_SAMPLE
    return (samples * 1000) // sample_rate


def _float_wavs_to_pcm16(wavs: Any) -> bytes:
    """`wavs` (recon §1.1: "a list of np.ndarray" float32 in [-1, 1]) -> concatenated PCM s16le.

    Imports `numpy` at call time only — this function is only ever reached from inside
    `_run_generate`, itself only called after a model (real or fake) has already produced
    `wavs`, so by then `numpy` is a real dependency of whichever venv is running (the worker's
    own, or a test's fake-model venv that chose to depend on numpy for its fixture data).
    """
    import numpy as np

    if hasattr(wavs, "shape") or hasattr(wavs, "dtype"):
        wavs = [wavs]
    pieces = [np.asarray(piece, dtype=np.float32).reshape(-1) for piece in wavs]
    if not pieces:
        return b""
    audio = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype("<i2")
    return pcm16.tobytes()


def _run_generate(model: ModelHandle, payload: SynthesizeRequest) -> tuple[bytes, int]:
    """Runs on a worker thread (`asyncio.to_thread`) — the model call itself is synchronous."""
    wavs, sample_rate = model.generate_custom_voice(
        text=payload.text,
        language=payload.language,
        speaker=payload.speaker,
        instruct=payload.instruct,
    )
    pcm = _float_wavs_to_pcm16(wavs)
    return pcm, sample_rate


def create_app(
    *,
    model_dir: Path | None = None,
    model_factory: ModelFactory | None = None,
    device: str = "cuda:0",
) -> FastAPI:
    """Build the app. `model_dir`/`model_factory` are overridable so tests can inject a fake
    factory and a throwaway directory — production callers (`scripts/run.py`-equivalent /
    `make run-tts-qwen3`) pass neither and get `SIM_TTS_QWEN3_MODEL_DIR` (default
    `models/qwen3-tts/`, gitignored) and the real loader."""
    resolved_model_dir = model_dir or Path(
        os.environ.get("SIM_TTS_QWEN3_MODEL_DIR", "models/qwen3-tts")
    )
    factory = model_factory or _default_model_factory
    state = WorkerState(model_dir=resolved_model_dir, model_factory=factory, device=device)

    app = FastAPI(title="tts_qwen3")
    app.state.worker = state  # exposed for tests/introspection only

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model": MODEL_REPO,
            "revision": MODEL_REVISION,
            "device": state.device,
            "loaded": state.loaded,
        }

    @app.post("/warm_up")
    async def warm_up() -> Response:
        try:
            await state.ensure_loaded()
        except Exception:
            log.exception("tts_qwen3: warm_up failed")
            return JSONResponse(status_code=503, content=_ERROR_BODY)
        return JSONResponse(content={"status": "ok", "loaded": True})

    @app.post("/synthesize")
    async def synthesize(payload: SynthesizeRequest, request: Request) -> Response:
        if payload.speaker not in VENDOR_SPEAKERS:
            log.warning("tts_qwen3: unknown speaker %r rejected", payload.speaker)
            return JSONResponse(status_code=503, content=_ERROR_BODY)

        try:
            await state.ensure_loaded()
        except Exception:
            log.exception("tts_qwen3: model load failed (request_id=%s)", payload.request_id)
            return JSONResponse(status_code=503, content=_ERROR_BODY)

        async with state.inference_lock:
            # Checked *after* acquiring the lock, not before: a request that queued behind a
            # slow generation and whose client gave up while waiting must never spend GPU time
            # (module docstring, this task's brief item 1).
            if await request.is_disconnected():
                log.info("tts_qwen3: dropping disconnected request_id=%s", payload.request_id)
                return JSONResponse(status_code=499, content=_ERROR_BODY)

            started = time.monotonic()
            try:
                assert state.model is not None  # ensure_loaded() above guarantees this
                pcm, sample_rate = await asyncio.to_thread(_run_generate, state.model, payload)
            except Exception:
                log.exception("tts_qwen3: synthesis failed (request_id=%s)", payload.request_id)
                return JSONResponse(status_code=503, content=_ERROR_BODY)
            gen_ms = int((time.monotonic() - started) * 1000)

        audio_ms = _pcm_audio_ms(pcm, sample_rate)
        headers = {
            "X-Sample-Rate": str(sample_rate),
            "X-Audio-Ms": str(audio_ms),
            "X-Gen-Ms": str(gen_ms),
        }
        return Response(content=pcm, media_type="audio/L16", headers=headers)

    return app

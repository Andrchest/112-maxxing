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

**E14-D: the model variant is a config choice.** `SIM_TTS_QWEN3_MODEL` (`MODEL_VARIANTS`, default
`DEFAULT_MODEL_VARIANT = "1.7B"`, the owner's evaluated model — unchanged) picks a `ModelVariant`
(repo, pinned revision, checkpoint subdirectory under `SIM_TTS_QWEN3_MODEL_DIR`). An unrecognised
value raises `UnknownModelVariantError` at `create_app()` time, so `python -m tts_qwen3` refuses to
start rather than silently loading the default or crashing deep inside a request. `/health`'s
`model`/`revision` come from the *resolved* variant (`WorkerState.variant_repo`/`variant_revision`),
not the 1.7B module constants — a worker actually serving 0.6B reports 0.6B.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_MODEL_VARIANT",
    "DEFAULT_PORT",
    "MODEL_REPO",
    "MODEL_REVISION",
    "MODEL_VARIANTS",
    "SAMPLE_RATE",
    "TOKENIZER_REPO",
    "TOKENIZER_REVISION",
    "VENDOR_SPEAKERS",
    "WARMUP_SPEAKER",
    "WARMUP_TEXT_RU",
    "ModelFactory",
    "ModelHandle",
    "ModelVariant",
    "SynthesizeRequest",
    "UnknownModelVariantError",
    "WorkerState",
    "create_app",
]

log = logging.getLogger("tts_qwen3")

#: Never 8012 (the owner's own qwen3-tts experiment) or 8016 (the owner's resident Higgs-TTS
#: worker, PID 1082982 — never touched by anything in this repository). `SIM_TTS_QWEN3_PORT`
#: overrides it.
DEFAULT_PORT = 8112
#: Loopback, and only a deployment that cannot work otherwise (a container whose port is not
#: published) sets `SIM_TTS_QWEN3_HOST` to something else — see `tts_qwen3.__main__` (SPEC §41).
DEFAULT_HOST = "127.0.0.1"
#: The one output shape `Qwen3TTS.output_sample_rate` (`app.inference.tts.qwen3_tts`) is pinned
#: to — measured by the owner (recon §1.1), not a guess.
SAMPLE_RATE = 24000
BYTES_PER_SAMPLE = 2

#: Pinned exactly (recon §1.1 / `docs/QWEN3_TTS_EXPERIMENT.md:25-30`) — immutable SHA revisions,
#: not "latest", so a re-run of `make models-tts-qwen3` a year from now still fetches the same
#: weights the owner evaluated. This is the 1.7B checkpoint's identity — kept as the module-level
#: name every existing importer (`backend/app/inference/tts/qwen3_tts.py`'s duplicated constants,
#: `Makefile`) already reads; `MODEL_VARIANTS["1.7B"]` below carries the same two values.
MODEL_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
MODEL_REVISION = "0c0e3051f131929182e2c023b9537f8b1c68adfe"
TOKENIZER_REPO = "Qwen/Qwen3-TTS-Tokenizer-12Hz"
TOKENIZER_REVISION = "7dd38ad4e9bad454aae9cd937d0cd577604fe229"


@dataclass(frozen=True)
class ModelVariant:
    """One `SIM_TTS_QWEN3_MODEL` choice: a repo id, its pinned revision, and the subdirectory
    under `SIM_TTS_QWEN3_MODEL_DIR` the checkpoint's own files (`config.json`,
    `model.safetensors`, …) live in directly — `Qwen3TTSModel.from_pretrained(pretrained_model_
    name_or_path, ...)` needs that exact directory, not its parent (this task's brief, item 1:
    "check how the factory resolves the checkpoint subdirectory today" — today it does not; it
    passes `SIM_TTS_QWEN3_MODEL_DIR` straight through, which is the *parent* of both checkpoints
    on disk (`make models-tts-qwen3` writes each variant into its own named subdirectory) and was
    therefore never actually loadable. This dataclass is what fixes that, for every variant."""

    repo: str
    revision: str
    subdirectory: str


#: Every configurable model variant (this task's brief, item 1). `"1.7B"` is the owner-evaluated
#: default (docs/hld/00-decisions.md D9, OWNER DECISION E14) — unchanged from `MODEL_REPO`/
#: `MODEL_REVISION` above. `"0.6B"`'s revision `85e237c12c027371202489a0ec509ded67b5e4b5` was
#: verified against every `.cache/huggingface/download/*.metadata` first line under
#: `models/qwen3-tts/Qwen3-TTS-12Hz-0.6B-CustomVoice/` during this task (all agree) — not a guess,
#: and not this task's own pin invention: it is the actually-resolved commit of an UNPINNED
#: download (this task's brief, FACTS).
MODEL_VARIANTS: dict[str, ModelVariant] = {
    "1.7B": ModelVariant(
        repo=MODEL_REPO,
        revision=MODEL_REVISION,
        subdirectory="Qwen3-TTS-12Hz-1.7B-CustomVoice",
    ),
    "0.6B": ModelVariant(
        repo="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        revision="85e237c12c027371202489a0ec509ded67b5e4b5",
        subdirectory="Qwen3-TTS-12Hz-0.6B-CustomVoice",
    ),
}
#: The owner's evaluated model (D9) — never changed by this task; a profile that wants 0.6B sets
#: `SIM_TTS_QWEN3_MODEL=0.6B` explicitly (Makefile / `docs/hld/60-inference-ops.md`'s profile
#: YAMLs), never by flipping this default (this task's brief, DO item 6: "Do NOT change any
#: profile's default variant — that is a manager decision").
DEFAULT_MODEL_VARIANT = "1.7B"


class UnknownModelVariantError(ValueError):
    """`SIM_TTS_QWEN3_MODEL` (or `create_app(variant=...)`) named a variant not in
    `MODEL_VARIANTS`. Raised at `create_app()` time, i.e. at module import in `__main__.py`
    (`app = create_app()`), so the process refuses to start rather than serving requests against
    an unresolved/wrong checkpoint (this task's brief, item 1: "the process refuses to start with
    a clear message")."""


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


#: `/warm_up` generates this, once, and throws the audio away (E18-C, HLD 60 §4.2 step 4).
#:
#: E14-D measured 13.1 s for the *first* synthesis after a load-only warm-up: loading the weights
#: leaves the CUDA graphs, the kernel autotuning and the tokenizer's first pass cold, so the first
#: caller line paid for all of it. That cost belongs to warm-up, which is why this is a real
#: generation of real Russian text and not a model load followed by an optimistic `{"status":"ok"}`.
#: Short on purpose — it is thrown away, and a long warm-up is VRAM pressure for nothing.
WARMUP_TEXT_RU = "Проверка."
#: One of `VENDOR_SPEAKERS`; the warm-up path must be the same path a real request takes.
WARMUP_SPEAKER = "Serena"


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
    """One model instance, a load lock and an inference lock (this task's brief, item 1).

    `variant_repo`/`variant_revision` are what `/health` reports as `model`/`revision` — the
    *actually configured* variant's identity (this task's brief, item 1: "`/health` reports the
    variant actually configured"), not a module-level constant that would silently keep claiming
    the 1.7B while a different checkpoint is loaded from `model_dir`.
    """

    def __init__(
        self,
        *,
        model_dir: Path,
        model_factory: ModelFactory,
        device: str = "cuda:0",
        variant_repo: str = MODEL_REPO,
        variant_revision: str = MODEL_REVISION,
    ) -> None:
        self.model_dir = model_dir
        self.model_factory = model_factory
        self.device = device
        self.variant_repo = variant_repo
        self.variant_revision = variant_revision
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
    variant: str | None = None,
) -> FastAPI:
    """Build the app. `model_dir`/`model_factory` are overridable so tests can inject a fake
    factory and a throwaway directory — production callers (`scripts/run.py`-equivalent /
    `make run-tts-qwen3`) pass neither and get `SIM_TTS_QWEN3_MODEL_DIR` (default
    `models/qwen3-tts/`, gitignored) and the real loader.

    `variant` selects the model config (`MODEL_VARIANTS`); when omitted it is read from
    `SIM_TTS_QWEN3_MODEL` (default `DEFAULT_MODEL_VARIANT`, `"1.7B"` — the owner's evaluated
    model, unchanged). An unknown variant raises `UnknownModelVariantError` **here**, i.e. at
    `python -m tts_qwen3` import time (`app = create_app()`), so the process refuses to start
    rather than serving anything against an unresolved checkpoint (this task's brief, item 1).

    When `model_dir` is not given, the effective checkpoint directory is
    `SIM_TTS_QWEN3_MODEL_DIR / MODEL_VARIANTS[variant].subdirectory` — `Qwen3TTSModel.
    from_pretrained()` needs the directory that directly contains `config.json`/
    `model.safetensors`, not `SIM_TTS_QWEN3_MODEL_DIR` itself (which is the parent both variants'
    subdirectories share, `make models-tts-qwen3`'s own download layout). An explicit `model_dir`
    (tests; a caller that already knows the exact checkpoint path) bypasses this join entirely and
    is used as-is."""
    resolved_variant = (
        variant
        if variant is not None
        else os.environ.get("SIM_TTS_QWEN3_MODEL", DEFAULT_MODEL_VARIANT)
    )
    try:
        variant_config = MODEL_VARIANTS[resolved_variant]
    except KeyError as exc:
        raise UnknownModelVariantError(
            f"SIM_TTS_QWEN3_MODEL={resolved_variant!r} is not a known Qwen3-TTS variant; "
            f"choose one of {tuple(MODEL_VARIANTS)}"
        ) from exc

    if model_dir is not None:
        resolved_model_dir = model_dir
    else:
        base_model_dir = Path(os.environ.get("SIM_TTS_QWEN3_MODEL_DIR", "models/qwen3-tts"))
        resolved_model_dir = base_model_dir / variant_config.subdirectory

    factory = model_factory or _default_model_factory
    state = WorkerState(
        model_dir=resolved_model_dir,
        model_factory=factory,
        device=device,
        variant_repo=variant_config.repo,
        variant_revision=variant_config.revision,
    )

    app = FastAPI(title="tts_qwen3")
    app.state.worker = state  # exposed for tests/introspection only
    app.state.variant = resolved_variant  # exposed for tests/introspection only

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model": state.variant_repo,
            "revision": state.variant_revision,
            "device": state.device,
            "loaded": state.loaded,
        }

    @app.post("/warm_up")
    async def warm_up() -> Response:
        """Load the model **and** run one real generation, discarding the audio (HLD 60 §4.2).

        Two steps, both of them warm-up cost rather than first-caller cost (see `WARMUP_TEXT_RU`).
        The generation goes through the same `_inference_lock` and the same `_run_generate` a real
        `/synthesize` uses, because a warm-up down a different path warms a different path.

        The response reports `output_audio_ms` and `generate_ms` so the caller can tell a real
        generation from a load-only warm-up without reading this source; `Qwen3TTS.warm_up` only
        requires HTTP 200.
        """
        try:
            await state.ensure_loaded()
        except Exception:
            log.exception("tts_qwen3: warm_up failed")
            return JSONResponse(status_code=503, content=_ERROR_BODY)

        payload = SynthesizeRequest(
            text=WARMUP_TEXT_RU,
            speaker=WARMUP_SPEAKER,
            language="Russian",
            instruct="",
            request_id="warmup:tts",
        )
        async with state.inference_lock:
            started = time.monotonic()
            try:
                assert state.model is not None  # ensure_loaded() above guarantees this
                pcm, sample_rate = await asyncio.to_thread(_run_generate, state.model, payload)
            except Exception:
                log.exception("tts_qwen3: warm_up generation failed")
                return JSONResponse(status_code=503, content=_ERROR_BODY)
            generate_ms = int((time.monotonic() - started) * 1000)
        audio_ms = _pcm_audio_ms(pcm, sample_rate)
        # The audio is discarded here, deliberately: nobody ever hears a warm-up.
        del pcm
        log.info("tts_qwen3: warm_up generated %d ms of audio in %d ms", audio_ms, generate_ms)
        return JSONResponse(
            content={
                "status": "ok",
                "loaded": True,
                "output_audio_ms": audio_ms,
                "generate_ms": generate_ms,
            }
        )

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

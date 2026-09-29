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

**I8 V1: the lab's generation recipe** (`/tmp/teamwork-112-maxxing/reports/i8/A1-plan.md` §2.2,
§4 V1). One `/synthesize` is still one client unit, but it is now generated the way the owner's
lab evaluated it:

* digits are spelled out (`pipeline.normalize_numbers`; the raw text with one WARN when
  `num2words` is missing);
* a unit longer than `SAFETY_NET_MAX_CHARS` (the client's splitter could not cut it) is split by
  the vendored `pipeline.segment_text`, each segment generated on its own and `pipeline.stitch`ed
  with `pause_s` of silence (`X-Units` says how many);
* every generation is capped at `max_new_tokens_for(text)` codec tokens — `clamp(ceil(expected_s
  x 12 x 2), 64, 400)`, `expected_s = spoken chars / 10` — instead of the library's 2048 (~170 s
  of runaway audio holding the inference lock); a request may only lower it;
* explicit sampling (`SAMPLING_DEFAULTS`, the lab's tested set) and, when the request carries a
  `seed`, `torch.manual_seed` + `cuda.manual_seed_all` before each generation;
* a free rate check on the RAW clip: fewer than `QC_MIN_CHARS_PER_SECOND` spoken chars per second,
  or longer than `QC_MAX_LENGTH_FACTOR` x the expected length, regenerates ONCE with `seed + 1` and
  keeps the better clip (`X-QC: regenerated`, `X-Seed` = the seed that won). Never a second retry;
* `torch.cuda.empty_cache()` after every generation (with `PYTORCH_CUDA_ALLOC_CONF=
  expandable_segments:True` in the service environment) so a session does not keep the peak;
* post-hoc tempo `sox tempo -s <tempo>` (WSOLA, pitch-preserving) outside the inference lock;
  `X-Tempo` echoes what was applied — `1` when the request asked for none, when `sox` is missing
  (one WARN) or when it failed. Tempo never fails a synthesis.

The torch calls go through a `GenerationRuntime` (`TorchRuntime` for the real loader); a test's
fake factory gets `NullRuntime` unless it injects a recording one: no test touches torch or a GPU.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .pipeline import normalize_numbers, segment_text, stitch

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_MODEL_VARIANT",
    "DEFAULT_PORT",
    "DEFAULT_SEGMENT_PAUSE_S",
    "MAX_NEW_TOKENS",
    "MIN_NEW_TOKENS",
    "MODEL_REPO",
    "MODEL_REVISION",
    "MODEL_VARIANTS",
    "QC_MAX_LENGTH_FACTOR",
    "QC_MIN_CHARS",
    "QC_MIN_CHARS_PER_SECOND",
    "SAFETY_NET_MAX_CHARS",
    "SAMPLE_RATE",
    "SAMPLING_DEFAULTS",
    "TOKENIZER_REPO",
    "TOKENIZER_REVISION",
    "VENDOR_SPEAKERS",
    "WARMUP_SPEAKER",
    "WARMUP_TEXT_RU",
    "GenerationRuntime",
    "ModelFactory",
    "ModelHandle",
    "ModelVariant",
    "NullRuntime",
    "SynthesizeRequest",
    "TorchRuntime",
    "UnknownModelVariantError",
    "WorkerState",
    "create_app",
    "expected_seconds",
    "max_new_tokens_for",
    "rate_check_passes",
    "spoken_chars",
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
#:
#: I8 V0: the speakers the owner evaluated by ear (serena; eric, aiden, uncle_fu) plus `ryan` as a
#: spare male; Vivian was rejected by listening. Lower-case, as `qwen_tts` lists them; a request's
#: `speaker` is matched case-insensitively. MUST equal `app.inference.tts.qwen3_tts.
#: VENDOR_SPEAKERS` (two copies by design — separate venvs; a gate test compares them).
VENDOR_SPEAKERS: tuple[str, ...] = ("serena", "eric", "aiden", "uncle_fu", "ryan")

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
WARMUP_SPEAKER = "serena"


# -- I8 V1: the generation recipe (module docstring) ------------------------------------------

#: The tokenizer's codec frame rate — `Qwen3-TTS-Tokenizer-12Hz`: 12 codec tokens per second.
CODEC_TOKENS_PER_SECOND = 12
#: Expected speaking rate for the token budget: 10 spoken characters (letters/digits) per second.
EXPECTED_CHARS_PER_SECOND = 10
#: Head-room over the expected length before the cap cuts a unit off.
TOKEN_BUDGET_FACTOR = 2
#: `max_new_tokens` bounds (manager decision, I8 V1): 64 tokens ~ 5.3 s, 400 ~ 33 s.
MIN_NEW_TOKENS = 64
MAX_NEW_TOKENS = 400
#: The live rate check (A1 §2.2 "Quality check"): a raw clip slower than this many spoken chars
#: per second is a runaway and is regenerated once with `seed + 1`.
QC_MIN_CHARS_PER_SECOND = 6.0
#: ...as is a raw clip longer than this many times the expected length.
QC_MAX_LENGTH_FACTOR = 3.0
#: Below this many spoken characters the rate check is skipped (`X-QC: skipped`): a one-word
#: unit («Да.», «Алло!») is mostly the model's own lead-in/tail, so its chars/s says nothing about
#: a runaway — and the token cap already bounds it to `MIN_NEW_TOKENS` (~5.3 s).
QC_MIN_CHARS = 10
#: The client's splitter (`tts.max_unit_chars`, 70 on the voice profile) normally keeps a unit far
#: below this; a longer one is split here by the vendored `segment_text` (A1 §2.2 "safety net").
SAFETY_NET_MAX_CHARS = 100
#: Silence between two safety-net segments (A1 §2.2: 0.15-0.25 s).
DEFAULT_SEGMENT_PAUSE_S = 0.2
#: The lab's tested sampling set (`~/emo-lab/tools/qwen3_pipeline.py` `PipelineConfig`), explicit
#: rather than the library's defaults. Each one is overridable per request.
SAMPLING_DEFAULTS: dict[str, float] = {
    "temperature": 0.65,
    "top_p": 0.9,
    "top_k": 30,
    "subtalker_temperature": 0.65,
    "subtalker_top_p": 0.9,
    "subtalker_top_k": 30,
    "repetition_penalty": 1.05,
}
#: `seed` is a 31-bit value (the adapter derives it `& 0x7fffffff`); `seed + 1` wraps inside it.
_SEED_MASK = 0x7FFFFFFF
#: `sox` must never hold a synthesis hostage.
_SOX_TIMEOUT_S = 10.0


def spoken_chars(text: str) -> int:
    """Characters that are spoken: letters and digits — no spaces, no punctuation."""
    return sum(1 for ch in text if ch.isalnum())


def expected_seconds(text: str) -> float:
    """How long `text` should take to say, at `EXPECTED_CHARS_PER_SECOND`."""
    return spoken_chars(text) / EXPECTED_CHARS_PER_SECOND


def max_new_tokens_for(text: str, requested: int | None = None) -> int:
    """`clamp(ceil(expected_seconds x 12 x 2), 64, 400)`; a request may only lower it."""
    budget = math.ceil(expected_seconds(text) * CODEC_TOKENS_PER_SECOND * TOKEN_BUDGET_FACTOR)
    cap = min(MAX_NEW_TOKENS, max(MIN_NEW_TOKENS, budget))
    return cap if requested is None else min(cap, requested)


def rate_check_passes(text: str, audio_s: float) -> bool | None:
    """The live QC on the RAW clip (before tempo). `None` when it does not apply (`QC_MIN_CHARS`).

    Fails when the clip is slower than `QC_MIN_CHARS_PER_SECOND` spoken chars per second or longer
    than `QC_MAX_LENGTH_FACTOR` x `expected_seconds(text)`.
    """
    chars = spoken_chars(text)
    if chars < QC_MIN_CHARS:
        return None
    if audio_s <= 0:
        return True
    if chars / audio_s < QC_MIN_CHARS_PER_SECOND:
        return False
    return audio_s <= QC_MAX_LENGTH_FACTOR * expected_seconds(text)


class ModelHandle(Protocol):
    """What `WorkerState` needs from a loaded model — real (`qwen_tts.Qwen3TTSModel`) or fake."""

    def generate_custom_voice(
        self, *, text: str, language: str, speaker: str, instruct: str, **kwargs: Any
    ) -> tuple[Any, int]:
        """Returns `(wavs, sample_rate)` — `wavs` a sequence of float32 arrays (recon §1.1).

        I8 V1 passes `max_new_tokens` and the sampling kwargs (`SAMPLING_DEFAULTS`) through
        `**kwargs`; `qwen_tts` forwards them to its `generate()`."""
        ...


class GenerationRuntime(Protocol):
    """The torch side effects around one generation — injectable so tests never import torch."""

    def seed(self, seed: int) -> None:
        """Seed every RNG the next generation samples from."""
        ...

    def release(self) -> None:
        """Hand cached allocator blocks back after a generation."""
        ...


class TorchRuntime:
    """The real runtime: `torch.manual_seed` + `cuda.manual_seed_all`, and `empty_cache()`."""

    def seed(self, seed: int) -> None:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

    def release(self) -> None:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()


class NullRuntime:
    """No torch: the runtime a fake model factory gets unless a test injects its own."""

    def seed(self, seed: int) -> None:
        return None

    def release(self) -> None:
        return None


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
    # -- I8 V1 (all optional: a client that sends none of them gets the recipe's defaults — no
    # seed, the length cap, the lab's sampling, no tempo) --
    #: Seeds the generation; the one retry uses `seed + 1`. `None` = unseeded.
    seed: int | None = Field(default=None, ge=0, le=_SEED_MASK)
    #: An explicit cap; it only ever LOWERS `max_new_tokens_for(text)`.
    max_new_tokens: int | None = Field(default=None, ge=1, le=MAX_NEW_TOKENS)
    #: Post-synthesis tempo (`sox tempo -s`); 1.0 = none.
    tempo: float = Field(default=1.0, ge=0.5, le=2.0)
    #: Silence between two safety-net segments (`SAFETY_NET_MAX_CHARS`), seconds.
    pause_s: float = Field(default=DEFAULT_SEGMENT_PAUSE_S, ge=0.0, le=1.0)
    temperature: float = Field(default=SAMPLING_DEFAULTS["temperature"], gt=0.0, le=2.0)
    top_p: float = Field(default=SAMPLING_DEFAULTS["top_p"], gt=0.0, le=1.0)
    top_k: int = Field(default=int(SAMPLING_DEFAULTS["top_k"]), ge=1, le=1000)
    subtalker_temperature: float = Field(
        default=SAMPLING_DEFAULTS["subtalker_temperature"], gt=0.0, le=2.0
    )
    subtalker_top_p: float = Field(default=SAMPLING_DEFAULTS["subtalker_top_p"], gt=0.0, le=1.0)
    subtalker_top_k: int = Field(default=int(SAMPLING_DEFAULTS["subtalker_top_k"]), ge=1, le=1000)
    repetition_penalty: float = Field(
        default=SAMPLING_DEFAULTS["repetition_penalty"], ge=1.0, le=2.0
    )

    def sampling(self) -> dict[str, float]:
        """The sampling kwargs `generate_custom_voice` receives."""
        return {name: getattr(self, name) for name in SAMPLING_DEFAULTS}


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
        runtime: GenerationRuntime | None = None,
    ) -> None:
        self.model_dir = model_dir
        self.model_factory = model_factory
        self.device = device
        self.variant_repo = variant_repo
        self.variant_revision = variant_revision
        self.runtime: GenerationRuntime = runtime if runtime is not None else NullRuntime()
        self.model: ModelHandle | None = None
        self.load_lock = asyncio.Lock()
        self.inference_lock = asyncio.Lock()
        #: One WARN per process for each missing optional tool, not one per unit.
        self.warned_no_sox = False
        self.warned_no_num2words = False

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


def _float_wavs_to_array(wavs: Any) -> Any:
    """`wavs` (recon §1.1: "a list of np.ndarray" float32 in [-1, 1]) -> one float32 array.

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
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(pieces) if len(pieces) > 1 else pieces[0]


def _array_to_pcm16(audio: Any) -> bytes:
    """Float32 in [-1, 1] -> PCM s16le."""
    import numpy as np

    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype("<i2")
    return bytes(pcm16.tobytes())


def _run_generate(
    model: ModelHandle,
    runtime: GenerationRuntime,
    payload: SynthesizeRequest,
    *,
    text: str,
    seed: int | None,
) -> tuple[Any, int]:
    """One generation of `text`. Runs on a worker thread (`asyncio.to_thread`) — the model call
    itself is synchronous. Seeds first when a seed is given; releases the allocator cache after,
    whatever happened (I8 V1)."""
    if seed is not None:
        runtime.seed(seed)
    try:
        wavs, sample_rate = model.generate_custom_voice(
            text=text,
            language=payload.language,
            speaker=payload.speaker,
            instruct=payload.instruct,
            max_new_tokens=max_new_tokens_for(text, payload.max_new_tokens),
            **payload.sampling(),
        )
    finally:
        runtime.release()
    return _float_wavs_to_array(wavs), sample_rate


@dataclass(frozen=True)
class _Synthesis:
    """What one `/synthesize` (or `/warm_up`) generated, before tempo."""

    pcm: bytes
    sample_rate: int
    seeds: tuple[int | None, ...]  # the seed that WON, per segment
    qc: str  # "ok" | "regenerated" | "skipped" | "failed"
    units: int


async def _never_disconnected() -> bool:
    return False


async def _generate_speech(
    state: WorkerState,
    payload: SynthesizeRequest,
    *,
    is_disconnected: Callable[[], Awaitable[bool]] = _never_disconnected,
) -> _Synthesis:
    """The I8 V1 recipe (module docstring). The caller holds `state.inference_lock`."""
    model = state.model
    assert model is not None  # the caller ran ensure_loaded()
    text = _speech_text(state, payload.text)
    segments = segment_text(text, SAFETY_NET_MAX_CHARS) if len(text) > SAFETY_NET_MAX_CHARS else []
    if not segments:
        segments = [text]
    audio: list[Any] = []
    seeds: list[int | None] = []
    verdicts: list[str] = []
    sample_rate = SAMPLE_RATE
    for segment in segments:
        wav, sample_rate = await asyncio.to_thread(
            _run_generate, model, state.runtime, payload, text=segment, seed=payload.seed
        )
        won_seed = payload.seed
        verdict = rate_check_passes(segment, wav.size / sample_rate if sample_rate else 0.0)
        if verdict is False and not await is_disconnected():
            retry_seed = None if payload.seed is None else (payload.seed + 1) & _SEED_MASK
            retry_wav, retry_rate = await asyncio.to_thread(
                _run_generate, model, state.runtime, payload, text=segment, seed=retry_seed
            )
            retry_s = retry_wav.size / retry_rate if retry_rate else 0.0
            # Both failure modes are "too long", so of two failing clips the shorter is better.
            if rate_check_passes(segment, retry_s) or retry_wav.size < wav.size:
                wav, sample_rate, won_seed = retry_wav, retry_rate, retry_seed
            log.info(
                "tts_qwen3: rate check failed, regenerated (request_id=%s, seed=%s -> kept %s)",
                payload.request_id,
                payload.seed,
                won_seed,
            )
            verdicts.append("regenerated")
        else:
            # `False` here only when the client left before the retry: nobody reads this answer.
            verdicts.append({None: "skipped", True: "ok", False: "failed"}[verdict])
        audio.append(wav)
        seeds.append(won_seed)
    joined = (
        audio[0]
        if len(audio) == 1
        else stitch(audio, sample_rate, [payload.pause_s] * (len(audio) - 1))
    )
    if "regenerated" in verdicts:
        qc = "regenerated"
    elif "failed" in verdicts:
        qc = "failed"
    elif all(verdict == "skipped" for verdict in verdicts):
        qc = "skipped"
    else:
        qc = "ok"
    return _Synthesis(
        pcm=_array_to_pcm16(joined),
        sample_rate=sample_rate,
        seeds=tuple(seeds),
        qc=qc,
        units=len(segments),
    )


def _speech_text(state: WorkerState, text: str) -> str:
    """Digits spelled out (`normalize_numbers`); the raw text, with one WARN, without num2words."""
    try:
        return normalize_numbers(text)
    except ImportError:
        if not state.warned_no_num2words:
            state.warned_no_num2words = True
            log.warning(
                "tts_qwen3: num2words is not installed; digits are sent to the model unspelled "
                "(run `make deps-tts-qwen3`)"
            )
        return text


def _apply_tempo(
    state: WorkerState, pcm: bytes, sample_rate: int, tempo: float
) -> tuple[bytes, float]:
    """`sox tempo -s <tempo>` over raw PCM s16le mono. Returns `(pcm, tempo actually applied)`.

    Never raises: a missing `sox` (one WARN per process) or a failing one (a WARN each time)
    returns the untouched clip and `1.0` — tempo is a nicety, the synthesis already succeeded.
    """
    if tempo == 1.0 or not pcm:
        return pcm, 1.0
    sox = shutil.which("sox")
    if sox is None:
        if not state.warned_no_sox:
            state.warned_no_sox = True
            log.warning("tts_qwen3: sox is not installed; tempo is not applied (X-Tempo: 1)")
        return pcm, 1.0
    raw = ["-t", "raw", "-r", str(sample_rate), "-e", "signed", "-b", "16", "-c", "1", "-L"]
    command = [sox, *raw, "-", *raw, "-", "tempo", "-s", f"{tempo:g}"]
    try:
        result = subprocess.run(  # fixed argv, no shell
            command, input=pcm, capture_output=True, timeout=_SOX_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        log.warning("tts_qwen3: sox tempo failed to run; tempo is not applied", exc_info=True)
        return pcm, 1.0
    out = result.stdout
    if result.returncode != 0 or not out:
        log.warning("tts_qwen3: sox tempo exited %d; tempo is not applied", result.returncode)
        return pcm, 1.0
    return out[: len(out) - len(out) % BYTES_PER_SAMPLE], tempo


#: The container prefix a model profile names (`/models/tts/qwen3-tts`), and the environment
#: variable that says where those files live on THIS host (E20 R15).
_CONTAINER_MODELS_PREFIX = "/models/"
_MODELS_ROOT_ENV = "SIM_MODELS_ROOT"


def _host_model_dir(raw: str) -> Path:
    """Rebase a container model path onto `SIM_MODELS_ROOT`, or return it unchanged.

    A model profile names `/models/tts/qwen3-tts`, which is where `infra/docker-compose.yml`
    mounts the host's `models/` directory — so under compose (`SIM_MODELS_ROOT` unset or
    `/models`) this is the identity, exactly as before. A **host** run
    (`make run-tts-qwen3`) has the same files under the repository's own `models/` and nothing at
    `/models`; it sets `SIM_MODELS_ROOT=./models` and this maps the path onto it.

    This worker is deliberately **not** a `sim112-workspace` member (see this package's
    `pyproject.toml`: `qwen-tts` pins a `torch` the backend venv cannot hold), so it cannot import
    `app.config.model_paths.resolve_model_path` the way the voice agent, `app/cli/preflight.py`
    and the benchmarks all do. What is reproduced here is only that function's **primary** mapping
    — `/models/<rest>` -> `<root>/<rest>`, the layout `make models-layout` produces. Its
    legacy-download-name fallback is not, on purpose: a second copy of that table in a second venv
    is exactly the drift R15 exists to remove, and a worker pointed at a stale layout should fail
    naming the path it actually opened.
    """
    if not raw.startswith(_CONTAINER_MODELS_PREFIX):
        return Path(raw)
    root = os.environ.get(_MODELS_ROOT_ENV, "").strip()
    if not root:
        return Path(raw)
    return Path(root).expanduser() / raw[len(_CONTAINER_MODELS_PREFIX) :]


def create_app(
    *,
    model_dir: Path | None = None,
    model_factory: ModelFactory | None = None,
    device: str = "cuda:0",
    variant: str | None = None,
    runtime: GenerationRuntime | None = None,
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
    is used as-is.

    `runtime` (I8 V1) owns the torch side effects (seeding, `empty_cache()`). Omitted, the real
    loader gets `TorchRuntime` and an injected fake factory gets `NullRuntime` — a test with a fake
    model never imports torch or touches a GPU."""
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
        base_model_dir = _host_model_dir(
            os.environ.get("SIM_TTS_QWEN3_MODEL_DIR", "models/qwen3-tts")
        )
        resolved_model_dir = base_model_dir / variant_config.subdirectory

    factory = model_factory or _default_model_factory
    if runtime is None:
        runtime = TorchRuntime() if model_factory is None else NullRuntime()
    state = WorkerState(
        model_dir=resolved_model_dir,
        model_factory=factory,
        device=device,
        variant_repo=variant_config.repo,
        variant_revision=variant_config.revision,
        runtime=runtime,
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
                synthesis = await _generate_speech(state, payload)
            except Exception:
                log.exception("tts_qwen3: warm_up generation failed")
                return JSONResponse(status_code=503, content=_ERROR_BODY)
            generate_ms = int((time.monotonic() - started) * 1000)
        audio_ms = _pcm_audio_ms(synthesis.pcm, synthesis.sample_rate)
        # The audio is discarded here, deliberately: nobody ever hears a warm-up.
        del synthesis
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
        speaker = payload.speaker.strip().lower()
        if speaker not in VENDOR_SPEAKERS:
            log.warning("tts_qwen3: unknown speaker %r rejected", payload.speaker)
            return JSONResponse(status_code=503, content=_ERROR_BODY)
        payload = payload.model_copy(update={"speaker": speaker})

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
                synthesis = await _generate_speech(
                    state, payload, is_disconnected=request.is_disconnected
                )
            except Exception:
                log.exception("tts_qwen3: synthesis failed (request_id=%s)", payload.request_id)
                return JSONResponse(status_code=503, content=_ERROR_BODY)
            gen_ms = int((time.monotonic() - started) * 1000)

        # Outside the inference lock: `sox` is CPU work and must not delay the next generation.
        pcm, tempo = await asyncio.to_thread(
            _apply_tempo, state, synthesis.pcm, synthesis.sample_rate, payload.tempo
        )
        audio_ms = _pcm_audio_ms(pcm, synthesis.sample_rate)
        headers = {
            "X-Sample-Rate": str(synthesis.sample_rate),
            "X-Audio-Ms": str(audio_ms),
            "X-Gen-Ms": str(gen_ms),
            # I8 V1: what was actually generated (the adapter records them on
            # CALLER_TTS_STARTED). `X-Seed` is the seed that WON per segment, `none` unseeded.
            "X-Tempo": f"{tempo:g}",
            "X-Seed": ",".join("none" if seed is None else str(seed) for seed in synthesis.seeds),
            "X-QC": synthesis.qc,
            "X-Units": str(synthesis.units),
        }
        return Response(content=pcm, media_type="audio/L16", headers=headers)

    return app

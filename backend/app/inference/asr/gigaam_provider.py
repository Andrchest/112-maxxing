"""`GigaAMProvider` — the real `ASRProvider` over the local GigaAM v3 CTC checkpoints
(`50-voice-pipeline.md` §2.3, `60-inference-ops.md`, E12 ruling 3).

Two checkpoints share one adapter, selected by `model_version` at construction: `v3_e2e_ctc`
(primary, sentencepiece tokenizer, punctuated output) and `v3_ctc` (benchmarked alternative, plain
lowercase Cyrillic char vocabulary embedded in `config.json`, no `tokenizer.model`). Both are
Conformer-CTC models loaded from a local HF-format directory (`config.json`, `modeling_gigaam.py`,
`pytorch_model.bin`, and `tokenizer.model` for `v3_e2e_ctc` only) via
`AutoModel.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True)` with
`HF_HUB_OFFLINE=1` set for the load — no network in the runtime path (SPEC §41).

This adapter deliberately does **not** call the checkpoint's own `GigaAMASR.transcribe(wav_file)`:
that method shells out to `ffmpeg` and switches to a pyannote-based longform path above 25 s, both
disallowed here (no subprocess, no extra heavy dependency, no network). Instead it builds the
float32 waveform tensor directly from the PCM s16le bytes the pipeline already holds in memory —
the same `int16 -> float32 / 32768.0` conversion `modeling_gigaam.load_audio` performs — and drives
the model's own `forward()` (preprocessor + Conformer encoder) and `CTCHead` +
`CTCGreedyDecoding.decode` directly (mirrors `GigaAMASR.transcribe`/`prepare_wav`/`forward` and
`CTCGreedyDecoding.decode`, `modeling_gigaam.py` lines ~1056-1150 and ~1196-1260 of the checkpoint).

`torch`/`torchaudio`/`transformers`/`hydra`/`omegaconf`/`sentencepiece` (the `asr-gigaam` extra) are
imported lazily inside `warm_up()` — `import app.inference.asr` must work without them (E12 ruling
2). `split_long_audio` and `ctc_confidence` below take/return plain numpy arrays, need no heavy
import, and carry their own gate-side unit tests.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np

from app.application.ports.asr import AsrResult, UnsupportedOperationError
from app.inference.errors import InferenceOutOfMemoryError, ModelNotAvailableError

__all__ = ["GigaAMProvider", "ctc_confidence", "split_long_audio"]

log = logging.getLogger(__name__)

_PROVIDER_NAME = "gigaam"
_LANGUAGE = "ru"
_BYTES_PER_SAMPLE = 2
_MS_PER_S = 1000
_INT16_SCALE = 32768.0

#: The checkpoint's own `LONGFORM_THRESHOLD` (`modeling_gigaam.py`): above this, a single forward
#: pass takes a code path the model was never evaluated on. `max_turn_ms` is 30 s, so this *will*
#: be exceeded on a long turn; `split_long_audio` below is what keeps every window under it.
_MODEL_WINDOW_S = 25.0
#: The window size `split_long_audio` targets once a turn exceeds `_MODEL_WINDOW_S` (ruling 3).
_SPLIT_WINDOW_S = 20.0
#: How far around each nominal boundary `split_long_audio` searches for a quiet cut point.
_SPLIT_SEARCH_S = 1.0
#: Energy-analysis granularity for the boundary search: 20 ms at 16 kHz.
_SPLIT_FRAME_S = 0.02


def split_long_audio(
    pcm: bytes,
    sample_rate: int,
    *,
    model_window_s: float = _MODEL_WINDOW_S,
    split_window_s: float = _SPLIT_WINDOW_S,
    search_s: float = _SPLIT_SEARCH_S,
) -> list[bytes]:
    """Split PCM s16le mono audio longer than the model's window into <= `split_window_s` windows.

    Audio at or under `model_window_s` is returned as a single window, unchanged. Otherwise, every
    ~`split_window_s` a cut point is chosen at the lowest-RMS-energy analysis frame within
    `search_s` of the nominal boundary (falling back to the boundary itself when there is no room
    to search), so a split lands in a pause rather than mid-word wherever one exists nearby.

    Pure function — no ffmpeg, no pyannote, no I/O, no torch (ruling 3) — so it is unit-tested
    without the `asr-gigaam` extra installed.
    """
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    samples = np.frombuffer(pcm, dtype="<i2")
    total = samples.shape[0]
    model_window_samples = int(model_window_s * sample_rate)
    if total <= model_window_samples:
        return [pcm]
    split_window_samples = int(split_window_s * sample_rate)
    search_samples = int(search_s * sample_rate)
    frame_samples = max(1, int(_SPLIT_FRAME_S * sample_rate))

    windows: list[bytes] = []
    start = 0
    while total - start > model_window_samples:
        boundary = start + split_window_samples
        lo = max(start + frame_samples, boundary - search_samples)
        hi = min(total - frame_samples, boundary + search_samples)
        cut = min(boundary, total)
        if hi > lo:
            best_energy: float | None = None
            for frame_start in range(lo, hi, frame_samples):
                frame = samples[frame_start : frame_start + frame_samples].astype(np.float64)
                energy = float(np.mean(frame * frame)) if frame.size else 0.0
                if best_energy is None or energy < best_energy:
                    best_energy = energy
                    cut = frame_start
        cut = max(start + 1, min(cut, total))
        windows.append(samples[start:cut].tobytes())
        start = cut
    windows.append(samples[start:total].tobytes())
    return windows


def ctc_confidence(max_probs: np.ndarray, labels: np.ndarray, blank_id: int, length: int) -> float:
    """Mean per-frame max-softmax probability over non-blank CTC frames (E12 ruling 3).

    `max_probs`/`labels` are 1-D arrays over every encoder timestep (`labels` is each frame's
    argmax class id, `max_probs` its softmax probability); only the first `length` frames are the
    model's real output, the rest is padding. Returns 0.0 when no frame's argmax is non-blank —
    never a divide-by-zero, never a fabricated number (SPEC §27).
    """
    if length <= 0:
        return 0.0
    max_probs = np.asarray(max_probs)[:length]
    labels = np.asarray(labels)[:length]
    mask = labels != blank_id
    if not np.any(mask):
        return 0.0
    return float(np.mean(max_probs[mask]))


class GigaAMProvider:
    """`ASRProvider` over a local GigaAM v3 CTC checkpoint (`v3_e2e_ctc` or `v3_ctc`)."""

    provider_name = _PROVIDER_NAME

    def __init__(
        self, *, model_dir: str, model_version: str, device: str, compute_type: str
    ) -> None:
        self._model_dir = model_dir
        self._model_version = model_version
        self._device = device
        self._compute_type = compute_type
        self._hf_model: Any = None
        self._asr: Any = None  # the underlying GigaAMASR instance (.forward / .head / .decoding)
        self._torch: Any = None
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def model_version(self) -> str:
        """The checkpoint version this instance was constructed with (`v3_e2e_ctc` / `v3_ctc`)."""
        return self._model_version

    @property
    def supports_streaming(self) -> bool:
        """False: no native streaming API; §4.5 pseudo-streams over `transcribe()` instead."""
        return False

    @property
    def required_sample_rate(self) -> int:
        """16 kHz — the sample rate every GigaAM v3 checkpoint was trained at."""
        return 16_000

    async def warm_up(self) -> None:
        """Load the checkpoint on `device`/`compute_type` and run one short dummy inference."""
        if self._hf_model is not None:
            return
        model_dir = Path(self._model_dir)
        if not await asyncio.to_thread(model_dir.is_dir):
            needs_tokenizer = self._model_version == "v3_e2e_ctc"
            raise ModelNotAvailableError(
                f"GigaAM checkpoint not found at {model_dir} — expected a local HF-format "
                "directory (config.json, modeling_gigaam.py, pytorch_model.bin"
                f"{', tokenizer.model' if needs_tokenizer else ''}); see models/README.md"
            )
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        import torch
        from transformers import AutoModel

        # The checkpoint's own modeling_gigaam.py imports `pyannote` inside the longform-only
        # helpers this adapter never calls (ruling 3 forbids the pyannote longform path
        # entirely — see the module docstring). `AutoModel.from_pretrained(...,
        # trust_remote_code=True)` still statically scans every import in the whole file before
        # loading it (`transformers.dynamic_module_utils.check_imports`) and refuses to proceed
        # if any top-level package name is unimportable — even one guarding a function this
        # adapter never reaches. A minimal stub module satisfies that static check without
        # installing the real (large, unrelated) package; nothing ever calls into it.
        if "pyannote" not in sys.modules:
            sys.modules["pyannote"] = types.ModuleType("pyannote")

        device = self._device
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("GigaAMProvider: device='cuda' requested but CUDA is not available")
        compute_type = self._compute_type
        if device != "cuda" and compute_type == "float16":
            log.warning(
                "GigaAMProvider(%s): float16 requested on device=%r; forcing float32 "
                "(float16 is cuda-only)",
                self._model_version,
                device,
            )
            compute_type = "float32"

        try:
            hf_model = AutoModel.from_pretrained(
                str(model_dir), trust_remote_code=True, local_files_only=True
            )
            # Move to `device` only — the parameters stay float32. The checkpoint's own
            # `GigaAM.forward()` (`modeling_gigaam.py`) already implements the mixed-precision
            # policy for `compute_type="float16"` itself: on any non-cpu device it wraps *only*
            # the Conformer encoder in `torch.autocast(dtype=torch.float16)`, deliberately leaving
            # the mel-spectrogram preprocessor and the `CTCHead` outside that block. Hard-casting
            # the whole model to float16 with `.to(dtype=torch.float16)` breaks both of those: the
            # preprocessor's `torch.stft` refuses half precision for this config's non-power-of-two
            # `n_fft=320` on this CUDA/cuFFT build, and the encoder's autocast output comes back
            # float32 (its last op is a LayerNorm, which autocast keeps at float32), which then
            # mismatches a float16 `CTCHead.Conv1d` (measured: both errors reproduced with an
            # explicit cast). Deferring entirely to the checkpoint's built-in autocast is what
            # actually gets `compute_type="float16"` compute on cuda without breaking either path;
            # `device="cpu"` never enters that autocast branch at all (checkpoint code), so cpu is
            # genuinely float32 either way — consistent with ruling 3's cpu behaviour.
            hf_model = hf_model.to(device=device)
        except RuntimeError as exc:
            if _is_cuda_oom(exc):
                raise InferenceOutOfMemoryError(
                    f"GigaAMProvider: CUDA out of memory loading {model_dir}"
                ) from exc
            raise
        hf_model.eval()

        self._torch = torch
        self._hf_model = hf_model
        self._asr = hf_model.model  # the wrapped GigaAMASR: .forward / .head / .decoding

        silence = b"\x00\x00" * (self.required_sample_rate // 10)  # 100 ms of digital silence
        await self.transcribe(silence, self.required_sample_rate, request_id="warmup")

    async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> AsrResult:
        """Transcribe one finalized turn. Runs the forward pass off the event loop (barge-in
        depends on the loop staying free) behind a one-at-a-time lock for this provider instance.
        """
        if sample_rate != self.required_sample_rate:
            raise ValueError(
                f"GigaAMProvider needs {self.required_sample_rate} Hz, got {sample_rate}"
            )
        if self._hf_model is None:
            raise RuntimeError("GigaAMProvider.warm_up() must be called before transcribe()")
        async with self._lock:
            try:
                text, confidence = await asyncio.to_thread(self._transcribe_sync, audio)
            except RuntimeError as exc:
                if _is_cuda_oom(exc):
                    raise InferenceOutOfMemoryError(
                        "GigaAMProvider: CUDA out of memory during transcribe "
                        f"(request_id={request_id})"
                    ) from exc
                raise
        duration_ms = _pcm_duration_ms(audio, sample_rate)
        return AsrResult(
            text=text,
            is_final=True,
            start_ms=0,
            end_ms=duration_ms,
            confidence=confidence,
            words=[],  # GigaAM's CTC greedy decoder gives no per-word timing (ruling 3)
            provider=self.provider_name,
            model_version=self._model_version,
            audio_duration_ms=duration_ms,
            language=_LANGUAGE,
        )

    def _transcribe_sync(self, audio: bytes) -> tuple[str, float]:
        """Runs on a worker thread (`asyncio.to_thread`) under `torch.inference_mode()`."""
        torch = self._torch
        asr = self._asr
        device = self._device
        windows = split_long_audio(audio, self.required_sample_rate)
        texts: list[str] = []
        confidences: list[float] = []
        with torch.inference_mode():
            for window in windows:
                if len(window) == 0:
                    continue
                wav = torch.frombuffer(bytearray(window), dtype=torch.int16).float() / (
                    _INT16_SCALE
                )
                # float32: the model's own parameters stay float32 (see `warm_up()`'s comment);
                # `GigaAM.forward()`'s `torch.autocast(dtype=torch.float16)` around the encoder
                # is what actually gives cuda its float16 compute for `compute_type="float16"`.
                wav = wav.to(device=device).unsqueeze(0)
                length = torch.tensor([wav.shape[-1]], device=device)
                encoded, encoded_len = asr.forward(wav, length)
                log_probs = asr.head(encoder_output=encoded)  # log_softmax, [1, T, C]
                probs = log_probs.exp()
                max_probs, labels = probs.max(dim=-1)  # each [1, T]
                blank_id = asr.decoding.blank_id
                # Mirrors `CTCGreedyDecoding.decode` exactly: collapse consecutive repeats and
                # drop blanks, so our text matches what the checkpoint's own decode() produces.
                skip_mask = labels != blank_id
                skip_mask[:, 1:] = torch.logical_and(
                    skip_mask[:, 1:], labels[:, 1:] != labels[:, :-1]
                )
                length0 = int(encoded_len[0].item())
                skip_mask[0, length0:] = False
                token_ids = labels[0][skip_mask[0]].cpu().tolist()
                texts.append(asr.decoding.tokenizer.decode(token_ids))
                confidences.append(
                    ctc_confidence(
                        max_probs[0].float().cpu().numpy(),
                        labels[0].cpu().numpy(),
                        blank_id,
                        length0,
                    )
                )
        text = " ".join(part for part in texts if part)
        confidence = float(np.mean(confidences)) if confidences else 0.0
        return text, confidence

    def stream(self, frames: Any, *, request_id: str) -> Any:
        """Not implemented: `supports_streaming` is False. §4.5's pipeline pseudo-streams by
        calling `transcribe()` on the accumulation-so-far instead; this method exists only so a
        caller that skipped the `supports_streaming` guard gets a clear error, not a hang.
        """
        raise UnsupportedOperationError(
            "GigaAMProvider.supports_streaming is False; the TurnPipeline pseudo-streams over "
            "transcribe() instead (docs/hld/50-voice-pipeline.md §4.5)"
        )

    async def close(self) -> None:
        """Drop the model and release CUDA memory. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._asr = None
        self._hf_model = None
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()


def _is_cuda_oom(exc: Exception) -> bool:
    return "out of memory" in str(exc).lower() or type(exc).__name__ == "OutOfMemoryError"


def _pcm_duration_ms(audio: bytes, sample_rate: int) -> int:
    if sample_rate <= 0:  # pragma: no cover - guarded by the port's contract
        return 0
    return (len(audio) * _MS_PER_S) // (sample_rate * _BYTES_PER_SAMPLE)

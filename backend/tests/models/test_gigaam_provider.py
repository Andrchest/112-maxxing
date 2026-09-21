"""`GigaAMProvider` contract test against the real checkpoints and a real Russian recording.

Marker `requires_models` (E12 ruling 1): `make test-models` only. Skips (never fails) when
`SIM_RUN_MODEL_TESTS!=1`, `torch`/`transformers` are not importable, or the relevant
`models/gigaam-v3-*` directory is absent. Parametrised over both checkpoints (SPEC §19: primary
`v3_e2e_ctc`, benchmarked `v3_ctc`) so they are directly comparable.

`_EXPECTED_TEXT` is the transcript the GigaAM project's own published example publishes for this
exact recording (`backend/tests/models/assets/README.md` has the source) — Pushkin's «У лукоморья
дуб зелёный», first lines. It is not this task's own model's output being checked against itself.
"""

from __future__ import annotations

import asyncio
import re
import time
import wave
from pathlib import Path

import pytest
from app.inference.asr.gigaam_provider import GigaAMProvider

from tests.models._skip import require_model_env

pytestmark = pytest.mark.requires_models

_MODELS_ROOT = Path(__file__).resolve().parents[3] / "models"
_SAMPLE_PATH = Path(__file__).resolve().parent / "assets" / "ru_sample.wav"
_SAMPLE_RATE = 16_000
_MAX_WER = 0.2

_EXPECTED_TEXT = (
    "ничьих не требуя похвал счастлив уж я надеждой сладкой что дева с трепетом любви "
    "посмотрит может быть украдкой на песни грешные мои у лукоморья дуб зеленый"
)

_CHECKPOINTS = {
    "v3_e2e_ctc": _MODELS_ROOT / "gigaam-v3-e2e_ctc",
    "v3_ctc": _MODELS_ROOT / "gigaam-v3-ctc",
}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, ё->е (E12 ruling 7's normalisation)."""
    text = text.lower().replace("ё", "е")
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def _word_error_rate(reference: str, hypothesis: str) -> float:
    """Standard word-level Levenshtein WER; pure stdlib, no extra dependency."""
    ref = _normalize(reference).split()
    hyp = _normalize(hypothesis).split()
    n, m = len(ref), len(hyp)
    if n == 0:
        return 0.0 if m == 0 else 1.0
    previous = list(range(m + 1))
    for i in range(1, n + 1):
        current = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            current[j] = min(
                previous[j] + 1,  # deletion
                current[j - 1] + 1,  # insertion
                previous[j - 1] + cost,  # substitution
            )
        previous = current
    return previous[m] / n


def _read_sample_pcm() -> bytes:
    with wave.open(str(_SAMPLE_PATH), "rb") as wf:
        assert wf.getframerate() == _SAMPLE_RATE
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        return wf.readframes(wf.getnframes())


@pytest.fixture(params=sorted(_CHECKPOINTS))
async def provider(request: pytest.FixtureRequest) -> GigaAMProvider:
    model_version = request.param
    model_dir = _CHECKPOINTS[model_version]
    require_model_env(packages=("torch", "transformers"), paths=(model_dir, _SAMPLE_PATH))
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "float32"
    instance = GigaAMProvider(
        model_dir=str(model_dir),
        model_version=model_version,
        device=device,
        compute_type=compute_type,
    )
    await instance.warm_up()
    yield instance
    await instance.close()


async def test_transcript_matches_the_known_text_within_wer_budget(
    provider: GigaAMProvider,
) -> None:
    pcm = _read_sample_pcm()
    result = await provider.transcribe(pcm, _SAMPLE_RATE, request_id="wer")
    wer = _word_error_rate(_EXPECTED_TEXT, result.text)
    assert wer <= _MAX_WER, f"{provider.model_version}: WER {wer:.3f} over {result.text!r}"


async def test_confidence_is_in_the_valid_range(provider: GigaAMProvider) -> None:
    pcm = _read_sample_pcm()
    result = await provider.transcribe(pcm, _SAMPLE_RATE, request_id="confidence")
    assert result.confidence is not None
    assert 0.0 < result.confidence <= 1.0


async def test_transcribe_never_stalls_the_event_loop_more_than_100ms(
    provider: GigaAMProvider,
) -> None:
    """Proves `transcribe()` runs the forward pass in `asyncio.to_thread` (ruling 3): a heartbeat
    ticking every 10 ms on the same loop must never see a gap over 100 ms while transcribe() runs.
    """
    pcm = _read_sample_pcm()
    gaps: list[float] = []
    stop = asyncio.Event()

    async def heartbeat() -> None:
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    heartbeat_task = asyncio.create_task(heartbeat())
    deadline = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            await provider.transcribe(pcm, _SAMPLE_RATE, request_id="heartbeat")
            if len(gaps) >= 5:
                break
    finally:
        stop.set()
        await heartbeat_task
    assert gaps, "heartbeat never ticked"
    assert max(gaps) <= 0.1, f"event loop stalled for {max(gaps) * 1000:.1f} ms"


async def test_the_wrong_sample_rate_is_refused(provider: GigaAMProvider) -> None:
    with pytest.raises(ValueError, match="16000"):
        await provider.transcribe(b"\x00\x00", 8_000, request_id="bad-rate")


async def test_close_returns_cuda_memory_to_roughly_zero(provider: GigaAMProvider) -> None:
    import torch

    if not torch.cuda.is_available():
        pytest.skip("no CUDA device available")
    pcm = _read_sample_pcm()
    await provider.transcribe(pcm, _SAMPLE_RATE, request_id="pre-close")
    await provider.close()
    # A few MB of allocator bookkeeping/fragmentation is normal; a whole model's worth is not.
    allocated_mb = torch.cuda.memory_allocated() / (1024 * 1024)
    assert allocated_mb < 50, f"{allocated_mb:.1f} MB still allocated after close()"

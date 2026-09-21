"""Real TTS contract tests — `PiperTTS` (CPU) and `Qwen3TTS` (GPU, against a worker this test
starts) — this task's brief, item 5.

Marker `requires_models` (E12 ruling 1, reused for E14-B): `make test-models` only. Every assertion
runs over five Russian dispatcher-style sentences and is measured, never invented (SPEC §27):
first-chunk latency, RTF, sample rate, non-silent audio, and a round trip through the **real**
GigaAM ASR (E12) with WER printed as intelligibility evidence, reusing
`tests.models.test_gigaam_provider`'s own WER/normalisation helpers rather than a second copy.

Piper: skips (never fails) unless `piper` is importable and `SIM_TTS_PIPER_VOICE_PATH` (default
`models/piper/ru_RU-irina-medium.onnx`, `make models-piper`) exists.

Qwen3-TTS: this test **starts its own `tts_qwen3` worker subprocess** (the package's own venv,
`workers/tts_qwen3/.venv`, created by `scripts/setup_tts_qwen3.sh`) — captured PID, always
terminated, never `killpg`/signalled anything this process did not start itself — **only if**
measured free VRAM >= 4600 MB (recon §1.1: ≈ 4.3 GB bf16 residency + headroom) **and** no
`llama-server` process is already running (two GPU-heavy processes loading at once is exactly how
the shared dev GPU OOMs). Otherwise the test SKIPs with the measured free VRAM (or the detected
`llama-server` PID) in the skip reason, and this task's report says NOT_RUN with that same reason —
never a fabricated number.

Smaller-checkpoint check (this task's brief, item 5): `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` exists
upstream (confirmed via the HF Hub API during this task, commit
`85e237c12c027371202489a0ec509ded67b5e4b5`) and its `model.safetensors` measures ≈ 1.73 GB on
disk — small enough to plausibly fit this
machine's free VRAM where the 1.7B checkpoint does not. `SIM_TTS_QWEN3_0_6B_MODEL_DIR` (this
task's own setting, not part of E14-B's Settings surface — a test-only override, since
`Qwen3TTS`/`build_tts` never need to know about a second checkpoint) points the worker at it
instead of the pinned 1.7B directory when set. Its numbers, if measured, are reported **as this
task's own measurement, not the owner's** (the owner evaluated only the 1.7B checkpoint — recon
§1.1) — see this task's report for whether the download/run actually completed in the time
available.

**E14-D addendum.** `MODEL_VARIANTS`/`SIM_TTS_QWEN3_MODEL` (`workers/tts_qwen3/tts_qwen3/server.py`)
now makes the 0.6B checkpoint a config choice with its own pinned subdirectory, and this task's real
run (`SIM_RUN_MODEL_TESTS=1`, free VRAM 3196 MB, well under the 4600 MB this file's own
`test_qwen3_tts_contract_real_synthesis_and_asr_round_trip` requires just to *attempt* the 1.7B —
so that test still always SKIPs on this machine, exactly as E14-B/E14-C measured, and never reaches
its own nested 0.6B branch) used `benchmarks/tts_qwen3_0_6b_real_run.py` instead: a worker started
by hand (`SIM_TTS_QWEN3_MODEL=0.6B`), 20 real syntheses (2 speakers x 2 emotions x 5 sentences),
then the worker stopped and the saved WAVs run through real GigaAM sequentially (this task's brief,
item 3 — TTS and ASR together may not fit the free VRAM). `test_qwen3_tts_0_6b_contract_against_a_
live_worker` below is this task's brief item 5's own requirement — "make the Qwen3-TTS real test
pass against the running 0.6B worker" — a **separate**, narrower test that does not start a worker
itself (unlike the test above): it skips cleanly unless something is already listening on
`127.0.0.1:8112`, and was run for real, once, while this task's own hand-started 0.6B worker was up
(see this task's report for the pasted result); it never loads GigaAM (same VRAM-concurrency
reasoning as `benchmarks/tts_qwen3_0_6b_real_run.py`'s two-phase split).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

import httpx
import numpy as np
import pytest
from app.application.ports.tts import TtsVoiceSpec
from app.inference.asr.gigaam_provider import GigaAMProvider
from app.inference.tts.piper_tts import PiperTTS
from app.inference.tts.qwen3_tts import Qwen3TTS

from tests.models._skip import require_model_env
from tests.models.conftest import free_vram_mb
from tests.models.test_gigaam_provider import _word_error_rate

pytestmark = pytest.mark.requires_models

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ASR_MODEL_DIR = _REPO_ROOT / "models" / "gigaam-v3-e2e_ctc"
_DEFAULT_PIPER_VOICE_PATH = _REPO_ROOT / "models" / "piper" / "ru_RU-irina-medium.onnx"
_PIPER_VOICE_PATH = Path(os.environ.get("SIM_TTS_PIPER_VOICE_PATH", str(_DEFAULT_PIPER_VOICE_PATH)))
_QWEN3_MODEL_DIR = Path(os.environ.get("SIM_TTS_QWEN3_MODEL_DIR", "models/qwen3-tts"))
_QWEN3_0_6B_MODEL_DIR_ENV = os.environ.get("SIM_TTS_QWEN3_0_6B_MODEL_DIR")
_MIN_FREE_VRAM_MB = 4600
# A throwaway test port — never the real worker's 8112, never 8000/8001/8012/8016.
_QWEN3_PORT = 18112
_ASR_SAMPLE_RATE = 16_000

#: Five Russian dispatcher-style sentences — the same register `test_llama_cpp_contract.py` uses,
#: none of them a scenario value.
_SENTENCES: tuple[str, ...] = (
    "Служба сто двенадцать, что у вас случилось?",
    "Назовите, пожалуйста, точный адрес происшествия.",
    "Есть ли пострадавшие, нуждающиеся в помощи?",
    "Оставайтесь на линии, я направляю к вам бригаду.",
    "Повторите, пожалуйста, номер телефона ещё раз.",
)

_VOICE = TtsVoiceSpec(voice_id="", speaking_rate=1.0)


def _no_llama_server_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "llama-server"], capture_output=True, timeout=5, text=True
        )
    except (OSError, subprocess.SubprocessError):
        return True  # can't tell -> don't block on a guess either way; VRAM check is primary
    return result.returncode != 0


def _resample_linear(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """One-shot linear-interpolation resample for the ASR round trip only (test-local; the
    product's own `app.application.voice.resampler.Resampler` is a stateful streaming re-blocker
    built for `AudioFrame` chunks, not a one-shot whole-utterance helper, so it is not reused
    here)."""
    if src_rate == dst_rate or not pcm:
        return pcm
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    src_n = samples.shape[0]
    dst_n = max(1, round(src_n * dst_rate / src_rate))
    src_positions = np.arange(src_n)
    dst_positions = np.linspace(0, src_n - 1, dst_n)
    resampled = np.interp(dst_positions, src_positions, samples)
    return resampled.astype("<i2").tobytes()


def _rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    return float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0


async def _asr_round_trip(
    asr: GigaAMProvider, pcm: bytes, sample_rate: int, request_id: str
) -> tuple[str, float]:
    asr_pcm = _resample_linear(pcm, sample_rate, _ASR_SAMPLE_RATE)
    result = await asr.transcribe(asr_pcm, _ASR_SAMPLE_RATE, request_id=request_id)
    return result.text, result.audio_duration_ms


async def _measure_provider(
    provider, *, label: str, asr: GigaAMProvider | None
) -> list[dict[str, object]]:
    """Shared measurement loop for both providers: first-chunk latency, RTF, sample rate,
    non-silence, and (if `asr` is given) the ASR round trip + WER."""
    results: list[dict[str, object]] = []
    for index, sentence in enumerate(_SENTENCES):
        started = time.perf_counter()
        stream = provider.stream(sentence, _VOICE, request_id=f"{label}-{index}", max_chunk_ms=40)
        chunks = []
        first_chunk_latency_ms: float | None = None
        async for chunk in stream:
            if first_chunk_latency_ms is None:
                first_chunk_latency_ms = (time.perf_counter() - started) * 1000
            chunks.append(chunk)
        total_latency_ms = (time.perf_counter() - started) * 1000
        assert chunks, f"{label}: no audio produced for {sentence!r}"

        pcm = b"".join(c.frame.pcm for c in chunks)
        sample_rate = chunks[0].frame.sample_rate
        audio_ms = sum(c.audio_ms for c in chunks)
        rtf = (total_latency_ms / audio_ms) if audio_ms else None
        rms = _rms(pcm)
        assert rms > 50, f"{label}: synthesized audio for {sentence!r} looks silent (rms={rms})"

        row: dict[str, object] = {
            "provider": label,
            "sentence": sentence,
            "first_chunk_latency_ms": round(first_chunk_latency_ms or 0.0, 1),
            "total_latency_ms": round(total_latency_ms, 1),
            "sample_rate": sample_rate,
            "audio_ms": audio_ms,
            "rtf": round(rtf, 3) if rtf is not None else None,
            "rms": round(rms, 1),
        }
        if asr is not None:
            asr_text, _ = await _asr_round_trip(asr, pcm, sample_rate, f"{label}-asr-{index}")
            row["asr_text"] = asr_text
            row["wer"] = round(_word_error_rate(sentence, asr_text), 3)
        results.append(row)
    return results


# -- Piper (CPU) ---------------------------------------------------------------------------------


async def test_piper_contract_real_synthesis_and_asr_round_trip() -> None:
    require_model_env(packages=("piper",), paths=(_PIPER_VOICE_PATH,))
    require_model_env(packages=("torch", "transformers"), paths=(_ASR_MODEL_DIR,))
    import torch

    provider = PiperTTS(voice_path=str(_PIPER_VOICE_PATH))
    await provider.warm_up()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "float32"
    asr = GigaAMProvider(
        model_dir=str(_ASR_MODEL_DIR),
        model_version="v3_e2e_ctc",
        device=device,
        compute_type=compute_type,
    )
    await asr.warm_up()

    try:
        results = await _measure_provider(provider, label="piper", asr=asr)
        print("\n=== Piper TTS contract measurements (real synthesis + real GigaAM ASR) ===")
        for row in results:
            print(row)
        for row in results:
            assert float(row["wer"]) <= 0.6, f"Piper output unintelligible to GigaAM: {row}"
    finally:
        await provider.close()
        await asr.close()


# -- Qwen3-TTS (GPU, worker started by this test) ------------------------------------------------


def _start_qwen3_worker(model_dir: Path, *, log_path: Path) -> subprocess.Popen[bytes]:
    venv_python = _REPO_ROOT / "workers" / "tts_qwen3" / ".venv" / "bin" / "python"
    env = dict(os.environ)
    env["SIM_TTS_QWEN3_PORT"] = str(_QWEN3_PORT)
    env["SIM_TTS_QWEN3_MODEL_DIR"] = str(model_dir)
    log_file = log_path.open("wb")
    return subprocess.Popen(
        [str(venv_python), "-m", "tts_qwen3"],
        cwd=str(_REPO_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def _wait_for_worker_health(base_url: str, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    with httpx.Client(timeout=3.0) as client:
        while time.monotonic() < deadline:
            try:
                if client.get(f"{base_url}/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    raise TimeoutError(f"tts_qwen3 worker did not answer /health within {timeout_s}s")


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        process.kill()
        process.wait(timeout=15)


async def _run_qwen3_contract(
    model_dir: Path, *, label: str, tmp_path: Path, asr: GigaAMProvider
) -> list[dict[str, object]]:
    venv_python = _REPO_ROOT / "workers" / "tts_qwen3" / ".venv" / "bin" / "python"
    venv_python_exists = await asyncio.to_thread(venv_python.is_file)
    if not venv_python_exists:
        pytest.skip(
            f"NOT_RUN: {venv_python} does not exist — run `make deps-tts-qwen3` first "
            "(this task's brief, item 1: the worker's own venv)"
        )
    model_dir_exists = await asyncio.to_thread(model_dir.exists)
    if not model_dir_exists:
        pytest.skip(
            f"NOT_RUN: Qwen3-TTS model dir missing: {model_dir} — run `make models-tts-qwen3`"
        )

    process = _start_qwen3_worker(model_dir, log_path=tmp_path / f"{label}.log")
    base_url = f"http://127.0.0.1:{_QWEN3_PORT}"
    try:
        _wait_for_worker_health(base_url, timeout_s=180.0)
        tts = Qwen3TTS(base_url=base_url, speaker="Serena", timeout_ms=30_000)
        try:
            results = await _measure_provider(tts, label=label, asr=asr)
        finally:
            await tts.close()
        return results
    finally:
        _terminate(process)
        assert process.poll() is not None, f"{label}: worker process {process.pid} did not exit"


async def test_qwen3_tts_contract_real_synthesis_and_asr_round_trip(tmp_path: Path) -> None:
    require_model_env(packages=("torch", "transformers"), paths=(_ASR_MODEL_DIR,))

    if not _no_llama_server_running():
        pytest.skip(
            "NOT_RUN: a llama-server process is already running — refusing to also load Qwen3-TTS"
        )
    free_mb = free_vram_mb()
    if free_mb is None or free_mb < _MIN_FREE_VRAM_MB:
        pytest.skip(
            f"NOT_RUN: free VRAM {free_mb} MB < required {_MIN_FREE_VRAM_MB} MB "
            "(Qwen3-TTS-1.7B-CustomVoice measures ~4.3 GB bf16 resident, recon §1.1)"
        )

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "float32"
    asr = GigaAMProvider(
        model_dir=str(_ASR_MODEL_DIR),
        model_version="v3_e2e_ctc",
        device=device,
        compute_type=compute_type,
    )
    await asr.warm_up()
    try:
        results = await _run_qwen3_contract(
            _QWEN3_MODEL_DIR, label="qwen3-tts-1.7b", tmp_path=tmp_path, asr=asr
        )
        print("\n=== Qwen3-TTS (1.7B CustomVoice, owner-pinned) contract measurements ===")
        for row in results:
            print(row)

        if _QWEN3_0_6B_MODEL_DIR_ENV:
            zero_six_b_dir = Path(_QWEN3_0_6B_MODEL_DIR_ENV)
            free_mb_now = free_vram_mb()
            if free_mb_now is not None and free_mb_now >= 2000:
                results_06b = await _run_qwen3_contract(
                    zero_six_b_dir, label="qwen3-tts-0.6b", tmp_path=tmp_path, asr=asr
                )
                print(
                    "\n=== Qwen3-TTS 0.6B CustomVoice (THIS TASK'S OWN measurement, "
                    "NOT the owner's — the owner evaluated only the 1.7B checkpoint) ==="
                )
                for row in results_06b:
                    print(row)
            else:
                print(f"\nNOT_RUN: 0.6B experiment skipped, free VRAM {free_mb_now} MB too low")
    finally:
        await asr.close()


# -- Qwen3-TTS against an already-running worker (E14-D, this task's brief, item 5) --------------

_QWEN3_LIVE_BASE_URL = "http://127.0.0.1:8112"


async def test_qwen3_tts_0_6b_contract_against_a_live_worker() -> None:
    """Does **not** start a `tts_qwen3` worker itself (unlike the test above) — it drives the real
    `Qwen3TTS` adapter against whatever is already listening on `127.0.0.1:8112`, the real port
    (never the throwaway `_QWEN3_PORT` the self-starting test above uses). This task's brief, item
    5, in its own words: "make the Qwen3-TTS real test ... pass against the running 0.6B worker;
    run it once for real while your worker is up and paste the result" — this is that test.

    Skips cleanly (`pytest.skip`, never a failure) if nothing answers `/health` on 8112 — the
    common case for `make test-models`, since no fixture here starts a worker. No GigaAM round
    trip: loading GigaAM and the `tts_qwen3` worker on GPU at the same time is exactly what this
    task's brief, item 3, says "may not fit the free VRAM" for the manual real run, and the same
    physical constraint applies here; the real GigaAM/WER measurement lives in
    `benchmarks/tts_qwen3_0_6b_real_run.py`'s sequential two-phase run instead (this task's report
    has its pasted results).
    """
    require_model_env()
    try:
        async with httpx.AsyncClient(timeout=3.0) as probe:
            response = await probe.get(f"{_QWEN3_LIVE_BASE_URL}/health")
    except httpx.HTTPError:
        pytest.skip(f"NOT_RUN: no tts_qwen3 worker reachable on {_QWEN3_LIVE_BASE_URL}")
        return
    if response.status_code != 200:
        pytest.skip(
            f"NOT_RUN: tts_qwen3 worker at {_QWEN3_LIVE_BASE_URL} answered "
            f"HTTP {response.status_code}, not healthy"
        )
        return
    health = response.json()

    tts = Qwen3TTS(base_url=_QWEN3_LIVE_BASE_URL, speaker="Serena", timeout_ms=30_000)
    try:
        results = await _measure_provider(tts, label="qwen3-tts-live-worker", asr=None)
        print(f"\n=== Qwen3-TTS live-worker contract measurements (worker /health: {health}) ===")
        for row in results:
            print(row)
    finally:
        await tts.close()

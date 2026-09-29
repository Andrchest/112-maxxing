"""`python -m app.cli preflight [--profile NAME] [--json] [--skip-audio-devices]` (SPEC §38, HLD
`60-inference-ops.md` §5, R7).

Twelve checks, each `PASS`/`FAIL`/`SKIP` with a one-line detail. **No ML model is ever loaded**:
every check either probes a running process over the network (LLM/ASR/TTS/PostgreSQL/Redis/
LiveKit), reads a file's existence/size, queries the GPU driver, or reuses the gate's own scenario
loader — the same posture `make gate` needs to stay fast and fake-provider-only (D13).

Every check is a small pure function over an **injected probe callable** (`QueryGpus`, `ProbeLlm`,
...): the function itself contains only the PASS/FAIL/SKIP *decision*, and the probe supplies the
one fact from the outside world the decision needs. That split is what gives each check both a
`PASS` and a `FAIL` unit test with fakes (`backend/tests/unit/cli/test_preflight.py`) without a
real GPU, model server, database or LiveKit instance anywhere near the test run. `build_real_checks`
below is the only place the real, network-touching implementations live; `main()` is the only place
that constructs them.

Checks 1-11 are `docs/hld/60-inference-ops.md` §5's table, verbatim order. Check 12
(`llama_server_binary`) is additive (this task's ruling R7): the Qwen3.5 GGUFs this profile uses
need a newer llama.cpp than the one already on this machine (`~/.local/share/llama.cpp`), so a
binary-version probe is the only thing preflight can assert without loading the model — the real
proof that the pinned binary can load *this* GGUF is check 4's "model id contains `llm.model_name`"
once the server is actually up.

Exit codes (HLD 60 §5): **0** every non-skipped check passed; **1** at least one `FAIL`; **2** the
preflight itself could not run (bad settings, a refused profile). A `SKIP` never changes the exit
code.
"""

from __future__ import annotations

import argparse
import asyncio
import json as json_module
import os
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from app.config.model_paths import CONTAINER_MODELS_PREFIX, host_model_path
from app.config.profile import ModelProfile, load_profile
from app.config.settings import Settings
from app.domain.common.errors import ScenarioValidationError
from app.infrastructure.scenarios.yaml_loader import discover, load_scenario_version
from app.infrastructure.transport.livekit_transport_status import http_origin_of

__all__ = [
    "CheckResult",
    "GpuInfo",
    "PreflightReport",
    "Status",
    "build_real_checks",
    "check_asr_responds",
    "check_audio_devices",
    "check_cuda_gpu_available",
    "check_expected_gpu_detected",
    "check_livekit_responds",
    "check_llama_server_binary",
    "check_llm_responds",
    "check_model_files_exist",
    "check_postgresql_responds",
    "check_redis_responds",
    "check_scenario_validation",
    "check_tts_responds",
    "has_cyrillic_word",
    "main",
    "profile_requires_gpu",
    "render_json",
    "render_table",
    "run_preflight",
]

Status = Literal["PASS", "FAIL", "SKIP"]

#: `SIM_VOICE_AGENT_HTTP_PORT` default (this task's ruling; loopback only, E18-C's endpoints).
DEFAULT_VOICE_AGENT_HTTP_PORT = 8113
_DEFAULT_SCENARIOS_DIR = Path("scenarios/examples")

#: The default `SIM_MODELS_ROOT`: `/models`, i.e. the container layout the profiles name, so the
#: resolution below is the identity under compose (E20 R15).
CONTAINER_MODELS_ROOT = CONTAINER_MODELS_PREFIX.rstrip("/")
_PROBE_TIMEOUT_S = 10.0


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One row of the preflight table."""

    number: int
    name: str
    status: Status
    detail: str


@dataclass(frozen=True, slots=True)
class GpuInfo:
    """One GPU as the driver reports it — from `pynvml` or the `nvidia-smi` CSV fallback."""

    name: str
    total_mb: int
    free_mb: int


@dataclass(frozen=True, slots=True)
class PreflightReport:
    profile_name: str
    checks: tuple[CheckResult, ...]

    @property
    def exit_code(self) -> int:
        """0 = all non-skipped PASS; 1 = at least one FAIL. A SKIP changes neither."""
        return 1 if any(check.status == "FAIL" for check in self.checks) else 0


# -- injected probe shapes ------------------------------------------------------------------------
# Each is the one fact a check needs from the outside world; every real implementation lives in the
# "real probes" section below, and every test supplies a fake of the same shape instead.

QueryGpus = Callable[[], Sequence[GpuInfo]]
StatFile = Callable[[Path], int | None]
#: (ok, detail) — for LLM, `detail` is the model id string on success.
BoolProbe = Callable[[], Awaitable[tuple[bool, str]]]
#: (ok, output_audio_ms, detail) — TTS is the one probe with a numeric PASS condition of its own.
TtsProbe = Callable[[], Awaitable[tuple[bool, int, str]]]
#: "are this profile's models already resident on the card?" — E20-G/G7's stack-aware check #2.
ModelsLoadedProbe = Callable[[], Awaitable[tuple[bool, str]]]
QueryAudioDevices = Callable[[], Sequence[str]]
IsFile = Callable[[str], bool]
IsExecutable = Callable[[str], bool]
RunVersion = Callable[[str], int]


# ---------------------------------------------------------------------------------------------
# The twelve checks — pure decisions over an injected probe
# ---------------------------------------------------------------------------------------------


#: I7 E52 (ТЗ ¶171-176; Q&A «в основном это будут все функции работы на центральном процессоре»):
#: a profile like `CPU.yaml` configures every component off the GPU, so checks #1/#2 below have
#: nothing to probe and must not FAIL a machine that correctly has no NVIDIA GPU at all.
_CUDA_DEVICE = "cuda"
NOT_REQUIRED_BY_PROFILE_DETAIL = "не требуется профилем"


def profile_requires_gpu(profile: ModelProfile) -> bool:
    """True when `profile` configures at least one component to run on a CUDA device.

    The LLM offloads layers to the GPU (`llm.n_gpu_layers != 0`) or any of ASR/TTS/VAD names
    `device: cuda`. A profile where none of these hold (`CPU.yaml`) needs no GPU at all, so
    `check_cuda_gpu_available`/`check_expected_gpu_detected` PASS outright for it instead of
    FAILing a machine that has none — HLD 60 §5's checks are about THIS profile's requirements,
    not about whether a GPU happens to be in the box.
    """
    if profile.llm.n_gpu_layers != 0:
        return True
    return _CUDA_DEVICE in (profile.asr.device, profile.tts.device, profile.vad.device)


async def check_cuda_gpu_available(
    query_gpus: QueryGpus, profile: ModelProfile | None = None
) -> CheckResult:
    """#1: at least one CUDA GPU is visible to the driver — unless `profile` needs none at all."""
    if profile is not None and not profile_requires_gpu(profile):
        return CheckResult(1, "cuda_gpu_available", "PASS", NOT_REQUIRED_BY_PROFILE_DETAIL)
    try:
        gpus = query_gpus()
    except Exception as exc:
        return CheckResult(1, "cuda_gpu_available", "FAIL", f"GPU query failed: {exc}")
    if not gpus:
        return CheckResult(1, "cuda_gpu_available", "FAIL", "no CUDA GPU detected")
    names = ", ".join(gpu.name for gpu in gpus)
    return CheckResult(1, "cuda_gpu_available", "PASS", f"{len(gpus)} GPU(s): {names}")


async def check_expected_gpu_detected(
    query_gpus: QueryGpus,
    profile: ModelProfile,
    models_loaded: ModelsLoadedProbe | None = None,
) -> CheckResult:
    """#2: a GPU whose name matches the profile, with enough free VRAM — STACK-AWARE (E20-G/G7).

    The pre-start rule is "the whole `vram_budget_mb + min_vram_margin_mb` must be FREE". That is
    the right rule before anything is loaded, and precisely the wrong one afterwards: E20-C's §46
    walk ran `make preflight` against a fully healthy, fully warmed stack and check #2 FAILed
    (`2341 MB free < 7680 MB required`) *because* the models it is checking for were resident.
    SPEC §38's preflight is the thing an operator runs before a session, warm stack included, so a
    check that can only pass on a cold card is a check that is red on a healthy machine.

    So: when `models_loaded` reports the voice agent's models are up, the profile's own remaining
    allowance is what must still be free — `vram_budget_mb - measured_peak_vram_mb`, the headroom
    the profile itself says the loaded stack leaves over. The detail then says "models loaded" so
    nobody mistakes the looser bound for the pre-start one. A profile with no
    `measured_peak_vram_mb` (nothing measured yet) keeps the pre-start rule: an unmeasured profile
    has no remaining allowance to claim.

    I7 E52: a profile that needs no GPU at all (`profile_requires_gpu` false, e.g. `CPU.yaml`)
    PASSes outright, same reasoning as check #1 — this check is never reached for such a profile.
    """
    if not profile_requires_gpu(profile):
        return CheckResult(2, "expected_gpu_detected", "PASS", NOT_REQUIRED_BY_PROFILE_DETAIL)
    try:
        gpus = query_gpus()
    except Exception as exc:
        return CheckResult(2, "expected_gpu_detected", "FAIL", f"GPU query failed: {exc}")
    needle = profile.hardware.gpu_name_contains.lower()
    matched = [gpu for gpu in gpus if needle in gpu.name.lower()]
    if not matched:
        found = ", ".join(gpu.name for gpu in gpus) or "none"
        return CheckResult(
            2,
            "expected_gpu_detected",
            "FAIL",
            f"no GPU name contains {profile.hardware.gpu_name_contains!r} (found: {found})",
        )
    measured_peak_mb = profile.measured_peak_vram_mb
    loaded = False
    loaded_detail = ""
    if models_loaded is not None and measured_peak_mb is not None:
        try:
            loaded, loaded_detail = await models_loaded()
        except Exception:  # a probe that cannot answer means "assume cold", never a crash
            loaded, loaded_detail = False, ""
    if loaded and measured_peak_mb is not None:
        required_mb = max(0, profile.vram_budget_mb - measured_peak_mb)
        rule = (
            f"models loaded ({loaded_detail}): vram_budget_mb {profile.vram_budget_mb} - "
            f"measured_peak_vram_mb {measured_peak_mb}"
        )
    else:
        required_mb = profile.vram_budget_mb + profile.min_vram_margin_mb
        rule = (
            f"vram_budget_mb {profile.vram_budget_mb} + "
            f"min_vram_margin_mb {profile.min_vram_margin_mb}"
        )
    best = max(matched, key=lambda gpu: gpu.free_mb)
    if best.free_mb < required_mb:
        return CheckResult(
            2,
            "expected_gpu_detected",
            "FAIL",
            f"{best.name}: {best.free_mb} MB free < {required_mb} MB required ({rule})",
        )
    return CheckResult(
        2,
        "expected_gpu_detected",
        "PASS",
        f"{best.name}: {best.free_mb} MB free >= {required_mb} MB required ({rule})",
    )


def profile_model_file_paths(
    profile: ModelProfile, models_root: str = CONTAINER_MODELS_ROOT
) -> dict[str, str]:
    """The five paths check #3 verifies — the model weights plus the warm-up sample (§4.2).

    Resolved onto **this host** through `app.config.model_paths` (E20 R15). A profile names
    container paths (`/models/...`), which is where compose mounts them; on a host run the same
    files live under `SIM_MODELS_ROOT` (`./models`) and nothing is at `/models`, so before E20 this
    check FAILed on every host run no matter what was installed. `models_root` defaults to
    `/models`, which leaves the mapping a no-op under compose.
    """
    return {
        label: host_model_path(raw, models_root)
        for label, raw in (
            ("llm.model_path", profile.llm.model_path),
            ("asr.model_path", profile.asr.model_path),
            ("tts.model_path", profile.tts.model_path),
            ("vad.model_path", profile.vad.model_path),
            ("warmup.asr_sample_path", profile.warmup.asr_sample_path),
        )
    }


async def check_model_files_exist(
    profile: ModelProfile, stat_file: StatFile, models_root: str = CONTAINER_MODELS_ROOT
) -> CheckResult:
    """#3: every model/warm-up-sample path exists and is non-empty, as resolved on this host."""
    paths = profile_model_file_paths(profile, models_root)
    missing = []
    for label, raw_path in paths.items():
        try:
            size = stat_file(Path(raw_path))
        except OSError as exc:
            size = None
            missing.append(f"{label}={raw_path} ({exc})")
            continue
        if size is None or size <= 0:
            missing.append(f"{label}={raw_path}")
    if missing:
        return CheckResult(
            3, "model_files_exist", "FAIL", "missing or empty: " + "; ".join(missing)
        )
    return CheckResult(3, "model_files_exist", "PASS", f"{len(paths)} file(s) present")


async def check_llm_responds(probe: BoolProbe, model_name: str) -> CheckResult:
    """#4: `GET /models` then a 4-token completion; the model id must name the profile's LLM."""
    try:
        ok, detail = await probe()
    except Exception as exc:
        return CheckResult(4, "llm_responds", "FAIL", f"LLM probe raised: {exc}")
    if not ok:
        return CheckResult(4, "llm_responds", "FAIL", detail)
    if model_name not in detail:
        return CheckResult(
            4, "llm_responds", "FAIL", f"model id {detail!r} does not contain {model_name!r}"
        )
    return CheckResult(4, "llm_responds", "PASS", detail)


def has_cyrillic_word(text: str) -> bool:
    """At least one run of Cyrillic letters (E20-G/G7's bar for check #5).

    Cyrillic by code point, not a word list: the warm-up sample says one short Russian phrase and
    the ASR is free to mis-hear it — "the ASR produced Russian words" is the claim, not "it
    produced these words".
    """
    run = 0
    for char in text:
        if "\u0400" <= char <= "\u04ff":
            run += 1
            if run >= 2:
                return True
        else:
            run = 0
    return False


async def check_asr_responds(probe: BoolProbe) -> CheckResult:
    """#5: the voice-agent's `GET /preflight/asr` transcribes REAL RUSSIAN SPEECH (E20-G/G7).

    "Non-empty text" was the old bar, and it made the check a liar in both directions. E20-C's
    §46 walk ran it against a demonstrably working GigaAM (every trainee turn of the walk was
    transcribed correctly) and got `[FAIL] 5. asr_responds: empty transcription` — because
    `.env.example` left `SIM_ASR_WARMUP_SAMPLE_PATH` empty, so the agent warms on a SYNTHESISED
    440 Hz TONE, and a tone correctly transcribes to nothing. The check was measuring the
    fixture, not the model.

    The bar is now "at least one Cyrillic word came back", and `.env.example` points
    `SIM_ASR_WARMUP_SAMPLE_PATH` at `models/warmup/warmup_ru.wav` (real Russian speech, E19-F) —
    the same file every model profile's `warmup.asr_sample_path` already names. A tone now fails
    with a detail that says WHY, instead of an unexplained "empty transcription".
    """
    try:
        ok, detail = await probe()
    except Exception as exc:
        return CheckResult(5, "asr_responds", "FAIL", f"ASR probe raised: {exc}")
    if not ok:
        return CheckResult(5, "asr_responds", "FAIL", detail)
    if not has_cyrillic_word(detail):
        return CheckResult(
            5,
            "asr_responds",
            "FAIL",
            f"transcription has no Cyrillic word ({detail!r}) — is "
            "SIM_ASR_WARMUP_SAMPLE_PATH pointing at real Russian speech "
            "(models/warmup/warmup_ru.wav)?",
        )
    return CheckResult(5, "asr_responds", "PASS", detail)


async def check_tts_responds(probe: TtsProbe) -> CheckResult:
    """#6: the voice-agent's `GET /preflight/tts` returns `output_audio_ms > 0`."""
    try:
        ok, output_audio_ms, detail = await probe()
    except Exception as exc:
        return CheckResult(6, "tts_responds", "FAIL", f"TTS probe raised: {exc}")
    if not ok:
        return CheckResult(6, "tts_responds", "FAIL", detail)
    if output_audio_ms <= 0:
        return CheckResult(
            6, "tts_responds", "FAIL", f"output_audio_ms={output_audio_ms} (must be > 0)"
        )
    return CheckResult(6, "tts_responds", "PASS", f"{output_audio_ms} ms of audio ({detail})")


async def check_postgresql_responds(probe: BoolProbe) -> CheckResult:
    """#7: `SELECT 1` plus `alembic_version` names exactly one head."""
    try:
        ok, detail = await probe()
    except Exception as exc:
        return CheckResult(7, "postgresql_responds", "FAIL", f"PostgreSQL probe raised: {exc}")
    return CheckResult(7, "postgresql_responds", "PASS" if ok else "FAIL", detail)


async def check_redis_responds(probe: BoolProbe) -> CheckResult:
    """#8: `PING` plus a `SET`/`GET`/`DEL` round trip on `preflight:probe`."""
    try:
        ok, detail = await probe()
    except Exception as exc:
        return CheckResult(8, "redis_responds", "FAIL", f"Redis probe raised: {exc}")
    return CheckResult(8, "redis_responds", "PASS" if ok else "FAIL", detail)


async def check_livekit_responds(probe: BoolProbe) -> CheckResult:
    """#9: the LiveKit origin answers HTTP within the timeout.

    HLD gap (see this task's report): §5's table also asks for a `livekit-api ListRooms` call,
    which needs the `livekit-api` SDK — not a dependency of this repo (grepped; only the manual
    JWT issuer at `container.py` uses the LiveKit credentials today). This reuses the same
    HTTP-reachability reading `LiveKitHealthProbe` (`/health/ready`'s `livekit` component,
    E7/E11) already uses rather than inventing a new dependency.
    """
    try:
        ok, detail = await probe()
    except Exception as exc:
        return CheckResult(9, "livekit_responds", "FAIL", f"LiveKit probe raised: {exc}")
    return CheckResult(9, "livekit_responds", "PASS" if ok else "FAIL", detail)


async def check_scenario_validation(
    scenarios_dir: Path,
    *,
    discover_files: Callable[[Path], Sequence[Path]] = discover,
    load_version: Callable[[Path], object] = load_scenario_version,
) -> CheckResult:
    """#10: every `<slug>/v<N>.yaml` under `scenarios_dir` validates — the gate's own loader."""
    files = discover_files(scenarios_dir)
    if not files:
        return CheckResult(
            10, "scenario_validation", "FAIL", f"no scenario file found under {scenarios_dir}"
        )
    failures: list[str] = []
    for path in files:
        try:
            load_version(path)
        except ScenarioValidationError as exc:
            failures.append(f"{path}: {'; '.join(exc.violations)}")
    if failures:
        return CheckResult(10, "scenario_validation", "FAIL", "; ".join(failures))
    return CheckResult(10, "scenario_validation", "PASS", f"{len(files)} scenario file(s) valid")


async def check_audio_devices(
    *,
    skip_audio_devices: bool,
    audio_device_check_enabled: bool,
    query_devices: QueryAudioDevices,
) -> CheckResult:
    """#11: `sounddevice.query_devices()` opens — SKIP (never FAIL) when it does not, per HLD 60
    §5's "device opens, else SKIP": a demo box with no configured microphone is not a preflight
    failure, only `--skip-audio-devices` / `AUDIO_DEVICE_CHECK` are what a real *absence* of the
    check looks like."""
    if skip_audio_devices or not audio_device_check_enabled:
        return CheckResult(
            11,
            "audio_devices_accessible",
            "SKIP",
            "skipped (--skip-audio-devices or AUDIO_DEVICE_CHECK != true)",
        )
    try:
        devices = query_devices()
    except Exception as exc:
        return CheckResult(
            11, "audio_devices_accessible", "SKIP", f"no audio device accessible: {exc}"
        )
    if not devices:
        return CheckResult(11, "audio_devices_accessible", "SKIP", "no audio device found")
    return CheckResult(11, "audio_devices_accessible", "PASS", f"{len(devices)} device(s) found")


async def check_llama_server_binary(
    *,
    bin_path: str | None,
    is_file: IsFile,
    is_executable: IsExecutable,
    run_version: RunVersion,
) -> CheckResult:
    """#12 (additive, R7): `SIM_LLAMA_SERVER_BIN` exists, is executable, and `--version` exits 0.

    SKIP when the var is unset: the Qwen3.5 GGUFs this profile uses need a newer llama.cpp than
    the one already on this machine, so this check cannot assume a pinned binary is configured yet
    — check #4 is the real proof once the server is actually up.
    """
    if not bin_path:
        return CheckResult(12, "llama_server_binary", "SKIP", "SIM_LLAMA_SERVER_BIN is not set")
    if not is_file(bin_path):
        return CheckResult(12, "llama_server_binary", "FAIL", f"{bin_path} does not exist")
    if not is_executable(bin_path):
        return CheckResult(12, "llama_server_binary", "FAIL", f"{bin_path} is not executable")
    try:
        code = run_version(bin_path)
    except Exception as exc:
        return CheckResult(12, "llama_server_binary", "FAIL", f"--version raised: {exc}")
    if code != 0:
        return CheckResult(12, "llama_server_binary", "FAIL", f"--version exited {code}")
    return CheckResult(12, "llama_server_binary", "PASS", f"{bin_path} --version exited 0")


# ---------------------------------------------------------------------------------------------
# Orchestration + rendering
# ---------------------------------------------------------------------------------------------


async def run_preflight(
    checks: Sequence[Callable[[], Awaitable[CheckResult]]], *, profile_name: str
) -> PreflightReport:
    """Run every check in order (HLD 60 §5's numbering) and assemble the report."""
    results = [await check() for check in checks]
    return PreflightReport(profile_name=profile_name, checks=tuple(results))


def render_table(report: PreflightReport) -> str:
    lines = [f"preflight — profile {report.profile_name}"]
    for check in report.checks:
        lines.append(f"[{check.status:4}] {check.number:2}. {check.name}: {check.detail}")
    lines.append(f"exit code: {report.exit_code}")
    return "\n".join(lines)


def render_json(report: PreflightReport) -> str:
    return json_module.dumps(
        {
            "profile": report.profile_name,
            "checks": [
                {
                    "number": check.number,
                    "name": check.name,
                    "status": check.status,
                    "detail": check.detail,
                }
                for check in report.checks
            ],
            "exit_code": report.exit_code,
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------------------------
# Real probes — the only place this module touches a network, a driver or a subprocess
# ---------------------------------------------------------------------------------------------


def _query_gpus_real() -> list[GpuInfo]:
    try:
        import pynvml  # type: ignore[import-untyped]

        pynvml.nvmlInit()
        try:
            gpus = []
            for index in range(pynvml.nvmlDeviceGetCount()):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode()
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                gpus.append(
                    GpuInfo(
                        name=name,
                        total_mb=int(memory.total // (1024 * 1024)),
                        free_mb=int(memory.free // (1024 * 1024)),
                    )
                )
            return gpus
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return _query_gpus_nvidia_smi()


def _query_gpus_nvidia_smi() -> list[GpuInfo]:
    binary = shutil.which("nvidia-smi")
    if binary is None:
        return []
    result = subprocess.run(
        [binary, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return []
    gpus = []
    for line in result.stdout.strip().splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        name, total, free = parts
        try:
            gpus.append(GpuInfo(name=name, total_mb=int(total), free_mb=int(free)))
        except ValueError:
            continue
    return gpus


def _stat_file_real(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


async def _probe_llm_real(base_url: str) -> tuple[bool, str]:
    root = base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            models_response = await client.get(f"{root}/models")
            if models_response.status_code != 200:
                return False, f"GET /models -> {models_response.status_code}"
            body = models_response.json()
            data = body.get("data") if isinstance(body, dict) else None
            model_id = str(data[0].get("id", "")) if data else ""
            completion = await client.post(
                f"{root}/chat/completions",
                json={
                    "model": model_id or "default",
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 4,
                },
            )
            if completion.status_code != 200:
                return False, f"POST /chat/completions -> {completion.status_code}"
            return True, model_id
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def _probe_voice_agent_asr_real(port: int) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            response = await client.get(f"http://127.0.0.1:{port}/preflight/asr")
        if response.status_code != 200:
            return False, f"GET /preflight/asr -> {response.status_code}"
        text = str(response.json().get("text", ""))
        if not text:
            return False, "empty transcription"
        return True, text
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def _probe_models_loaded_real(port: int) -> tuple[bool, str]:
    """ "Are the voice agent's models resident?" for the stack-aware check #2 (E20-G/G7).

    Derived from the two endpoints the agent already serves rather than from a new one: both
    `GET /preflight/asr` and `GET /preflight/tts` run the **already loaded** provider and answer
    500 when it was never warmed (`voice_agent.main.VoiceAgent._probe_asr`/`_probe_tts` raise
    `RuntimeError` on a `None` provider), so two 200s is exactly "this process has its models up".
    Any other outcome — nothing listening, a timeout, a 500 — means "assume cold", which keeps the
    stricter pre-start rule.
    """
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            for path in ("/preflight/asr", "/preflight/tts"):
                response = await client.get(f"http://127.0.0.1:{port}{path}")
                if response.status_code != 200:
                    return False, f"GET {path} -> {response.status_code}"
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, f"voice-agent :{port} ASR+TTS ready"


async def _probe_voice_agent_tts_real(port: int) -> tuple[bool, int, str]:
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            response = await client.get(f"http://127.0.0.1:{port}/preflight/tts")
        if response.status_code != 200:
            return False, 0, f"GET /preflight/tts -> {response.status_code}"
        body = response.json()
        return True, int(body.get("output_audio_ms", 0)), "ok"
    except httpx.HTTPError as exc:
        return False, 0, f"{type(exc).__name__}: {exc}"


async def _probe_postgresql_real(database_url: str) -> tuple[bool, str]:
    from sqlalchemy import text as sql_text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(sql_text("SELECT 1"))
            heads = (
                await connection.execute(sql_text("SELECT count(*) FROM alembic_version"))
            ).scalar_one()
        if heads != 1:
            return False, f"alembic_version has {heads} row(s), expected exactly one head"
        return True, "SELECT 1 ok; exactly one alembic head"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        await engine.dispose()


async def _probe_redis_real(redis_url: str) -> tuple[bool, str]:
    import redis.asyncio as redis_asyncio

    client = redis_asyncio.from_url(redis_url, decode_responses=True)
    try:
        if not await client.ping():
            return False, "PING did not return truthy"
        await client.set("preflight:probe", "1", ex=5)
        value = await client.get("preflight:probe")
        await client.delete("preflight:probe")
        if value != "1":
            return False, f"SET/GET round trip failed: got {value!r}"
        return True, "PING ok; SET/GET/DEL ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        await client.aclose()


async def _probe_livekit_real(livekit_url: str) -> tuple[bool, str]:
    origin = http_origin_of(livekit_url)
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            response = await client.get(origin)
        return True, f"GET {origin} -> {response.status_code}"
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _query_audio_devices_real() -> list[str]:
    import sounddevice as sd  # type: ignore[import-untyped]

    return [str(device.get("name", "")) for device in sd.query_devices()]


def _run_llama_server_version_real(bin_path: str) -> int:
    result = subprocess.run([bin_path, "--version"], capture_output=True, timeout=10, check=False)
    return result.returncode


def build_real_checks(
    profile: ModelProfile, settings: Settings, *, skip_audio_devices: bool
) -> list[Callable[[], Awaitable[CheckResult]]]:
    """The twelve checks wired to their real, network-touching probes (`main()`'s only caller)."""
    voice_agent_port = int(
        os.environ.get("SIM_VOICE_AGENT_HTTP_PORT", str(DEFAULT_VOICE_AGENT_HTTP_PORT))
    )
    llama_bin = os.environ.get("SIM_LLAMA_SERVER_BIN")
    audio_check_enabled = os.environ.get("AUDIO_DEVICE_CHECK", "").strip().lower() == "true"

    return [
        lambda: check_cuda_gpu_available(_query_gpus_real, profile),
        lambda: check_expected_gpu_detected(
            _query_gpus_real,
            profile,
            lambda: _probe_models_loaded_real(voice_agent_port),
        ),
        lambda: check_model_files_exist(profile, _stat_file_real, settings.models_root),
        # E20-G/G7: the EFFECTIVE base url (`Settings`, i.e. the env overlay), never the profile
        # literal. A profile names the COMPOSE url (`http://llama-server:8080/v1`); on a host run
        # `SIM_LLM_BASE_URL` points at `http://127.0.0.1:8101/v1` and the profile literal cannot
        # even be resolved — E20-C's walk got `[FAIL] 4. llm_responds: ConnectError: [Errno -3]
        # Temporary failure in name resolution` against a llama-server that was answering fine.
        # `apply_profile` has already overlaid the profile onto `Settings` where the operator did
        # not set the variable, so this is the profile value whenever there is no override.
        lambda: check_llm_responds(
            lambda: _probe_llm_real(settings.llm_base_url), profile.llm.model_name
        ),
        lambda: check_asr_responds(lambda: _probe_voice_agent_asr_real(voice_agent_port)),
        lambda: check_tts_responds(lambda: _probe_voice_agent_tts_real(voice_agent_port)),
        lambda: check_postgresql_responds(lambda: _probe_postgresql_real(settings.database_url)),
        lambda: check_redis_responds(lambda: _probe_redis_real(settings.redis_url)),
        lambda: check_livekit_responds(lambda: _probe_livekit_real(settings.livekit_url)),
        lambda: check_scenario_validation(_DEFAULT_SCENARIOS_DIR),
        lambda: check_audio_devices(
            skip_audio_devices=skip_audio_devices,
            audio_device_check_enabled=audio_check_enabled,
            query_devices=_query_audio_devices_real,
        ),
        lambda: check_llama_server_binary(
            bin_path=llama_bin,
            is_file=lambda p: Path(p).is_file(),
            is_executable=lambda p: os.access(p, os.X_OK),
            run_version=_run_llama_server_version_real,
        ),
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli preflight", description="SPEC §38 preflight (HLD 60 §5)"
    )
    parser.add_argument(
        "--profile", default=None, help="profile name (default: SIM_MODEL_PROFILE / Settings)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    parser.add_argument(
        "--skip-audio-devices", action="store_true", help="skip check #11 unconditionally"
    )
    args = parser.parse_args(argv)

    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as exc:
        print(f"preflight could not start: invalid settings: {exc}", file=sys.stderr)
        return 2

    profile_name = args.profile or settings.model_profile
    try:
        profile = load_profile(profile_name)
    except Exception as exc:
        print(f"preflight could not start: {exc}", file=sys.stderr)
        return 2

    checks = build_real_checks(profile, settings, skip_audio_devices=args.skip_audio_devices)
    report = asyncio.run(run_preflight(checks, profile_name=profile_name))

    print(render_json(report) if args.json else render_table(report))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

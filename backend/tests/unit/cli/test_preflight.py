"""`app.cli.preflight` — one PASS and one FAIL unit test per check, with fakes (R7).

Every check is exercised through its injected probe only: no GPU, model server, database, Redis,
LiveKit or audio device is ever touched. `DEV_3060TI` is loaded for real (`load_profile`) so the
fixture is the actual shipped profile rather than a hand-rolled stand-in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.cli.preflight import (
    NOT_REQUIRED_BY_PROFILE_DETAIL,
    CheckResult,
    GpuInfo,
    PreflightReport,
    check_asr_responds,
    check_audio_devices,
    check_cuda_gpu_available,
    check_expected_gpu_detected,
    check_livekit_responds,
    check_llama_server_binary,
    check_llm_responds,
    check_model_files_exist,
    check_postgresql_responds,
    check_redis_responds,
    check_scenario_validation,
    check_tts_responds,
    has_cyrillic_word,
    profile_model_file_paths,
    profile_requires_gpu,
    render_json,
    render_table,
)
from app.config.profile import ModelProfile, load_profile
from app.config.settings import Settings
from app.domain.common.errors import ScenarioValidationError


@pytest.fixture
def profile() -> ModelProfile:
    return load_profile("DEV_3060TI")


@pytest.fixture
def cpu_profile() -> ModelProfile:
    """I7 E52: `CPU.yaml` — every component runs off the GPU (ТЗ ¶171-176)."""
    return load_profile("CPU")


# -- #1 cuda_gpu_available ------------------------------------------------------------------------


async def test_cuda_gpu_available_passes_with_at_least_one_gpu() -> None:
    result = await check_cuda_gpu_available(lambda: [GpuInfo("RTX 3060 Ti", 8192, 3000)])
    assert result.status == "PASS"
    assert result.number == 1


async def test_cuda_gpu_available_fails_with_no_gpu() -> None:
    result = await check_cuda_gpu_available(lambda: [])
    assert result.status == "FAIL"


async def test_cuda_gpu_available_fails_when_the_probe_raises() -> None:
    def raising() -> list[GpuInfo]:
        raise RuntimeError("nvml not found")

    result = await check_cuda_gpu_available(raising)
    assert result.status == "FAIL"
    assert "nvml not found" in result.detail


# I7 E52 (ТЗ ¶171-176): a profile that needs no GPU at all PASSes outright and never even calls the
# probe — a machine with no NVIDIA GPU / no nvidia container runtime must not FAIL this check.


async def test_cuda_gpu_available_passes_without_a_probe_call_for_a_profile_that_needs_no_gpu(
    cpu_profile: ModelProfile,
) -> None:
    def raising() -> list[GpuInfo]:
        raise AssertionError("query_gpus must not be called when the profile needs no GPU")

    result = await check_cuda_gpu_available(raising, cpu_profile)

    assert result.status == "PASS"
    assert result.detail == NOT_REQUIRED_BY_PROFILE_DETAIL


async def test_cuda_gpu_available_still_checks_for_a_profile_that_needs_a_gpu(
    profile: ModelProfile,
) -> None:
    result = await check_cuda_gpu_available(lambda: [], profile)
    assert result.status == "FAIL"


# -- #2 expected_gpu_detected ---------------------------------------------------------------------


async def test_expected_gpu_detected_passes_when_name_and_margin_match(
    profile: ModelProfile,
) -> None:
    required = profile.vram_budget_mb + profile.min_vram_margin_mb
    result = await check_expected_gpu_detected(
        lambda: [GpuInfo("NVIDIA GeForce RTX 3060 Ti", 8192, required + 100)], profile
    )
    assert result.status == "PASS"


async def test_expected_gpu_detected_fails_on_a_name_mismatch(profile: ModelProfile) -> None:
    result = await check_expected_gpu_detected(lambda: [GpuInfo("RTX 4090", 24576, 20000)], profile)
    assert result.status == "FAIL"
    assert "3060 Ti" in result.detail


async def test_expected_gpu_detected_fails_when_free_vram_is_below_the_margin(
    profile: ModelProfile,
) -> None:
    required = profile.vram_budget_mb + profile.min_vram_margin_mb
    result = await check_expected_gpu_detected(
        lambda: [GpuInfo("NVIDIA GeForce RTX 3060 Ti", 8192, required - 1)], profile
    )
    assert result.status == "FAIL"
    assert "MB free" in result.detail


# E20-G/G7: STACK-AWARE. On a warm stack the pre-start rule ("the whole budget must be FREE")
# fails precisely because the models it checks for are loaded — E20-C's §46 walk got
# `2341 MB free < 7680 MB required` against a healthy machine.


async def _loaded() -> tuple[bool, str]:
    return True, "voice-agent :8113 ASR+TTS ready"


async def _cold() -> tuple[bool, str]:
    return False, "ConnectError: connection refused"


async def test_expected_gpu_detected_passes_on_a_warm_stack_with_only_the_remaining_allowance(
    profile: ModelProfile,
) -> None:
    assert profile.measured_peak_vram_mb is not None
    remaining = profile.vram_budget_mb - profile.measured_peak_vram_mb
    pre_start = profile.vram_budget_mb + profile.min_vram_margin_mb
    free = remaining + 10
    assert free < pre_start  # the same card would FAIL the pre-start rule

    result = await check_expected_gpu_detected(
        lambda: [GpuInfo("NVIDIA GeForce RTX 3060 Ti", 8192, free)], profile, _loaded
    )
    assert result.status == "PASS"
    assert "models loaded" in result.detail


async def test_expected_gpu_detected_keeps_the_pre_start_rule_when_nothing_is_loaded(
    profile: ModelProfile,
) -> None:
    remaining = profile.vram_budget_mb - (profile.measured_peak_vram_mb or 0)
    result = await check_expected_gpu_detected(
        lambda: [GpuInfo("NVIDIA GeForce RTX 3060 Ti", 8192, remaining + 10)], profile, _cold
    )
    assert result.status == "FAIL"
    assert "models loaded" not in result.detail


async def test_expected_gpu_detected_still_fails_on_a_warm_stack_below_the_remaining_allowance(
    profile: ModelProfile,
) -> None:
    assert profile.measured_peak_vram_mb is not None
    remaining = profile.vram_budget_mb - profile.measured_peak_vram_mb
    result = await check_expected_gpu_detected(
        lambda: [GpuInfo("NVIDIA GeForce RTX 3060 Ti", 8192, remaining - 1)], profile, _loaded
    )
    assert result.status == "FAIL"


async def test_expected_gpu_detected_assumes_cold_when_the_loaded_probe_raises(
    profile: ModelProfile,
) -> None:
    async def raising() -> tuple[bool, str]:
        raise RuntimeError("no route to host")

    remaining = profile.vram_budget_mb - (profile.measured_peak_vram_mb or 0)
    result = await check_expected_gpu_detected(
        lambda: [GpuInfo("NVIDIA GeForce RTX 3060 Ti", 8192, remaining + 10)], profile, raising
    )
    assert result.status == "FAIL"


async def test_expected_gpu_detected_passes_without_a_probe_call_for_a_profile_that_needs_no_gpu(
    cpu_profile: ModelProfile,
) -> None:
    """I7 E52: same bypass as check #1 — `CPU.yaml` PASSes without ever calling `query_gpus`."""

    def raising() -> list[GpuInfo]:
        raise AssertionError("query_gpus must not be called when the profile needs no GPU")

    result = await check_expected_gpu_detected(raising, cpu_profile)

    assert result.status == "PASS"
    assert result.detail == NOT_REQUIRED_BY_PROFILE_DETAIL


# -- #3 model_files_exist -------------------------------------------------------------------------


async def test_model_files_exist_passes_when_every_path_has_a_size(profile: ModelProfile) -> None:
    result = await check_model_files_exist(profile, lambda path: 1024)
    assert result.status == "PASS"
    assert str(len(profile_model_file_paths(profile))) in result.detail


async def test_model_files_exist_fails_when_a_path_is_missing(profile: ModelProfile) -> None:
    def stat(path: Path) -> int | None:
        return None if "llm" in str(path) else 1024

    result = await check_model_files_exist(profile, stat)
    assert result.status == "FAIL"
    assert "llm.model_path" in result.detail


async def test_model_files_exist_reports_a_missing_cpu_model_instead_of_crashing(
    cpu_profile: ModelProfile,
) -> None:
    """I7 E52 acceptance: a CPU model not present locally is reported by name in the FAIL detail —
    the check never raises, matching `test_model_files_exist_fails_when_a_path_is_missing` above
    but against the CPU profile's own paths (gigaam CPU checkpoint, Piper voice, the CPU llama.cpp
    GGUF)."""
    result = await check_model_files_exist(cpu_profile, lambda path: None)

    assert result.status == "FAIL"
    assert "asr.model_path" in result.detail
    assert "tts.model_path" in result.detail
    assert "llm.model_path" in result.detail


async def test_check_3_resolves_the_profiles_container_paths_onto_the_host(
    profile: ModelProfile, tmp_path: Path
) -> None:
    """E20 R15: on a host run the files are under `SIM_MODELS_ROOT`, never at `/models`.

    Before this, check #3 stat-ed `/models/...` verbatim and therefore FAILed on every host run no
    matter what was installed — the same defect that made the voice agent's four components go
    FATAL (E19-E2/E3).
    """
    seen: list[Path] = []

    def stat(path: Path) -> int | None:
        seen.append(path)
        return 1024

    result = await check_model_files_exist(profile, stat, str(tmp_path))

    assert result.status == "PASS"
    assert seen, "check #3 stat-ed nothing"
    assert all(str(path).startswith(str(tmp_path)) for path in seen), seen
    assert not any(str(path).startswith("/models/") for path in seen)


async def test_check_3_is_unchanged_under_compose(profile: ModelProfile) -> None:
    """`/models` is the default root, so compose sees exactly the paths the profile names."""
    assert profile_model_file_paths(profile) == {
        "llm.model_path": profile.llm.model_path,
        "asr.model_path": profile.asr.model_path,
        "tts.model_path": profile.tts.model_path,
        "vad.model_path": profile.vad.model_path,
        "warmup.asr_sample_path": profile.warmup.asr_sample_path,
    }


# -- #4 llm_responds ------------------------------------------------------------------------------


async def test_llm_responds_passes_when_the_model_id_matches(profile: ModelProfile) -> None:
    async def probe() -> tuple[bool, str]:
        return True, profile.llm.model_name

    result = await check_llm_responds(probe, profile.llm.model_name)
    assert result.status == "PASS"


async def test_llm_responds_fails_when_the_probe_reports_not_ok(profile: ModelProfile) -> None:
    async def probe() -> tuple[bool, str]:
        return False, "GET /models -> 500"

    result = await check_llm_responds(probe, profile.llm.model_name)
    assert result.status == "FAIL"
    assert "500" in result.detail


async def test_llm_responds_fails_when_the_model_id_does_not_match(profile: ModelProfile) -> None:
    async def probe() -> tuple[bool, str]:
        return True, "some-other-model"

    result = await check_llm_responds(probe, profile.llm.model_name)
    assert result.status == "FAIL"
    assert profile.llm.model_name in result.detail


# -- #5 asr_responds ------------------------------------------------------------------------------


async def test_asr_responds_passes_with_non_empty_text() -> None:
    async def probe() -> tuple[bool, str]:
        return True, "проверка связи"

    result = await check_asr_responds(probe)
    assert result.status == "PASS"


async def test_asr_responds_fails_when_the_probe_reports_not_ok() -> None:
    async def probe() -> tuple[bool, str]:
        return False, "connection refused"

    result = await check_asr_responds(probe)
    assert result.status == "FAIL"


# E20-G/G7: the bar is a CYRILLIC WORD, not "non-empty". A 440 Hz tone (what `.env.example` used
# to make the agent warm on) transcribes to nothing or to noise, and check 5 must say why.


async def test_asr_responds_fails_when_the_transcription_has_no_cyrillic_word() -> None:
    async def probe() -> tuple[bool, str]:
        return True, "beep beep 440"

    result = await check_asr_responds(probe)
    assert result.status == "FAIL"
    assert "Cyrillic" in result.detail
    assert "warmup_ru.wav" in result.detail


async def test_asr_responds_fails_on_an_empty_transcription_from_a_tone() -> None:
    async def probe() -> tuple[bool, str]:
        return True, ""

    result = await check_asr_responds(probe)
    assert result.status == "FAIL"


def test_has_cyrillic_word() -> None:
    assert has_cyrillic_word("проверка связи")
    assert has_cyrillic_word("mixed текст here")
    assert not has_cyrillic_word("")
    assert not has_cyrillic_word("beep 440 hz")
    assert not has_cyrillic_word("a б c")  # one stray letter is not a word


# -- #6 tts_responds ------------------------------------------------------------------------------


async def test_tts_responds_passes_with_positive_audio_duration() -> None:
    async def probe() -> tuple[bool, int, str]:
        return True, 480, "ok"

    result = await check_tts_responds(probe)
    assert result.status == "PASS"


async def test_tts_responds_fails_with_zero_audio_duration() -> None:
    async def probe() -> tuple[bool, int, str]:
        return True, 0, "ok"

    result = await check_tts_responds(probe)
    assert result.status == "FAIL"
    assert "output_audio_ms" in result.detail


# -- #7 postgresql_responds -----------------------------------------------------------------------


async def test_postgresql_responds_passes_when_the_probe_reports_ok() -> None:
    async def probe() -> tuple[bool, str]:
        return True, "SELECT 1 ok; exactly one alembic head"

    result = await check_postgresql_responds(probe)
    assert result.status == "PASS"


async def test_postgresql_responds_fails_with_more_than_one_head() -> None:
    async def probe() -> tuple[bool, str]:
        return False, "alembic_version has 2 row(s), expected exactly one head"

    result = await check_postgresql_responds(probe)
    assert result.status == "FAIL"


# -- #8 redis_responds ----------------------------------------------------------------------------


async def test_redis_responds_passes_when_the_probe_reports_ok() -> None:
    async def probe() -> tuple[bool, str]:
        return True, "PING ok; SET/GET/DEL ok"

    result = await check_redis_responds(probe)
    assert result.status == "PASS"


async def test_redis_responds_fails_when_the_probe_raises() -> None:
    async def probe() -> tuple[bool, str]:
        raise ConnectionRefusedError("no redis")

    result = await check_redis_responds(probe)
    assert result.status == "FAIL"
    assert "no redis" in result.detail


# -- #9 livekit_responds --------------------------------------------------------------------------


async def test_livekit_responds_passes_when_the_probe_reports_ok() -> None:
    async def probe() -> tuple[bool, str]:
        return True, "GET http://livekit:7880 -> 200"

    result = await check_livekit_responds(probe)
    assert result.status == "PASS"


async def test_livekit_responds_fails_when_the_probe_reports_not_ok() -> None:
    async def probe() -> tuple[bool, str]:
        return False, "ConnectError: refused"

    result = await check_livekit_responds(probe)
    assert result.status == "FAIL"


# -- #10 scenario_validation ----------------------------------------------------------------------


async def test_scenario_validation_passes_when_every_file_validates() -> None:
    path = Path("scenarios/examples/demo/v1.yaml")

    result = await check_scenario_validation(
        Path("scenarios/examples"),
        discover_files=lambda _dir: [path],
        load_version=lambda _path: object(),
    )
    assert result.status == "PASS"


async def test_scenario_validation_fails_when_a_file_is_invalid() -> None:
    path = Path("scenarios/examples/demo/v1.yaml")

    def load_version(_path: Path) -> object:
        raise ScenarioValidationError(["R01: missing incident.type"])

    result = await check_scenario_validation(
        Path("scenarios/examples"), discover_files=lambda _dir: [path], load_version=load_version
    )
    assert result.status == "FAIL"
    assert "R01" in result.detail


async def test_scenario_validation_fails_when_no_file_is_found() -> None:
    result = await check_scenario_validation(
        Path("scenarios/nowhere"),
        discover_files=lambda _dir: [],
        load_version=lambda _path: object(),
    )
    assert result.status == "FAIL"


# -- #11 audio_devices_accessible -----------------------------------------------------------------


async def test_audio_devices_passes_when_a_device_is_found() -> None:
    result = await check_audio_devices(
        skip_audio_devices=False,
        audio_device_check_enabled=True,
        query_devices=lambda: ["default"],
    )
    assert result.status == "PASS"


async def test_audio_devices_skips_rather_than_fails_when_none_are_found() -> None:
    """HLD 60 §5: "device opens, else SKIP" — a headless box is not a preflight failure."""
    result = await check_audio_devices(
        skip_audio_devices=False, audio_device_check_enabled=True, query_devices=lambda: []
    )
    assert result.status == "SKIP"


async def test_audio_devices_skips_when_the_flag_is_passed() -> None:
    def unreachable() -> list[str]:
        raise AssertionError("must not be called when --skip-audio-devices is set")

    result = await check_audio_devices(
        skip_audio_devices=True, audio_device_check_enabled=True, query_devices=unreachable
    )
    assert result.status == "SKIP"


# -- #12 llama_server_binary (additive) -----------------------------------------------------------


async def test_llama_server_binary_skips_when_the_env_var_is_unset() -> None:
    result = await check_llama_server_binary(
        bin_path=None,
        is_file=lambda p: True,
        is_executable=lambda p: True,
        run_version=lambda p: 0,
    )
    assert result.status == "SKIP"


async def test_llama_server_binary_passes_when_version_exits_zero() -> None:
    result = await check_llama_server_binary(
        bin_path="/usr/local/bin/llama-server",
        is_file=lambda p: True,
        is_executable=lambda p: True,
        run_version=lambda p: 0,
    )
    assert result.status == "PASS"


async def test_llama_server_binary_fails_when_the_file_does_not_exist() -> None:
    result = await check_llama_server_binary(
        bin_path="/no/such/binary",
        is_file=lambda p: False,
        is_executable=lambda p: True,
        run_version=lambda p: 0,
    )
    assert result.status == "FAIL"


async def test_llama_server_binary_fails_when_version_exits_non_zero() -> None:
    result = await check_llama_server_binary(
        bin_path="/usr/local/bin/llama-server",
        is_file=lambda p: True,
        is_executable=lambda p: True,
        run_version=lambda p: 1,
    )
    assert result.status == "FAIL"


# -- orchestration / rendering --------------------------------------------------------------------


def _result(number: int, status: str) -> CheckResult:
    return CheckResult(number, f"check_{number}", status, "detail")  # type: ignore[arg-type]


def test_exit_code_is_zero_when_nothing_failed() -> None:
    report = PreflightReport("DEV_3060TI", (_result(1, "PASS"), _result(2, "SKIP")))
    assert report.exit_code == 0


def test_exit_code_is_one_when_anything_failed() -> None:
    report = PreflightReport("DEV_3060TI", (_result(1, "PASS"), _result(2, "FAIL")))
    assert report.exit_code == 1


def test_a_skip_never_flips_the_exit_code_even_when_everything_else_skips() -> None:
    report = PreflightReport("DEV_3060TI", (_result(1, "SKIP"), _result(2, "SKIP")))
    assert report.exit_code == 0


def test_render_table_lists_every_check() -> None:
    report = PreflightReport("DEV_3060TI", (_result(1, "PASS"), _result(2, "FAIL")))
    table = render_table(report)
    assert "DEV_3060TI" in table
    assert "PASS" in table
    assert "FAIL" in table


def test_render_json_round_trips_through_json() -> None:
    import json

    report = PreflightReport("DEV_3060TI", (_result(1, "PASS"),))
    body = json.loads(render_json(report))
    assert body["profile"] == "DEV_3060TI"
    assert body["exit_code"] == 0
    assert body["checks"][0]["status"] == "PASS"


# -- E20-G/G7: check #4 dials the EFFECTIVE base url ----------------------------------------------


async def test_build_real_checks_dials_the_settings_llm_base_url_not_the_profile_literal(
    profile: ModelProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A profile names the COMPOSE url; on a host run `SIM_LLM_BASE_URL` overrides it.

    E20-C's §46 walk got `[FAIL] 4. llm_responds: ConnectError: [Errno -3] Temporary failure in
    name resolution` against a llama-server that was answering perfectly on 127.0.0.1:8101,
    because the check dialled `profile.llm.base_url` (`http://llama-server:8080/v1`).
    """
    from app.cli import preflight as preflight_module

    dialled: list[str] = []

    async def fake_probe(base_url: str) -> tuple[bool, str]:
        dialled.append(base_url)
        return True, profile.llm.model_name

    monkeypatch.setattr(preflight_module, "_probe_llm_real", fake_probe)
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        redis_url="redis://localhost:56379/0",
        jwt_secret="test-only-secret-padded-32-bytes!",
        livekit_url="ws://localhost:7880",
        livekit_api_key="devkey",
        livekit_api_secret="devsecret1234567890",
        llm_base_url="http://127.0.0.1:8101/v1",
    )
    assert settings.llm_base_url != profile.llm.base_url

    checks = preflight_module.build_real_checks(profile, settings, skip_audio_devices=True)
    result = await checks[3]()

    assert dialled == ["http://127.0.0.1:8101/v1"]
    assert result.number == 4
    assert result.status == "PASS"


# -- profile_requires_gpu (I7 E52, ТЗ ¶171-176) ----------------------------------------------------


def test_profile_requires_gpu_is_true_for_a_gpu_profile(profile: ModelProfile) -> None:
    assert profile_requires_gpu(profile) is True


def test_profile_requires_gpu_is_false_for_the_cpu_profile(cpu_profile: ModelProfile) -> None:
    assert profile_requires_gpu(cpu_profile) is False


def test_profile_requires_gpu_is_true_when_only_one_component_names_cuda(
    cpu_profile: ModelProfile,
) -> None:
    """Any single `device: cuda` (or `llm.n_gpu_layers != 0`) is enough to require a GPU — not
    only an all-or-nothing profile shape."""
    asr_on_gpu = cpu_profile.model_copy(
        update={"asr": cpu_profile.asr.model_copy(update={"device": "cuda"})}
    )
    assert profile_requires_gpu(asr_on_gpu) is True

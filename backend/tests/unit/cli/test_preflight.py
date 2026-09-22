"""`app.cli.preflight` — one PASS and one FAIL unit test per check, with fakes (R7).

Every check is exercised through its injected probe only: no GPU, model server, database, Redis,
LiveKit or audio device is ever touched. `DEV_3060TI` is loaded for real (`load_profile`) so the
fixture is the actual shipped profile rather than a hand-rolled stand-in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.cli.preflight import (
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
    profile_model_file_paths,
    render_json,
    render_table,
)
from app.config.profile import ModelProfile, load_profile
from app.domain.common.errors import ScenarioValidationError


@pytest.fixture
def profile() -> ModelProfile:
    return load_profile("DEV_3060TI")


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

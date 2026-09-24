"""`app.config.profile` — loading, schema, and the VRAM-margin refusal rule (HLD 60 §2, E18-A).

R1/R2/DO items 5 of the E18-A task brief: every shipped YAML loads, an unknown key is refused, a
FINAL_* profile with no measured peak is refused, a margin below the minimum is refused, an
unmeasured DEV profile only warns, and `DEV_3060TI_SHARED` (measured, positive margin) passes.
"""

from __future__ import annotations

import logging

import pytest
from app.config.profile import (
    ModelProfile,
    ProfileRefused,
    load_profile,
    validate_vram_margin,
)

ALL_PROFILE_NAMES = (
    "DEV_3060TI",
    "DEV_3060TI_SHARED",
    "FINAL_3080TI_12GB",
    "FINAL_3080TI_16GB",
)


@pytest.mark.parametrize("name", ALL_PROFILE_NAMES)
def test_every_shipped_profile_loads(name: str) -> None:
    """R2: the SPEC's three profiles plus the additive DEV_3060TI_SHARED all parse and validate."""
    profile = load_profile(name)

    assert profile.profile_name == name
    assert isinstance(profile, ModelProfile)


def test_an_unknown_top_level_key_is_refused() -> None:
    """`extra="forbid"` (R1): a typo'd key is a load-time refusal, not a silently ignored one."""
    base = load_profile("DEV_3060TI").model_dump(mode="json")
    base["not_a_real_key"] = True

    with pytest.raises(Exception, match=r"not_a_real_key|extra"):
        ModelProfile(**base)


def test_an_unknown_nested_key_is_refused() -> None:
    """The same `extra="forbid"` rule applies inside every nested block, not just the top level."""
    base = load_profile("DEV_3060TI").model_dump(mode="json")
    base["llm"]["not_a_real_field"] = 1

    with pytest.raises(Exception, match=r"not_a_real_field|extra"):
        ModelProfile(**base)


def test_thinking_enabled_true_is_refused_at_load() -> None:
    """HLD 60 §2.1: `llm.thinking_enabled` must be false (SPEC §22)."""
    base = load_profile("DEV_3060TI").model_dump(mode="json")
    base["llm"]["thinking_enabled"] = True

    with pytest.raises(Exception, match="thinking_enabled"):
        ModelProfile(**base)


def test_load_profile_refuses_a_name_with_no_file() -> None:
    with pytest.raises(ProfileRefused, match="NOT_A_REAL_PROFILE"):
        load_profile("NOT_A_REAL_PROFILE")


def test_load_profile_refuses_a_profile_name_filename_mismatch(tmp_path, monkeypatch) -> None:
    import app.config.profile as profile_module

    base = load_profile("DEV_3060TI").model_dump(mode="json")
    base["profile_name"] = "SOMETHING_ELSE"
    (tmp_path / "MISNAMED.yaml").write_text(_dump_yaml(base), encoding="utf-8")
    monkeypatch.setattr(profile_module, "PROFILES_DIR", tmp_path)

    with pytest.raises(ProfileRefused, match="MISNAMED"):
        profile_module.load_profile("MISNAMED")


def _dump_yaml(data: dict) -> str:
    import yaml

    return yaml.safe_dump(data)


# -- voip.* (I3 E6f, HLD 80 §80.8.3) --------------------------------------------------------------


def test_voip_block_defaults_to_all_none_when_a_profile_does_not_declare_it() -> None:
    """Every shipped profile predates E6f; `voip` must be optional and unmeasured by default
    (SPEC §27: no number a script did not produce)."""
    profile = load_profile("DEV_3060TI_SHARED")

    assert profile.voip.one_way_delay_ms_p50 is None
    assert profile.voip.one_way_delay_ms_p95 is None
    assert profile.voip.concurrent_calls_measured is None


def test_voip_block_accepts_measured_numbers() -> None:
    base = load_profile("DEV_3060TI").model_dump(mode="json")
    base["voip"] = {
        "one_way_delay_ms_p50": 110.2,
        "one_way_delay_ms_p95": 120.3,
        "concurrent_calls_measured": 40,
    }
    profile = ModelProfile(**base)

    assert profile.voip.one_way_delay_ms_p50 == 110.2
    assert profile.voip.one_way_delay_ms_p95 == 120.3
    assert profile.voip.concurrent_calls_measured == 40


def test_an_unknown_voip_key_is_refused() -> None:
    base = load_profile("DEV_3060TI").model_dump(mode="json")
    base["voip"] = {"not_a_real_key": True}

    with pytest.raises(Exception, match=r"not_a_real_key|extra"):
        ModelProfile(**base)


# -- validate_vram_margin (HLD 60 §2.5) ----------------------------------------------------------


def test_dev_profile_with_no_measurement_only_warns(caplog: pytest.LogCaptureFixture) -> None:
    """The DEV-only warn branch of `validate_vram_margin` (HLD 60 §2.5) — exercised on a
    synthetic unmeasured profile, independent of whether any *particular* shipped DEV profile
    currently has a measurement. `DEV_3060TI` itself got a real one (E19-D3,
    `docs/benchmarks/results/vram-DEV_3060TI-20260922T092121636Z.json`) — see
    `test_dev_3060ti_passes_with_a_measured_margin` below."""
    profile = load_profile("DEV_3060TI_SHARED").model_copy(update={"measured_peak_vram_mb": None})
    assert profile.measured_peak_vram_mb is None

    with caplog.at_level(logging.WARNING):
        validate_vram_margin(profile)  # must not raise

    assert any("unmeasured" in record.message for record in caplog.records)


def test_dev_3060ti_passes_with_a_measured_margin() -> None:
    """R2: measured 5560 MB (E19-D3, real `benchmark_vram.py --profile DEV_3060TI --turns 20`,
    the owner's GPU process stopped for this run, all three GPU components loaded and 20 turns
    completed — docs/benchmarks/results/vram-DEV_3060TI-20260922T092121636Z.json), budget
    7168 MB, min margin 512 MB -> margin 1608 MB, passes."""
    profile = load_profile("DEV_3060TI")
    assert profile.measured_peak_vram_mb == 5560

    validate_vram_margin(profile)  # must not raise


def test_dev_3060ti_shared_passes_with_a_positive_margin() -> None:
    """R2: measured 1559 MB (E19-D, benchmark_vram.py on 2026-09-22 —
    docs/benchmarks/results/vram-DEV_3060TI_SHARED-20260922T050401Z.json), budget 3000 MB,
    min margin 512 MB -> margin 1441 MB, passes."""
    profile = load_profile("DEV_3060TI_SHARED")
    assert profile.measured_peak_vram_mb == 1559

    validate_vram_margin(profile)  # must not raise


@pytest.mark.parametrize("name", ("FINAL_3080TI_12GB", "FINAL_3080TI_16GB"))
def test_a_final_profile_with_no_measurement_is_refused(name: str) -> None:
    profile = load_profile(name)
    assert profile.measured_peak_vram_mb is None

    with pytest.raises(ProfileRefused, match="measured_peak_vram_mb"):
        validate_vram_margin(profile)


def test_a_margin_below_the_minimum_is_refused() -> None:
    """The generic branch of HLD 60 §2.5: any profile (not just FINAL_*) whose measured peak
    leaves less than `min_vram_margin_mb` of headroom is refused."""
    profile = load_profile("DEV_3060TI_SHARED").model_copy(
        update={"measured_peak_vram_mb": 2900}  # budget 3000, min margin 512 -> margin 100 < 512
    )

    with pytest.raises(ProfileRefused, match="margin"):
        validate_vram_margin(profile)


def test_a_dev_profile_with_a_measured_and_sufficient_margin_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    profile = load_profile("DEV_3060TI_SHARED")

    with caplog.at_level(logging.WARNING):
        validate_vram_margin(profile)

    assert caplog.records == []

"""Every SPEC §35 script's `main()` with `--provider fake` — the gate-side shape proof (R2).

One module per script would repeat the same four assertions five times, so the envelope contract
is asserted once in `assert_envelope()` and each script gets the checks that are its own.
**Shape only:** no number produced by a fake provider is asserted, because none of them is a
measurement.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import benchmark_asr
import benchmark_e2e
import benchmark_llm
import benchmark_tts
import benchmark_vram
import pytest

ENVELOPE_KEYS = {
    "schema_version",
    "benchmark",
    "status",
    "profile",
    "git_sha",
    "started_at",
    "finished_at",
    "hardware",
    "config",
    "samples",
    "aggregates",
    "notes",
}


def read_result(out: Path, benchmark: str) -> tuple[dict[str, Any], list[list[str]]]:
    """The one JSON+CSV pair the run wrote."""
    jsons = sorted(out.glob(f"{benchmark}-*.json"))
    csvs = sorted(out.glob(f"{benchmark}-*.csv"))
    assert len(jsons) == 1 and len(csvs) == 1, f"expected one JSON+CSV pair, got {jsons} {csvs}"
    with csvs[0].open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return json.loads(jsons[0].read_text(encoding="utf-8")), rows


def assert_envelope(payload: dict[str, Any], benchmark: str, *, status: str = "OK") -> None:
    assert set(payload) >= ENVELOPE_KEYS, ENVELOPE_KEYS - set(payload)
    assert payload["schema_version"] == 1
    assert payload["benchmark"] == benchmark
    assert payload["status"] == status
    assert set(payload["hardware"]) == {"gpu_name", "driver", "total_vram_mb"}
    assert isinstance(payload["notes"], list)
    if status in ("NOT_RUN", "FAILED"):
        assert payload["reason"], "a non-result must say why"
    if status == "NOT_RUN":
        assert payload["samples"] == [] and payload["aggregates"] == {}


def assert_csv_header_is_the_sample_keys(payload: dict[str, Any], rows: list[list[str]]) -> None:
    """HLD §7.0: the CSV is a flat per-sample export of the very rows in the JSON."""
    seen: list[str] = []
    for sample in payload["samples"]:
        for key in sample:
            if key not in seen:
                seen.append(key)
    assert rows[0] == seen
    assert len(rows) == len(payload["samples"]) + 1


# -- benchmark_asr -------------------------------------------------------------------------------


def test_asr_fake_run_writes_a_complete_ok_envelope(tmp_path: Path, asr_corpus: Path) -> None:
    out = tmp_path / "out"
    assert (
        benchmark_asr.main(["--provider", "fake", "--manifest", str(asr_corpus), "--out", str(out)])
        == 0
    )
    payload, rows = read_result(out, "asr")
    assert_envelope(payload, "asr")
    assert_csv_header_is_the_sample_keys(payload, rows)
    assert len(payload["samples"]) == 2
    assert set(payload["aggregates"]) == {"overall", "by_category_condition", "by_source"}
    # The fake replays the manifest's own reference, so the folding path is exercised end to end.
    assert all(sample["wer"] == 0.0 for sample in payload["samples"])
    assert set(payload["aggregates"]["by_source"]) == {
        "piper:ru_RU-irina-medium",
        "human:gigaam-sample",
    }


def test_asr_missing_manifest_is_not_run_with_the_path_and_zero_numbers(tmp_path: Path) -> None:
    out = tmp_path / "out"
    missing = tmp_path / "nope" / "manifest.jsonl"
    assert (
        benchmark_asr.main(["--provider", "fake", "--manifest", str(missing), "--out", str(out)])
        == 0
    )
    payload, rows = read_result(out, "asr")
    assert_envelope(payload, "asr", status="NOT_RUN")
    assert str(missing) in payload["reason"]
    assert rows == []


def test_asr_missing_model_directory_is_not_run(tmp_path: Path, asr_corpus: Path) -> None:
    """`--provider real` against an empty models root: a path in `reason`, never an estimate."""
    out = tmp_path / "out"
    assert (
        benchmark_asr.main(
            [
                "--provider",
                "real",
                "--manifest",
                str(asr_corpus),
                "--models-root",
                str(tmp_path / "empty-models"),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    payload, _rows = read_result(out, "asr")
    assert_envelope(payload, "asr", status="NOT_RUN")
    assert "model directory not found" in payload["reason"]


def test_asr_fake_run_populates_the_hardware_block(tmp_path: Path, asr_corpus: Path) -> None:
    """R2/§7.0: every envelope carries `hardware:{gpu_name, driver, total_vram_mb}` — E19-B found
    `benchmark_asr.py` never populated it and added the same `NvmlSampler` read
    `benchmark_tts.py`/`benchmark_vram.py` already use (one instantaneous read, not continuous
    sampling). This machine's own GPU/driver may or may not be visible to the gate sandbox, so
    this only asserts the three keys exist and `notes` records which sampler path answered —
    never a specific value (that would not be a shape test any more)."""
    out = tmp_path / "out"
    assert (
        benchmark_asr.main(["--provider", "fake", "--manifest", str(asr_corpus), "--out", str(out)])
        == 0
    )
    payload, _rows = read_result(out, "asr")
    assert set(payload["hardware"]) == {"gpu_name", "driver", "total_vram_mb"}
    assert any(note.startswith("nvml_mode=") for note in payload["notes"])


def test_asr_faster_whisper_without_a_model_path_is_not_run(tmp_path: Path) -> None:
    """SPEC §19's optional fallback (R4): selecting it never fabricates a number — it is always
    `NOT_RUN` unless a real `--whisper-model-path`/`SIM_WHISPER_MODEL_PATH` exists. `--provider
    real` is used here (the `asr_provider` branch is real-only, checked before the corpus/model
    load, so no torch/GPU is touched — safe for the gate, D13)."""
    out = tmp_path / "out"
    assert (
        benchmark_asr.main(
            [
                "--provider",
                "real",
                "--asr-provider",
                "faster_whisper",
                "--manifest",
                str(tmp_path / "does-not-matter.jsonl"),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    payload, rows = read_result(out, "asr")
    assert_envelope(payload, "asr", status="NOT_RUN")
    assert "faster-whisper" in payload["reason"]
    assert "E12 ruling 4" in payload["reason"]
    assert rows == []


# -- benchmark_llm -------------------------------------------------------------------------------


def test_llm_fake_run_covers_all_three_suites(
    tmp_path: Path, llm_corpora: tuple[Path, Path]
) -> None:
    out = tmp_path / "out"
    interpreter, dialogue = llm_corpora
    assert (
        benchmark_llm.main(
            [
                "--provider",
                "fake",
                "--suite",
                "all",
                "--interpreter-cases",
                str(interpreter),
                "--dialogue-cases",
                str(dialogue),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    payload, rows = read_result(out, "llm")
    assert_envelope(payload, "llm")
    assert_csv_header_is_the_sample_keys(payload, rows)
    assert set(payload["aggregates"]["by_suite"]) == {"interpreter", "dialogue", "explanation"}
    overall = payload["aggregates"]["overall"]
    for key in (
        "ttft_ms",
        "tokens_per_second",
        "structured_output_validity_rate",
        "repair_rate",
        "forbidden_fact_leak_rate",
        "validator_failure_codes",
    ):
        assert key in overall, key
    assert "dialogue_consistency_rate" in payload["aggregates"]["by_suite"]["dialogue"]
    assert "explicit_acc" in payload["aggregates"]["by_suite"]["interpreter"]
    # E13-B3's ruling: every metric twice, all / excluding uncertain.
    assert "excluding_uncertain" in payload["aggregates"]


def test_llm_missing_corpus_is_not_run(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert (
        benchmark_llm.main(
            [
                "--provider",
                "fake",
                "--interpreter-cases",
                str(tmp_path / "nope.jsonl"),
                "--dialogue-cases",
                str(tmp_path / "nope2.jsonl"),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    payload, _rows = read_result(out, "llm")
    assert_envelope(payload, "llm", status="NOT_RUN")
    assert "corpus not found" in payload["reason"]


def test_the_43_attack_matrix_is_reused_not_duplicated() -> None:
    """HLD §7.2/D13: the §43 matrix lives in `backend/tests/adversarial/`, and is imported."""
    suite = benchmark_llm._adversarial()
    assert suite.__name__ == "tests.adversarial.test_forbidden_fact_leak_suite"
    assert len(suite.ATTACKS) >= 12 and len(suite.PROBES) >= 10


# -- benchmark_tts -------------------------------------------------------------------------------


def test_tts_fake_run_reports_synthesis_and_cancellation(tmp_path: Path, tts_corpus: Path) -> None:
    out = tmp_path / "out"
    assert (
        benchmark_tts.main(
            [
                "--provider",
                "fake",
                "--lines",
                str(tts_corpus),
                "--nvml",
                "stub",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    payload, rows = read_result(out, "tts")
    assert_envelope(payload, "tts")
    assert_csv_header_is_the_sample_keys(payload, rows)
    suites = {sample["suite"] for sample in payload["samples"]}
    assert suites == {"synthesis", "cancellation"}
    cancellation = payload["aggregates"]["cancellation"]
    # HLD §7.3: "chunks_after_cancel (must be 0 or 1)".
    assert cancellation["chunks_after_cancel_max"] in (0, 1)
    assert "first_audio_latency_ms" in payload["aggregates"]["overall"]


def test_tts_chatterbox_is_not_run_because_the_provider_does_not_exist(
    tmp_path: Path, tts_corpus: Path
) -> None:
    out = tmp_path / "out"
    assert (
        benchmark_tts.main(
            [
                "--provider",
                "fake",
                "--tts-provider",
                "chatterbox",
                "--lines",
                str(tts_corpus),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    payload, _rows = read_result(out, "tts")
    assert_envelope(payload, "tts", status="NOT_RUN")
    assert "not implemented" in payload["reason"]


# -- benchmark_e2e -------------------------------------------------------------------------------


def test_e2e_inprocess_fake_run_reads_the_metric_from_the_event_log(
    tmp_path: Path, e2e_corpus: Path
) -> None:
    out = tmp_path / "out"
    assert (
        benchmark_e2e.main(
            ["--provider", "fake", "--turns-file", str(e2e_corpus), "--out", str(out)]
        )
        == 0
    )
    payload, rows = read_result(out, "e2e")
    assert_envelope(payload, "e2e")
    assert_csv_header_is_the_sample_keys(payload, rows)
    assert payload["samples"], "the pipeline produced no completed turn"
    sample = payload["samples"][0]
    assert sample["speech_end_to_first_audio_ms"] is not None
    assert sample["transport"] == "inprocess"
    aggregates = payload["aggregates"]
    assert aggregates["latency_targets"] == {"p50_ms": 1500, "p95_ms": 2500}
    assert isinstance(aggregates["meets_target"], bool)
    assert set(aggregates["per_stage_p50_ms"]) == {
        "asr_ms",
        "interpret_ms",
        "generate_ms",
        "tts_first_chunk_ms",
        "tts_ms",
    }


def test_e2e_livekit_without_a_room_is_not_run(tmp_path: Path, e2e_corpus: Path) -> None:
    out = tmp_path / "out"
    assert (
        benchmark_e2e.main(
            [
                "--provider",
                "fake",
                "--transport",
                "livekit",
                "--turns-file",
                str(e2e_corpus),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    payload, _rows = read_result(out, "e2e")
    assert_envelope(payload, "e2e", status="NOT_RUN")
    assert "--livekit-url" in payload["reason"]


def test_the_benchmark_never_imports_the_livekit_sdk_itself() -> None:
    """D9 / `check_imports.py`: the SDK may only be touched through the headless client."""
    source = Path(benchmark_e2e.__file__).read_text(encoding="utf-8")
    assert "import livekit" not in source
    assert "from livekit" not in source


# -- benchmark_vram ------------------------------------------------------------------------------


def test_vram_fake_run_with_the_stub_sampler_reports_every_delta(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert (
        benchmark_vram.main(
            ["--provider", "fake", "--nvml", "stub", "--turns", "2", "--out", str(out)]
        )
        == 0
    )
    payload, rows = read_result(out, "vram")
    assert_envelope(payload, "vram")
    assert_csv_header_is_the_sample_keys(payload, rows)
    aggregates = payload["aggregates"]
    for key in (
        "baseline_used_mb",
        "idle_after_load_mb",
        "peak_mb",
        "project_peak_mb",
        "free_min_mb",
        "vad_delta_mb",
        "asr_delta_mb",
        "tts_delta_mb",
        "llm_delta_mb",
    ):
        assert key in aggregates, key


def test_vram_without_nvml_is_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """HLD §7.5, literally: NVML unavailable ⇒ `NOT_RUN`, `reason: "NVML unavailable"`."""
    import _common

    monkeypatch.setattr(_common.NvmlSampler, "_probe", lambda self: None)
    out = tmp_path / "out"
    assert benchmark_vram.main(["--provider", "fake", "--out", str(out)]) == 0
    payload, _rows = read_result(out, "vram")
    assert_envelope(payload, "vram", status="NOT_RUN")
    assert payload["reason"] == "NVML unavailable"


def test_vram_never_edits_a_profile_file() -> None:
    """HLD §7.5: "never edits the profile file itself" — it prints the line to paste."""
    source = Path(benchmark_vram.__file__).read_text(encoding="utf-8")
    assert "write_text" not in source
    assert "measured_peak_vram_mb" in source  # it prints the ready-to-paste line


# -- every script: profile handling --------------------------------------------------------------


@pytest.mark.parametrize(
    ("module", "argv"),
    [
        (benchmark_asr, ["--provider", "fake"]),
        (benchmark_llm, ["--provider", "fake"]),
        (benchmark_tts, ["--provider", "fake"]),
        (benchmark_e2e, ["--provider", "fake"]),
        (benchmark_vram, ["--provider", "fake", "--nvml", "stub"]),
    ],
)
def test_an_unknown_profile_exits_2(module: Any, argv: list[str], tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        module.main([*argv, "--profile", "NO_SUCH_PROFILE", "--out", str(tmp_path)])
    assert excinfo.value.code == 2


def test_a_refused_final_profile_is_not_run_with_the_refusal_as_the_reason(
    tmp_path: Path, asr_corpus: Path
) -> None:
    """SPEC §26: `FINAL_3080TI_12GB` has no measured peak, so `validate_vram_margin` refuses it.

    The benchmark's honest answer is `NOT_RUN` carrying that refusal — never a number produced
    against a profile the product itself would not start on.
    """
    from app.config.profile import ProfileRefused, load_profile, validate_vram_margin

    with pytest.raises(ProfileRefused):
        validate_vram_margin(load_profile("FINAL_3080TI_12GB"))

    out = tmp_path / "out"
    assert (
        benchmark_asr.main(
            [
                "--provider",
                "real",
                "--profile",
                "FINAL_3080TI_12GB",
                "--manifest",
                str(asr_corpus),
                "--models-root",
                str(tmp_path / "empty-models"),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    payload, _rows = read_result(out, "asr")
    assert_envelope(payload, "asr", status="NOT_RUN")
    assert payload["profile"] == "FINAL_3080TI_12GB"

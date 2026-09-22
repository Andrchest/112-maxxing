"""`benchmarks/_common.py` — percentiles, numeral folding, the path table, and the honesty rule.

The three "red" cases of `write_result()` are the point of this module: SPEC §27's "Do not fake or
hard-code benchmark values" is only real if the writer *refuses*, so each refusal is asserted by
name rather than assumed.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import _common as common
import pytest

# -- percentiles -------------------------------------------------------------------------------


def test_percentile_is_nearest_rank_over_the_raw_samples() -> None:
    """HLD §7.0: nearest rank, `ceil(p/100 * n)`-th of the sorted samples — never interpolated."""
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert common.percentile_nearest_rank(values, 50) == 50
    assert common.percentile_nearest_rank(values, 95) == 100
    assert common.percentile_nearest_rank(values, 10) == 10
    assert common.percentile_nearest_rank([7], 99) == 7
    assert common.percentile_nearest_rank([], 50) is None


def test_every_aggregate_carries_its_n() -> None:
    payload = common.aggregate([3.0, 1.0, 2.0])
    assert payload["n"] == 3
    assert payload["p50"] == 2.0
    assert payload["max"] == 3.0
    empty = common.aggregate([])
    assert empty["n"] == 0 and empty["p50"] is None


def test_rate_over_booleans_carries_n() -> None:
    assert common.rate([True, False, True, True]) == {"n": 4, "rate": 0.75}
    assert common.rate([]) == {"n": 0, "rate": None}


# -- WER / CER with §7.2 numeral folding ---------------------------------------------------------


def test_numeral_folding_makes_27_and_dvadcat_sem_the_same_token() -> None:
    """`50-voice-pipeline.md` §7.2 step 5: a digit and its spelled-out form are one value."""
    assert common.fold("дом двадцать семь") == common.fold("дом 27")
    assert common.wer("улица Ленина дом двадцать семь", "улица ленина дом 27") == 0.0
    assert common.cer("дом двадцать семь", "дом 27") == 0.0


def test_wer_counts_a_wrong_number_as_an_error() -> None:
    assert common.wer("дом двадцать семь", "дом двадцать восемь") == pytest.approx(1 / 2)
    assert common.wer("", "") == 0.0
    assert common.wer("", "что-то") == 1.0


def test_entity_accuracy_is_none_when_the_reference_has_no_numbers() -> None:
    """A sample with no entity must not be scored 1.0 and inflate the mean."""
    assert common.entity_tokens("пожар в доме") == ()
    assert common.entity_accuracy("пожар в доме", "пожар в доме") is None
    assert (
        common.entity_accuracy("дом двадцать семь квартира пять", "дом 27 квартира восемь") == 0.5
    )


# -- the model-path mapping table (R1) -----------------------------------------------------------


def test_profile_paths_map_onto_the_models_root_first(tmp_path: Path) -> None:
    (tmp_path / "asr" / "gigaam-v3-e2e-ctc").mkdir(parents=True)
    path, exists = common.resolve_model_path("/models/asr/gigaam-v3-e2e-ctc", tmp_path)
    assert exists and path == tmp_path / "asr" / "gigaam-v3-e2e-ctc"


@pytest.mark.parametrize(
    ("profile_path", "legacy"),
    [
        ("/models/asr/gigaam-v3-e2e-ctc", "gigaam-v3-e2e_ctc"),
        ("/models/asr/gigaam-v3-ctc", "gigaam-v3-ctc"),
        ("/models/vad/silero_vad.onnx", "silero-vad/silero_vad.onnx"),
        ("/models/tts/piper/ru_RU-irina-medium.onnx", "piper/ru_RU-irina-medium.onnx"),
        ("/models/tts/qwen3-tts", "qwen3-tts"),
        ("/models/llm/Qwen3-4B-Q4_K_M.gguf", "Qwen3-4B-Q4_K_M.gguf"),
    ],
)
def test_the_legacy_layout_is_the_documented_fallback(
    tmp_path: Path, profile_path: str, legacy: str
) -> None:
    """Before `make models-layout` has run the files still sit under the flat download names."""
    target = tmp_path / legacy
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x") if target.suffix else target.mkdir(exist_ok=True)
    path, exists = common.resolve_model_path(profile_path, tmp_path)
    assert exists, f"{profile_path} did not fall back to {legacy}"
    assert path == target


def test_a_missing_model_reports_the_primary_path_and_does_not_exist(tmp_path: Path) -> None:
    path, exists = common.resolve_model_path("/models/llm/Nope-Q4_K_M.gguf", tmp_path)
    assert not exists and path == tmp_path / "llm" / "Nope-Q4_K_M.gguf"


def test_an_absolute_host_path_is_used_as_given(tmp_path: Path) -> None:
    """The owner's read-only GGUFs are pointed at directly, never mapped."""
    gguf = tmp_path / "Qwen3.5-2B-Q4_K_M.gguf"
    gguf.write_bytes(b"x")
    assert common.resolve_model_path(str(gguf), tmp_path) == (gguf, True)


# -- write_result: the honesty rule --------------------------------------------------------------


def _ok_envelope(**kwargs: object) -> common.Envelope:
    return common.Envelope(benchmark="unit", status="OK", profile="DEV_3060TI", **kwargs)


def test_write_result_writes_a_json_and_a_csv_whose_header_is_the_sample_keys(
    tmp_path: Path,
) -> None:
    envelope = _ok_envelope(
        samples=[{"id": "a", "latency_ms": 1.0}, {"id": "b", "latency_ms": 2.0, "extra": True}],
        aggregates={"latency_ms": common.aggregate([1.0, 2.0])},
    )
    json_path, csv_path = common.write_result(envelope, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert set(payload) == {
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
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["id", "latency_ms", "extra"]
    assert rows[1] == ["a", "1.0", ""]
    assert rows[2] == ["b", "2.0", "true"]


def test_write_result_refuses_an_aggregate_with_no_samples(tmp_path: Path) -> None:
    """RED 1 — the whole point of SPEC §27's rule."""
    envelope = _ok_envelope(samples=[], aggregates={"latency_ms": {"n": 0, "p50": 1.0}})
    with pytest.raises(common.BenchmarkHonestyError, match="no samples"):
        common.write_result(envelope, tmp_path)


def test_write_result_refuses_a_not_run_that_carries_numbers(tmp_path: Path) -> None:
    """RED 2 — `NOT_RUN` writes `samples: []`, `aggregates: {}` and never a number."""
    envelope = common.Envelope(
        benchmark="unit",
        status="NOT_RUN",
        profile="DEV_3060TI",
        reason="no model",
        samples=[{"id": "a"}],
    )
    with pytest.raises(common.BenchmarkHonestyError, match="NOT_RUN"):
        common.write_result(envelope, tmp_path)


def test_write_result_refuses_a_not_run_or_failed_with_no_reason(tmp_path: Path) -> None:
    """RED 3 — an unexplained non-result is not a result."""
    for status in ("NOT_RUN", "FAILED"):
        envelope = common.Envelope(benchmark="unit", status=status, profile="DEV_3060TI")
        with pytest.raises(common.BenchmarkHonestyError, match="requires a reason"):
            common.write_result(envelope, tmp_path)


def test_write_result_rejects_an_unknown_status(tmp_path: Path) -> None:
    envelope = common.Envelope(benchmark="unit", status="GREEN", profile="DEV_3060TI")
    with pytest.raises(common.BenchmarkHonestyError, match="status must be one of"):
        common.write_result(envelope, tmp_path)


# -- write_result: same-timestamp collisions never overwrite (E19-B2) ----------------------------


class _FixedClock(datetime):
    """A `datetime` subclass whose `.now()` always answers the same instant — used to force two
    `write_result()` calls into the exact same filename stamp, deterministically, without racing
    the real clock."""

    _FIXED = datetime(2026, 1, 1, 0, 0, 0, 123_000, tzinfo=UTC)

    @classmethod
    def now(cls, tz: object = None) -> datetime:
        return cls._FIXED


def test_write_result_filename_carries_millisecond_precision(tmp_path: Path) -> None:
    json_path, _csv_path = common.write_result(_ok_envelope(), tmp_path)
    # `benchmark-profile-YYYYMMDDTHHMMSSmmmZ.json` — 3 digits of milliseconds before the `Z`,
    # where the old format (`...SSZ`, second precision only) had none.
    stamp = json_path.stem.rsplit("-", 1)[-1]
    date_part, _, clock_part = stamp.partition("T")
    assert date_part.isdigit() and len(date_part) == 8  # YYYYMMDD
    assert clock_part.endswith("Z")
    assert clock_part[:-1].isdigit()
    assert len(clock_part) == len("000000123Z")  # HHMMSS + 3-digit ms + Z


def test_write_result_never_overwrites_a_same_millisecond_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED 4 — two runs finishing inside the same millisecond (E19-C hit this for real: it
    destroyed one of their results) must both survive, under a `-NN` counter suffix, never a
    silent overwrite."""
    monkeypatch.setattr(common, "datetime", _FixedClock)

    first_json, first_csv = common.write_result(_ok_envelope(), tmp_path)
    second_json, second_csv = common.write_result(_ok_envelope(), tmp_path)
    third_json, third_csv = common.write_result(_ok_envelope(), tmp_path)

    paths = {first_json, second_json, third_json, first_csv, second_csv, third_csv}
    assert len(paths) == 6, "every path must be distinct — nothing was overwritten"
    assert second_json.stem == first_json.stem + "-01"
    assert third_json.stem == first_json.stem + "-02"
    for path in paths:
        assert path.exists()


def test_write_result_refuses_once_every_collision_suffix_is_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counter itself is bounded (`COLLISION_SUFFIX_LIMIT`) — exhausting it is a refusal, not
    a silent pick-one-to-clobber. Shrunk to 2 so the test does not need to create 100 files."""
    monkeypatch.setattr(common, "datetime", _FixedClock)
    monkeypatch.setattr(common, "COLLISION_SUFFIX_LIMIT", 2)

    common.write_result(_ok_envelope(), tmp_path)  # the base stamp
    common.write_result(_ok_envelope(), tmp_path)  # "-01"
    common.write_result(_ok_envelope(), tmp_path)  # "-02" (the limit)
    with pytest.raises(common.BenchmarkHonestyError, match="collision suffixes"):
        common.write_result(_ok_envelope(), tmp_path)  # would need "-03" — refused


def test_not_run_builds_the_honest_empty_result() -> None:
    envelope = common.not_run("asr", "DEV_3060TI", "manifest not found: x")
    assert envelope.status == "NOT_RUN"
    assert envelope.samples == [] and envelope.aggregates == {}
    assert "manifest not found" in (envelope.reason or "")


def test_git_sha_is_a_sha_or_the_word_unknown() -> None:
    sha = common.git_sha()
    assert sha == "unknown" or (len(sha) == 40 and all(c in "0123456789abcdef" for c in sha))


def test_the_nvml_stub_is_deterministic_and_never_claims_a_real_card() -> None:
    sampler = common.NvmlSampler(stub=True)
    assert sampler.available and sampler.mode == "stub"
    assert sampler.read() == (0, 8192)

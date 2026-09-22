"""Shared machinery for the five SPEC §35 benchmark scripts (HLD `60-inference-ops.md` §7.0).

Everything the five scripts have in common lives here: the CLI shape, profile loading, the host
model-path mapping, NVML sampling, percentiles, WER/CER with Russian numeral folding, and — the
point of the module — `write_result()`, the **only** writer of a benchmark result.

`write_result()` is where SPEC §27's "Do not fake or hard-code benchmark values" is mechanical
rather than aspirational: it raises `BenchmarkHonestyError` rather than emit an aggregate that no
sample backs, a `NOT_RUN` result that carries numbers, or a `NOT_RUN`/`FAILED` result with no
reason. A benchmark that could not run writes `status: "NOT_RUN"`, a `reason`, `samples: []` and
`aggregates: {}` — there is no default, no estimate and no carried-over figure.

**Dev tooling, not product code.** These scripts import `app.*` (and, for the E2E benchmark,
`voice_agent.*`) through the ports the product uses — they never reach past them for a number
(SPEC §44, D13/R13). `backend/` is inserted on `sys.path` by `ensure_backend_on_path()` so the
`backend/tests/adversarial/` §43 attack matrix and the voice-pipeline test helpers can be *reused*
rather than duplicated (HLD §7.2 says so in as many words); that is a deliberate dev-tooling
allowance, documented here and in `benchmarks/README.md`, and it is the only place it happens.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "COLLISION_SUFFIX_LIMIT",
    "DEFAULT_MODELS_ROOT",
    "DEFAULT_OUT_DIR",
    "DEFAULT_PROFILE",
    "LEGACY_MODEL_PATHS",
    "REPO_ROOT",
    "SCHEMA_VERSION",
    "BenchmarkHonestyError",
    "Envelope",
    "NvmlSampler",
    "aggregate",
    "cer",
    "ensure_backend_on_path",
    "entity_tokens",
    "fold",
    "git_sha",
    "load_jsonl",
    "load_profile_for_bench",
    "now_iso",
    "parse_common_args",
    "percentile_nearest_rank",
    "resolve_model_path",
    "wer",
    "write_result",
]

#: Bumped only when the envelope's own shape changes (HLD §7.0).
SCHEMA_VERSION = 1

#: `…/112-maxxing` — this file is `benchmarks/_common.py`.
REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OUT_DIR = REPO_ROOT / "benchmarks" / "results"
DEFAULT_MODELS_ROOT = REPO_ROOT / "models"
#: HLD §7.0 says "default `$MODEL_PROFILE`"; the env var the product actually reads is
#: `SIM_MODEL_PROFILE` (`app.config.settings.Settings.model_profile`), so both are honoured, the
#: `SIM_`-prefixed one first, and `DEV_3060TI` is the fallback (R1).
DEFAULT_PROFILE = "DEV_3060TI"

_STATUSES = ("OK", "PARTIAL", "FAILED", "NOT_RUN")


class BenchmarkHonestyError(RuntimeError):
    """`write_result()` refused to write a result that would state an unmeasured number."""


# ---------------------------------------------------------------------------------------------
# sys.path / imports
# ---------------------------------------------------------------------------------------------


def ensure_backend_on_path() -> None:
    """Put `backend/` on `sys.path` so `tests.adversarial.*` (the §43 matrix, HLD §7.2) and the
    voice-pipeline test helpers can be imported instead of copied.

    `app.*` itself is a normal workspace dependency (`benchmarks/pyproject.toml` depends on
    `sim-backend`), so this is only ever about the `tests.*` package, which is not installed.
    """
    backend = str(REPO_ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------


def parse_common_args(
    name: str,
    argv: Sequence[str] | None = None,
    *,
    extra: Any = None,
    description: str = "",
) -> argparse.Namespace:
    """The HLD §7.0 CLI, plus R1's two additive flags, plus whatever `extra(parser)` adds.

    `--profile NAME` (default `$SIM_MODEL_PROFILE`/`$MODEL_PROFILE`, falling back to
    `DEV_3060TI`), `--out DIR`, `--runs N`, `--seed N`, `--tag TEXT`; additive:
    `--provider fake|real` (default `real`; `fake` is what the gate exercises, D13) and
    `--models-root DIR` (the host layout the profile's `/models/...` paths are mapped onto).
    """
    parser = argparse.ArgumentParser(prog=f"benchmark_{name}.py", description=description or name)
    parser.add_argument(
        "--profile",
        default=os.environ.get("SIM_MODEL_PROFILE")
        or os.environ.get("MODEL_PROFILE")
        or DEFAULT_PROFILE,
        help="model profile name (default: $SIM_MODEL_PROFILE, else DEV_3060TI)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="directory the JSON+CSV pair is written to (default: benchmarks/results/)",
    )
    parser.add_argument("--runs", type=int, default=1, help="repetitions of the whole corpus")
    parser.add_argument("--seed", type=int, default=0, help="seed for every random choice")
    parser.add_argument("--tag", default="", help="free-text tag recorded in the envelope config")
    parser.add_argument(
        "--provider",
        choices=("fake", "real"),
        default="real",
        help="`fake` runs the D13 fake providers (what the gate exercises); `real` loads models",
    )
    parser.add_argument(
        "--models-root",
        type=Path,
        default=DEFAULT_MODELS_ROOT,
        help="host directory the profile's /models/<kind>/<file> paths are resolved against",
    )
    if extra is not None:
        extra(parser)
    return parser.parse_args(list(argv) if argv is not None else None)


def load_profile_for_bench(name: str) -> Any:
    """`app.config.profile.load_profile(name)`; an unknown/invalid profile exits 2 with its message.

    A `ProfileRefused` is *not* caught here — a refused profile is a legitimate benchmark outcome
    (`status: NOT_RUN`, the refusal as `reason`), and only the caller knows that. Loading is what
    this wrapper owns; refusal is the script's own business (`validate_vram_margin`).
    """
    from app.config.profile import load_profile

    try:
        return load_profile(name)
    except Exception as exc:
        print(f"benchmark: --profile {name!r} could not be loaded: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


# ---------------------------------------------------------------------------------------------
# Model paths: the profile's compose paths -> this host's layout (R1)
# ---------------------------------------------------------------------------------------------

#: The profile YAMLs name container paths (`/models/<kind>/<file>`), which `make models-layout`
#: (E19-F) materialises under the host `models/` directory. The primary mapping is therefore the
#: trivial one: `/models/<rest>` -> `<models_root>/<rest>`.
#:
#: Until that layout step has been run, the files are still under the flat names the individual
#: `make models-*` targets downloaded them to (recon §5). This table is that fallback, keyed by
#: the path *relative to* `/models/`, most specific first. It is a documented mapping of what is
#: actually on disk today — never a guess: a path that resolves to neither form is reported as
#: missing and the benchmark writes `NOT_RUN` with the path in `reason`.
LEGACY_MODEL_PATHS: tuple[tuple[str, str], ...] = (
    ("asr/gigaam-v3-e2e-ctc", "gigaam-v3-e2e_ctc"),
    ("asr/gigaam-v3-ctc", "gigaam-v3-ctc"),
    ("vad/silero_vad.onnx", "silero-vad/silero_vad.onnx"),
    ("tts/piper", "piper"),
    ("tts/qwen3-tts", "qwen3-tts"),
    ("warmup/warmup_ru.wav", "warmup/warmup_ru.wav"),
    # The GGUFs `make models-llm*` fetches land in `models/llm/`; the one that predates that
    # target (recon §5) sits at the top level under its bare file name.
    ("llm", ""),
)


def resolve_model_path(profile_path: str, models_root: Path) -> tuple[Path, bool]:
    """Map a profile's `/models/<kind>/<file>` onto this host, returning `(host_path, exists)`.

    A path that is not under `/models/` is returned as-is (an operator may point a profile at an
    absolute host path — the owner's read-only GGUFs are used exactly that way, through
    `--model-path`). `exists` is the caller's cue to write `NOT_RUN` with the path in `reason`
    rather than invent a number.
    """
    raw = str(profile_path)
    if not raw.startswith("/models/"):
        candidate = Path(raw).expanduser()
        return candidate, candidate.exists()
    rest = raw[len("/models/") :]
    primary = models_root / rest
    if primary.exists():
        return primary, True
    for prefix, replacement in LEGACY_MODEL_PATHS:
        if rest == prefix or rest.startswith(prefix + "/"):
            tail = rest[len(prefix) :].lstrip("/")
            legacy_rel = "/".join(part for part in (replacement, tail) if part)
            legacy = models_root / legacy_rel if legacy_rel else models_root
            if legacy.exists():
                return legacy, True
    return primary, False


# ---------------------------------------------------------------------------------------------
# NVML sampling (HLD §7.0 "NVML sampling"; reuses the strategy of app/cli/preflight.py)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GpuFacts:
    """What the envelope's `hardware` block carries."""

    gpu_name: str | None
    driver: str | None
    total_vram_mb: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "gpu_name": self.gpu_name,
            "driver": self.driver,
            "total_vram_mb": self.total_vram_mb,
        }


class NvmlSampler:
    """Polls used/free VRAM every `interval_ms` on a background thread.

    `pynvml` when it imports (`nvidia-ml-py` is a `sim-benchmarks` dependency), else the
    `nvidia-smi` CSV path `app/cli/preflight.py` already falls back to, else `available=False`
    — which `benchmark_vram.py` turns into `status: "NOT_RUN", reason: "NVML unavailable"`
    (HLD §7.5) rather than a zero.
    """

    def __init__(self, *, interval_ms: int = 100, stub: bool = False) -> None:
        self._interval_s = max(interval_ms, 1) / 1000.0
        self._stub = stub
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        #: Every `(used_mb, free_mb)` sample, in order.
        self.samples: list[tuple[int, int]] = []
        self._handle: Any = None
        self._pynvml: Any = None
        self._facts = GpuFacts(None, None, None)
        self._mode = "unavailable"
        if stub:
            self._mode = "stub"
            self._facts = GpuFacts("STUB-GPU", "stub", 8192)
        else:
            self._probe()

    # -- discovery ----------------------------------------------------------------------------

    def _probe(self) -> None:
        try:
            import pynvml  # type: ignore[import-not-found]

            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            driver = pynvml.nvmlSystemGetDriverVersion()
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            self._pynvml = pynvml
            self._handle = handle
            self._mode = "pynvml"
            self._facts = GpuFacts(_text(name), _text(driver), int(info.total // (1024 * 1024)))
            return
        except Exception:
            self._pynvml = None
            self._handle = None
        row = _nvidia_smi(("name", "driver_version", "memory.total"))
        if row is not None and len(row) == 3:
            self._mode = "nvidia-smi"
            self._facts = GpuFacts(row[0], row[1], _int_or_none(row[2]))

    # -- the port -----------------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """False when neither pynvml nor `nvidia-smi` answered — no number may be reported."""
        return self._mode != "unavailable"

    @property
    def mode(self) -> str:
        """`pynvml` | `nvidia-smi` | `stub` | `unavailable` — recorded in `notes`."""
        return self._mode

    @property
    def hardware(self) -> dict[str, Any]:
        return self._facts.as_dict()

    def read(self) -> tuple[int, int] | None:
        """One `(used_mb, free_mb)` reading, or `None` when no sampler is available."""
        if self._mode == "stub":
            return (0, 8192)
        if self._mode == "pynvml" and self._pynvml is not None:
            try:
                info = self._pynvml.nvmlDeviceGetMemoryInfo(self._handle)
                mib = 1024 * 1024
                return (int(info.used // mib), int(info.free // mib))
            except Exception:
                return None
        if self._mode == "nvidia-smi":
            row = _nvidia_smi(("memory.used", "memory.free"))
            if row is not None and len(row) == 2:
                used, free = _int_or_none(row[0]), _int_or_none(row[1])
                if used is not None and free is not None:
                    return (used, free)
        return None

    def start(self) -> None:
        """Begin polling. A no-op when no sampler is available."""
        if not self.available or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="nvml-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> tuple[int | None, int]:
        """Stop polling; returns `(peak_used_mb, n_samples)` (`None` when nothing was sampled)."""
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=5)
            self._thread = None
        return (self.peak_used_mb, len(self.samples))

    @property
    def peak_used_mb(self) -> int | None:
        return max((used for used, _ in self.samples), default=None)

    @property
    def min_free_mb(self) -> int | None:
        return min((free for _, free in self.samples), default=None)

    def _loop(self) -> None:
        while not self._stop.is_set():
            reading = self.read()
            if reading is not None:
                self.samples.append(reading)
            self._stop.wait(self._interval_s)


def _text(value: Any) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value) if value is not None else None


def _int_or_none(value: str) -> int | None:
    try:
        return int(float(value.strip()))
    except (TypeError, ValueError):
        return None


def _nvidia_smi(fields: Sequence[str]) -> list[str] | None:
    binary = shutil.which("nvidia-smi")
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    first = completed.stdout.strip().splitlines()[0]
    return [part.strip() for part in first.split(",")]


# ---------------------------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------------------------


def percentile_nearest_rank(values: Sequence[float], p: float) -> float | None:
    """The nearest-rank percentile HLD §7.0 mandates: `ceil(p/100 * n)`-th of the sorted samples."""
    if not values:
        return None
    if not 0 < p <= 100:
        raise ValueError("p must be in (0, 100]")
    ordered = sorted(values)
    rank = math.ceil(p / 100.0 * len(ordered))
    return float(ordered[max(1, min(rank, len(ordered))) - 1])


def aggregate(values: Sequence[float]) -> dict[str, Any]:
    """`{n, p50, p95, p99, mean, max}` over raw samples; every aggregate carries its `n`."""
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return {"n": 0, "p50": None, "p95": None, "p99": None, "mean": None, "max": None}
    return {
        "n": len(numeric),
        "p50": percentile_nearest_rank(numeric, 50),
        "p95": percentile_nearest_rank(numeric, 95),
        "p99": percentile_nearest_rank(numeric, 99),
        "mean": sum(numeric) / len(numeric),
        "max": max(numeric),
    }


def rate(flags: Sequence[bool]) -> dict[str, Any]:
    """`{n, rate}` over booleans — the shape every `*_rate` aggregate uses."""
    if not flags:
        return {"n": 0, "rate": None}
    return {"n": len(flags), "rate": sum(1 for flag in flags if flag) / len(flags)}


# ---------------------------------------------------------------------------------------------
# WER / CER with the Russian numeral folding of 50-voice-pipeline.md §7.2
# ---------------------------------------------------------------------------------------------


def fold(text: str) -> tuple[str, ...]:
    """Tokenise and numeral-fold `text` with the product's own §7.2 normaliser.

    Reused, not reimplemented: `app.application.dialogue.text_normalization.normalize_text` is
    what the forbidden-value check (§7.6) and the validator already run on, so a benchmark and the
    product cannot disagree about whether «27» and «двадцать семь» are the same value.
    """
    from app.application.dialogue.text_normalization import normalize_text

    parsed = normalize_text(text)
    #: `NumberRun` carries the canonical value and the token span it was folded from; replacing
    #: each run by its one value is exactly §7.2 step 5's digit/word equivalence.
    replacement = {run.first_index: run.value for run in parsed.numbers}
    swallowed = {
        index for run in parsed.numbers for index in range(run.first_index + 1, run.last_index + 1)
    }
    folded: list[str] = []
    for token in parsed.tokens:
        if token.index in swallowed:
            continue
        folded.append(replacement.get(token.index, token.text))
    return tuple(folded)


def _levenshtein(reference: Sequence[Any], hypothesis: Sequence[Any]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, start=1):
        current = [i]
        for j, hyp in enumerate(hypothesis, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref != hyp)))
        previous = current
    return previous[-1]


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate over §7.2-folded tokens. An empty reference scores 0.0 for an empty
    hypothesis and 1.0 for anything else."""
    ref = fold(reference)
    hyp = fold(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate over the §7.2-folded token strings joined by a single space."""
    ref = " ".join(fold(reference))
    hyp = " ".join(fold(hypothesis))
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


def entity_tokens(reference: str) -> tuple[str, ...]:
    """The reference's ENTITY tokens for `entity_accuracy` (HLD §7.1).

    **The rule, stated once:** an entity token is a token whose §7.2 folding produced a canonical
    *number* (so «двадцать семь» and «27» are one entity, `27`). Numbers are what a dispatcher
    card is graded on — house, apartment, floor, entrance, victim counts — and they are the only
    class §7.2 canonicalises, so they are the only class a benchmark can compare without a
    second, hand-written lexicon. Street and surname tokens are covered by `wer`/`cer`, which is
    why `entity_accuracy` does not double-count them.
    """
    from app.application.dialogue.text_normalization import normalize_text

    return tuple(run.value for run in normalize_text(reference).numbers)


def entity_accuracy(reference: str, hypothesis: str) -> float | None:
    """Fraction of the reference's entity tokens present in the hypothesis; `None` when there are
    none (a sample with no numbers must not be scored 1.0 and inflate the mean)."""
    entities = entity_tokens(reference)
    if not entities:
        return None
    found = set(fold(hypothesis))
    return sum(1 for entity in entities if entity in found) / len(entities)


# ---------------------------------------------------------------------------------------------
# The envelope and the one writer
# ---------------------------------------------------------------------------------------------


@dataclass
class Envelope:
    """HLD §7.0's envelope, field for field (`reason` is additive, and required by §7.0's own
    `NOT_RUN` rule)."""

    benchmark: str
    status: str
    profile: str
    config: dict[str, Any] = field(default_factory=dict)
    samples: list[dict[str, Any]] = field(default_factory=list)
    aggregates: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    hardware: dict[str, Any] = field(
        default_factory=lambda: {"gpu_name": None, "driver": None, "total_vram_mb": None}
    )
    reason: str | None = None
    started_at: str = field(default_factory=lambda: now_iso())
    finished_at: str | None = None
    git_sha: str = field(default_factory=lambda: git_sha())
    schema_version: int = SCHEMA_VERSION

    def note(self, text: str) -> None:
        self.notes.append(text)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "status": self.status,
            "profile": self.profile,
            "git_sha": self.git_sha,
            "started_at": self.started_at,
            "finished_at": self.finished_at or now_iso(),
            "hardware": dict(self.hardware),
            "config": dict(self.config),
            "samples": list(self.samples),
            "aggregates": dict(self.aggregates),
            "notes": list(self.notes),
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


def not_run(benchmark: str, profile: str, reason: str, **kwargs: Any) -> Envelope:
    """The honest empty result: `NOT_RUN`, a reason, no samples, no aggregates, zero numbers."""
    return Envelope(benchmark=benchmark, status="NOT_RUN", profile=profile, reason=reason, **kwargs)


#: `write_result()`'s collision-suffix search width (E19-B2: two runs finishing inside the same
#: millisecond — two `--provider fake` gate runs racing, or two phase-2 workers launching within
#: the same millisecond under GPU-lock contention — must never silently overwrite one another's
#: result). A module-level constant, not a magic number in the loop, so a test can shrink it
#: cheaply to exercise the "even the counter is exhausted" refusal without creating 100 files.
COLLISION_SUFFIX_LIMIT = 100


def write_result(envelope: Envelope, out_dir: Path) -> tuple[Path, Path]:
    """The ONLY writer of a benchmark result (HLD §7.0). Returns `(json_path, csv_path)`.

    Refuses, with `BenchmarkHonestyError`:

    1. an aggregate with no sample behind it (`aggregates` non-empty, `samples` empty);
    2. a `NOT_RUN` result carrying any sample or any aggregate;
    3. a `NOT_RUN` or `FAILED` result with no `reason`;
    4. overwriting an existing result file (E19-B2: `write_result` found two runs that finished
       within the same second destroy one another's JSON/CSV — the timestamp now carries
       millisecond precision, and a `-NN` counter is appended when even that collides; if
       `COLLISION_SUFFIX_LIMIT` counters are all taken too — practically never — this raises
       rather than pick one to clobber).
    """
    if envelope.status not in _STATUSES:
        raise BenchmarkHonestyError(f"status must be one of {_STATUSES}, got {envelope.status!r}")
    if envelope.status == "NOT_RUN" and (envelope.samples or envelope.aggregates):
        raise BenchmarkHonestyError(
            "NOT_RUN must carry no samples and no aggregates (SPEC §27): "
            f"{len(envelope.samples)} samples, {len(envelope.aggregates)} aggregates"
        )
    if envelope.aggregates and not envelope.samples:
        raise BenchmarkHonestyError(
            "refusing to write an aggregate with no samples behind it (SPEC §27)"
        )
    if envelope.status in ("NOT_RUN", "FAILED") and not envelope.reason:
        raise BenchmarkHonestyError(f"status {envelope.status} requires a reason string")

    payload = envelope.as_dict()
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    # Millisecond precision (not just seconds): `benchmark-profile-YYYYMMDDTHHMMSSmmmZ`.
    stamp = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"
    stem = f"{envelope.benchmark}-{envelope.profile}-{stamp}"
    json_path = out_dir / f"{stem}.json"
    csv_path = out_dir / f"{stem}.csv"
    if json_path.exists() or csv_path.exists():
        json_path, csv_path = _next_free_pair(out_dir, stem)

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(csv_path, envelope.samples)
    return json_path, csv_path


def _next_free_pair(out_dir: Path, stem: str) -> tuple[Path, Path]:
    """The first `-NN` suffix of `stem` whose JSON *and* CSV path are both free. Raises
    `BenchmarkHonestyError` rather than return a path that already exists — `write_result` never
    silently overwrites a prior run's result."""
    for suffix in range(1, COLLISION_SUFFIX_LIMIT + 1):
        candidate_stem = f"{stem}-{suffix:02d}"
        candidate_json = out_dir / f"{candidate_stem}.json"
        candidate_csv = out_dir / f"{candidate_stem}.csv"
        if not candidate_json.exists() and not candidate_csv.exists():
            return candidate_json, candidate_csv
    raise BenchmarkHonestyError(
        f"refusing to overwrite an existing result: {out_dir / stem}.json "
        f"({COLLISION_SUFFIX_LIMIT} collision suffixes all taken)"
    )


def _write_csv(path: Path, samples: Sequence[Mapping[str, Any]]) -> None:
    """Flat per-sample rows; the header is the union of sample keys in first-seen order."""
    header: list[str] = []
    for sample in samples:
        for key in sample:
            if key not in header:
                header.append(key)
    if not header:
        # A `NOT_RUN`/`FAILED` result has no rows; the CSV is created and left empty rather than
        # carrying a lone blank header line that a reader could mistake for a column-less table.
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        for sample in samples:
            writer.writerow({key: _csv_value(sample.get(key)) for key in header})


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple | dict):
        return json.dumps(value, ensure_ascii=False)
    return value


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def git_sha() -> str:
    """`git rev-parse HEAD`, or `"unknown"` — never a crash and never a fabricated value."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = completed.stdout.strip()
    return sha if completed.returncode == 0 and sha else "unknown"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a `.jsonl` corpus file. Blank lines are skipped; a bad line names itself."""
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
    return rows


def elapsed_ms(started: float) -> float:
    """Milliseconds since a `time.perf_counter()` mark."""
    return (time.perf_counter() - started) * 1000.0


def finish(envelope: Envelope, out_dir: Path, *, quiet: bool = False) -> int:
    """Stamp `finished_at`, write both files, print where they went. Returns a process exit code.

    `NOT_RUN` and `PARTIAL` exit 0: they are *honest results*, not failures of the run. Only
    `FAILED` — the benchmark tried and the measurement itself broke — exits non-zero.
    """
    envelope.finished_at = now_iso()
    json_path, csv_path = write_result(envelope, out_dir)
    if not quiet:
        print(f"{envelope.benchmark}: {envelope.status}", file=sys.stderr)
        if envelope.reason:
            print(f"  reason: {envelope.reason}", file=sys.stderr)
        print(f"  {json_path}", file=sys.stderr)
        print(f"  {csv_path}", file=sys.stderr)
    return 1 if envelope.status == "FAILED" else 0


def profile_config_subtree(profile: Any, *blocks: str) -> dict[str, Any]:
    """The relevant profile subtree for the envelope's `config` (HLD §7.0)."""
    payload: dict[str, Any] = {"profile_name": getattr(profile, "profile_name", None)}
    for block in blocks:
        value = getattr(profile, block, None)
        if value is None:
            continue
        payload[block] = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return payload


def iter_runs(items: Sequence[Any], runs: int) -> Iterable[tuple[int, Any]]:
    """`(run_index, item)` for `--runs N` repetitions of the corpus, in order."""
    for run_index in range(max(1, runs)):
        for item in items:
            yield run_index, item

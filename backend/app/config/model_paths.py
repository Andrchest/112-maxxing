"""`resolve_model_path` — the ONE mapping from a profile's model path onto this host (E20 R15).

A model profile (`app.config.profile`, HLD 60 §2) names its weights with **container** paths:
`/models/llm/Qwen3.5-2B-Q4_K_M.gguf`, `/models/asr/gigaam-v3-e2e-ctc`,
`/models/vad/silero_vad.onnx`, `/models/tts/piper/ru_RU-irina-medium.onnx`. Under
`infra/docker-compose.yml` that is exactly where the host's `models/` directory is mounted, so the
path is literally correct and nothing has to be resolved.

Off compose it is not. A **host run** — `make run-voice-agent`, `make run-tts-qwen3`,
`uv run python -m app.cli.preflight` — has the same files under the repository's own `models/`
directory and nothing at `/models`. Until E20 the voice agent and preflight check 3 opened the
container path regardless: every component's warm-up failed with `ModelNotAvailableError`, all four
went FATAL, and the agent served nothing while looking healthy. E19-E3 measured that verbatim and
worked around it by exporting the three `SIM_*` paths by hand; preflight check 3 simply always
FAILed on a host run.

`benchmarks/_common.resolve_model_path` + `--models-root` had already solved this for the five
benchmark scripts. This module is that function, moved down into the application so the product
uses it too — `benchmarks/_common` now re-exports from here, so there is exactly one mapping table
in the workspace and the benchmarks cannot drift from the agent.

The root comes from `Settings.models_root` (`SIM_MODELS_ROOT`), whose default is `/models`: compose
is unchanged and needs no new variable, while a host run sets `SIM_MODELS_ROOT=./models`.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["CONTAINER_MODELS_PREFIX", "LEGACY_MODEL_PATHS", "resolve_model_path"]

#: The prefix a profile path must start with to be a container path at all.
CONTAINER_MODELS_PREFIX = "/models/"

#: The profile YAMLs name container paths (`/models/<kind>/<file>`), which `make models-layout`
#: (E19-F) materialises under the host `models/` directory. The primary mapping is therefore the
#: trivial one: `/models/<rest>` -> `<models_root>/<rest>`.
#:
#: Until that layout step has been run, the files are still under the flat names the individual
#: `make models-*` targets downloaded them to. This table is that fallback, keyed by the path
#: *relative to* `/models/`, most specific first. It is a documented mapping of what is actually on
#: disk today — never a guess: a path that resolves to neither form is reported as missing, and the
#: caller (a benchmark, the preflight, a provider) says so rather than inventing a number or a file.
LEGACY_MODEL_PATHS: tuple[tuple[str, str], ...] = (
    ("asr/gigaam-v3-e2e-ctc", "gigaam-v3-e2e_ctc"),
    ("asr/gigaam-v3-ctc", "gigaam-v3-ctc"),
    ("vad/silero_vad.onnx", "silero-vad/silero_vad.onnx"),
    ("tts/piper", "piper"),
    ("tts/qwen3-tts", "qwen3-tts"),
    ("warmup/warmup_ru.wav", "warmup/warmup_ru.wav"),
    # The GGUFs `make models-llm*` fetches land in `models/llm/`; the one that predates that
    # target sits at the top level under its bare file name.
    ("llm", ""),
)


def resolve_model_path(profile_path: str, models_root: Path) -> tuple[Path, bool]:
    """Map a profile's `/models/<kind>/<file>` onto this host, returning `(host_path, exists)`.

    A path that is not under `/models/` is returned as-is (an operator may point a profile at an
    absolute host path — the owner's read-only GGUFs are used exactly that way, through
    `--model-path`). `exists` is the caller's cue to report the path as missing rather than to
    invent a number or open a file that is not there.
    """
    raw = str(profile_path)
    if not raw.startswith(CONTAINER_MODELS_PREFIX):
        candidate = Path(raw).expanduser()
        return candidate, candidate.exists()
    rest = raw[len(CONTAINER_MODELS_PREFIX) :]
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


def host_model_path(profile_path: str, models_root: str) -> str:
    """`resolve_model_path`'s path alone, as a string — what a provider constructor wants.

    A path that resolves to nothing on this host is returned in its **primary** mapped form rather
    than left as the container path: the component then fails with a message naming a path an
    operator can actually look for, instead of one that only exists inside a container.
    """
    resolved, _exists = resolve_model_path(profile_path, Path(models_root).expanduser())
    return str(resolved)

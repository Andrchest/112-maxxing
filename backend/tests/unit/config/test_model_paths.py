"""`SIM_MODELS_ROOT` and the one model-path resolver every process shares (E20 R15).

A model profile names **container** paths (`/models/asr/gigaam-v3-e2e-ctc`), which is where
`infra/docker-compose.yml` mounts the host's `models/` directory. On a host run those paths do not
exist: E19-E2/E3 measured a voice agent whose four components all went FATAL with
`ModelNotAvailableError` while reporting itself healthy, and an `app/cli/preflight.py` check 3 that
FAILed no matter what was installed. `benchmarks/_common.resolve_model_path` already solved it for
the benchmark scripts; R15 moved that function into `app.config.model_paths` so the product uses
the same one.
"""

from __future__ import annotations

from pathlib import Path

from app.config.model_paths import host_model_path, resolve_model_path
from app.config.settings import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
        "redis_url": "redis://localhost:56379/0",
        "jwt_secret": "test-only-secret-padded-32-bytes!",
        "livekit_url": "ws://localhost:7880",
        "livekit_api_key": "devkey",
        "livekit_api_secret": "devsecret1234567890",
        "llm_base_url": "http://localhost:8080/v1",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_the_default_models_root_is_the_container_one_so_compose_is_unchanged() -> None:
    """Compose mounts the models at `/models`; the default must keep that a no-op."""
    assert _settings().models_root == "/models"
    silero = "/models/vad/silero_vad.onnx"
    assert host_model_path(silero, "/models") == silero


def test_a_container_path_is_rebased_onto_the_host_models_root(tmp_path: Path) -> None:
    """The host-run case: the same file, under this machine's `models/` directory."""
    target = tmp_path / "asr" / "gigaam-v3-e2e-ctc"
    target.mkdir(parents=True)

    path, exists = resolve_model_path("/models/asr/gigaam-v3-e2e-ctc", tmp_path)

    assert (path, exists) == (target, True)
    assert host_model_path("/models/asr/gigaam-v3-e2e-ctc", str(tmp_path)) == str(target)


def test_the_legacy_download_layout_is_still_found(tmp_path: Path) -> None:
    """Before `make models-layout` has run, the files sit under their download names."""
    legacy = tmp_path / "silero-vad" / "silero_vad.onnx"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"x")

    assert resolve_model_path("/models/vad/silero_vad.onnx", tmp_path) == (legacy, True)


def test_a_missing_file_resolves_to_the_primary_mapping_and_says_so(tmp_path: Path) -> None:
    """The caller must be able to print a path an operator can look for on this machine."""
    path, exists = resolve_model_path("/models/llm/Nope-Q4_K_M.gguf", tmp_path)

    assert exists is False
    assert path == tmp_path / "llm" / "Nope-Q4_K_M.gguf"
    # Never the container path: that one only exists inside a container.
    assert not str(path).startswith("/models/")


def test_an_absolute_host_path_is_left_alone(tmp_path: Path) -> None:
    """An operator may point a profile straight at a host file (the owner's read-only GGUFs)."""
    gguf = tmp_path / "Qwen3-4B-Q4_K_M.gguf"
    gguf.write_bytes(b"x")

    assert resolve_model_path(str(gguf), tmp_path / "elsewhere") == (gguf, True)
    assert host_model_path(str(gguf), str(tmp_path / "elsewhere")) == str(gguf)


def test_the_legacy_table_is_the_one_the_benchmarks_re_export() -> None:
    """R15's point: one mapping in the workspace, so the scripts cannot drift from the agent.

    `benchmarks/` is not importable from the backend test run (it is a separate workspace member
    with its own `sys.path` bootstrap), so the identity is asserted from the benchmark side, in
    `benchmarks/tests/test_bench_common.py`. What is asserted here is that the table this module
    owns is the one with the legacy download names in it.
    """
    from app.config.model_paths import LEGACY_MODEL_PATHS

    assert ("vad/silero_vad.onnx", "silero-vad/silero_vad.onnx") in LEGACY_MODEL_PATHS
    assert ("llm", "") in LEGACY_MODEL_PATHS

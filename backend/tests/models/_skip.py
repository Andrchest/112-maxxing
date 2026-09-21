"""Shared skip gate for `requires_models` contract tests (E12 ruling 1).

A test in `backend/tests/models/` only actually runs when all three hold:

1. `SIM_RUN_MODEL_TESTS=1` is set — never set by `make gate`, only by `make test-models`;
2. every package it needs actually imports (the `asr-gigaam`/`asr-whisper`/`vad-silero` extras);
3. every model path it needs actually exists on disk.

Anything short of that is a `pytest.skip`, never a failure: a developer (or CI runner) without the
extras/weights still gets a green `make gate`, and `make test-models` itself explains *why* a test
did not run rather than erroring on an `ImportError` or a `FileNotFoundError`.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

__all__ = ["require_model_env"]


def require_model_env(
    *, packages: tuple[str, ...] = (), paths: tuple[str | Path, ...] = ()
) -> None:
    """Skip the calling test unless the env var, every package and every path are all present."""
    if os.environ.get("SIM_RUN_MODEL_TESTS") != "1":
        pytest.skip("SIM_RUN_MODEL_TESTS != 1 (run via `make test-models`)")
    for package in packages:
        try:
            importlib.import_module(package)
        except ImportError as exc:
            pytest.skip(f"{package!r} is not importable ({exc}); run `make deps-models`")
    for path in paths:
        if not Path(path).exists():
            pytest.skip(f"model path missing: {path}")

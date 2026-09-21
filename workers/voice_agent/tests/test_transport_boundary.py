"""The LiveKit import boundary, proven from the worker's side (D9, D2, SPEC §15).

SPEC §15 says "Domain logic must not import LiveKit objects" and D9 narrows it to one module:
`workers/voice_agent/voice_agent/transport/` is the only place in the workspace that may import
the `livekit` SDK, and the framework package `livekit.agents` is forbidden even there (it brings
its own session, turn-detection and pipeline abstractions, which would quietly compete with the
`TurnPipeline` of `50-voice-pipeline.md`).

A rule nobody can break is not a rule that was checked — so each test here **sabotages** the tree
and asserts that `backend/tools/check_imports.py` reports it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from tools.check_imports import main  # noqa: E402


def _run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    exit_code = main(["--root", str(root)])
    return exit_code, capsys.readouterr().out


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal workspace: the transport package, one backend module, one worker module."""
    for rel in (
        "backend/app/domain",
        "backend/app/application",
        "backend/tests/unit",
        "workers/voice_agent/voice_agent/transport",
        "workers/voice_agent/tests",
        "benchmarks",
    ):
        directory = tmp_path / rel
        directory.mkdir(parents=True, exist_ok=True)
        if rel.startswith(("backend/app", "workers/voice_agent/voice_agent")):
            (directory / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "workers/voice_agent/voice_agent/transport/livekit_transport.py").write_text(
        "import livekit\nfrom livekit import rtc\n", encoding="utf-8"
    )
    return tmp_path


def test_the_transport_package_may_import_the_sdk(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole point of the boundary: one module is allowed, and it is this one."""
    exit_code, out = _run(tree, capsys)
    assert exit_code == 0, out


def test_the_transport_package_may_not_import_the_agents_framework(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D9: "plain `livekit` rtc + `livekit-api`, NOT the livekit-agents framework"."""
    (tree / "workers/voice_agent/voice_agent/transport/sabotage.py").write_text(
        "from livekit.agents import VoicePipelineAgent\n", encoding="utf-8"
    )
    exit_code, out = _run(tree, capsys)
    assert exit_code == 1
    assert "must not import livekit.agents" in out


@pytest.mark.parametrize(
    "relative_path",
    [
        "backend/app/domain/sabotage.py",
        "backend/app/application/sabotage.py",
        "backend/tests/unit/test_sabotage.py",
        "workers/voice_agent/voice_agent/sabotage.py",
        "workers/voice_agent/tests/test_sabotage.py",
        "benchmarks/sabotage.py",
    ],
)
def test_livekit_is_refused_everywhere_else(
    tree: Path, capsys: pytest.CaptureFixture[str], relative_path: str
) -> None:
    """Every other corner of the workspace, including the test trees (this task's ruling 2).

    The backend mints LiveKit access tokens as plain HS256 JWTs with `pyjwt`, so it needs nothing
    from the SDK — and an `import livekit` in `backend/tests/**` would make the dependency real
    while passing every layer rule, because a test file has no dotted package name to key on.
    """
    (tree / relative_path).write_text("import livekit\n", encoding="utf-8")
    exit_code, out = _run(tree, capsys)
    assert exit_code == 1, out
    assert "must not import livekit" in out
    assert relative_path in out


def test_the_real_repository_has_exactly_one_livekit_importer() -> None:
    """Not a rule about a temp tree: the actual checked-in source, scanned for `livekit`."""
    importers: list[str] = []
    for path in sorted((REPO_ROOT / "backend").rglob("*.py")) + sorted(
        (REPO_ROOT / "workers").rglob("*.py")
    ):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        tree_ = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree_):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            if any(name == "livekit" or name.startswith("livekit.") for name in names):
                importers.append(str(path.relative_to(REPO_ROOT)))
    assert set(importers) == {"workers/voice_agent/voice_agent/transport/livekit_transport.py"}, (
        importers
    )

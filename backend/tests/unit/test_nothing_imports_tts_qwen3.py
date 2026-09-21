"""Nothing under `backend/` or `workers/voice_agent/` imports `tts_qwen3` (E14, MANAGER RULING 2).

`workers/tts_qwen3/` is a standalone package with its own venv, **not** a `sim112-workspace`
member (`workers/tts_qwen3/README.md`, `docs/hld/50-voice-pipeline.md` §2.4's OWNER DECISION
note): the backend and `voice_agent` talk to it only over loopback HTTP
(`app.inference.tts.qwen3_tts.Qwen3TTS`), never by importing its Python package, because that
package pins `torch==2.14.0` — outside the backend's `asr-gigaam` `torch<2.9` ceiling (recon
§1.1). E14-B tried this rule inside `backend/tools/check_imports.py`'s existing `(anywhere)`
`LayerRule` and reverted it: that rule has no path-exclusion mechanism, so it false-positived on
`workers/tts_qwen3/`'s own internal files (`tests/test_server.py`, `__main__.py`), which
legitimately `import tts_qwen3.server`. This test mirrors `backend/tests/api/test_router_layering.
py`'s AST-scan-the-source pattern instead: it walks only `backend/` and `workers/voice_agent/` —
`workers/tts_qwen3/` is never in that walk at all, so no exclusion mechanism is needed, and
`check_imports.py` itself is left untouched (E14 close-out, item 6).
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCAN_ROOTS: tuple[Path, ...] = (
    _REPO_ROOT / "backend",
    _REPO_ROOT / "workers" / "voice_agent",
)
_IGNORED_DIR_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".git",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    }
)


def _python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in _IGNORED_DIR_NAMES for part in path.relative_to(root).parts[:-1]):
            continue
        files.append(path)
    return files


def _imported_top_level_names(path: Path) -> list[tuple[int, str]]:
    """Every top-level dotted-import root a file imports, with its line number."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name.split(".")[0]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


def test_backend_and_voice_agent_import_root_confirms_this_test_scans_something() -> None:
    """A guard against the walk silently finding zero files (a path typo would pass vacuously)."""
    total = sum(len(_python_files(root)) for root in _SCAN_ROOTS)
    assert total > 100


def test_nothing_under_backend_or_voice_agent_imports_tts_qwen3() -> None:
    """The only process allowed to import `tts_qwen3` is the worker itself, outside this walk."""
    violations: list[str] = []
    for root in _SCAN_ROOTS:
        for path in sorted(_python_files(root)):
            for lineno, top_level_name in _imported_top_level_names(path):
                if top_level_name == "tts_qwen3":
                    violations.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}")
    assert not violations, (
        "tts_qwen3 (the standalone Qwen3-TTS worker package, own venv, torch==2.14.0) must never "
        "be imported by backend/ or workers/voice_agent/ (SPEC §41, MANAGER RULING 2): "
        f"{violations}"
    )

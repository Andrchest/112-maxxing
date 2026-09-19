"""Tests for `backend/tools/check_imports.py` (D2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.check_imports import main

PACKAGE_DIRS = [
    "backend/app",
    "backend/app/domain",
    "backend/app/application",
    "backend/app/api",
    "backend/app/infrastructure",
    "backend/app/inference",
    "backend/app/db",
    "backend/app/config",
    "backend/app/tools",
    "workers/voice_agent/voice_agent",
    "workers/voice_agent/voice_agent/transport",
]


def _make_clean_tree(root: Path) -> None:
    for rel_dir in PACKAGE_DIRS:
        directory = root / rel_dir
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (root / "backend/app/domain/incident.py").write_text(
        "from __future__ import annotations\n\nclass Incident:\n    pass\n",
        encoding="utf-8",
    )
    (root / "backend/app/application/use_cases.py").write_text(
        "from app.domain.incident import Incident\n\n\ndef noop() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (root / "backend/tools").mkdir(parents=True, exist_ok=True)
    (root / "backend/tools/ok_tool.py").write_text(
        "import json\n\nprint(json.dumps({}))\n", encoding="utf-8"
    )
    (root / "workers/voice_agent/voice_agent/transport/livekit_transport.py").write_text(
        "import livekit\n", encoding="utf-8"
    )


@pytest.fixture
def clean_tree(tmp_path: Path) -> Path:
    _make_clean_tree(tmp_path)
    return tmp_path


def _run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    exit_code = main(["--root", str(root)])
    return exit_code, capsys.readouterr().out


def test_clean_tree_passes(clean_tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 0
    assert out == ""


def test_domain_forbidden_vendor_import(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "backend/app/domain/_sabotage.py").write_text(
        "import sqlalchemy\n", encoding="utf-8"
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert "backend/app/domain/_sabotage.py:1: app.domain must not import sqlalchemy" in out


def test_domain_forbidden_first_party_import(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "backend/app/domain/_sabotage.py").write_text(
        "from app.infrastructure import repo\n", encoding="utf-8"
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert "backend/app/domain/_sabotage.py:1: app.domain must not import app.infrastructure" in out


def test_domain_random_module_import_is_rejected(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "backend/app/domain/_sabotage.py").write_text("import random\n", encoding="utf-8")

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert "backend/app/domain/_sabotage.py:1: app.domain must not import random" in out


def test_domain_random_non_random_symbol_is_rejected(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "backend/app/domain/_sabotage.py").write_text(
        "from random import choice\n", encoding="utf-8"
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert "backend/app/domain/_sabotage.py:1: app.domain must not import random.choice" in out


def test_domain_random_random_class_is_allowed(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "backend/app/domain/_ok.py").write_text(
        "from random import Random\n\nRandom(0)\n", encoding="utf-8"
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 0
    assert out == ""


def test_domain_catches_function_local_import(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "backend/app/domain/_sabotage.py").write_text(
        "def f():\n    import time\n    return time.time()\n", encoding="utf-8"
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert "backend/app/domain/_sabotage.py:2: app.domain must not import time" in out


def test_domain_catches_type_checking_import(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "backend/app/domain/_sabotage.py").write_text(
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    import httpx\n",
        encoding="utf-8",
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert "backend/app/domain/_sabotage.py:4: app.domain must not import httpx" in out


def test_application_forbidden_import(clean_tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (clean_tree / "backend/app/application/_sabotage.py").write_text(
        "from app.infrastructure import repo\n", encoding="utf-8"
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert (
        "backend/app/application/_sabotage.py:1: app.application must not import "
        "app.infrastructure" in out
    )


def test_api_forbidden_import(clean_tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (clean_tree / "backend/app/api/_sabotage.py").write_text(
        "from app.db import models\n", encoding="utf-8"
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert "backend/app/api/_sabotage.py:1: app.api must not import app.db" in out


def test_any_app_module_forbids_voice_agent_and_llm_vendors(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "backend/app/infrastructure/_sabotage.py").write_text(
        "import voice_agent\nimport openai\n", encoding="utf-8"
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert "backend/app/infrastructure/_sabotage.py:1: app must not import voice_agent" in out
    assert "backend/app/infrastructure/_sabotage.py:2: app must not import openai" in out


def test_voice_agent_non_transport_forbids_livekit(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "workers/voice_agent/voice_agent/_sabotage.py").write_text(
        "import livekit\n", encoding="utf-8"
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert (
        "workers/voice_agent/voice_agent/_sabotage.py:1: voice_agent must not import livekit" in out
    )


def test_voice_agent_transport_allows_livekit_but_not_anthropic(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "workers/voice_agent/voice_agent/transport/_sabotage.py").write_text(
        "import livekit\nimport anthropic\n", encoding="utf-8"
    )

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert "voice_agent/transport/_sabotage.py:1" not in out
    assert (
        "workers/voice_agent/voice_agent/transport/_sabotage.py:2: voice_agent.transport "
        "must not import anthropic" in out
    )


def test_anywhere_forbids_openai_and_anthropic_outside_app_and_voice_agent(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (clean_tree / "backend/tools/_sabotage.py").write_text("import anthropic\n", encoding="utf-8")

    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 1
    assert "backend/tools/_sabotage.py:1: (anywhere) must not import anthropic" in out


def test_sabotage_file_removed_goes_green_again(
    clean_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sabotage = clean_tree / "backend/app/domain/_sabotage.py"
    sabotage.write_text("import sqlalchemy\n", encoding="utf-8")
    exit_code, _out = _run(clean_tree, capsys)
    assert exit_code == 1

    sabotage.unlink()
    exit_code, out = _run(clean_tree, capsys)

    assert exit_code == 0
    assert out == ""

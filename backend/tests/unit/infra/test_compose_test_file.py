"""`infra/docker-compose.test.yml` structural checks (the stack `make infra-up` starts).

Parsed with PyYAML like `test_compose_file.py` — no Docker daemon needed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

TEST_COMPOSE_PATH = Path(__file__).resolve().parents[4] / "infra" / "docker-compose.test.yml"


def test_the_test_postgres_runs_under_docker_init_so_an_orphaned_probe_never_crashes_it() -> None:
    # I6 PGCRASH: without `init: true` the postmaster is PID 1, reaps the pg_isready a timed-out
    # healthcheck leaves behind, takes its exit code 2 for a crashed backend and restarts the
    # server mid-suite (~1174 errors in `make gate`).
    doc = yaml.safe_load(TEST_COMPOSE_PATH.read_text(encoding="utf-8"))
    assert doc["services"]["postgres"].get("init") is True

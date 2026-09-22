#!/usr/bin/env bash
# Wraps `python -m app.cli preflight` for the compose stack (docs/hld/60-inference-ops.md §5, SPEC
# §38). A demo operator runs this once the seven-service (+ tts-qwen3) stack is up
# (`make dev-infra-up-full` / `docker compose -f infra/docker-compose.yml up -d --wait`) to get an
# explicit PASS/FAIL/SKIP report before starting a session, exactly as SPEC §38 asks.
#
# The preflight COMMAND itself (`backend/app/cli/preflight.py`, the 11+1 checks) belongs to a
# different slice of this epic — this script only locates the workspace and execs it, the same
# "thin wrapper" shape `make run-api`/`make preflight` already use for other `app.*` entry points.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"
exec uv run python -m app.cli preflight "$@"

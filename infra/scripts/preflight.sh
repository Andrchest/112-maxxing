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

# Under `make up` (E20): the voice agent's preflight endpoint binds loopback INSIDE its container
# (SPEC §41, never published) and llama-server publishes no port (HLD 60 §9), so the host cannot
# see the stack. The voice-agent container can — its own 127.0.0.1:8113, `llama-server:8080`,
# postgres/redis/livekit by service name, `/models`, the GPU, and `scenarios/` (mounted read-only
# for exactly this) — so the checks run there. Without a running compose voice-agent this is a
# host run (`make run-*`), where `SIM_MODELS_ROOT` defaults to the repo's `models/`.
COMPOSE=(docker compose -f infra/docker-compose.yml)
if [[ -f .env ]]; then
    COMPOSE+=(--env-file .env)
fi
if command -v docker >/dev/null 2>&1 \
    && "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx voice-agent; then
    exec "${COMPOSE[@]}" exec -T voice-agent python -m app.cli preflight "$@"
fi
export SIM_MODELS_ROOT="${SIM_MODELS_ROOT:-./models}"
exec uv run python -m app.cli preflight "$@"

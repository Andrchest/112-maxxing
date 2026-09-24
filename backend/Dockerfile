# Backend API image (SPEC §36, D1, HLD 60 §9). Serves `app.api.main:create_app` only — it never
# loads an ML model itself (VAD/ASR/TTS live in workers/voice_agent and workers/tts_qwen3), so this
# image installs the plain `sim-backend` package with no optional ML extras (D1: "heavy ML
# dependencies are optional extras; the gate installs base + dev only").
#
# Build context is the REPO ROOT (`infra/docker-compose.yml`'s `backend.build.context: ..`), not
# `backend/`: `sim-backend` is a member of the `sim112-workspace` uv workspace (root
# `pyproject.toml`), and `uv sync --package sim-backend --frozen` needs every workspace member's
# `pyproject.toml` on disk to resolve against the shared `uv.lock`, even though only `sim-backend`
# itself gets installed.
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pinned uv release, copied out of the official distroless image (no curl|sh installer — SPEC §41
# posture of "nothing unpinned fetched at build/run time" extended to tooling too).
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /usr/local/bin/

WORKDIR /workspace

# Every workspace member's manifest, so `uv sync --frozen` can validate against `uv.lock` without
# re-resolving. Root `pyproject.toml` has `[tool.uv] package = false` (not installable itself).
COPY pyproject.toml uv.lock ./
COPY workers/voice_agent/pyproject.toml workers/voice_agent/pyproject.toml
COPY benchmarks/pyproject.toml benchmarks/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml

# `--frozen`: never re-resolves or edits uv.lock inside the image build (the lock is the gate's
# lock). `--no-dev`: ruff/mypy/pytest stay out of the runtime image. `--package sim-backend`: only
# this workspace member and its (non-extra) dependencies are installed.
# Layer order (E20, same as workers/voice_agent/Dockerfile): third-party dependencies first, from
# the lock + manifests alone, so a source edit does not re-download them; the uv cache is a
# BuildKit cache mount so a PyPI timeout mid-build resumes on the next build instead of restarting.
ENV UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package sim-backend

COPY backend/ backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package sim-backend
# I3 E2a (HLD 70 §70.6.1): the sha-pinned reference pack the composition root loads
# (`SIM_REFERENCE_DIR`, default `/workspace/reference` — the repository layout). After the sync so a
# reference-only change does not invalidate the dependency layer.
COPY reference/ reference/

ENV PATH="/workspace/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace/backend

# No secret, model path or URL is baked in here (SPEC §41): every SIM_* value comes from the
# container's environment (`infra/docker-compose.yml`'s `env_file: ../.env`).
EXPOSE 8100

# `GET /api/v1/health/live` touches nothing (process liveness only, `backend/app/api/routers/
# health.py`) — the right probe for a container healthcheck, distinct from `/health/ready`'s
# inference-readiness aggregation (SPEC §37).
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:8100/api/v1/health/live" || exit 1

CMD ["uvicorn", "app.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8100"]

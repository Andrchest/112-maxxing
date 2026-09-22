# voice-agent worker image (SPEC §36, D1, HLD 60 §9). Runs the LiveKit-facing turn pipeline and
# loads VAD/ASR/TTS-fallback models in-process (unlike backend/Dockerfile), so it installs the
# heavy ML extras the active profile needs — as image BUILD ARGS, so a DEV image never carries GPU
# TTS stacks it will not use (D1). `tts-qwen3` is never one of these extras (E14-B): Qwen3-TTS
# lives in the separate `workers/tts_qwen3/Dockerfile` worker, reached over loopback HTTP —
# `backend/tools/check_imports.py` enforces that `voice_agent` never imports it.
#
# UNVERIFIED-BUILD (this task's report): this image was written carefully against
# `workers/voice_agent/pyproject.toml` and the `asr-gigaam`/`vad-silero`/`tts-piper` extras'
# dependency floors, but NOT built here — the brief forbids building a CUDA image in this task
# (no GPU work in E18; E19 builds and runs it for real).
#
# Build context is the REPO ROOT (`infra/docker-compose.yml`'s `voice-agent.build.context: ..`):
# `sim-voice-agent` depends on `sim-backend` as a uv workspace source (`[tool.uv.sources]`), so both
# packages' source and the shared `uv.lock` must be in the build context.
FROM python:3.12-slim AS base

# `torch`/`torchaudio` (asr-gigaam extra) and `onnxruntime` (vad-silero) both need the CUDA runtime
# libraries the NVIDIA base normally provides; `nvidia/cuda:*-runtime` is deliberately NOT used here
# because the exact CUDA minor version this project's pinned torch floor (`torch>=2.6,<2.9`, per
# `backend/pyproject.toml`) needs was not verified in this task (no GPU work allowed) — pip-installed
# torch wheels bundle their own CUDA runtime libraries for the common case, so a plain `python:3.12
# -slim` base plus `runtime: nvidia` (driver passthrough only) is the documented starting point;
# flag any CUDA-version mismatch found at first real build as an E19 finding.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /usr/local/bin/

WORKDIR /workspace

# Comma-separated so a build can trim the list (e.g. a CPU-only smoke image: --build-arg
# VOICE_AGENT_EXTRAS=). Defaults to what DEV_3060TI's profile needs on the ASR/VAD/fallback-TTS
# side (HLD 60 §2.2): gigaam (ASR, cuda), silero (VAD, cpu), piper (TTS fallback, cpu).
ARG VOICE_AGENT_EXTRAS="asr-gigaam,vad-silero,tts-piper"

COPY pyproject.toml uv.lock ./
COPY benchmarks/pyproject.toml benchmarks/pyproject.toml
COPY backend/ backend/
COPY workers/voice_agent/ workers/voice_agent/

RUN set -eu; \
    extra_flags=""; \
    old_ifs="$IFS"; IFS=","; \
    for e in $VOICE_AGENT_EXTRAS; do \
        [ -n "$e" ] && extra_flags="$extra_flags --extra $e"; \
    done; \
    IFS="$old_ifs"; \
    uv sync --frozen --no-dev --package sim-voice-agent $extra_flags

ENV PATH="/workspace/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1

WORKDIR /workspace

# Publishes NO port to the host (HLD 60 §9: "publishes no port"). The loopback preflight HTTP
# server (R7 of the E18 brief, `SIM_VOICE_AGENT_HTTP_PORT`, default 8113, 127.0.0.1 only) is
# reachable from other containers on the compose network only, never published here.
#
# HLD 60 §9's documented healthcheck (`python -m voice_agent.cli health`, returns 0 only when every
# `voice:health:{service}` key this process owns is READY or WARMING) is not built yet as of this
# task — `workers/voice_agent/voice_agent/cli.py` does not exist (owned by the E18 slice that adds
# the health/readiness backend wiring, not by this compose/Dockerfile task). The HEALTHCHECK line
# below is written to match the HLD exactly and will start working once that CLI lands; until then
# it fails (container shows "unhealthy"), which is visible and correct, not silently green.
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -m voice_agent.cli health || exit 1

CMD ["python", "-m", "voice_agent.main"]

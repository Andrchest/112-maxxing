# voice-agent worker image (SPEC §36, D1, HLD 60 §9). Runs the LiveKit-facing turn pipeline and
# loads VAD/ASR/TTS-fallback models in-process (unlike backend/Dockerfile), so it installs the
# heavy ML extras the active profile needs — as image BUILD ARGS, so a DEV image never carries GPU
# TTS stacks it will not use (D1). `tts-qwen3` is never one of these extras (E14-B): Qwen3-TTS
# lives in the separate `workers/tts_qwen3/Dockerfile` worker, reached over loopback HTTP —
# `backend/tools/check_imports.py` enforces that `voice_agent` never imports it.
#
# BUILT 2026-09-22 (E19-F): `docker build -f workers/voice_agent/Dockerfile -t
# sim112/voice-agent:e19 .` succeeded (image 7.23 GB) after fixing a real bug the first attempt
# surfaced (see the `RUN uv sync` line below); smoke-tested with `docker run --rm --gpus all
# sim112/voice-agent:e19 python -c "import torch; print(torch.cuda.is_available(),
# torch.version.cuda)"` (no model load) → `True 12.8`.
#
# Build context is the REPO ROOT (`infra/docker-compose.yml`'s `voice-agent.build.context: ..`):
# `sim-voice-agent` depends on `sim-backend` as a uv workspace source (`[tool.uv.sources]`), so both
# packages' source and the shared `uv.lock` must be in the build context.
FROM python:3.12-slim AS base

# `torch`/`torchaudio` (asr-gigaam extra) and `onnxruntime` (vad-silero) both need the CUDA runtime
# libraries the NVIDIA base normally provides; `nvidia/cuda:*-runtime` is deliberately NOT used here
# — pip-installed torch wheels bundle their own CUDA runtime libraries, so a plain `python:3.12-slim`
# base plus `runtime: nvidia` (driver passthrough only) is enough. VERIFIED (E19-F, 2026-09-22): the
# real build resolves `torch==2.8.0` with `cu12`-suffixed CUDA wheels (`torch.version.cuda` reports
# `12.8` at runtime, matching the main workspace venv's own `torch==2.8.0+cu128`, backend/pyproject.
# toml's `torch>=2.6,<2.9` floor) — no base-image change was needed; the smoke test above confirms
# the driver (595.84) accepts it.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /usr/local/bin/

WORKDIR /workspace

# Comma-separated so a build can trim the list (e.g. a CPU-only smoke image: --build-arg
# VOICE_AGENT_EXTRAS=). Defaults to what DEV_3060TI's profile needs on the ASR/VAD/fallback-TTS
# side (HLD 60 §2.2): gigaam (ASR, cuda), silero (VAD, cpu), piper (TTS fallback, cpu).
#
# `transport-livekit` (E19-E2, `workers/voice_agent/pyproject.toml:24` — the only extra declared on
# `sim-voice-agent` itself; the other three are `sim-backend`'s) was ADDED to this default on
# 2026-09-22 (E20-G). Without it the image has no `livekit` rtc SDK, and E20-C's `make up` walk
# died on every call with `ModuleNotFoundError: No module named 'livekit'` ->
# `TransportError: the 'livekit' SDK is not installed; install the voice extra or run with
# SIM_CALL_TRANSPORT=fake` — i.e. the documented compose demo path could not place a voice call at
# all. The compose stack runs `SIM_CALL_TRANSPORT=livekit`, so this extra is not optional there.
ARG VOICE_AGENT_EXTRAS="asr-gigaam,vad-silero,tts-piper,transport-livekit"

# Layer order (E20): the third-party dependencies are installed from the lock and the four
# `pyproject.toml` files ALONE, before any source is copied, so editing backend/ or the agent no
# longer re-downloads ~4 GB of CUDA wheels (E20-G measured ~38 min per rebuild and two builds lost
# to PyPI timeouts). The uv cache is a BuildKit cache mount: a download interrupted by a timeout is
# resumed by the next build instead of restarted. The second `uv sync` below then installs only the
# two workspace packages (editable) from the copied source.
COPY pyproject.toml uv.lock ./
COPY benchmarks/pyproject.toml benchmarks/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml
COPY workers/voice_agent/pyproject.toml workers/voice_agent/pyproject.toml

# E19-F, first real build (2026-09-22): `--package sim-voice-agent` alone FAILED —
# `error: Extra 'asr-gigaam' is not defined in the project's optional-dependencies table`. The
# `asr-gigaam`/`vad-silero`/`tts-piper` extras are defined on `sim-backend`'s own
# `[project.optional-dependencies]` (backend/pyproject.toml), not on `sim-voice-agent`'s (which has
# none at all, workers/voice_agent/pyproject.toml) — `uv sync --package X --extra Y` requires Y
# defined on X itself, not on a workspace dependency of X. Fix verified with `--dry-run` against the
# real lock file before use here: pass BOTH `--package sim-backend --package sim-voice-agent` so the
# extras resolve against the package that actually declares them while still syncing (installing)
# `sim-voice-agent` itself into the same venv.
ENV UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eu; \
    extra_flags=""; \
    old_ifs="$IFS"; IFS=","; \
    for e in $VOICE_AGENT_EXTRAS; do \
        [ -n "$e" ] && extra_flags="$extra_flags --extra $e"; \
    done; \
    IFS="$old_ifs"; \
    uv sync --frozen --no-dev --no-install-workspace \
        --package sim-backend --package sim-voice-agent $extra_flags

COPY backend/ backend/
COPY workers/voice_agent/ workers/voice_agent/

RUN --mount=type=cache,target=/root/.cache/uv \
    set -eu; \
    extra_flags=""; \
    old_ifs="$IFS"; IFS=","; \
    for e in $VOICE_AGENT_EXTRAS; do \
        [ -n "$e" ] && extra_flags="$extra_flags --extra $e"; \
    done; \
    IFS="$old_ifs"; \
    uv sync --frozen --no-dev --package sim-backend --package sim-voice-agent $extra_flags

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
# `voice:health:{service}` key this process owns is READY or WARMING) is built:
# `workers/voice_agent/voice_agent/cli.py:100` registers the `health` subcommand (E20-D2,
# 2026-09-22 — corrected from a stale "not built yet" comment; the CLI landed before this compose
# task's own hand-back and the healthcheck below has been live since).
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -m voice_agent.cli health || exit 1

CMD ["python", "-m", "voice_agent.main"]

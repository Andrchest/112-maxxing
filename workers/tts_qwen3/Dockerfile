# tts-qwen3 worker image (E14-B; HLD 60 §9's profiled eighth compose service — additive beyond
# SPEC §36's seven, `compose profiles: ["qwen3-tts"]`). Standalone package, own venv, own pinned
# dependency set (`qwen-tts==0.1.1` pins `torch==2.14.0`, outside the backend's `asr-gigaam` extra's
# `torch<2.9` ceiling — see `workers/tts_qwen3/README.md`) — this image never touches the
# `sim112-workspace` uv workspace at all.
#
# BUILT 2026-09-22 (E19-F): `docker build -f workers/tts_qwen3/Dockerfile -t sim112/tts-qwen3:e19
# workers/tts_qwen3` succeeded, no fix needed (image 6.5 GB); smoke-tested with
# `docker run --rm --gpus all sim112/tts-qwen3:e19 python -c "import torch;
# print(torch.cuda.is_available(), torch.version.cuda)"` (no model load) → `True 13.0`.
# `torch==2.14.0` resolves `cu13`-suffixed wheels (different from `workers/voice_agent`'s
# `torch==2.8.0`/`cu12` — expected, the two images pin different torch versions on purpose, see
# above) — the driver (595.84) accepts both; no base-image change was needed either way.
#
# Build context is `workers/tts_qwen3/` itself (self-contained, not a uv workspace member).
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml ./
COPY tts_qwen3/ tts_qwen3/

# No `uv.lock` here (this package is deliberately outside the workspace lock — its README explains
# why): `uv pip install` against the exact pins `pyproject.toml` already carries, the same
# mechanism `scripts/setup_tts_qwen3.sh` uses for the host venv.
RUN uv venv --python 3.12 /app/.venv \
    && uv pip install --python /app/.venv/bin/python -e .

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1

# `SIM_TTS_QWEN3_PORT` default 8112, loopback-only inside the container too (`tts_qwen3/__main__.py`
# hard-codes `--host 127.0.0.1`, per `workers/tts_qwen3/README.md`) — reachable from other compose
# services only as `http://tts-qwen3:8112`, and this image publishes NO host port (HLD 60 §9).
EXPOSE 8112

HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:8112/health" || exit 1

CMD ["python", "-m", "tts_qwen3"]

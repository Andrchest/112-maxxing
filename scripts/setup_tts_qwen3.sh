#!/usr/bin/env bash
# Creates workers/tts_qwen3/.venv and installs the pinned Qwen3-TTS worker dependencies into it
# (E14-B, `workers/tts_qwen3/pyproject.toml`). Never touches the main `sim112-workspace` venv —
# `qwen-tts==0.1.1` pins `torch==2.14.0`, outside the backend's `asr-gigaam` extra's
# `torch>=2.6,<2.9` ceiling (see `workers/tts_qwen3/README.md`).
#
# Usage: scripts/setup_tts_qwen3.sh   (from anywhere; resolves paths off this script's location)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PKG_DIR="${REPO_ROOT}/workers/tts_qwen3"
VENV_DIR="${PKG_DIR}/.venv"

# Refuse to run inside the main workspace venv (this task's brief, item 1): a `uv pip install`
# invoked with the wrong venv active would pull qwen-tts's pinned torch==2.14.0 into the venv the
# backend and every other worker share, wrecking the asr-gigaam torch<2.9 ceiling for everyone.
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    resolved_active="$(cd "${VIRTUAL_ENV}" && pwd)"
    resolved_main="${REPO_ROOT}/.venv"
    if [[ -d "${resolved_main}" ]] && [[ "${resolved_active}" == "$(cd "${resolved_main}" && pwd)" ]]; then
        echo "error: refusing to run inside the main workspace venv (${resolved_active})." >&2
        echo "Deactivate it first (\`deactivate\`), or just run this script directly — it never" >&2
        echo "needs an active venv of its own; it creates and populates ${VENV_DIR}." >&2
        exit 1
    fi
fi
if [[ "${VIRTUAL_ENV:-}" == "${VENV_DIR}" ]]; then
    : # already the worker's own venv — fine, `uv pip install` below is idempotent
fi

echo "== creating ${VENV_DIR} (python 3.12) =="
uv venv --python 3.12 "${VENV_DIR}"

echo "== installing workers/tts_qwen3's pinned dependencies (qwen-tts==0.1.1, torch==2.14.0) =="
# `uv pip install --python` targets this venv explicitly and never touches the workspace lockfile
# or the main `.venv` — this is not `uv sync` (the machine rule this task's brief repeats: never
# a bare `uv sync` in the repo root; this script's target is a venv outside the workspace entirely).
uv pip install --python "${VENV_DIR}/bin/python" -e "${PKG_DIR}[test]"

echo "== done. Run it with: make run-tts-qwen3 (or: ${VENV_DIR}/bin/python -m tts_qwen3) =="

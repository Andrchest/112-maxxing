#!/usr/bin/env bash
# Computes and launches the `llama-server` flag line of docs/hld/60-inference-ops.md §8.
#
# The `llama.cpp` CUDA server image has no Python of its own to read a profile YAML directly, so
# this script never touches `backend/app/config/profiles/*.yaml`. Instead it reads the SIM_LLAMA_*
# environment variables that `make profile-env` (`backend/app/config/profile_env.py --emit-env`,
# writing `infra/.env.profile`) derives from the active profile's `llm.*` block — `env_file:
# ../infra/.env.profile` on the `llama-server` compose service loads them, and
# `make run-llama-server` sources the same file for a host run.
#
# Usage:
#   llama-server-entrypoint.sh            # exec llama-server with the computed flags (container use)
#   llama-server-entrypoint.sh --print    # print the computed command line and exit 0, no exec —
#                                          # what the unit test and `make run-llama-server --print`
#                                          # style debugging use to check the flag spelling without
#                                          # starting a server or needing a GPU.
set -euo pipefail

: "${SIM_LLAMA_SERVER_BIN:=llama-server}"
: "${SIM_LLAMA_MODEL_PATH:?SIM_LLAMA_MODEL_PATH is required — set by 'make profile-env' (llm.model_path)}"
: "${SIM_LLAMA_ALIAS:?SIM_LLAMA_ALIAS is required — set by 'make profile-env' (llm.model_name)}"
: "${SIM_LLAMA_N_CTX:?SIM_LLAMA_N_CTX is required — set by 'make profile-env' (llm.n_ctx)}"
: "${SIM_LLAMA_PARALLEL:?SIM_LLAMA_PARALLEL is required — set by 'make profile-env' (llm.parallel_slots)}"
: "${SIM_LLAMA_N_GPU_LAYERS:?SIM_LLAMA_N_GPU_LAYERS is required — set by 'make profile-env' (llm.n_gpu_layers)}"
: "${SIM_LLAMA_N_BATCH:=512}"
: "${SIM_LLAMA_N_UBATCH:=256}"
: "${SIM_LLAMA_FLASH_ATTENTION:=on}"
: "${SIM_LLAMA_KV_CACHE_TYPE:=q8_0}"
: "${SIM_LLAMA_THREADS:=8}"
# Bound 0.0.0.0 ONLY inside the compose network (HLD 60 §8/§9: "no flag exposes the server outside
# the compose network" — the compose service itself publishes no host port, SPEC §41). A host run
# via `make run-llama-server` sets SIM_LLAMA_HOST=127.0.0.1 on a loopback port that is never
# 8000/8001/8011/8012/8016 (those belong to the owner's other work on this machine).
: "${SIM_LLAMA_HOST:=0.0.0.0}"
: "${SIM_LLAMA_PORT:=8080}"

# HLD 60 §8, ratified decision (this task's brief, R10): --ctx-size is the TOTAL KV budget shared
# across --parallel slots; the profile's llm.n_ctx stays the PER-REQUEST context SPEC §22/§26
# mandates. This script computes the product; no profile file restates it.
ctx_size=$(( SIM_LLAMA_N_CTX * SIM_LLAMA_PARALLEL ))

flags=(
  --model "${SIM_LLAMA_MODEL_PATH}"
  --alias "${SIM_LLAMA_ALIAS}"
  --host "${SIM_LLAMA_HOST}" --port "${SIM_LLAMA_PORT}"
  --ctx-size "${ctx_size}"
  --parallel "${SIM_LLAMA_PARALLEL}"
  --n-gpu-layers "${SIM_LLAMA_N_GPU_LAYERS}"
  --batch-size "${SIM_LLAMA_N_BATCH}" --ubatch-size "${SIM_LLAMA_N_UBATCH}"
  --flash-attn "${SIM_LLAMA_FLASH_ATTENTION}"
  --cache-type-k "${SIM_LLAMA_KV_CACHE_TYPE}" --cache-type-v "${SIM_LLAMA_KV_CACHE_TYPE}"
  --threads "${SIM_LLAMA_THREADS}"
  --jinja
  --chat-template-kwargs '{"enable_thinking": false}'
  --metrics
)

if [[ "${1:-}" == "--print" ]]; then
  printf '%s' "${SIM_LLAMA_SERVER_BIN}"
  printf ' %s' "${flags[@]}"
  printf '\n'
  exit 0
fi

exec "${SIM_LLAMA_SERVER_BIN}" "${flags[@]}"

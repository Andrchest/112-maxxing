#!/usr/bin/env bash
# E20-I: the documented fresh-clone path, then one real call (README "Fresh clone to a working demo").
set -uo pipefail
cd /home/andreipc/112-maxxing
echo "=== $(date +%T) GPU before"; nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader; nvidia-smi --query-gpu=memory.free --format=csv,noheader
[ -e .env ] && { echo "REFUSING: .env already exists"; exit 9; }
cp .env.example .env
# README: the ONLY edits for a real run
sed -i -e 's/^SIM_VAD_PROVIDER=.*/SIM_VAD_PROVIDER=silero/' -e 's/^SIM_ASR_PROVIDER=.*/SIM_ASR_PROVIDER=gigaam/' \
       -e 's/^SIM_LLM_PROVIDER=.*/SIM_LLM_PROVIDER=llama_cpp/' -e 's/^SIM_TTS_PROVIDER=.*/SIM_TTS_PROVIDER=qwen3_tts/' \
       -e 's/^SIM_CALL_TRANSPORT=.*/SIM_CALL_TRANSPORT=livekit/' .env
diff <(grep -v '^#' .env.example | grep .) <(grep -v '^#' .env | grep .)
echo "=== $(date +%T) make demo-init"; make demo-init 2>&1 | tail -n 8
echo "=== $(date +%T) TTS_COMPOSE_PROFILE=qwen3-tts make up"; t0=$(date +%s)
TTS_COMPOSE_PROFILE=qwen3-tts make up 2>&1 | tail -n 14; echo "MAKE_UP_EXIT=${PIPESTATUS[0]} after $(( $(date +%s)-t0 )) s"
docker compose -f infra/docker-compose.yml --env-file .env ps --format '{{.Service}} {{.Status}}'
echo "=== $(date +%T) waiting for GET /health/ready overall=READY (cold warm-up of every model)"
t0=$(date +%s)
for i in $(seq 1 90); do o=$(curl -s http://127.0.0.1:8100/api/v1/health/ready | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['overall'], [(c['component'],c['status']) for c in d['components'] if c['status']!='READY'])" 2>/dev/null); case "$o" in READY*) break;; esac; sleep 5; done
echo "ready: $o after $(( $(date +%s)-t0 )) s"
echo "=== $(date +%T) make preflight"; make preflight 2>&1 | tail -n 16
echo "=== $(date +%T) proof call"; uv run python /tmp/teamwork-112-maxxing/logs/e20i/proof.py; echo "PROOF_EXIT=$?"
echo "=== $(date +%T) GPU during"; nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
docker compose -f infra/docker-compose.yml --env-file .env logs voice-agent 2>&1 | grep -iE "error|fallback|warn" | tail -n 15 > /tmp/teamwork-112-maxxing/logs/e20i/voice-agent-warnings.log
echo "=== $(date +%T) done (stack left UP for inspection)"

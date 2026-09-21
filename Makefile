SHELL := /bin/bash
UV := uv
# `-n auto` (pytest-xdist) parallelizes the backend suite across the machine's idle cores;
# `PYTEST_WORKERS=0` on the invocation gives a serial run (E11-0). Left out of `addopts` on
# purpose: a bare `uv run pytest path::test` must stay serial and debuggable.
PYTEST_WORKERS ?= auto
COMPOSE_TEST := docker compose -f infra/docker-compose.test.yml -p sim112test
# The local development stack (postgres, redis, livekit). Separate project name and separate
# ports from COMPOSE_TEST, so the two can run side by side.
COMPOSE_DEV := docker compose -f infra/docker-compose.yml
export SIM_DATABASE_URL ?= postgresql+asyncpg://sim:sim@localhost:55432/sim_test
export SIM_REDIS_URL ?= redis://localhost:56379/0
export SIM_JWT_SECRET ?= test-only-secret
export SIM_REQUIRE_INFERENCE_READY ?= false

ALEMBIC := $(UV) run alembic -c backend/alembic.ini
# Throwaway database used only by `db-check` (never by the test suite).
SCRATCH_DB := sim_dbcheck
SCRATCH_DATABASE_URL := postgresql+asyncpg://sim:sim@localhost:55432/$(SCRATCH_DB)

export SIM_API_HOST ?= 127.0.0.1
export SIM_API_PORT ?= 8100

.PHONY: deps deps-models models-silero models-llm test-models infra-up infra-down dev-infra-up dev-infra-down fmt lint typecheck boundaries scenarios migrate db-check run-api seed-users test-backend gate-backend gate-frontend gate test deps-tts-qwen3 models-tts-qwen3 run-tts-qwen3 test-tts-qwen3 models-piper deps-tts-piper
deps:
	$(UV) sync --all-packages --group dev
	cd frontend && npm ci
# The heavy ML extras (E12): onnxruntime (SileroVAD) + torch/torchaudio/transformers/hydra-core/
# omegaconf/sentencepiece (GigaAMProvider). `--inexact` so this never strips packages another
# worker's plain `make deps`/`uv run` added; `--all-packages` because the extras belong to the
# `sim-backend` workspace member, not the (unpackaged, `tool.uv.package = false`) root — uv still
# needs `--all-packages` to resolve a member's extra from the workspace root. NEVER run a bare
# `uv sync` here or anywhere else (it would remove `--inexact`'s protection for other workers).
deps-models:
	$(UV) sync --all-packages --group dev --inexact --extra vad-silero --extra asr-gigaam
# E14 close-out, item 7: `deps-models` plus `tts-piper`, so `PiperTTS`'s real contract test
# (`backend/tests/models/test_tts_contract.py -k piper`) can actually import `piper-tts` — E14-B's
# real run SKIPPED because it was never installed anywhere (SPEC §27: measured, never invented).
# `--inexact` so this never strips a package another worker's plain `make deps`/`uv run` added;
# NEVER a bare `uv sync`.
deps-tts-piper:
	$(UV) sync --all-packages --group dev --inexact --extra vad-silero --extra asr-gigaam --extra tts-piper
# Fetches the Silero VAD v5 onnx graph from a PINNED release tag (MIT licence) and verifies its
# sha256 before it is trusted — see docs/hld/60-inference-ops.md's model table / models/README.md
# for the URL and hash this checks against. GigaAM's checkpoints are not fetched here: the owner
# downloaded them by hand into models/gigaam-v3-e2e_ctc and models/gigaam-v3-ctc (models/ is
# gitignored; `warm_up()` raises ModelNotAvailableError with the expected path if they are absent).
SILERO_VAD_URL := https://raw.githubusercontent.com/snakers4/silero-vad/v5.1.2/src/silero_vad/data/silero_vad.onnx
SILERO_VAD_SHA256 := 2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f
models-silero:
	mkdir -p models/silero-vad
	curl -sL -o models/silero-vad/silero_vad.onnx $(SILERO_VAD_URL)
	echo "$(SILERO_VAD_SHA256)  models/silero-vad/silero_vad.onnx" | sha256sum -c -
# Fetches the DEV_3060TI profile's LLM (SPEC §22, `60-inference-ops.md` §1) from the official
# Qwen/Qwen3-4B-GGUF Hugging Face repo (owner-approved, E13-B1). `hf download`'s own resume plus
# the `curl -C -` fallback both survive an interrupted fetch. Size and sha256 are measured here,
# not pinned in advance (the HF repo's own integrity backs the download, unlike the single pinned
# Silero tag above) — recorded in `60-inference-ops.md`'s model table by the task that ran this.
QWEN3_4B_HF_REPO := Qwen/Qwen3-4B-GGUF
QWEN3_4B_FILE := Qwen3-4B-Q4_K_M.gguf
models-llm:
	mkdir -p models
	uvx --from huggingface_hub hf download $(QWEN3_4B_HF_REPO) $(QWEN3_4B_FILE) --local-dir models || \
		curl -L -C - -o models/$(QWEN3_4B_FILE) \
			https://huggingface.co/$(QWEN3_4B_HF_REPO)/resolve/main/$(QWEN3_4B_FILE)
	sha256sum models/$(QWEN3_4B_FILE)
# -- E14-B: the standalone Qwen3-TTS GPU worker (own venv — `workers/tts_qwen3/README.md`) -----
# Creates workers/tts_qwen3/.venv with `uv` and installs the pinned deps (qwen-tts==0.1.1,
# torch==2.14.0) into it — never into the main workspace venv (`scripts/setup_tts_qwen3.sh`
# refuses to run inside it).
deps-tts-qwen3:
	scripts/setup_tts_qwen3.sh
# Pinned exactly (recon §1.1 / docs/QWEN3_TTS_EXPERIMENT.md:25-30) — immutable SHA revisions, not
# "latest". ~4.3 GB total; only fetched when at least 12 GB is free (this task's brief, item 1) —
# otherwise this prints NOT_RUN and its reason and exits 0, the same "measured, never invented"
# posture SPEC §27 asks for everywhere else (a partial/failed download would be worse than none).
# E14-D: `QWEN3_TTS_VARIANT` (`1.7B` default, matching `tts_qwen3.server.DEFAULT_MODEL_VARIANT` —
# the owner's evaluated model, unchanged) picks which checkpoint this target fetches; `0.6B`'s
# revision was verified from the already-downloaded checkpoint's own
# `.cache/huggingface/download/*.metadata` (every file agrees on `85e237c12c027371202489a0ec5
# 09ded67b5e4b5`), not invented. The tokenizer is shared by both variants and always fetched.
# Disk floor is per variant: the 1.7B checkpoint + tokenizer measures ~5 GB on disk (12 GB floor,
# ~2.4x margin); the 0.6B checkpoint + tokenizer measures ~3.05 GB on disk (`du -sh`, this task,
# 2026-09-22: 2.4G + 651M) — same ~2.4x margin gives an 8 GB floor, lower than the 1.7B's, per
# this task's brief, item 2.
QWEN3_TTS_VARIANT ?= 1.7B
QWEN3_TTS_MODEL_REPO_1_7B := Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
QWEN3_TTS_MODEL_REVISION_1_7B := 0c0e3051f131929182e2c023b9537f8b1c68adfe
QWEN3_TTS_MODEL_SUBDIR_1_7B := Qwen3-TTS-12Hz-1.7B-CustomVoice
QWEN3_TTS_MIN_FREE_DISK_GB_1_7B := 12
QWEN3_TTS_MODEL_REPO_0_6B := Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice
QWEN3_TTS_MODEL_REVISION_0_6B := 85e237c12c027371202489a0ec509ded67b5e4b5
QWEN3_TTS_MODEL_SUBDIR_0_6B := Qwen3-TTS-12Hz-0.6B-CustomVoice
QWEN3_TTS_MIN_FREE_DISK_GB_0_6B := 8
QWEN3_TTS_TOKENIZER_REPO := Qwen/Qwen3-TTS-Tokenizer-12Hz
QWEN3_TTS_TOKENIZER_REVISION := 7dd38ad4e9bad454aae9cd937d0cd577604fe229
QWEN3_TTS_MODEL_DIR := models/qwen3-tts
models-tts-qwen3:
	@if [ "$(QWEN3_TTS_VARIANT)" = "1.7B" ]; then \
		repo="$(QWEN3_TTS_MODEL_REPO_1_7B)"; rev="$(QWEN3_TTS_MODEL_REVISION_1_7B)"; \
		subdir="$(QWEN3_TTS_MODEL_SUBDIR_1_7B)"; min_gb=$(QWEN3_TTS_MIN_FREE_DISK_GB_1_7B); \
	elif [ "$(QWEN3_TTS_VARIANT)" = "0.6B" ]; then \
		repo="$(QWEN3_TTS_MODEL_REPO_0_6B)"; rev="$(QWEN3_TTS_MODEL_REVISION_0_6B)"; \
		subdir="$(QWEN3_TTS_MODEL_SUBDIR_0_6B)"; min_gb=$(QWEN3_TTS_MIN_FREE_DISK_GB_0_6B); \
	else \
		echo "NOT_RUN: unknown QWEN3_TTS_VARIANT=$(QWEN3_TTS_VARIANT) (must be 1.7B or 0.6B)"; \
		exit 1; \
	fi; \
	free_kb=$$(df --output=avail -k . | tail -1); \
	free_gb=$$((free_kb / 1024 / 1024)); \
	if [ "$$free_gb" -lt "$$min_gb" ]; then \
		echo "NOT_RUN: models-tts-qwen3 ($(QWEN3_TTS_VARIANT)) needs >= $${min_gb} GB free disk, only $${free_gb} GB free"; \
	else \
		mkdir -p $(QWEN3_TTS_MODEL_DIR); \
		uvx --from huggingface_hub hf download "$$repo" \
			--revision "$$rev" \
			--local-dir $(QWEN3_TTS_MODEL_DIR)/"$$subdir"; \
		uvx --from huggingface_hub hf download $(QWEN3_TTS_TOKENIZER_REPO) \
			--revision $(QWEN3_TTS_TOKENIZER_REVISION) \
			--local-dir $(QWEN3_TTS_MODEL_DIR)/Qwen3-TTS-Tokenizer-12Hz; \
	fi
# Loopback only (`tts_qwen3/__main__.py` hard-codes `--host 127.0.0.1`); port from
# SIM_TTS_QWEN3_PORT, default 8112 (never 8012/8016 — those belong to the owner's other work).
# E14-D: `QWEN3_TTS_VARIANT` (default `1.7B`, same as `models-tts-qwen3`) is passed through as
# `SIM_TTS_QWEN3_MODEL` — `tts_qwen3.server.create_app()` resolves it against `MODEL_VARIANTS` and
# refuses to start the process on an unknown value.
run-tts-qwen3:
	SIM_TTS_QWEN3_MODEL=$(QWEN3_TTS_VARIANT) workers/tts_qwen3/.venv/bin/python -m tts_qwen3
# The fake-model-factory suite (`workers/tts_qwen3/tests/test_server.py`), in the worker's own
# venv — this task's brief, item 1: "run in ITS OWN venv only if you created it".
test-tts-qwen3:
	cd workers/tts_qwen3 && .venv/bin/python -m pytest -q
# `PiperTTS`'s Russian voice (CPU fallback, D9's "configured fallback"). URL pattern confirmed
# from the owner's own downloader script (recon §4): rhasspy/piper-voices on Hugging Face. The
# sha256 is measured here, not pinned in advance (like `models-llm`'s Qwen3-4B GGUF) — record it
# in `docs/hld/60-inference-ops.md`'s model table after a real run (this task's report does).
PIPER_VOICE_NAME := irina
PIPER_VOICE_QUALITY := medium
PIPER_VOICE_FILE := ru_RU-$(PIPER_VOICE_NAME)-$(PIPER_VOICE_QUALITY)
PIPER_VOICE_URL := https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/$(PIPER_VOICE_NAME)/$(PIPER_VOICE_QUALITY)/$(PIPER_VOICE_FILE).onnx
models-piper:
	mkdir -p models/piper
	curl -sL --retry 5 --retry-all-errors -C - -o models/piper/$(PIPER_VOICE_FILE).onnx $(PIPER_VOICE_URL)
	curl -sL --retry 5 --retry-all-errors -C - -o models/piper/$(PIPER_VOICE_FILE).onnx.json $(PIPER_VOICE_URL).json
	sha256sum models/piper/$(PIPER_VOICE_FILE).onnx models/piper/$(PIPER_VOICE_FILE).onnx.json
# Real-model contract tests (marker `requires_models`): never part of `make gate` (ruling 1). Skips
# per-test when the extra/model/env is missing (see backend/tests/models/_skip.py).
test-models:
	SIM_RUN_MODEL_TESTS=1 $(UV) run pytest -q -m requires_models backend/tests/models
infra-up:
	$(COMPOSE_TEST) up -d --wait
infra-down:
	$(COMPOSE_TEST) down -v
# The development stack of infra/docker-compose.yml (SPEC §36, D9). Named volumes, so `down`
# deliberately does NOT take `-v`: a developer's local database survives a restart of the stack.
dev-infra-up:
	$(COMPOSE_DEV) up -d --wait
dev-infra-down:
	$(COMPOSE_DEV) down
fmt:
	$(UV) run ruff format . && $(UV) run ruff check --fix .
lint:
	$(UV) run ruff format --check . && $(UV) run ruff check .
typecheck:
	$(UV) run mypy backend/app/domain backend/app/application
boundaries:
	$(UV) run python backend/tools/check_imports.py
scenarios:
	$(UV) run python -m app.tools.validate_scenarios scenarios/examples
	$(UV) run python -m app.tools.export_scenario_schema --check
# Apply the Alembic history to SIM_DATABASE_URL (HLD 20-db-schema.md, D5).
migrate:
	$(ALEMBIC) upgrade head
# Models-versus-migration drift check: upgrade a throwaway scratch database from scratch and let
# `alembic check` diff Base.metadata against it. The scratch database is dropped first so the run
# always starts from an empty schema.
db-check: infra-up
	$(COMPOSE_TEST) exec -T postgres psql -v ON_ERROR_STOP=1 -U sim -d postgres \
		-c 'DROP DATABASE IF EXISTS $(SCRATCH_DB) WITH (FORCE)' \
		-c 'CREATE DATABASE $(SCRATCH_DB)'
	$(ALEMBIC) -x url=$(SCRATCH_DATABASE_URL) upgrade head
	$(ALEMBIC) -x url=$(SCRATCH_DATABASE_URL) check
# Run the API (D8). `--factory` because `create_app` takes an optional Container (E7-A).
# The default port is 8100, NOT 8000/8001: those belong to another project on the dev machine.
run-api:
	$(UV) run uvicorn app.api.main:create_app --factory --host $(SIM_API_HOST) --port $(SIM_API_PORT)
# Idempotent upsert of the three local accounts. The passwords come from SIM_SEED_*_PASSWORD;
# there is no default and none is ever written in source (SPEC §41).
seed-users:
	$(UV) run python -m app.tools.seed_users
test-backend: infra-up
	$(UV) run pytest -q -n $(PYTEST_WORKERS) --dist loadfile
gate-backend: lint typecheck boundaries scenarios db-check test-backend
gate-frontend:
	cd frontend && npm run check:api && npm run lint && npm run typecheck && npm run test -- --run && npm run build
gate: gate-backend gate-frontend
	@echo "GATE GREEN"
test: test-backend

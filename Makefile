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
# The FULL seven-service (+ profiled eighth) stack (SPEC §36, HLD 60 §9, E18-E). Needs a real
# `.env` (`cp .env.example .env`) — unlike COMPOSE_DEV/COMPOSE_TEST above, `up`/`down` read secrets
# and profile selection from it explicitly, so a missing `.env` fails loudly rather than silently
# running a demo-shaped stack on fake dev placeholders.
# I7 E52 (ТЗ ¶171-176, no NVIDIA GPU / no nvidia container runtime): COMPOSE_FULL_CPU is the base
# file alone, with no `runtime: nvidia` / GPU device reservation anywhere in it; `make up-cpu`
# below uses it directly. COMPOSE_FULL layers infra/docker-compose.gpu.yml on top — today's
# behaviour, unchanged: `make up` still requires a real GPU + nvidia container runtime by default.
COMPOSE_FULL_CPU := docker compose -f infra/docker-compose.yml --env-file .env
COMPOSE_GPU_FILE := infra/docker-compose.gpu.yml
COMPOSE_FULL := $(COMPOSE_FULL_CPU) -f $(COMPOSE_GPU_FILE)
# --- I7 E49 (Q-E27-1): the tls profile stops publishing the plain http ports ------------------
# `infra/docker-compose.tls.yml` removes the plain http ports (5173/8100/7880) once `.env`'s
# COMPOSE_PROFILES names `tls` — the same file `make compose-check` renders below. `up`/`down`/
# `up-cpu`/`down-cpu` layer it in only then (COMPOSE_TLS_ARGS), so dev/demo (no `tls` profile) are
# unaffected: `.env`'s COMPOSE_PROFILES is read here with plain shell tools (not sourced — it may
# carry values Make should not evaluate), split on commas, and matched for the exact token `tls`.
COMPOSE_TLS_FILE := infra/docker-compose.tls.yml
TLS_PROFILE_ACTIVE := $(shell test -f .env && grep -E '^COMPOSE_PROFILES=' .env | tail -1 | cut -d= -f2- | tr ',' '\n' | grep -qx tls && echo 1)
COMPOSE_TLS_ARGS := $(if $(TLS_PROFILE_ACTIVE),-f $(COMPOSE_TLS_FILE),)
# `docker compose --profile qwen3-tts up` starts the additive eighth service too (HLD 60 §9); a
# plain `make up` starts exactly the SPEC §36 seven. `TTS_COMPOSE_PROFILE=qwen3-tts make up` opts in.
TTS_COMPOSE_PROFILE ?=
export SIM_DATABASE_URL ?= postgresql+asyncpg://sim:sim@localhost:55432/sim_test
export SIM_REDIS_URL ?= redis://localhost:56379/0
export SIM_JWT_SECRET ?= test-only-secret-padded-32-bytes!
export SIM_REQUIRE_INFERENCE_READY ?= false
export SIM_MODEL_PROFILE ?= DEV_3060TI
# Where `make profile-env` writes the active profile's llm.* block for llama-server's entrypoint
# (infra/scripts/llama-server-entrypoint.sh) to read — gitignored, regenerated on every `make up` /
# `make run-llama-server`, never hand-edited.
PROFILE_ENV_FILE := infra/.env.profile
# A host run of llama-server (`make run-llama-server`) must NOT be 8000/8001/8011/8012/8016 (the
# owner's other work on this machine) and must not collide with anything else this project binds
# (API 8100, Qwen3-TTS worker 8112, voice-agent preflight HTTP 8113, test/dev postgres/redis).
LLAMA_SERVER_HOST ?= 127.0.0.1
LLAMA_SERVER_PORT ?= 8180

ALEMBIC := $(UV) run alembic -c backend/alembic.ini
# Throwaway database used only by `db-check` (never by the test suite).
SCRATCH_DB := sim_dbcheck
SCRATCH_DATABASE_URL := postgresql+asyncpg://sim:sim@localhost:55432/$(SCRATCH_DB)

export SIM_API_HOST ?= 127.0.0.1
export SIM_API_PORT ?= 8100

.PHONY: deps deps-models deps-livekit models-silero models-llm test-models infra-up infra-down dev-infra-up dev-infra-down fmt lint typecheck boundaries scenarios migrate db-check run-api seed-users test-backend gate-backend gate-frontend gate test deps-tts-qwen3 models-tts-qwen3 run-tts-qwen3 test-tts-qwen3 models-piper deps-tts-piper compose-check profile-env preflight run-llama-server run-voice-agent up down up-cpu down-cpu models-llm-qwen35 models-llm-qwen3-8b models-warmup models-layout models bench-asr bench-llm bench-tts bench-e2e bench-vram bench-all demo-db demo-init demo-inject backup-now restore backup-verify certs settings-import e2e-scenarios e2e-scenarios-doc e2e-scenarios-bundle e2e-scenarios-bundle-http
# `--inexact` matches every other sync target in this file: without it `uv sync` PRUNES the
# environment down to the base dependency set, silently uninstalling the ML extras a previous
# `make deps-models` / `deps-tts-piper` / `deps-livekit` installed (E20-A, R4). Re-run those
# targets to ADD an extra; `make deps` is only ever the baseline.
deps:
	$(UV) sync --all-packages --group dev --inexact
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
# E19-E2: the `livekit` rtc SDK (`sim-voice-agent`'s `transport-livekit` extra), needed by
# `voice_agent.transport.livekit_transport` / `headless_client` at RUN time — `make gate` never
# needs it (D13) and `benchmark_e2e.py --transport livekit` answers NOT_RUN without it. Same
# `--inexact` discipline as the two targets above: NEVER a bare `uv sync`, which would strip
# torch/onnxruntime/piper out of the shared venv.
deps-livekit:
	$(UV) sync --all-packages --group dev --inexact --extra transport-livekit
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
	$(MAKE) models-layout
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
	$(MAKE) models-layout
# -- E19-F: DEV_3060TI*'s actual LLM (Qwen3.5-{0.8B,2B,4B} Q4_K_M, OWNER DECISION 2026-09-21,
# e13-b3/e13-b4) has no OFFICIAL Qwen HF GGUF repo — `Qwen/Qwen3.5-<size>-GGUF` all 401 (HF API,
# checked 2026-09-22: same response a nonexistent repo gets; Qwen only ships Qwen3.5 as safetensors,
# `pipeline_tag: image-text-to-text`). `unsloth/Qwen3.5-<size>-GGUF`'s `Q4_K_M` file is
# byte-for-byte (size AND sha256, this task's report) the owner's already-downloaded
# `~/models/Qwen3.5-<size>/Qwen3.5-<size>-Q4_K_M.gguf` copy for all three sizes — that identity is
# the provenance evidence, not a guess — so these are PINNED to the exact commit `unsloth/Qwen3.5-
# <size>-GGUF` was at when this task resolved it (HF API `sha` field, 2026-09-22), not "main".
# Default target fetches only the profile-default 2B (~1.3 GB); QWEN35_LLM_SIZE overrides.
QWEN35_LLM_SIZE ?= 2B
QWEN35_LLM_REPO_0.8B := unsloth/Qwen3.5-0.8B-GGUF
QWEN35_LLM_REVISION_0.8B := 6ab461498e2023f6e3c1baea90a8f0fe38ab64d0
QWEN35_LLM_FILE_0.8B := Qwen3.5-0.8B-Q4_K_M.gguf
QWEN35_LLM_REPO_2B := unsloth/Qwen3.5-2B-GGUF
QWEN35_LLM_REVISION_2B := f6d5376be1edb4d416d56da11e5397a961aca8ae
QWEN35_LLM_FILE_2B := Qwen3.5-2B-Q4_K_M.gguf
QWEN35_LLM_REPO_4B := unsloth/Qwen3.5-4B-GGUF
QWEN35_LLM_REVISION_4B := e87f176479d0855a907a41277aca2f8ee7a09523
QWEN35_LLM_FILE_4B := Qwen3.5-4B-Q4_K_M.gguf
models-llm-qwen35:
	@repo="$(QWEN35_LLM_REPO_$(QWEN35_LLM_SIZE))"; rev="$(QWEN35_LLM_REVISION_$(QWEN35_LLM_SIZE))"; \
	file="$(QWEN35_LLM_FILE_$(QWEN35_LLM_SIZE))"; \
	if [ -z "$$repo" ]; then \
		echo "NOT_RUN: unknown QWEN35_LLM_SIZE=$(QWEN35_LLM_SIZE) (must be 0.8B, 2B or 4B)"; exit 1; \
	fi; \
	mkdir -p models/llm; \
	uvx --from huggingface_hub hf download "$$repo" "$$file" --revision "$$rev" --local-dir models/llm || \
		curl -L -C - -o models/llm/"$$file" "https://huggingface.co/$$repo/resolve/$$rev/$$file"; \
	sha256sum models/llm/"$$file"
	$(MAKE) models-layout
# Qwen3-8B Q4_K_M for the FINAL_3080TI_* profiles (SPEC §22/§26) — defined and pinned (HF API,
# 2026-09-22: `Qwen/Qwen3-8B-GGUF`, official Qwen repo), NOT executed by this task (R4/R9 of this
# task's brief): no Qwen3-8B GGUF and no 3080 Ti exist on this machine; running this would only
# leave an untested 4.7 GB file behind. Run it for real on the target 3080 Ti card.
QWEN3_8B_HF_REPO := Qwen/Qwen3-8B-GGUF
QWEN3_8B_REVISION := 7c41481f57cb95916b40956ab2f0b139b296d974
QWEN3_8B_FILE := Qwen3-8B-Q4_K_M.gguf
models-llm-qwen3-8b:
	mkdir -p models/llm
	uvx --from huggingface_hub hf download $(QWEN3_8B_HF_REPO) $(QWEN3_8B_FILE) \
		--revision $(QWEN3_8B_REVISION) --local-dir models/llm || \
		curl -L -C - -o models/llm/$(QWEN3_8B_FILE) \
			https://huggingface.co/$(QWEN3_8B_HF_REPO)/resolve/$(QWEN3_8B_REVISION)/$(QWEN3_8B_FILE)
	sha256sum models/llm/$(QWEN3_8B_FILE)
	$(MAKE) models-layout
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
	$(MAKE) models-layout
# Loopback only (`tts_qwen3/__main__.py` hard-codes `--host 127.0.0.1`); port from
# SIM_TTS_QWEN3_PORT, default 8112 (never 8012/8016 — those belong to the owner's other work).
# E14-D: `QWEN3_TTS_VARIANT` (default `1.7B`, same as `models-tts-qwen3`) is passed through as
# `SIM_TTS_QWEN3_MODEL` — `tts_qwen3.server.create_app()` resolves it against `MODEL_VARIANTS` and
# refuses to start the process on an unknown value.
# E20: the variant follows the active profile (`make profile-env` writes SIM_TTS_QWEN3_MODEL into
# infra/.env.profile, exactly as compose's tts-qwen3 service reads it); an explicit
# `QWEN3_TTS_VARIANT=...` on the command line or in the environment still wins.
run-tts-qwen3: profile-env
	set -a && . $(PROFILE_ENV_FILE) && set +a && \
	SIM_TTS_QWEN3_MODEL=$(if $(filter command line environment,$(origin QWEN3_TTS_VARIANT)),$(QWEN3_TTS_VARIANT),$${SIM_TTS_QWEN3_MODEL:-$(QWEN3_TTS_VARIANT)}) \
	workers/tts_qwen3/.venv/bin/python -m tts_qwen3
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
	$(MAKE) models-layout
# The warm-up sample every profile's `warmup.asr_sample_path` names
# (`/models/warmup/warmup_ru.wav`, SPEC §37, HLD 60 §4.2) — absent on this machine until this task
# (E19-F recon: no `make` target and no file existed anywhere). Built by the real `piper-tts`
# package (benchmarks/data/warmup/build_warmup.py) against the already-fetched `models/piper`
# voice — NOT byte-for-byte reproducible run to run (that script's own docstring measures why:
# Piper/VITS's noise input is generated inside the ONNX graph itself, unseedable through the public
# API), so re-running this target replaces the committed WAV with a new (still valid, still <= 3 s)
# synthesis rather than reproducing the old one exactly. The WAV itself is COMMITTED under
# `benchmarks/data/` (small, <= 3 s) per this task's brief, then a real `cp` (not a symlink, unlike
# `models-layout` below) puts a copy at the profile path `models/warmup/warmup_ru.wav`.
models-warmup:
	$(UV) run python benchmarks/data/warmup/build_warmup.py
	mkdir -p models/warmup
	cp benchmarks/data/warmup/warmup_ru.wav models/warmup/warmup_ru.wav
# RULING (this task's brief + the E19-A/E19-F concurrency note): the compose mount stays
# `../models:/models` (`infra/docker-compose.yml`, unchanged) — this target reconciles the HOST
# layout to MATCH what the profile YAMLs' `/models/<rest>` paths (and `resolve_model_path`'s
# primary mapping, owned by E19-A's `benchmarks/_common.py`) expect, entirely with symlinks INSIDE
# the gitignored `models/` directory. It never moves, renames or deletes a file already on disk —
# every link is `ln -sfn` and every step is guarded by "does the source exist", so re-running this
# after a partial `make models` (e.g. before `models-llm-qwen35` has run) just leaves the
# not-yet-fetched links missing rather than failing the whole target. `models-silero`,
# `models-llm`, `models-llm-qwen35`, `models-piper` and `models-tts-qwen3` each call this as their
# last step; `models-warmup` handles its own `/models/warmup/` path itself (a real `cp`, R9).
#
# Final host layout (documented in docs/benchmarks/models.md):
#   models/llm/Qwen3-4B-Q4_K_M.gguf        -> ../Qwen3-4B-Q4_K_M.gguf          (symlink)
#   models/llm/Qwen3.5-<size>-Q4_K_M.gguf  -> fetched directly here by models-llm-qwen35 (real file)
#   models/asr/gigaam-v3-e2e-ctc           -> ../gigaam-v3-e2e_ctc             (symlink, hyphenated
#                                              to match the profile path; the owner's dir keeps its
#                                              underscore name, never renamed)
#   models/asr/gigaam-v3-ctc               -> ../gigaam-v3-ctc                (symlink)
#   models/tts/piper                       -> ../piper                        (symlink)
#   models/tts/qwen3-tts                   -> ../qwen3-tts                    (symlink)
#   models/vad/silero_vad.onnx             -> ../silero-vad/silero_vad.onnx   (symlink)
#   models/warmup/warmup_ru.wav            -> real file, cp'd by models-warmup (not a symlink)
models-layout:
	@mkdir -p models/llm models/asr models/tts models/vad
	@if [ -f models/Qwen3-4B-Q4_K_M.gguf ]; then ln -sfn ../Qwen3-4B-Q4_K_M.gguf models/llm/Qwen3-4B-Q4_K_M.gguf; fi
	@if [ -d models/gigaam-v3-e2e_ctc ]; then ln -sfn ../gigaam-v3-e2e_ctc models/asr/gigaam-v3-e2e-ctc; fi
	@if [ -d models/gigaam-v3-ctc ]; then ln -sfn ../gigaam-v3-ctc models/asr/gigaam-v3-ctc; fi
	@if [ -d models/piper ]; then ln -sfn ../piper models/tts/piper; fi
	@if [ -d models/qwen3-tts ]; then ln -sfn ../qwen3-tts models/tts/qwen3-tts; fi
	@if [ -f models/silero-vad/silero_vad.onnx ]; then ln -sfn ../silero-vad/silero_vad.onnx models/vad/silero_vad.onnx; fi
	@echo "models/ layout reconciled against the profile paths (docs/benchmarks/models.md)"
# One entry point (R9 of this task's brief): every download target except `models-llm-qwen3-8b`
# (FINAL_* only, no 3080 Ti here) and the 1.7B Qwen3-TTS variant (needs ~4.6 GB, this machine has
# ~3.2 GB free beside the owner's process — `models-tts-qwen3`'s own NOT_RUN guard would just print
# and skip it anyway, but the 0.6B variant is what this task actually measured, so that is the
# default this aggregate target fetches). `models-layout` runs last, once, after everything above
# has already called it individually — idempotent, so the repeat is free.
models:
	$(MAKE) models-silero
	$(MAKE) models-llm
	$(MAKE) models-llm-qwen35
	$(MAKE) models-piper
	$(MAKE) models-tts-qwen3 QWEN3_TTS_VARIANT=0.6B
	$(MAKE) models-warmup
	$(MAKE) models-layout
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
	$(UV) run python -m app.tools.validate_scenarios scenarios/tickets
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
# I5 E41 CHANGE B: upload reference/materials/organizer.yaml's organizer files through the E34
# `uploadMaterial` use case, as the seeded `admin` account. Idempotent (sha256 dedupe) — run
# `make seed-users` first.
seed-materials:
	$(UV) run python -m app.tools.seed_materials
test-backend: infra-up
	SIM_ENV_FILE= $(UV) run pytest -q -n $(PYTEST_WORKERS) --dist loadfile
gate-backend: lint typecheck boundaries scenarios db-check compose-check test-backend
gate-frontend:
	cd frontend && npm run check:api && npm run lint && npm run typecheck && npm run test -- --run && npm run build
gate: gate-backend gate-frontend
	@echo "GATE GREEN"
test: test-backend

# --- E18-E: full compose (seven + one), llama-server, preflight (SPEC §36-§38, HLD 60 §8-§9) -----
# Renders infra/docker-compose.yml against a throwaway env file (>= 32-byte placeholder secrets,
# see infra/compose.check.env) — never a developer's real `.env`. Builds and pulls NOTHING: `config
# -q` only parses/validates the YAML and its `${VAR}` interpolations. `--profile qwen3-tts` so the
# additive eighth service's own definition is validated too, even though a plain `up` never starts it.
# I7 E52: renders BOTH variants — the base file alone (what `make up-cpu` starts: no `runtime:
# nvidia`, no GPU device reservation anywhere) and the base file with infra/docker-compose.gpu.yml
# layered on (what `make up` starts, today's behaviour unchanged).
# I7 E49 (Q-E27-1): BOTH variants also layer $(COMPOSE_TLS_FILE) — the exact invocation `make up`/
# `make up-cpu` run once `.env`'s COMPOSE_PROFILES names `tls` (COMPOSE_TLS_ARGS above) — so a typo
# in the tls port override fails this gate step, not a classroom deploy.
compose-check:
	docker compose -f infra/docker-compose.yml --env-file infra/compose.check.env --profile qwen3-tts --profile tls config -q
	docker compose -f infra/docker-compose.yml -f $(COMPOSE_GPU_FILE) --env-file infra/compose.check.env --profile qwen3-tts --profile tls config -q
	docker compose -f infra/docker-compose.yml -f $(COMPOSE_TLS_FILE) --env-file infra/compose.check.env --profile qwen3-tts --profile tls config -q
	docker compose -f infra/docker-compose.yml -f $(COMPOSE_GPU_FILE) -f $(COMPOSE_TLS_FILE) --env-file infra/compose.check.env --profile qwen3-tts --profile tls config -q
# I4 E27: local CA + server certificate for the `tls` profile's edge proxy (infra/certs/, gitignored).
# See docs/RUNBOOK.md «HTTPS в классе».
certs:
	infra/scripts/make-certs.sh
# Emits the active profile's llm.* block as SIM_LLAMA_* env lines (app.config.profile_env, E18-E)
# for infra/scripts/llama-server-entrypoint.sh to read — see that script's own header comment.
# Depends on E18-A's `app.config.profile.load_profile`; fails loudly (not silently) if that module
# or the named profile YAML is not yet present, rather than inventing a flag value (SPEC §26/§27).
# PROFILE_MODELS_ROOT is where the READER of infra/.env.profile will find the model files
# (E20-G/G8). `/models` is the compose mount, so `make up`'s llama-server container gets the
# profile's own paths untouched; `run-llama-server` below overrides it with the host's ./models
# (or SIM_MODELS_ROOT) so a host run needs no hand-exported SIM_LLAMA_MODEL_PATH.
PROFILE_MODELS_ROOT ?= /models
profile-env:
	$(UV) run python -m app.config.profile_env --profile $(SIM_MODEL_PROFILE) --emit-env --models-root $(PROFILE_MODELS_ROOT) > $(PROFILE_ENV_FILE)
# Wraps `python -m app.cli preflight` (docs/hld/60-inference-ops.md §5, SPEC §38); pass flags
# straight through, e.g. `make preflight ARGS='--profile DEV_3060TI --json'`.
preflight:
	infra/scripts/preflight.sh $(ARGS)
# Runs llama-server on the HOST (not in a container) with the same flag line the compose service
# computes (docs/hld/60-inference-ops.md §8) — useful when iterating on a profile without a GPU
# passthrough container. SIM_LLAMA_SERVER_BIN must point at a real llama-server build (the owner's
# own newer build is one example: SIM_LLAMA_SERVER_BIN=~/src/llama.cpp/build/bin/llama-server —
# never hard-coded here, since that path is this machine's, not every developer's). Binds
# loopback-only on LLAMA_SERVER_PORT (default 8180), never 8000/8001/8011/8012/8016.
# E20-G/G8: a target-specific variable, which GNU make propagates into the `profile-env`
# prerequisite — so the file this target then sources already names a path that exists on THIS
# host. E20-C's walk had to export SIM_LLAMA_MODEL_PATH by hand because it did not.
run-llama-server: PROFILE_MODELS_ROOT = $(or $(SIM_MODELS_ROOT),./models)
run-llama-server: profile-env
	set -a && . $(PROFILE_ENV_FILE) && set +a && \
	SIM_LLAMA_HOST=$(LLAMA_SERVER_HOST) SIM_LLAMA_PORT=$(LLAMA_SERVER_PORT) \
	infra/scripts/llama-server-entrypoint.sh
# Runs the voice-agent worker process on the HOST (`python -m voice_agent.main`), the same entry
# point `workers/voice_agent/Dockerfile`'s CMD uses in the compose service.
run-voice-agent:
	$(UV) run python -m voice_agent.main
# Brings up the full stack: the SPEC §36 seven, or all eight with
# `TTS_COMPOSE_PROFILE=qwen3-tts make up` (HLD 60 §9). Regenerates infra/.env.profile first so
# llama-server always launches with the currently-selected SIM_MODEL_PROFILE's flags. Named volumes
# for postgres/recordings, so `down` deliberately does NOT take `-v` (same posture as
# dev-infra-down above: a developer's local database and recordings survive a restart).
up: profile-env
	$(COMPOSE_FULL) $(COMPOSE_TLS_ARGS) $(if $(TTS_COMPOSE_PROFILE),--profile $(TTS_COMPOSE_PROFILE),) up -d --wait
down:
	$(COMPOSE_FULL) $(COMPOSE_TLS_ARGS) $(if $(TTS_COMPOSE_PROFILE),--profile $(TTS_COMPOSE_PROFILE),) down

# --- I7 E52: no-GPU start (ТЗ ¶171-176; Q&A 09:20 «проверка решений на стандартных бытовых
# компьютерах») -------------------------------------------------------------------------------
# The same seven (+ profiled eighth) services as `make up`, WITHOUT infra/docker-compose.gpu.yml:
# `make compose-check` renders this exact invocation and asserts no `runtime: nvidia` / GPU device
# reservation appears anywhere in it. SIM_MODEL_PROFILE defaults to CPU
# (backend/app/config/profiles/CPU.yaml: llm.n_gpu_layers: 0, every asr/tts/vad device: cpu) —
# `make preflight`'s GPU checks (#1/#2) PASS "не требуется профилем" for that profile instead of
# FAILing a machine that correctly has neither a GPU nor the nvidia container runtime. An operator
# who wants a different profile under this override-free compose file can still say
# `make up-cpu SIM_MODEL_PROFILE=SOME_OTHER_PROFILE` (a command-line assignment wins over the
# target-specific default below).
up-cpu: SIM_MODEL_PROFILE = CPU
up-cpu: profile-env
	$(COMPOSE_FULL_CPU) $(COMPOSE_TLS_ARGS) $(if $(TTS_COMPOSE_PROFILE),--profile $(TTS_COMPOSE_PROFILE),) up -d --wait
down-cpu:
	$(COMPOSE_FULL_CPU) $(COMPOSE_TLS_ARGS) $(if $(TTS_COMPOSE_PROFILE),--profile $(TTS_COMPOSE_PROFILE),) down

# --- E19-A: the SPEC §35/§40 benchmark scripts (HLD 60 §7) ---------------------------------------
# NEVER part of `gate*`: a benchmark loads real models on a real card, and the gate must stay
# GPU-free (D13). What the gate does run is `benchmarks/tests/`, which drives the same five
# `main()`s with `--provider fake` and asserts the envelope's SHAPE only — it is in the root
# pyproject's `testpaths`, so plain `make test-backend` picks it up.
#
# PROFILE selects the model profile (default: the SIM_MODEL_PROFILE exported above);
# BENCH_ARGS is passed through verbatim, e.g.
#   make bench-asr BENCH_ARGS="--model-version v3_ctc --device cpu --runs 3"
#   make bench-llm PROFILE=DEV_3060TI_SHARED BENCH_ARGS="--suite interpreter --parallel 1"
# Results land in benchmarks/results/ (gitignored scratch); whatever a doc or profile ends up
# citing is copied into docs/benchmarks/results/ by hand, per docs/benchmarks/README.md.
PROFILE ?= $(SIM_MODEL_PROFILE)
BENCH_ARGS ?=
bench-asr:
	$(UV) run python benchmarks/benchmark_asr.py --profile $(PROFILE) $(BENCH_ARGS)
bench-llm:
	$(UV) run python benchmarks/benchmark_llm.py --profile $(PROFILE) $(BENCH_ARGS)
bench-tts:
	$(UV) run python benchmarks/benchmark_tts.py --profile $(PROFILE) $(BENCH_ARGS)
bench-e2e:
	$(UV) run python benchmarks/benchmark_e2e.py --profile $(PROFILE) $(BENCH_ARGS)
bench-vram:
	$(UV) run python benchmarks/benchmark_vram.py --profile $(PROFILE) $(BENCH_ARGS)
bench-all: bench-asr bench-llm bench-tts bench-e2e bench-vram

# --- E20-B: one-shot demo bootstrap + mic-less injection (R7/R8, docs/RUNBOOK.md) ----------------
# `demo-init` is the fresh-clone-to-demo-data path in one idempotent command: `migrate` is
# idempotent (Alembic no-ops once the DB is at head), `seed-users` is an upsert keyed on username,
# and `app.tools.import_scenarios` is a no-op on a version it has already imported with the same
# content (`app/application/scenarios/import_scenarios.py`'s own D4 contract — re-running this
# target against an already-seeded database is safe and its last line reads "0 version(s) created"
# the second time; no `--skip-existing` flag was needed, the use case already behaves that way).
# E20: the README's fresh-clone path runs `demo-init` BEFORE `make up` (the backend container does
# not migrate on start), so `demo-db` starts the compose `postgres` itself first — idempotent,
# `up --wait` returns at once when it is already healthy. Needs `.env` (COMPOSE_FULL reads it).
demo-db:
	$(COMPOSE_FULL) up -d --wait postgres
demo-init: demo-db migrate seed-users
	$(UV) run python -m app.tools.import_scenarios scenarios/examples
# Mic-less demo: logs in as the seeded trainee, joins SESSION's LiveKit room and plays WAV(s) at
# real-time pace (R8) — `workers/voice_agent/voice_agent/tools/inject.py`. The session's call must
# already be RINGING or CONNECTED and `make preflight` green first (the CLI's own docstring names
# the trap). Pass flags straight through, e.g.
#   make demo-inject ARGS='--session <id> --wav a.wav --wav b.wav --wait-caller'
demo-inject:
	$(UV) run python -m voice_agent.tools.inject $(ARGS)

# --- I4 E26: ops hardening — backup / restore (docs/hld/71-i4-wave4.md §71.3, D33) ----------------
# Forces one backup run right now, via the running (or a freshly started) compose `backup` service
# — never waits for its daily loop. Needs `.env` (COMPOSE_FULL reads it); `docker compose run`
# starts `postgres` first if it is not already up (same `depends_on` the `backup` service declares).
backup-now:
	$(COMPOSE_FULL) run --rm backup /scripts/backup-once.sh
# Restores a dump (and, optionally, a recordings archive) produced by backup-now/the daily loop.
# Stops the backend, `pg_restore --clean`s the dump, restores the recordings, restarts the backend
# (infra/scripts/restore.sh). Example: `make restore FILE=./backups/sim-20260925T120000Z.dump
# RECORDINGS=./backups/recordings-20260925T120000Z.tar.gz`.
restore:
	PGUSER=$${SIM_POSTGRES_USER:-sim} PGDATABASE=$${SIM_POSTGRES_DB:-sim} \
		infra/scripts/restore.sh "$(FILE)" "$(RECORDINGS)"
# Reads backups/last.json (written by the last backup-now/loop run) and exits non-zero if it is
# missing, malformed, records a failed backup, or is older than 26h. No `.env`/compose needed — it
# only reads a file. `uv run` so it uses the repo's own Python (the `backup` container's
# `postgres:16` image has none — see backup-once.sh's header comment).
backup-verify:
	$(UV) run python infra/scripts/backup_status.py --path backups/last.json

# --- I5 E37: settings XML import (Q-E16-1) ---------------------------------------------------
# The CLI half of `exportSettingsXml` (ADMIN, `GET /api/v1/admin/settings/export`): validates the
# XML (schema, known SIM_* names, no secret, each value against its Settings field's type) and
# writes plain NAME=value lines to OUT (default infra/.env.settings) — never the running process.
# `make settings-import FILE=./settings.xml [OUT=infra/.env.settings]`.
OUT ?= infra/.env.settings
settings-import:
	$(UV) run python -m app.cli settings_import --file "$(FILE)" --out "$(OUT)"
# --- end I5 E37 ---------------------------------------------------------------------------------

# --- I6 SCENARIOS: the test scenarios (docs/test-scenarios/, frontend/e2e/scenarios/) -----------
# `e2e-scenarios` runs them against a RUNNING stand (not part of `gate`): env E2E_BASE_URL,
# E2E_ADMIN_USER/E2E_ADMIN_PASS, E2E_INSTRUCTOR_USER/E2E_INSTRUCTOR_PASS,
# E2E_TRAINEE_USER/E2E_TRAINEE_PASS (never written into the repo); `SCENARIO=S03` (or `S01,S03`)
# runs a subset; results (summary.md/json, screenshots) go to E2E_RESULTS_DIR, by default
# /tmp/teamwork-112-maxxing/reports/i6/scenario-runs/<timestamp>/. A broken scenario stops at
# its first unseen expectation and the run continues with the next one.
# `e2e-scenarios-doc` rewrites the Russian text in docs/test-scenarios/ from the definitions
# (the vitest check `e2e/scenarios/doc.test.ts` fails when they drift).
# `e2e-scenarios-bundle` copies the text for a tester on another machine to BUNDLE_DIR.
# I6 HTTP: `E2E_SKIP_SECURE_ONLY=1 make e2e-scenarios` skips every `secureOnly` step (the phone,
# needs a secure context) instead of failing on it — for a run against the temporary http demo.
# `e2e-scenarios-bundle-http` builds the http-only bundle (`secureOnly` steps omitted, access.md's
# address from E2E_HTTP_BASE_URL) to BUNDLE_DIR_HTTP, leaving docs/test-scenarios/ and the plain
# https bundle untouched.
BUNDLE_DIR ?= /home/andreipc/112-demo/e2e-bundle
BUNDLE_DIR_HTTP ?= /home/andreipc/112-demo/e2e-bundle-http
e2e-scenarios:
	cd frontend && E2E_SCENARIO="$(SCENARIO)" npx playwright test -c e2e/scenarios/playwright.config.ts
e2e-scenarios-doc:
	cd frontend && SCENARIO_DOC_WRITE=1 npx vitest run e2e/scenarios/doc.test.ts
e2e-scenarios-bundle:
	frontend/e2e/scenarios/build-bundle.sh "$(BUNDLE_DIR)"
e2e-scenarios-bundle-http:
	frontend/e2e/scenarios/build-bundle.sh --http "$(BUNDLE_DIR_HTTP)"
# --- end I6 SCENARIOS ---------------------------------------------------------------------------

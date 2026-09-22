# System-112 / DDS training simulator

A local, AI-assisted training and assessment simulator for emergency-response personnel. A
simulation is one persistent incident that can pass through several professional roles — Operator
112, profile DDS dispatcher, and (later) an EDDS/coordinator role — as one continuous exercise, not
three independent ones. The primary flow is: an incoming emergency call reaches an Operator 112
trainee, who interviews the caller and manually fills the incident card; the trainee selects
recipients/services and hands the card off immutably; a DDS trainee receives exactly that card,
dispatches and manages resources as the simulated incident develops; the incident closes and a
deterministic, evidence-based assessment is produced.

The canonical simulation state is deterministic Python/domain state — the LLM voices the caller and
is never the source of truth for the simulation (see `docs/SPEC.md` §2).

## Layout

```
frontend/       Vite + React + TypeScript console (operator/DDS/instructor/report UIs)
backend/        FastAPI app, package `app` (api, domain, application, infrastructure, inference, db, config, tools)
workers/
  voice_agent/  Voice-agent worker process (package `voice_agent`), depends on backend's `app`
  tts_qwen3/    Standalone Qwen3-TTS GPU worker (own venv, own image — never a workspace member)
scenarios/      Scenario content (schemas/, examples/)
benchmarks/     Benchmark scripts (ASR/LLM/TTS/E2E/VRAM — arrive in a later epic)
infra/          Docker Compose files (dev/test/full stacks), LiveKit config, launch scripts
docs/           SPEC.md (the owner's specification) and hld/ (the high-level design)
```

## Getting started

```
make deps          # uv sync (backend workspace) + npm ci (frontend)
make gate           # full gate: backend (lint, typecheck, import-boundary check, scenario
                     # validation, compose-check, tests) + frontend (lint, typecheck, tests, build)
```

See `make help`-equivalent targets in the `Makefile` (`fmt`, `lint`, `typecheck`, `boundaries`,
`scenarios`, `test-backend`, `infra-up`, `infra-down`) for running one slice at a time.

## Running the full stack (demo/local run-book)

`infra/docker-compose.yml` is the SPEC §36 seven services (`postgres`, `redis`, `livekit`,
`backend`, `frontend`, `llama-server`, `voice-agent`) plus an additive eighth, `tts-qwen3`, gated
behind a compose profile so a plain run never starts it (docs/hld/60-inference-ops.md §9).

```
cp .env.example .env         # once; fill in real secrets before anything but a local demo
make up                      # the seven; regenerates infra/.env.profile from SIM_MODEL_PROFILE first
TTS_COMPOSE_PROFILE=qwen3-tts make up   # the seven + tts-qwen3
make preflight                # SPEC §38's 11(+1) checks against the running stack
make down                    # stop (named volumes for postgres/recordings survive)
```

`make compose-check` validates `infra/docker-compose.yml` (all eight service definitions) against a
throwaway env file — no `.env`, no build, no pull — and is part of `make gate`.

`make run-llama-server` / `make run-voice-agent` run those two processes on the **host** instead of
in a container, using the same flags/entry point the compose services use — useful when iterating
without a GPU-passthrough container. See `infra/scripts/llama-server-entrypoint.sh` and
`docs/hld/60-inference-ops.md` §8-§9 for the full flag/service reference.

## Documentation

- `docs/SPEC.md` — the owner's specification, verbatim. The law; never edit it.
- `docs/hld/` — the high-level design: `00-decisions.md` fixes the cross-cutting choices every other
  document and every epic must agree with; `openapi.yaml` is the REST contract; the rest cover the
  domain model, DB schema, scenario format, realtime protocol, voice pipeline and inference ops.

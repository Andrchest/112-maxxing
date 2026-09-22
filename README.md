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

For the day-to-day operator tasks once the stack is running (start/stop, preflight, resetting demo
data, clearing a `FATAL` inference latch, switching a profile) see `docs/RUNBOOK.md`. What follows
here is the one-time fresh-clone path to a working demo.

### Fresh clone to a working demo

```
cp .env.example .env         # once; every value below is a placeholder until you change it
make deps                    # uv sync (backend workspace, --inexact) + npm ci (frontend)
make models                  # fetches the DEV_3060TI profile's weights + warm-up sample (~GB-sized)
make demo-init                # migrate + seed-users + import scenarios/examples (idempotent - safe to re-run)
make up                       # the seven services; regenerates infra/.env.profile from SIM_MODEL_PROFILE first
make preflight                # SPEC §38's 11(+1) checks; under `make up` they run inside the voice-agent container (docs/RUNBOOK.md)
#   ... run the SPEC §46 demo walk here - docs/DOD_WALK.md ...
make down                     # stop (named volumes for postgres/recordings survive)
```

`.env`'s defaults run the **gate's fake providers** (`SIM_VAD_PROVIDER=energy`,
`SIM_ASR_PROVIDER=fake`, `SIM_LLM_PROVIDER=fake`, `SIM_TTS_PROVIDER=fake`,
`SIM_CALL_TRANSPORT=fake`) — the stack comes up and the API answers, but the caller says nothing
real. For a **real** run, edit `.env` before `make up`:

- `SIM_VAD_PROVIDER=silero`, `SIM_ASR_PROVIDER=gigaam`, `SIM_LLM_PROVIDER=llama_cpp`,
  `SIM_TTS_PROVIDER=qwen3_tts` (or `piper`), `SIM_CALL_TRANSPORT=livekit` — the provider selection
  (`.env.example`'s "VAD and ASR providers" / "Local LLM" / E14-B sections list every value);
- `SIM_MODEL_PROFILE` (default `DEV_3060TI`) — which `backend/app/config/profiles/*.yaml` supplies
  the model paths and llama-server flags `make profile-env` (called by `make up`/`run-llama-server`)
  turns into `infra/.env.profile`;
- `SIM_MODELS_ROOT` matters only for a **host** run (`make run-*` below, see that section) — inside
  `make up`'s containers the profile's own `/models/...` paths are correct as shipped
  (`${MODELS_DIR}:/models:ro`, `make models-layout` reconciles the host `models/` directory into
  that same layout).
- `MODELS_DIR` (default `../models`) is resolved by compose against **`infra/`**, the compose
  file's own directory — not against the repo root and not against your shell's cwd. The repo's
  `models/` is therefore `../models`; an absolute path works too. (`./models` silently mounts an
  empty, Docker-created `infra/models`, which is how E20-C's walk got
  `gguf_init_from_file: failed to open GGUF file '/models/llm/...gguf'`.)
- `TTS_COMPOSE_PROFILE=qwen3-tts make up` starts the additive eighth service (`tts-qwen3`) too; a
  plain `make up` never does.

`make compose-check` validates `infra/docker-compose.yml` (all eight service definitions) against a
throwaway env file — no `.env`, no build, no pull — and is part of `make gate`.

### Host-run (development) variant

Iterating without a GPU-passthrough container: run each service as a host process instead of
`make up`'s containers, in this order.

**Never `source` / `set -a && . ./.env`.** `Settings` reads `.env` itself (`SIM_ENV_FILE`), and
sourcing the file breaks the two JSON-list variables — `set -a && . ./.env` ends with
`SettingsError: error parsing value for field "cors_allow_origins"` (E20-C reproduced it). The
`make run-*` targets export only what the two NON-`Settings` processes need: `make profile-env`
writes `infra/.env.profile` for `llama-server`'s entrypoint (a plain `KEY=VALUE` file, safe to
source), and the Qwen3-TTS worker reads its own `SIM_TTS_QWEN3_*` vars from the environment. Every
other process reads `.env` through `Settings`, so it needs nothing exported at all.

```
docker compose -f infra/docker-compose.yml up -d --wait postgres redis livekit  # infra only (*)
make demo-init                # once (or after a fresh infra start): migrate + seed-users + scenarios
make run-llama-server         # host llama-server, SIM_LLAMA_SERVER_BIN must point at a real build
                              #   (it resolves the profile's model path onto this host by itself)
make run-tts-qwen3            # only if SIM_TTS_PROVIDER=qwen3_tts (own venv, workers/tts_qwen3/README.md)
make run-voice-agent          # python -m voice_agent.main, same entry point the container CMD uses
make run-api                  # uvicorn, SIM_API_HOST:SIM_API_PORT (default 127.0.0.1:8100)
cd frontend && npm run dev    # Vite dev server, port 5173
make preflight
#   ... §46 demo walk - docs/DOD_WALK.md ...
docker compose -f infra/docker-compose.yml down                                 # (*) matching stop
```

(*) `make dev-infra-up`/`dev-infra-down` exist too, but as of this writing they run `docker compose
-f infra/docker-compose.yml up`/`down` with **no service filter**, which starts the same seven
containers `make up` does (`infra/docker-compose.yml`'s own header comment says "three infra
services only" — that comment and the target have drifted apart; see `docs/AUDIT.md`). The explicit
`postgres redis livekit` filter above is what an infra-only host-run actually needs today.

A model profile names **container** paths (`/models/...`) — exactly where `make up`'s containers
mount `${MODELS_DIR}`, so they need nothing extra. A host run has no such mount, so set
`SIM_MODELS_ROOT=./models` (E20 ruling R15, `backend/app/config/model_paths.py`) in `.env` before
`run-voice-agent` / `run-tts-qwen3` / `preflight`: one env var, applied by a single resolver the
voice agent's providers, `app/cli/preflight.py` check 3, the Qwen3-TTS worker and every benchmark
script all share — `make models-layout` already lays the host `models/` directory out to match.

`make run-llama-server` needs nothing further: it regenerates `infra/.env.profile` through the
same resolver (`make profile-env PROFILE_MODELS_ROOT=$SIM_MODELS_ROOT`, E20-G), so
`SIM_LLAMA_MODEL_PATH` already names a file on this host. Only `SIM_LLAMA_SERVER_BIN` has to point
at a real llama.cpp build, since that binary is not part of this repository.

Also set `SIM_ASR_WARMUP_SAMPLE_PATH=models/warmup/warmup_ru.wav` on a host run (`.env.example`
ships that value): an empty path warms the ASR on a synthesised tone, which transcribes to nothing
and makes preflight check 5 red on a perfectly healthy ASR.

### Mic-less demo (no microphone, no browser)

```
python -m voice_agent.tools.inject --session <session-id> --wav a.wav --wav b.wav --wait-caller
make demo-inject ARGS='--session <session-id> --turns benchmarks/data/e2e/turns.jsonl'
```

Logs in as the seeded `trainee` account (`SIM_SEED_TRAINEE_PASSWORD` from the environment, exactly
like a browser would), joins the session's LiveKit room, and plays one or more 16 kHz mono WAVs (or
a `turns.jsonl` corpus, same shape as `benchmarks/data/e2e/turns.jsonl`) at real-time pace as the
trainee's "microphone", printing what the trainee's own realtime event stream reports about each
turn. `--help` documents every flag; `workers/voice_agent/voice_agent/tools/inject.py`'s own
docstring documents the session-state trap (the call must already be RINGING or CONNECTED) and why
it never prints the caller's literal words (HLD 40 §40.4 redacts them for the trainee role — this
tool authenticates as the trainee and must not reopen that leak).

## Documentation

- `docs/SPEC.md` — the owner's specification, verbatim. The law; never edit it.
- `docs/hld/` — the high-level design: `00-decisions.md` fixes the cross-cutting choices every other
  document and every epic must agree with; `openapi.yaml` is the REST contract; the rest cover the
  domain model, DB schema, scenario format, realtime protocol, voice pipeline and inference ops.
- `docs/RUNBOOK.md` — the operator runbook (start/stop, preflight, resetting demo data,
  troubleshooting) for a stack that is already running; `docs/DOD_WALK.md` is the SPEC §46
  Definition-of-Done walk's evidence.

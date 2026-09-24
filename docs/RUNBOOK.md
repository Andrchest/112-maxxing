# Operator runbook

Day-to-day operation of an already-cloned, already-`make deps`'d checkout (ruling R7 of the E20
epic). For the one-time fresh-clone-to-demo path (dependencies, models, `.env`), see the
README's "Running the full stack" section; this document starts from "the stack is (or was)
running" and covers start/stop, preflight, resetting demo data, and the maintenance operations a
demo session needs mid-way. Every command below is `make`-wrapped where a target exists; the
underlying command is named too, so this file stays correct if a target is renamed.

## Start / stop

```
make up                               # the SPEC §36 seven; TTS_COMPOSE_PROFILE=qwen3-tts adds tts-qwen3
make preflight                        # SPEC §38's 11(+1) checks; ARGS='--json' for machine output
make down                             # stop; postgres/redis/recordings volumes survive
```

The host-run variant (no containers for the app processes) is in the README's "Host-run
(development) variant" section.

**Never `source` `.env`.** `Settings` reads it itself (`SIM_ENV_FILE`); `set -a && . ./.env`
breaks the two JSON-list variables and ends with
`SettingsError: error parsing value for field "cors_allow_origins"` (E20-C reproduced it). The
only file meant to be sourced is `infra/.env.profile`, which `make profile-env` writes for
`llama-server`'s entrypoint — a plain `KEY=VALUE` file, and the `make run-*` targets source it for
you.

## Preflight

`make preflight` (`infra/scripts/preflight.sh`, wraps `python -m app.cli preflight`) runs every
`docs/hld/60-inference-ops.md` §5 check and prints PASS/FAIL/SKIP per check, plus a summary line.
Run it after every `make up` / host-run start, and again after clearing a FATAL latch or switching
a profile (below) before trusting the stack for a demo.

**Where it runs (E20).** Under `make up` the host cannot see the stack: `llama-server` publishes no
port and the voice agent's preflight endpoint binds loopback *inside* its container (SPEC §41, HLD
60 §9). So when a compose `voice-agent` is running, the script runs the checks **inside that
container** (`docker compose exec voice-agent python -m app.cli preflight`), which reaches every
dependency — its own `127.0.0.1:8113`, `llama-server:8080`, postgres/redis/livekit by service name,
`/models`, the GPU, and `scenarios/` (mounted read-only for this). Check 12 (`llama_server_binary`)
is a SKIP there — the binary lives in the llama-server image. Without a compose `voice-agent` it is
a host run and `SIM_MODELS_ROOT` defaults to the repo's `models/`.

```
make preflight ARGS='--profile DEV_3060TI --json'   # flags pass straight through
```

A `FAIL` on checks 1-3 (GPU / expected GPU / model files) usually means the profile's weights are
not where `SIM_MODEL_PROFILE`'s YAML expects them — re-run `make models` (compose) or see the
README's "Known host-run trap" (a host run's model paths, R15). A `FAIL` on checks 4-6 (LLM / ASR /
TTS respond) means the corresponding service is not up yet or the wrong provider is selected in
`.env` (`SIM_LLM_PROVIDER`/`SIM_ASR_PROVIDER`/`SIM_TTS_PROVIDER` — `fake` always passes trivially
and proves nothing about the real path).

## Resetting demo data

```
make demo-init          # migrate + seed-users + import scenarios/examples - idempotent, safe to re-run
```

Re-running `make demo-init` against an already-seeded database does **not** wipe anything: `migrate`
no-ops at head, `seed-users` upserts the three accounts by username (rotating passwords from the
current `SIM_SEED_*_PASSWORD` without touching `id`), and the scenario import is a no-op on a
version it already holds with the same content (`app/application/scenarios/import_scenarios.py`'s
own idempotence, D4) — it only fails loudly if a *file* changed under an already-imported version
number, which means the source YAML was edited without bumping `version`.

`make down` / `make dev-infra-down` deliberately do **not** pass `-v`, so a session's data
(PostgreSQL rows, recorded audio) survives a stack restart on purpose (SPEC §39's "never silently
reset the simulation"). To actually **wipe** the named volumes (a fresh empty database and no
recordings) and start over from `make demo-init`:

```
# DESTRUCTIVE - drops postgres-data, redis-data and recordings-data. Documented here, not run by
# this task: only run it when you mean to lose every session in the stack.
docker compose -f infra/docker-compose.yml down -v
```

## Troubleshooting

### "inference not ready" / a session's call never rings for real

1. `make preflight` — start here; it names exactly which of VAD/ASR/LLM/TTS/Postgres/Redis/LiveKit
   is not answering.
2. Check `.env`'s provider selection (`SIM_VAD_PROVIDER`, `SIM_ASR_PROVIDER`, `SIM_LLM_PROVIDER`,
   `SIM_TTS_PROVIDER`, `SIM_CALL_TRANSPORT`) — `fake`/`energy` providers are always "ready" and
   never contact a real model; a demo needs the real values (README's "Fresh clone to a working
   demo" section lists them).
3. `SIM_REQUIRE_INFERENCE_READY=true` (the shipped default) means `ring` refuses to start a call
   until every `voice:health:{vad,asr,llm,tts}` key is `READY` — this is correct behaviour, not a
   bug: create the session (or run `voice_agent.tools.inject`) only after preflight is green.
4. A component that warmed up once and then failed hard (an OOM, a wedged provider) can latch
   `FATAL` rather than flip back to `NOT_READY` on its own (`docs/hld/60-inference-ops.md` §4.3) —
   see the next section.

### A component is latched FATAL

`voice:health:fatal` is deliberately **sticky**: a container restart alone does not clear it
(§4.3's "a restart loop cannot make a fatal condition look transient"). Clear it explicitly once
the underlying cause (usually a GPU OOM another process caused, or a wedged provider) is gone:

```
# CLI (ADMIN role is implicit for a local operator; no REST auth needed from the shell)
uv run python -m app.cli preflight            # confirm which component is FATAL first
```

The clearing operation itself is a REST call, `POST /api/v1/admin/inference/clear-fatal`
(`clearInferenceFatal`, ADMIN only, `backend/app/api/routers/admin.py`) — log in as `admin`
(`SIM_SEED_ADMIN_PASSWORD`) and call it with a bearer token; it deletes the latch and returns the
readiness snapshot taken immediately after, which still reports `NOT_READY` for a component whose
warm-up has not actually re-run. Re-run `make preflight` afterward to confirm.

### Purging recordings

```
uv run python -m app.cli purge_recordings                              # dry run (the CLI's own default)
uv run python -m app.cli purge_recordings --no-dry-run                 # actually delete
uv run python -m app.cli purge_recordings --no-dry-run --older-than-days 7
uv run python -m app.cli purge_recordings --no-dry-run --session-id <uuid>
```

Same use case as `POST /api/v1/admin/recordings/purge` (`purgeRecordings`, ADMIN only) — a bare
`POST` with no body is also a dry run; `SIM_RECORDING_RETENTION_DAYS` (`.env`, default 30, `0` =
never purge) is the default window either front door uses when `--older-than-days`/the request body
does not override it.

### Switching a model profile

1. Edit `.env`: `SIM_MODEL_PROFILE=<name>` (a file under `backend/app/config/profiles/`, e.g.
   `DEV_3060TI`, `DEV_3060TI_SHARED`).
2. If the new profile needs weights you have not fetched yet, `make models` (or the individual
   `models-llm-qwen35 QWEN35_LLM_SIZE=...` / `models-tts-qwen3 QWEN3_TTS_VARIANT=...` targets) —
   the profile YAML names exactly which files under `models/` it expects
   (`docs/benchmarks/models.md`).
3. `make up` again (it calls `make profile-env` first, which regenerates `infra/.env.profile` from
   the *new* profile's `llm.*` block) — or, for a host run, `make run-llama-server` picks up the
   same regenerated file. Compose services that read the profile only at start-up (`llama-server`,
   `voice-agent`, `tts-qwen3`) need a restart; `docker compose -f infra/docker-compose.yml restart
   llama-server voice-agent` (add `tts-qwen3` with `--profile qwen3-tts` if it is running) is enough
   — `postgres`/`redis`/`livekit`/`backend`/`frontend` do not read the profile and need no restart.
4. `make preflight` to confirm the new profile's checks 1-6 are green before starting a session.

## SIP gateway (I3 E6a — `docs/hld/80-telephony.md` §80.2, §80.8)

**Ports** (prove them free first: `ss -lntup | awk '$5 ~ /:(5060|8114|20[01][0-9][0-9])$/'`
must print nothing): SIP **5060** udp+tcp, RTP **20000–20199**/udp, health **8114** on
`127.0.0.1`. Never 8000/8001/8011/8012/5000 (the entry point refuses them). Settings, all from the
environment or `.env`: `SIM_SIP_PASSWORD` (required, never committed; [credential redacted] in
every document), `SIM_SIP_REALM` (default `sim112`), `SIM_SIP_PORT`, `SIM_SIP_RTP_PORT_RANGE`,
`SIM_SIP_GATEWAY_HTTP_PORT`, `SIM_SIP_MEDIA_IP` (the LAN address advertised in SDP),
`SIM_SIP_BIND_HOST` (default `0.0.0.0`; `127.0.0.1` for a bench-only run), `SIM_SIP_JITTER_MS` (40).

- **Start:** `docker compose -f infra/docker-compose.yml --env-file .env --profile sip up -d
  sip-gateway`, or a host run `uv run python -m voice_agent.sip_gateway`.
- **Check:** `curl -s http://127.0.0.1:8114/health` → `{"status": "ok", "registrations": N,
  "calls": M, …}` (inside the container under compose).
- **Call the echo:** `uv run python -m voice_agent.tools.softphone --server <host>:5060 --register
  <name> --dial 999 --duration 5 --capture echo.wav` prints REGISTER/INVITE status, codec, RTP
  sent/received/lost, continuity and the echo round trip; `--headset` uses sox `rec`/`play` instead
  of the test tone. A third-party softphone: account `sip:<name>@<realm>`, server `<host>:5060`,
  the deployment password, codec G.711 A-law or μ-law.
- **Stop:** SIGTERM (`docker compose … stop sip-gateway`, or Ctrl-C on a host run) — the gateway
  sends BYE to every live call, then closes every port; re-run the `ss` line to confirm.
- **Symptoms:** `403` on REGISTER = wrong password or a username binding someone else's address;
  `403` on INVITE = the caller is not registered; `404` = a number other than `999` (ДДС numbers
  come with E6e); `488` = the softphone offers no G.711; one-way audio across machines =
  `SIM_SIP_MEDIA_IP` unset or the RTP range firewalled.

## E2E screenshot comparison (I3 E7a — the reference look, D20, C9)

`frontend/e2e/reference-look.e2e.ts` (Playwright, `@playwright/test`, pinned in
`frontend/package.json` to the version whose Chromium build is already cached in
`~/.cache/ms-playwright`) compares small, near-solid colour regions of the 112 card and the ДДС
memo workstation — the orange services bar, a selected blue questionnaire tag, the fill-deadline
timer (both states), and the dark title bars — against crops taken from the organizer's own
extracted screenshots (`frontend/e2e/reference/*.png`, cropped to the compared region; not
whole-page pixel equality — fonts/OS chrome differ from the organizer's real system). It needs a
real fake-provider backend + Vite dev server already running (the `_common.md` UI-check recipe
this task also used) — **it is not part of `make gate`** (vitest never starts a backend) and does
not start the stack itself.

**Start the stack** (fake providers, no GPU, ports 8100/5174 — never 8000/8001/8011/8012/5000):

```
# 1. A scratch Postgres database and a free Redis logical DB on the already-running test stack
#    (sim112test-postgres-1 :55432, sim112test-redis-1 :56379) — or your own dev stack (D1: dev
#    Postgres/Redis are 15432/16379). Pick any DB name / logical index not already in use.
docker exec sim112test-postgres-1 psql -U sim -d sim_test -c "CREATE DATABASE sim_e2e_ui"

# 2. Migrate, seed the three demo accounts and import the example scenarios — SIM_ENV_FILE points
#    at a scratch env file (copy .env.example, override SIM_DATABASE_URL / SIM_REDIS_URL to the
#    scratch DB above, SIM_JWT_SECRET / SIM_LIVEKIT_API_SECRET to real random values >= 32 bytes,
#    and SIM_SEED_{TRAINEE,INSTRUCTOR,ADMIN}_PASSWORD to your own — never a literal in a committed
#    file, SPEC §41). From backend/:
export SIM_ENV_FILE=/path/to/scratch.env
uv run alembic upgrade head
uv run python -m app.tools.seed_users
uv run python -m app.tools.import_scenarios ../scenarios/examples

# 3. Backend (same SIM_ENV_FILE, plus the fake providers — from backend/):
SIM_CALL_TRANSPORT=fake SIM_ASR_PROVIDER=fake SIM_LLM_PROVIDER=fake SIM_TTS_PROVIDER=fake \
SIM_EXPLANATION_LLM_PROVIDER=fake SIM_VAD_PROVIDER=energy SIM_REQUIRE_INFERENCE_READY=false \
  uv run uvicorn app.api.main:create_app --factory --host 127.0.0.1 --port 8100 &

# 4. Vite dev server (from frontend/):
VITE_API_PROXY_TARGET=http://127.0.0.1:8100 npx vite --port 5174 --strictPort --host 127.0.0.1 &
```

**Run the suite** (from `frontend/`; `SIM_SEED_TRAINEE_PASSWORD` / `SIM_SEED_INSTRUCTOR_PASSWORD`
are the same values the scratch env file above carries):

```
SIM_SEED_TRAINEE_PASSWORD=... SIM_SEED_INSTRUCTOR_PASSWORD=... UI_BASE=http://127.0.0.1:5174 \
  npm run e2e
```

Each test creates its own session through the instructor UI (`apartment-fire` for the 112 card —
the only schema-2 *operator* scenario is E3a′'s own TODO, so the test answers a real call and then
swaps only the snapshot's `card` for one built from the live `GET /reference/card-schema/v2`
through `page.route`, the same technique the I3 E3b task report verified end-to-end; `street-
rubbish-fire` for the ДДС memo workstation, a real schema-2 `GENERATED_CARD` scenario, no fake
needed) and tears nothing else down — drop the scratch database and flush the scratch Redis DB
yourself when done, the same way you created them, and stop the backend/Vite processes you started
(never the `sim112test-*` containers, never ports 8000/8001/8011/8012/5000).

**No browser download**: `npm install` never re-fetches a browser build
(`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`, set once when the `@playwright/test` devDependency was
added) — `~/.cache/ms-playwright` must show no new directory after `npm install` or `npm run e2e`.

## §46 demo walk

The full SPEC §46 Definition-of-Done walk (16 items, exercised for real against the stack) is
`docs/DOD_WALK.md` (E20-C) — this runbook only gets the stack ready for it.

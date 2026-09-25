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
  `403` on INVITE = the caller is not registered; `404` = a number other than `999` on a
  standalone gateway (the ДДС numbers: «SIP-телефон» below); `488` = the softphone offers no G.711; one-way audio across machines =
  `SIM_SIP_MEDIA_IP` unset or the RTP range firewalled.

## SIP-телефон — the ДДС phone on a softphone (I3 E6e — `docs/hld/80-telephony.md` §80.2.3, §80.3.5, §80.3.7, D27)

The gateway above, wired to the backend: a trainee's registered softphone places and receives the
ДДС calls the browser widget places and receives (`dds_brigade_call: ON`, memo mode).

- **Settings.** Both processes: the same `SIM_SIP_GATEWAY_SECRET` (the gateway's service credential
  on `/api/v1/telephony/*`; `.env` only, never committed — [credential redacted]). Gateway:
  `SIM_SIP_BACKEND_URL` (compose sets `http://backend:8100`; a host run `http://127.0.0.1:8100`),
  `SIM_REDIS_URL`, `SIM_LIVEKIT_URL` / `SIM_LIVEKIT_API_KEY` / `SIM_LIVEKIT_API_SECRET` (the room
  token is minted locally), `SIM_SIP_INVITE_AUTH` (`challenge`, the default: every INVITE is
  `407`-challenged; `registered_only`: E6a's rule). Backend: `SIM_TELEPHONY_ENDPOINTS=browser,sip`
  (without `sip` every call stays in the browser even with a softphone registered). The gateway
  refuses to start with a backend URL and no secret.
- **Accounts.** The SIP username is the trainee's login (`users.username`); an unknown or retired
  username gets `403` at REGISTER. Password: the deployment `SIM_SIP_PASSWORD`, or the user's own —
  `uv run python -m app.tools.set_sip_password --username <login>` (prompts twice; or
  `--password-env NAME`), `--clear` to go back to the deployment one. Only the HA1
  (`users.sip_ha1`) is stored. **Changing `SIM_SIP_REALM` invalidates every per-user password** —
  re-run the command for each user.
- **Numbers** (the ДДС screen shows «тел. …» on each service tab and the claimant's number beside
  «Позвонить заявителю»): `101`…`104` and `7xxx` — the service head of that service's leg on the
  card; `112` — the AI 112 operator; the claimant's number (`8…`, `+7…` or 10 digits) — the
  claimant; `999` — the echo. The session is the one whose card the trainee opened last, else the
  oldest ACTIVE ДДС session with the phone.
- **Dial from the softphone:** `uv run python -m voice_agent.tools.softphone --server <host>:5060
  --register <login> --dial 101 --duration 20 [--headset]` (the password from `SIM_SIP_PASSWORD`
  or `--password-env`). It rings until the AI party answers (4 s by default), then talks;
  hang up = `BYE` (the call ends as the trainee's `HANGUP`).
- **Be called on the softphone:** keep it registered and waiting — `… --register <login> --answer
  --answer-timeout 600 --duration 30` — then press «Позвонить старшему» / «Позвонить заявителю» /
  «Позвонить в 112» in the browser (the widget says «Разговор идёт на SIP-телефоне»), or let a
  brigade's `CALL_IN` step ring. Not answered within 30 s ⇒ the call ends by SYSTEM `ABORT`.
- **Check:** `curl -s http://127.0.0.1:8114/health` → `"backend": true`, `"dds_calls": N`,
  `"invite_auth": "challenge"`; `redis-cli --scan --pattern 'sip:binding:*'` lists the registered
  softphones; the ДДС call's `DDS_CALL_STARTED.endpoint` is `SIP`.
- **Symptoms:** `480` on dial = no ACTIVE ДДС session with the phone for this login (or the phone not
  offered in this stage state); `404` = the number reaches nobody on the card (a service with no
  leg, or a leg another trainee plays); `486` = the trainee already has a live ДДС call; `403` on
  INVITE = unregistered, or the `407` answered with a wrong password / another user's name; `503`
  = the backend is unreachable or the secret is wrong on one side; calls ring in the browser
  although the softphone is registered = `SIM_TELEPHONY_ENDPOINTS` lacks `sip`, or the Redis key
  expired (re-register); a foreign softphone: account `sip:<login>@<realm>`, outbound proxy
  `<host>:5060`, the user's SIP password, G.711.

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

## Резервное копирование (I4 E26 — `docs/hld/71-i4-wave4.md` §71.3, D33)

A daily `pg_dump -Fc` of the database plus a `tar.gz` of the recordings volume, written into
`./backups/` by the compose `backup` service (`postgres:16`, no extra image to pull). Every backup
is rotated to `SIM_BACKUP_KEEP` (default 14) and recorded in `backups/last.json` (timestamp, file
names, sizes, sha256, `status: "ok"|"failed"`).

```
make up                 # the backup service starts with the rest of the stack, no extra flag
make backup-now         # forces one run right now (does not wait for the daily loop)
make backup-verify      # reads backups/last.json; fails if missing, failed, or older than 26h
```

`make backup-now` runs `infra/scripts/backup-once.sh` inside the `backup` service (`docker compose
run --rm backup …`), so it also works before the service has been up for a full day. There is
**no gate-side restore test** (§3.1: too slow) — `make backup-verify` plus the recorded walk below
stand in for it, same as SPEC §46's other manually-walked items.

**What it does not cover** (Q-E14-2, not built): starting/stopping/backing-up from the admin UI, or
an off-box copy — this repo runs in a closed contour with no such destination.

## Восстановление (I4 E26 — `docs/hld/71-i4-wave4.md` §71.3, D33)

```
make restore FILE=./backups/sim-<ts>.dump RECORDINGS=./backups/recordings-<ts>.tar.gz
```

`infra/scripts/restore.sh` stops the `backend` service, copies the dump into the `postgres`
container and runs `pg_restore --clean --if-exists --no-owner` there, restores the recordings
archive into the `recordings-data` named volume via a throwaway container, then starts `backend`
again. `RECORDINGS=` is optional — omit it to restore only the database.

### Recorded restore walk (2026-09-25, scratch database — never a real one)

Proved end to end against a scratch database on the **test** Postgres (`:55432`, container
`sim112test-postgres-1`), per this epic's own rule never to touch a real database:

1. Created `sim_e26_backup_src` with one marker row (`marker(id, note)` = `(42,
   'e26-restore-proof')`) and a throwaway `fake-call.wav` standing in for a recording.
2. Ran `infra/scripts/backup-once.sh` for real (`docker run --network host … postgres:16 bash
   /scripts/backup-once.sh`, `PGHOST=127.0.0.1 PGPORT=55432 PGDATABASE=sim_e26_backup_src`):
   produced `sim-20260924T235958Z.dump` (1357 B), `recordings-20260924T235958Z.tar.gz` (169 B) and
   a `last.json` with `"status": "ok"` and both sha256 hashes.
3. `python infra/scripts/backup_status.py --path <scratch>/backups/last.json` → `OK: … 0.0h ago`,
   exit 0.
4. Ran three more backups with `SIM_BACKUP_KEEP=2`: rotation correctly dropped every dump/archive
   pair past the newest two.
5. Created an empty `sim_e26_backup_dst`. Ran `infra/scripts/restore.sh <dump> <recordings-archive>`
   with `SIM_RESTORE_SKIP_SERVICE_CONTROL=1` (no compose stack involved — this scratch walk never
   touches `backend`/any running container besides an `exec` into the already-running test
   Postgres) and `SIM_RESTORE_PG_CONTAINER=sim112test-postgres-1`, `PGDATABASE=sim_e26_backup_dst`,
   `SIM_RESTORE_RECORDINGS_DIR=<scratch>/restored-recordings`.
6. Verified: `SELECT * FROM marker` on `sim_e26_backup_dst` returned `(42, 'e26-restore-proof')` —
   the restored row, byte-identical to the source — and `restored-recordings/fake-call.wav`
   contained the original bytes.
7. Cleanup: dropped both scratch databases, removed the scratch directory. No project or owner
   container was started, stopped or restarted by this walk.

A real (compose-stack) walk follows the same `make restore FILE=…` command; the mechanism proved
above (steps 2, 5, 6) is identical, the only difference being which Postgres/container the dump
targets.

## HTTPS в классе (I4 E27 — `docs/hld/71-i4-wave4.md` §71.4, D32)

Browsers grant the microphone only in a **secure context**. A classroom PC that opens
`http://<server-LAN-IP>:5173` gets no microphone at all (`navigator.mediaDevices` is undefined), so
the phone widget, the ДДС call-back and the service-head calls are silent. `localhost` is the only
plain-http exception, which is why the problem never shows on the server itself. The fix is one
TLS endpoint, the compose `edge` service (Caddy, `infra/edge/Caddyfile`, profile `tls`), on 443:

| Path | Goes to | Notes |
|:--|:--|:--|
| `/rtc`, `/rtc/*` | `livekit:7880` | LiveKit signalling (WebSocket). Media stays WebRTC DTLS-SRTP on UDP 7882 (TCP 7881 fallback), straight to the SFU. |
| `/api/*` | `backend:8100` | REST and the realtime WebSocket `/api/v1/ws/...`. |
| everything else | `frontend:5173` | The Vite dev server, including its HMR WebSocket. |

Responses are compressed with zstd or gzip (¶390). Neither the access log nor the error log ever
contains the `?token=` / `?access_token=` of a WebSocket URL: both are replaced with `REDACTED`.

### 1. Certificates (once per server, and again whenever its address changes)

```
infra/scripts/make-certs.sh --ip <server LAN IP> --host <server hostname>
```

This writes `infra/certs/` (git-ignored, private keys `0600`). `ca.crt` is the local CA, and it is
the **only** file that goes onto classroom PCs. `ca.key` never leaves the server and never enters a
container. `server.crt`/`server.key` are what the edge serves. The certificate names `localhost`,
`127.0.0.1`, `::1`, every `--ip` and every `--host`. Without flags the script uses the default
route's source address and `hostname`. Re-running it **keeps the CA** and re-issues only the
server certificate, so the PCs install nothing again. `--new-ca` replaces the CA, and then every PC
must install the new `ca.crt`. The script prints the CA's SHA-256 and SHA-1 fingerprints; the
teacher compares one of them on each PC.

### 2. Start

In `.env` (all four lines are in `.env.example`, I4 E27 section):

```
COMPOSE_PROFILES=tls                         # `make up` now starts `edge` too
SIM_LIVEKIT_PUBLIC_URL=wss://<the IP or hostname the PCs open>
VITE_ALLOWED_HOSTS=<server hostname>         # only if PCs open a hostname; IPs are always allowed
#SIM_EDGE_HTTPS_BIND=<one address>           # only if something else already owns 443 on this box
```

Then `make up`. `TTS_COMPOSE_PROFILE=qwen3-tts make up` passes `--profile`, which **replaces**
`COMPOSE_PROFILES`; with both, write `COMPOSE_PROFILES=tls,qwen3-tts` and leave
`TTS_COMPOSE_PROFILE` unset. Before `make-certs.sh` has run, `up` stops with a "bind source path
does not exist" error that names `infra/certs/server.crt`. That is on purpose: Docker would
otherwise create an empty directory at that path.

Check from any machine that already trusts the CA: `curl --cacert infra/certs/ca.crt
https://<LAN IP>/api/v1/health/live` → `{"status":"LIVE",…}`. The PCs open **`https://<LAN IP or
hostname>`**. The old plain ports (5173, 8100, 7880) stay published for the host-run and development
paths, but a PC that uses them gets no microphone.

**CORS:** through the edge, the UI, the API and both WebSockets share one origin, so
`SIM_CORS_ALLOW_ORIGINS` needs no entry for the edge. **Audit addresses:** the backend trusts
`X-Forwarded-For` from Docker's bridge pool (`SIM_FORWARDED_ALLOW_IPS`, default `172.16.0.0/12`),
so `audit_log.client_ip` is the user's address, not the edge's. Caddy discards any
client-supplied `X-Forwarded-For`. **HMR** works through the edge: Vite's client dials
`wss://<page host:port>/`, and the edge forwards it (proved by the browser check below).

### 3. Установка корневого сертификата на компьютеры класса (один раз на каждый ПК)

Скопируйте `infra/certs/ca.crt` на флешку или в общую папку. Перед установкой сверьте отпечаток
сертификата с тем, что напечатал `make-certs.sh`.

- **Windows (Chrome, Edge, Яндекс Браузер):** дважды щёлкните `ca.crt`. На вкладке «Состав»
  сверьте «Отпечаток» (SHA-1). Затем «Установить сертификат…» → «Локальный компьютер» →
  «Поместить все сертификаты в следующее хранилище» → «Доверенные корневые центры сертификации»
  → «Готово». Перезапустите браузер. Вместо этого можно выполнить в командной строке от имени
  администратора: `certutil -addstore -f Root ca.crt`.
- **Firefox (любая ОС):** «Настройки» → «Приватность и защита» → «Сертификаты» → «Просмотр
  сертификатов» → «Центры сертификации» → «Импортировать…» → `ca.crt` → отметьте «Доверять при
  идентификации веб-сайтов».
- **Linux (Ubuntu), системное хранилище:** `sudo cp ca.crt /usr/local/share/ca-certificates/sim112-ca.crt
  && sudo update-ca-certificates`. Chrome/Chromium на Linux берёт корневые сертификаты из своей базы
  NSS: `certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n sim112-ca -i ca.crt` (пакет
  `libnss3-tools`).

Проверка: откройте `https://<адрес сервера>`. Замка с предупреждением быть не должно. При первом
звонке браузер спросит разрешение на микрофон.

### Host-run variant (backend, Vite and LiveKit on the host)

A container on this kind of host often cannot reach services bound on the host (the dev machine's
firewall drops container→host traffic), so the edge runs on the host network. `SIM_EDGE_LISTEN_PORT`
chooses the port, and the upstreams name host addresses:

```
docker run -d --name sim112-edge --network host \
  -e SIM_EDGE_LISTEN_PORT=9443 \
  -e SIM_EDGE_FRONTEND_UPSTREAM=127.0.0.1:5174 -e SIM_EDGE_BACKEND_UPSTREAM=127.0.0.1:8100 \
  -e SIM_EDGE_LIVEKIT_UPSTREAM=127.0.0.1:7880 \
  -v "$PWD/infra/edge/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v "$PWD/infra/certs/server.crt:/certs/server.crt:ro" -v "$PWD/infra/certs/server.key:/certs/server.key:ro" \
  caddy:2.11.4@sha256:0c994536bddb66445885237f1a5dcc1916bccea922661c76b4e9fc24061f9b52
```

Pass the same `SIM_LIVEKIT_PUBLIC_URL=wss://<LAN IP>:9443` to the backend, and start uvicorn with
`--forwarded-allow-ips 127.0.0.1` (the default) or the address the edge dials from. Remove the
container with `docker rm -f sim112-edge`.

### Browser check (Playwright, not part of `make gate`)

`frontend/e2e/tls-edge.e2e.ts` opens the UI through the edge at `https://<LAN IP>` (never
`localhost`, which is a secure context even over http) and asserts:

- `window.isSecureContext === true`, that `getUserMedia({audio: true})` returns a track, and that
  Vite's HMR socket connects over `wss://`;
- a control: the same UI over `http://<non-loopback address>` is **not** a secure context;
- the ДДС phone widget joins LiveKit over `wss://<edge>/rtc`, and its WebRTC transport reaches
  `connected`. It also asserts that the realtime channel runs over `wss://` and that nothing on the
  page dials plain `ws://`.

Chromium trusts exactly the local CA's key (`--ignore-certificate-errors-spki-list`, computed
from `SIM_EDGE_CA_CERT`). Any other certificate still fails. The stack is the "E2E screenshot
comparison" one above, plus LiveKit (`docker compose … up -d --no-deps livekit`, same
`SIM_LIVEKIT_API_KEY/SECRET` as the backend) and the edge:

```
SIM_SEED_TRAINEE_PASSWORD=... SIM_SEED_INSTRUCTOR_PASSWORD=... \
UI_BASE=https://<LAN IP>:<edge port> UI_INSECURE_BASE=http://<non-loopback Vite address> \
SIM_EDGE_CA_CERT=../infra/certs/ca.crt npx playwright test e2e/tls-edge.e2e.ts
```

**What this does not cover.** SIP TLS/SRTP (Q-E15-2): `sip-gateway` stays plain SIP/RTP and is not
behind the edge. The CA install is a manual step on each workstation. A second physical device
was not tested; the same box through its LAN IP stands in for the secure-context rule (§71.15).

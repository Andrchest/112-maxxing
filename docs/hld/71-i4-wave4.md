# HLD 71 — I4 wave 4: audit, operations, TLS, administrator, instructor, reports, materials, text quality

Turns the accepted wave-4 analysis (I4 E22, "wave-4 analysis (E9b, E11, E12, E13, E14, E15, E16)",
HEAD f94a257) into the repo's design. The E23 data recon supplies the spelling dictionary and street
list facts for §71.12. The manager's decisions on that analysis are final and are recorded as D29–D35
in `00-decisions.md`. **This document does not re-decide the design.** Where the analysis offered a
choice, the manager's decision is copied. Where a name was missing (an operationId, a path, a problem
code), E24 chose it as a technical detail, and every such name is listed in §71.16.

Nothing here edits HLD 10/30/40 or `openapi.yaml`. Those documents are parsed by tests
(`tests/api/test_contract.py`, `tests/integration/db/test_migration_baseline.py` and others), so
**each implementing epic updates them together with its code**, copying identifiers from this file
and from `docs/hld/contracts/i4-openapi-delta.yaml` literally. HLD 20 gains only a *planned* I4
section, §20.11. The §20.1 inventory is not touched, because a row there without its table fails
`test_migrated_tables_equal_the_hld_inventory`. The schemes are `docs/hld/puml/i4-*.puml`. The epic
list is the "I4 TBD epics" section of `docs/hld/90-tbd-epics.md`. The owner questions are in Russian
in `docs/owner-decisions.md`, under «Ждёт решения владельца».

Language rule unchanged (header of 00): identifiers are English, and trainee-facing labels are Russian.

Source shorthand, as in the analysis:
- ¶ is the ordinal paragraph of the ТЗ docx (`requirements/normalized/SRC-001-formal-docs.md`).
- REQ-nnnn are the normalized requirement ids.
- F-nn and §n.n point into the assessment `requirements/assessments/2026-09-23-requirements-vs-product.md`.
- «Q&A Lnnn» is a line of the Q&A transcript.

## 71.0 The eleven slices in one table

The owner's seven epics (E9b, E11, E12, E13, E14, E15, E16) are re-cut into the eleven slices of the
analysis §3.3 (D30). The epic ids are E25 = S1 … E35 = S11.

| Slice | Epic | Content | Deps | Wave | Tier | Migration |
|:--|:--|:--|:--|:--|:--|:--|
| S1 | E25 | Audit + JSON logs | — | α | opus | `0016_audit_log` |
| S2 | E26 | Ops hardening + backup/restore | — | α | sonnet | none |
| S3 | E27 | TLS edge | E26 | β | opus | none |
| S4 | E28 | Accounts backend | E25 | β | sonnet | none |
| S5 | E29 | Admin monitoring backend | E25, E26 | γ | sonnet | none |
| S6 | E30 | Admin UI | E28, E29 | δ | sonnet | none |
| S7 | E31 | Instructor core (timers, ABORTED cards) | E21 committed (tickets) | α → β | opus | none |
| S8 | E32 | Instructor misc (comments, scenario upload/archive, all-trainees board) | — | α | sonnet | `0017_result_comments_scenario_archive` |
| S9 | E33 | Reports, statistics, CSV, trainee history | E31 | γ | sonnet (opus review of the norms definitions) | none |
| S10 | E34 | Materials | — | α | sonnet | `0018_training_materials` |
| S11 | E35 | Text quality (report-only) | E23 data, E33 | δ | sonnet; any scoring waits for Q-E11-1 | none |

Waves, copied from §3.3 (parallel, no file overlap except the hot files of §71.1):
- α: S1 ∥ S2 ∥ S8 ∥ S10. S7 starts as soon as E21 is committed, because it edits tickets.
  E21 is committed as 3ee2764.
- β: S3 (after S2) ∥ S4 (after S1) ∥ S7.
- γ: S5 (after S1 and S2) ∥ S9 (after S7).
- δ: S6 ∥ S11.

The gate runs alone between commits, as usual.

## 71.1 Rules every I4 slice follows

- **Build only what the organizers fully define (D29).** An ambiguous organizer answer is not fully
  defined, so it becomes an owner question, not two variants behind a switch. Every excluded item
  below names its owner-question id.
- **Audit first.** S1 lands in wave α. Every later slice's HTTP actions are then audited by the
  middleware without per-slice code.
- **Hot shared files.** Each slice appends its own section to these files and never rewrites
  another slice's section. The manager regenerates `schema.d.ts` last, the same as E9a/E6b.
  - `backend/app/api/container.py`
  - `docs/hld/openapi.yaml`
  - `frontend/src/shared/i18n/ru.ts`
  - `frontend/src/shared/api/client.ts`
  - `docs/hld/20-db-schema.md`: the epic moves its §20.11 table into §20.1/§20.x when it builds it.
- **Migrations are pre-allocated (D30).** `0016` is audit (E25), `0017` is comments + scenario
  archive (E32), and `0018` is materials (E34). Parallel slices therefore never collide on
  `down_revision`. The chain at E24 ends at `0015_users_sip_ha1` (listed:
  `backend/app/db/migrations/versions/0001…0015`).
  - E32 and E34 set their `down_revision` to whatever is head when they land. The numbers are fixed;
    the order of landing is not.
- **SPEC invariants.** INV 1–14 stay as they are. The one scoring change is S7's timer-driven
  DEADLINE (§71.8); INV 9 holds, because the value comes from the log.

---

## 71.2 S1 / E25 — Audit + JSON logs

**Purpose.** One cross-cutting audit of every user action outside a session's own event log, plus
JSON logs from every process (analysis finding 4).

**Organizer sources** (analysis §1: E15 rows 3–5, E9b row 7, E16 row 2):
- ¶296 REQ-2244, ¶128 REQ-2114 and ¶213 REQ-2180: «Аудит всех действий пользователей», «Ведение
  учета всех действий» (F-26).
- ¶297 REQ-2245: «Хранение журналов безопасности не менее 6 месяцев».
- ¶246 REQ-2206: no change of grades «без фиксации в журнале аудита». A persisted rescore logs actor
  SYSTEM today (`application/scoring/rescore_session.py:93-124`, F-17).
- ¶372 REQ-2308: «JSON для логов и журналов».
- ¶205 REQ-2173: the admin views the logs. S1 writes them and S5 reads them.

**Design** (D31; scheme `puml/i4-audit-components.puml`, `puml/i4-audit-sequence.puml`).
- Domain: none. The audit is not a domain concern. `session_events` stay the in-session record
  (D5 unchanged).
- Application:
  - port `application/ports/audit_log.py`, with `AuditRecorder.record(entry)` and
    `AuditReader.page(filter)`;
  - `AuditEntry` holds ts, user_id, role, action, operation_id, method, path template, target ids,
    status, client ip and outcome.
- Infrastructure:
  - `infrastructure/persistence/audit_log_repository.py`;
  - `infrastructure/logging/json_formatter.py`, stdlib only and with no dependency. It is wired
    into the uvicorn `log_config` and the backend app logger. The voice agent and the SIP gateway
    replace their `logging.basicConfig` with it (`workers/voice_agent/voice_agent/main.py:1115`).
  - LiveKit's `livekit.yaml` `json: true` belongs to S2.
- API: an ASGI middleware in `api/main.py` records every authenticated request after the response.
  - It uses the path template and the operationId, and never the bodies (passwords, personal data).
  - It also records 401/403 as security events, and WebSocket connects.
  - It excludes `/health/*`: the instructor page polls readiness every `HEALTH_POLL_INTERVAL_MS`.
- `loginUser` records success and failure explicitly, because it is unauthenticated. The attempted
  username sits in `target_ids`, and a password never does.
- `rescoreSession persist=true` carries the real INSTRUCTOR/ADMIN user id in its audit entry.
- Config:
  - `SIM_AUDIT_RETENTION_DAYS`: default 365, and a settings validator refuses `< 183` (¶297).
  - `SIM_LOG_FORMAT=json|text`: default `json`.
  - `SIM_LOG_DIR`: the backend JSON log file with rotation, which S5's error report reads.
- What an entry does not hold: a before/after value. See "Not built".

**Data / DB.** Migration `0016_audit_log` creates the table `audit_log`, append-only through the
shared `trg_reject_mutation()` (HLD 20 §20.9 pattern), with indexes `(ts)` and `(user_id, ts)`. The
columns are in HLD 20 §20.11.1.

**API.** None of its own. `listAuditLog` is S5's read side. `loginUser` and `rescoreSession` keep
their contracts, and only their audit side-effect is new.

**Acceptance** (tests from the analysis):
- UPDATE/DELETE on `audit_log` is rejected.
- Every route in `openapi.yaml` except health produces exactly one entry. The test is parametrised
  over the contract, the same way `test_contract.py` iterates routes.
- A login failure is recorded, and no password appears in the entry.
- A retention below 183 is refused at settings load.
- The backend, voice agent and SIP gateway emit one JSON object per log line under
  `SIM_LOG_FORMAT=json`.

**Not built (owner questions).**
- **Q-E15-3**: a semantic before/after journal, such as «Иванов изменил оценку с 42 на 50»
  (analysis §5, first case; D-e). If the owner wants it, S1 grows domain-level records in the
  mutating use cases outside sessions. Everything else stands.
- Audit volume: roughly 50k rows or fewer per day for a 30-seat class, fine for PostgreSQL over
  6 months (§3.2). Health is excluded.

## 71.3 S2 / E26 — Ops hardening + backup/restore

**Purpose.** A classroom server that restarts itself, has no open datastore ports and has a daily
backup with a documented restore.

**Organizer sources** (E15 rows 2, 6, 7, 8; E16 row 3):
- ¶295 REQ-2243: «Защита от несанкционированного доступа». Today redis on host 16379 has no
  `requirepass`, and postgres 15432 has the defaults `sim/sim` (`infra/docker-compose.yml`, F-24).
- ¶143 REQ-2126, ¶286 REQ-2235 and ¶193 REQ-2164: backup «не реже 1 раза в сутки».
- ¶307 REQ-2252: documented procedures of installation, configuration and **restore**.
- ¶288 REQ-2237: automatic restart of services. `restart: unless-stopped` is missing on postgres,
  redis and livekit.
- ¶390 REQ-2321: «Поддержка сжатия данных», met here by `pg_dump -Fc` and a gzip of the recordings.

**Design** (D33; scheme `puml/i4-backup-restore.puml`).
- Compose:
  - redis gets `requirepass` via `SIM_REDIS_PASSWORD`, and `SIM_REDIS_URL` carries it;
  - postgres and redis ports are bound to `127.0.0.1`; the test compose is untouched;
  - postgres, redis and livekit get `restart: unless-stopped`;
  - `infra/livekit/livekit.yaml` gets `json: true`.
- Backup service `backup`, on image `postgres:16`, which is already local:
  - it loops `pg_dump -Fc` daily, plus a `tar.gz` of the recordings volume (`recordings-data`,
    mounted at `/data` in `backend`), into `./backups/`;
  - it keeps N = `SIM_BACKUP_KEEP` (default 14);
  - it writes `backups/last.json` (ts, sizes, sha256, status).
- `infra/scripts/restore.sh`: stops the backend, runs `pg_restore --clean`, restores the recordings
  and starts the backend again.
- `make backup-now`, `make restore FILE=…` and `make backup-verify`.
- RUNBOOK sections «Резервное копирование» and «Восстановление», including one recorded manual
  restore walk.
- The backend reads `last.json` from a mounted volume. S5 serves it, together with the purge guard.
- The FATAL latch stays manual (by design, SPEC §39).

**Data / DB.** No migration. The backups are files outside the database.

**API.** None. Backup status and the purge guard are S5.

**Acceptance.**
- `make backup-now` produces a dump and a recordings archive plus `last.json`.
- `make restore FILE=…` on the dev stack brings the data back, walked once and recorded in RUNBOOK.
- `redis-cli` without a password is refused.
- `docker compose config` shows loopback binds and the restart policies.
- Unit side: `last.json` parsing.
- A gate-side restore test is **not** added: it is too slow for the gate (§3.1).

**Not built (owner questions).** Q-E14-2: starting and stopping services, updating, and configuring
SIP/DB/logs/backup from the UI (¶189–¶203). Today these stay shell commands plus RUNBOOK. There is no
off-box backup copy, because none exists in a closed contour.

## 71.4 S3 / E27 — TLS edge

**Purpose.** Finding 2: browsers grant the microphone (`getUserMedia`, a WebRTC mic) only in a
secure context. A classroom where trainee PCs open `http://<server-LAN-IP>` gets no microphone. That
breaks the phone widget, the ДДС call-back (E6b) and the service-head calls (E6c). TLS is a working
prerequisite.

**Organizer sources** (E15 rows 1 and 13; E16 row 3):
- ¶293 REQ-2241: «Шифрование всех передаваемых данных (TLS/SSL внутри контура)».
- ¶142 REQ-2125: «Защиту каналов передачи данных» (F-24).
- REQ-5903: «Да, все в классе» (a real classroom LAN).
- ¶390 REQ-2321: compression, via gzip/zstd at the proxy.
- ¶279 REQ-2231 is met in part: TLS, least privilege and audit cover the technical side.
- Today everything is http/ws (`backend/Dockerfile:64`; `.env.example` `SIM_LIVEKIT_URL=ws://…`).

**Design** (D32; scheme `puml/i4-tls-edge-topology.puml`).
- One reverse-proxy service `edge` on 443, with these routes:
  - the frontend (Vite dev, or built assets);
  - `/api`, and `/api/v1/ws` with upgrade;
  - LiveKit signalling `/rtc` → `livekit:7880`.
- `SIM_LIVEKIT_PUBLIC_URL=wss://<host>`. Media stays WebRTC DTLS-SRTP on UDP 7882, which is already
  encrypted.
- `infra/scripts/make-certs.sh` (the host has `/usr/bin/openssl`) creates a local CA and a server
  certificate with SANs for `localhost`, the LAN IP and a hostname. RUNBOOK tells the teacher how to
  install the CA on classroom PCs.
- CORS and Vite `allowedHosts` are updated.
- **Proxy: Caddy** (D-f).
  - **The first step of E27 is pulling the image, within the time-box its brief sets.** The image
    is not local and the network is a slow proxy (analysis §5, fourth case).
  - **Fallback, if the pull fails:** uvicorn `--ssl-keyfile`/`--ssl-certfile`, Vite `server.https`,
    and the backend proxying LiveKit's `/rtc` WebSocket.
  - The fallback is doable, but it puts transport plumbing in the API process. It is described
    here and built only if the pull fails.

**Data / DB.** None.

**API.** None changed. URLs become `https://` and `wss://`, and paths are unchanged.

**Acceptance.**
- Open `https://<LAN-IP>` in Chrome on the same machine. A non-localhost origin is exactly the
  insecure-context case, so the microphone prompt appearing is a real test.
- Playwright asserts `window.isSecureContext === true`.
- The ДДС phone widget connects over `wss://`.
- HMR through the proxy works, or its absence is recorded in RUNBOOK.

**Not built (owner questions).** Q-E15-2: SIP TLS/SRTP. Real phones and softphones may not support
it, and E6e left it out. The SIP gateway stays plain. Separately, the self-signed CA is a one-time
manual step on each workstation.

## 71.5 S4 / E28 — Accounts backend

**Purpose.** An administrator can create, block/unblock, re-role and reset accounts. Today only a
CLI seed of three accounts exists (`backend/app/tools/seed_users.py`).

**Organizer sources** (E14 rows 1–3):
- ¶195 REQ-2165: «Создавать учетные записи пользователей всех категорий».
- ¶196 REQ-2166: «Назначать роли и права доступа». This is defined for the three fixed roles.
- ¶197 REQ-2167: «Блокировать/разблокировать учетные записи». `is_active` is already honoured at
  login and per request (`application/auth/get_current_user.py:59`), but it cannot be set.

**Design.**
- `application/users/{create_user,update_user,set_active,reset_password}.py`.
- Technical guards: you cannot block or demote yourself, and the last active ADMIN cannot be
  removed.
- Passwords are argon2 as today, with a minimum length from config.
- Every action is audited by S1 automatically.

**Data / DB.** No migration: `users.is_active` exists.

**API** (delta, `x-epic: E28`):
- `createUser` `POST /api/v1/admin/users`;
- `updateUser` `PATCH /api/v1/admin/users/{user_id}` (role, display name, is_active);
- `resetUserPassword` `POST /api/v1/admin/users/{user_id}/password`;
- `listUsers` gains `include_inactive` (ADMIN only), and `UserAccount` gains `is_active`.

ADMIN only. New problem codes are `USERNAME_TAKEN`, `SELF_MODIFICATION_FORBIDDEN` and
`LAST_ADMIN_REQUIRED`. A short password is the existing `422 VALIDATION_ERROR`.

**Acceptance.**
- The role gate: INSTRUCTOR and TRAINEE get 403.
- The self and last-admin guards hold.
- A blocked user's live token is rejected on the next request (already true; assert it).
- Each operation leaves one audit entry.

**Not built (owner questions).**
- Q-E14-1: whether ADMIN keeps instructor powers (¶218 least privilege, ¶215).
- Q-E15-1: multi-level authentication or a second factor (§8.1).
- Q-E14-4: an external access-control system.
- Q-E16-4: a JSON profile export (¶363).
- Custom rights beyond the three roles are discretion (no id; outside the ТЗ's defined part).

## 71.6 S5 / E29 — Admin monitoring backend

**Purpose.** The administrator's read side:
- logs;
- usage statistics;
- server load;
- errors and failures;
- alerts;
- backup status;
- a purge that is refused without a backup.

**Organizer sources** (E14 rows 4–8 and 11; E15 rows 9–10):
- ¶205 REQ-2173: «Просматривать системные журналы».
- ¶206 REQ-2174: «Анализировать статистику использования системы».
- ¶207 REQ-2175: «Формировать отчеты об ошибках и сбоях». Partial today: `MODEL_ERROR` events and
  the FATAL latch.
- ¶208 REQ-2176: «Отслеживать нагрузку на сервер». `gpu_memory_mb` is always None (F-23).
- ¶289 REQ-2238: real-time monitoring of critical parameters.
- ¶209 REQ-2177: already met (`/health/ready`, preflight).
- ¶308 REQ-2253: «система оповещения администратора об ошибках». The channel is in-app, because
  there is no internet and no mail server (technical).
- ¶216 REQ-2182: no deletion of critical data without a backup. `purgeRecordings` deletes WAVs with
  no backup check today (`application/recording/purge_recordings.py`).

**Design.**
- `application/admin/*`, `api/routers/admin.py`.
- `listAuditLog`: filters by user, action and period; paged.
- `getUsageStats`: per-day counts of logins, sessions, lessons and active users, from `audit_log`,
  `simulation_sessions` and `lessons`.
- `getServerLoad`: CPU from `/proc/stat`, memory from `/proc/meminfo` and disk from
  `shutil.disk_usage` (there is no `psutil`).
  - GPU comes from the voice-agent health heartbeat if it carries it, else `null`.
  - A metric is never faked: an absent metric is never 0 (the SPEC §27 rule, reused).
- `getErrorReport`, over a period, merges:
  - backend JSON-log records at level ≥ ERROR (from `SIM_LOG_DIR`);
  - `MODEL_ERROR` events;
  - `INFERENCE_HEALTH_CHANGED` to FATAL.
- `listAdminAlerts`: derived, not stored. It covers:
  - FATAL latches;
  - a stale backup (`last.json` older than 26 h) or a failed one;
  - repeated login failures.
- `getBackupStatus`: `last.json` as read, or `available: false`.
- `purgeRecordings`: refused with `409 BACKUP_REQUIRED` unless `last.json` is newer than the rows
  being purged.

**Data / DB.** No migration. It reads `audit_log` (0016) and existing tables.

**API** (delta, `x-epic: E29`):
- `listAuditLog` `GET /api/v1/admin/audit-log`;
- `getUsageStats` `GET /api/v1/admin/usage-stats`;
- `getServerLoad` `GET /api/v1/admin/server-load`;
- `getErrorReport` `GET /api/v1/admin/errors`;
- `listAdminAlerts` `GET /api/v1/admin/alerts`;
- `getBackupStatus` `GET /api/v1/admin/backup-status`;
- `purgeRecordings` CHANGED (`409 BACKUP_REQUIRED`).

ADMIN only.

**Acceptance.**
- An API test for each operation.
- The load endpoint returns `null`, never 0, for an absent metric.
- The purge is refused without a fresh `last.json` and allowed with one.
- An alert appears for a stale `last.json` and for a FATAL latch.

**Not built (owner questions).**
- Q-E14-3 (confirm only): the usage metric set above is built as proposed, and the owner confirms
  it is enough.
- Q-E14-2: service control from the UI.
- Q-E14-4: an external monitoring system (Zabbix/Prometheus).
- Q-E14-1: whether ADMIN reads reports, transcripts and recordings.

## 71.7 S6 / E30 — Admin UI

**Purpose.** The screens over S4 and S5.

**Organizer sources.** Those of §71.5 and §71.6 (¶195–¶197, ¶205–¶209, ¶216, ¶289, ¶308).

**Design.**
- `frontend/src/features/admin/*` at route `/admin`, ADMIN only. `homeRouteForRole` is updated.
- Tabs: Пользователи / Журнал / Статистика / Нагрузка / Ошибки / Оповещения.
- The app shell shows an alerts badge for ADMIN.
- The backup status is shown on the admin page (S2 → S5).
- Russian strings are in `ru.ts`.

**Data / DB.** None.

**API.** None new; it consumes the S4 and S5 operations.

**Acceptance.**
- A vitest per tab.
- The route is refused to non-ADMIN users.
- An absent metric renders «нет данных», never 0.

**Not built (owner questions).** Q-E14-1, Q-E14-2, Q-E14-3, Q-E14-4 and Q-E15-1, as in §71.5–§71.6.

## 71.8 S7 / E31 — Instructor core (scoring-adjacent)

**Purpose.**
- The instructor sets the per-card timers.
- Scoring follows those timers.
- An early-ended lesson keeps the unfinished cards in its report (findings 3 and 6).

**Organizer sources** (E9b rows 3 and 14; E12 row 1):
- ¶240 REQ-2200/2201: «Устанавливать временные рамки… По умолчанию значение - 30 сек.». See also
  REQ-6020 and assessment §9.5.
  - The 30 s default is the accept timer, and already exists as `accept_within_ms: 30_000`
    (`backend/app/domain/dds/card_status.py`).
  - It is not settable at assignment, and DEADLINE rules carry literal ms (`max_offset_ms: 30000`).
- ¶342–343 REQ-2288/2289: «Преподаватель завершает занятие (в любой момент)», and then a report «с
  информацией о действиях, замечаниях (ошибках), времени заполнения карточки…».
  - Today `abortLesson` aborts every open card (`application/lessons/abort_lesson.py`).
  - `getLessonReport` skips any card that is not COMPLETED (`application/lessons/lesson_report.py`).
- ¶329/¶343 REQ-2271–2273 (partial): the lesson report lists all actions.

**Design** (D34).
- Timer override:
  - `PlanEntry.timers: CardTimers | None` and `SessionCreateRequest.timers`;
  - resolved as scenario timers ← lesson/session override, in the same precedence style as the
    variants (HLD 70 §70.2.2);
  - recorded in `SESSION_CREATED.timers`, which is already recorded (`create_session.py:39-40`).
- DEADLINE:
  - a new optional `DeadlineConfig.max_offset_timer: accept_within_ms | fill_within_ms`;
  - when it is set, the evaluator reads the session's recorded timers from the log
    (`SESSION_CREATED.timers`), not a literal;
  - INV 9 holds because the value comes from the log;
  - a rescore of a pre-change log is unchanged, because the field is optional.
- Tickets' `memo_*_in_time` rules switch to `max_offset_timer: accept_within_ms`. This is a
  scenario content edit of `scenarios/tickets/**`, possible now that E21 is committed.
- Scenario validation gets rule **R43**: `max_offset_timer` names an existing timer key (HLD 30).
- ABORTED cards in the lesson report:
  - `LessonReport.cards[].score` becomes nullable;
  - a new `unscored: {state, timeline, times}` is built from the same `timeline_entry` projection
    and visibility;
  - no change to SPEC §28 or to the session transitions;
  - the weighted sum ignores unscored cards, unchanged.

**Data / DB.** None: `SESSION_CREATED.timers` is already in the payload.

**API** (delta, `x-epic: E31`):
- `createSession` ADDITIVE `timers`;
- `createLesson` via `PlanEntry` ADDITIVE `timers`;
- `getLessonReport` CHANGED (`LessonReportI4`: nullable `score`, `unscored`).

**Acceptance.**
- INV 9 on a session with an overridden timer.
- R43 allow and deny.
- A lesson aborted mid-card lists the card unscored with its events.
- The weighted sum ignores it.
- Ticket scoring fixtures still pass with the default timer.

**Not built (owner questions).**
- Q-E9b-2: what "filling" means for a ДДС card under the 3-minute norm. REQ-6020's 3 minutes are not
  measured in the default ДДС mode, because `fill_within_ms` starts at `CALL_ANSWERED`, which never
  happens under `GENERATED_CARD` (HLD 70 §70.3.4).
- Q-E9b-6: scoring an unfinished card. It is shown unscored.
- Q-E9b-3: pass/fail criteria (¶241).
- Q-E9b-5: the instructor's expert grade (¶231).

## 71.9 S8 / E32 — Instructor misc

**Purpose.**
- Teacher comments on results.
- The scenario upload UI with archive.
- One live board of every trainee's cards.

**Organizer sources** (E9b rows 1, 2, 9, 10, 11; E13 row 8):
- ¶236 REQ-2197: «Предоставлять обратную связь (комментарии к результатам) через интерфейс»
  (§7.6 F-17).
- ¶237 REQ-2198: «Давать рекомендации по улучшению навыков», through the same channel.
- ¶267 REQ-2222: «Видеть рекомендации системы». The trainee side is completed by the comments.
- Q&A L786–789: «видит действия обучаемых, их результаты… всех обучаемых» (REQ-4059 context).
- ¶224/¶235 REQ-2188/2196: real-time monitoring.
- ¶222 REQ-2186: «Создавать, редактировать и валидировать (утверждать) учебные сценарии».
  - REST `importScenarioVersion`/`validateScenarioFile` exist (`routers/scenarios.py:115-160`), but
    no UI calls them.
  - "Edit" means uploading a new version, because versions are immutable (D4).
  - "Approve generated" belongs to E10.
- ¶229 REQ-2192: «Редактировать и удалять неактуальные сценарии». Delete means archive, because the
  FKs are RESTRICT.

**Design.**
- Comments:
  - table `result_comments` on a session or a lesson, append-only, with edits as new rows;
  - the trainee sees them when the report is visible to them (the same `report_visibility` gate);
  - report section «Комментарии преподавателя».
- Scenario upload UI:
  - an «Сценарии» page with a file input → the `validateScenarioFile` report →
    `importScenarioVersion`, using existing operations;
  - the content is read client-side, and `format` comes from the file extension.
- Archive:
  - `scenarios.archived_at`, with archive and unarchive operations;
  - pickers hide archived scenarios, and existing sessions are untouched (FK RESTRICT stays).
- All-trainees board `/instructor/board`:
  - a per-lesson table of every card: trainee, card title, `card_status`, countdown, and the score
    when completed;
  - built from `getLesson` plus one WS per active card, the pattern E4b uses;
  - or from a new `getLessonBoard` read model if N sockets per instructor is too many. That choice
    is technical and E32's. The delta carries `getLessonBoard` marked `x-optional`.

**Data / DB.** Migration `0017_result_comments_scenario_archive`:
- table `result_comments`, append-only trigger;
- column `scenarios.archived_at`.

See HLD 20 §20.11.2–§20.11.3.

**API** (delta, `x-epic: E32`):
- `listSessionComments` / `createSessionComment` `…/reports/{session_id}/comments`;
- `listLessonComments` / `createLessonComment` `…/lessons/{lesson_id}/comments`;
- `archiveScenario` / `unarchiveScenario` `…/scenarios/{scenario_id}/archive|unarchive`;
- `listScenarios` ADDITIVE `include_archived`, and `ScenarioSummary.archived_at`;
- optional `getLessonBoard` `…/lessons/{lesson_id}/board`.

**Acceptance.**
- A comment is visible to the trainee exactly when the report is.
- An edit adds a row and never updates one.
- Archive hides the scenario from `listScenarios` by default, and a running session on it is
  unaffected.
- The upload page shows the validation issues before importing.
- The board lists every card of a lesson with its status.

**Not built (owner questions).**
- **Q-E9b-4**: instructor isolation (¶245 REQ-2205) against the E9a shared-groups decision and
  Q&A L786–789. No change is made (D-g). Every INSTRUCTOR still manages every session, lesson and
  comment.
- Q-E9b-5: the expert grade (¶231).

## 71.10 S9 / E33 — Reports, statistics, CSV, trainee history

**Purpose.**
- A lesson report with times against the system's norms.
- A per-trainee statistics table.
- CSV export.
- The trainee's own history.

**Organizer sources** (E12 rows 1, 2, 5, 7, 10; E13 row 7; E16 row 1):
- ¶329/¶343 REQ-2271–2273: the lesson report «с информацией о действиях, замечаниях (ошибках)».
- ¶329 REQ-2274/2275: «времени заполнения карточки, отличия времени от нормативного (заданного в
  системе)». Today there is only the DEADLINE evidence string «N мс при норме M мс»
  (`domain/scoring/evaluators/deadline.py:74-78`).
- These ask for keeping records of results and progress, the history of performance, and
  statistics (there is no aggregate endpoint today):
  - ¶101 REQ-2092;
  - ¶225 REQ-2189;
  - ¶138 REQ-2122;
  - ¶232 REQ-2194.
- ¶252 REQ-2210 and ¶265/266 REQ-2220/2221: the trainee's own results, progress and history of
  errors. Today `/report` lists own sessions without scores.
- ¶360 REQ-2299 and ¶379 REQ-2313: «CSV для выгрузки отчетов и статистики».
- ¶165 REQ-2142: «Время формирования аналитических отчетов не более 30 секунд».

**Design.**
- The pure module `application/reports/norms.py` works per card and per leg:
  - `accept_ms` (HANDOFF_RECEIVED → first ACCEPTED/NOT_ACCEPTED) vs `accept_within_ms`;
  - `fill_ms` (112: CALL_ANSWERED → HANDOFF_CREATED) vs `fill_within_ms`;
  - the deviation;
  - the failed-rules count;
  - the critical errors.
- The norms are the ones the system holds: the session's recorded timers (after S7).
- `getTraineeStatistics`: per trainee, the sessions, lessons, average %, failed-rule counts by
  category and norm deviations. INSTRUCTOR/ADMIN see everyone, and a TRAINEE only themselves.
- `getMyHistory`: the same scoped to self, plus the list of own completed sessions with score and
  date.
- CSV:
  - `GET …/lessons/{lesson_id}/report.csv` and `GET …/statistics.csv`;
  - stdlib `csv`, UTF-8 with BOM, `;` separator, column headers in Russian.
- Frontend:
  - the lesson report table plus «Скачать CSV»;
  - `/instructor/statistics`;
  - the trainee's `/history`.
- Reports never recompute scores (the existing D11 guard).

**Data / DB.** None.

**API** (delta, `x-epic: E33`):
- `getTraineeStatistics` `GET /api/v1/statistics`;
- `getTraineeStatisticsCsv` `GET /api/v1/statistics.csv`;
- `getMyHistory` `GET /api/v1/me/history`;
- `getLessonReportCsv` `GET /api/v1/lessons/{lesson_id}/report.csv`;
- `getLessonReport` ADDITIVE per-card `norms`, `failed_rule_count` and `critical_error_count`
  (in `LessonReportI4`, together with S7).

**Acceptance.**
- The CSV parses back to the same numbers.
- No score is recomputed by a report path.
- A TRAINEE asking for another trainee's statistics gets 403.
- ¶165: one integration test, marked, generates the statistics in 30 s or less on a seeded
  1000-session dataset.

**Not built (owner questions).**
- Q-E12-1: which interval is the «время реакции». Both are measurable; neither is labelled so until
  the owner answers.
- Q-E12-2: a leaderboard, «уровень подготовленности», and charts. Charts are «рекомендуется» in
  ¶151, a bonus.
- Q-E12-3: «номер рабочего места».
- Q-E9b-2: the ДДС fill norm.
- Bonus items not built: charts, heat maps and Excel/PDF export (¶151–152, on the owner's bonus
  list).
- Out of scope: «инсайты ИИ» (¶233, ML).

## 71.11 S10 / E34 — Materials

**Purpose.** A reference base of methodical materials that instructors upload and trainees open.

**Organizer sources** (E13 rows 1–4; E16 row 4):
- ¶256 REQ-2213: «Просматривать инструкции и методические материалы (справочную базу)».
- ¶227 REQ-2190: «Создавать новые учебные материалы и загружать дополнительные ресурсы».
- ¶249 REQ-2207: «Доступ к назначенным учебным материалам и сценариям». Defined for scenarios, which
  already exist; for materials see Q-E13-1.
- ¶387 «DOCX для методических материалов», ¶370 «PDF для документации», ¶386: the accepted upload
  types.

**Design.**
- Table `training_materials`. Files live under `Settings.data_dir/materials/<sha256>`, the same
  pattern as recordings.
- Allow-list: pdf, docx, doc, xlsx, txt, md, png, jpg. The maximum size is `SIM_MATERIAL_MAX_MB`.
- Frontend:
  - the instructor page «Материалы»: upload, list and archive;
  - the trainee page «Справочная база»: list, open or download. A PDF opens inline and a DOCX
    downloads.
- The materials directory is inside the backed-up data (S2).

**Data / DB.** Migration `0018_training_materials` (HLD 20 §20.11.4).

**API** (delta, `x-epic: E34`):
- `uploadMaterial` `POST /api/v1/materials` (multipart; INSTRUCTOR/ADMIN);
- `listMaterials` `GET /api/v1/materials` (every authenticated role);
- `getMaterialFile` `GET /api/v1/materials/{material_id}/file` (every authenticated role);
- `archiveMaterial` `POST /api/v1/materials/{material_id}/archive`.

**Acceptance.**
- The role gates.
- The allow-list refusal.
- The sha dedupe: the same bytes are stored once.
- The download content type.

**Not built (owner questions).**
- **Q-E13-1**: whom a material is assigned to. Until it is answered, there is no assignment: every
  trainee sees the unarchived list, which is the ¶256 «справочная база» reading the analysis builds.
- Q-E13-2: preloading the organizers' memo, manual and classifier. Redistribution rights are not
  stated.
- ¶368 «XML для структурирования методических материалов»: discretion, no structure defined.
- Q-E16-2: PDF certificates and documents.

## 71.12 S11 / E35 — Text quality (report-only)

**Purpose.** The lesson report's «…а также грамматики» (¶329). It is a **report-time** annotation
of the text the trainee typed, with **no effect on the score** until the owner answers Q-E11-1
(D35, D-d).

**Organizer sources** (E11 rows 1–5):
- ¶329/¶343 REQ-2276, 2289: the lesson report «…а также грамматики» (F-21).
- ¶106 REQ-2096: «Оценка уровня подготовки… на основе анализа ручного ввода текста». Defined as
  "analysed"; "scored" is discretion.
- REQ-6017 (mentor): «проверка грамматики нужна только в момент оценки… опечатки в названиях улиц».
  So the check runs at report time, and **live underlining would contradict it**; it is not built.
- REQ-6018 (room): «Дубнинская… Дубининская… высылка пошла не туда». **A directory cannot detect
  this**: E23 found both streets in OSM. The error is caught by the existing truth comparison
  (`CARD_FIELD_CORRECT`, `domain/scoring/comparisons.py`), only in scenarios that carry that rule.
- The street directory, F-20: defined only on the 112 card path. In the default ДДС mode the trainee
  types no street (REQ-6029).

**Design.**
- The port `application/ports/text_checker.py` has two methods:
  - `misspellings(text) -> list[Span]`;
  - `street_status(street, locality) -> KNOWN | UNKNOWN | NEAR(n)`.
- Adapters in `infrastructure/reference/`:
  - spelling: the LibreOffice `ru_RU` hunspell dictionary (BSD-style, 146269 stems), read by
    `spylls` 0.1.7 (MIT, pure Python). E23 proved it offline.
  - streets: the OSM Moscow named-highway name list (ODbL 1.0, 5629 unique names). OSM carries no
    okrug or district.
- Where these live: E23 left them in `/tmp/teamwork-112-maxxing/data/{spell,streets}/` with
  `SOURCES.txt` and sha256. **E35 decides the packaging** (`reference/{lexicon,streets}`, sha-pinned
  in the manifest, licence notes) and adds `spylls` as a dependency (D-i). E24 adds no data file.
- The annotation is a pure function over the texts the trainee typed:
  - the final 112 card (`address.street`, `description.text`, `recipients.comment`);
  - the ДДС texts (`DDS_SERVICE_STATUS_SET.comment`, the reasons and the close comment). The ТЗ's
    own example is ¶341 «Сообщение принято, дежурная бригада направлена на место».
- The annotation becomes report section «Грамотность и адреса», plus a column in the lesson report
  and the statistics (after S9).
- Absent-data fallback: `available: false` renders «Проверка недоступна: словарь/справочник не
  установлен». It never shows «0 ошибок» (the SPEC §27 honesty rule).
- If the owner later wants a score, that is an 11th `EvaluatorType`. SPEC §28 says «exact ten», so
  it is a SPEC departure to record, not a silent add.
- Invariants:
  - INV 3 is unaffected: the directory is reference data, not WorldTruth.
  - INV 9: the checker is deterministic, and its data sha is recorded in the report envelope.
  - INV 10 is unaffected.
- Facts E23 measured that this design must survive:
  - the dictionary rejects the real street «Дубининская» and suggests «Дубнинская»;
  - 53 of the 75 scenario `address.street` values hit the OSM list. The misses are word order
    («улица Домодедовская»), МКАД by kilometre, oblast roads, «набережная Яузы», and «ул.
    Зверенецкая».

**Data / DB.** None.

**API.** Its report-section schema is **not** in the I4 delta. The shape depends on Q-E11-2 and
Q-E23-3/Q-E23-4, so E35 writes its own `openapi.yaml` section when it lands (§71.16).

**Acceptance.**
- A seeded misspelling in a ДДС comment appears in the section.
- With the data removed the section says «Проверка недоступна».
- The score and the report checksum are identical with and without the checker.
- The data sha is recorded.

**Not built (owner questions).**
- **Q-E11-1**: whether grammar changes the score.
- **Q-E11-2**: checking streets outside Moscow.
- **Q-E23-1**: registering an apidata.mos.ru key for ОМК УМ.
- **Q-E23-2**: pulling КЛАДР.
- **Q-E23-3**: pairs of real names like Дубнинская/Дубининская.
- **Q-E23-4**: whether street names bypass the general spell check. The analysis does not say so,
  so it is not decided here (D-d). E35 escalates if it is still open when E35 starts.
- Live underlining in the 112 card contradicts REQ-6017 and is not built. A "live, in the default
  flow" answer would need a 112-trainee text path (A-7), a new epic (analysis §5).
- «ул. Зверенецкая» in `scenarios/tickets/ticket-15-call-3` is **organizer-verbatim**: the same
  spelling is in `requirements/normalized/SRC-005-tickets-and-dds-memo.md` (REQ-5226) and
  `requirements/evidence/tickets-ocr.md`. OSM has «Зверинецкая». It is **not changed** (D-h) and is
  recorded as an observation for the owner.
- **Not built (manager, 2026-09-25): statistics column** — a per-trainee aggregate would re-check
  every session's text on every `getTraineeStatistics` call, which reads
  `StatisticsReader.scored_sessions` (deliberately narrowed to `norms.NORM_EVENT_TYPES`, no card
  text, no re-run of anything) precisely to hold ¶165's 30-second budget at a class's volume; the
  lesson report's own `text_quality` (per card, already computed for `getSessionReport`) carries no
  such cost and is built. Q-E23-4 stays open, as E35 left it.

---

## 71.13 Defined or discretionary items no slice builds

These come from the analysis tables. Each is either an owner question or is recorded for the manager.

| Item | Source | Why not built | Where |
|:--|:--|:--|:--|
| XML configuration / settings / workstations | ¶359, ¶373, ¶364 | contradicts `.env` + YAML (SPEC §26, §36); no workstation entity | Q-E16-1 |
| «XML для совместимости с legacy-системами» | ¶377 | no legacy system named; «все локалка без интеграции» (REQ-6022) | recorded, no question |
| PDF certificates / official documents | ¶365, ¶380, ¶386 | not defined anywhere | Q-E16-2 |
| MP3 recordings | ¶383 vs ¶369, ¶384 | conflict; WAV meets ¶369 | Q-E16-3 |
| JSON user profiles | ¶363 | conflict with SPEC §30 | Q-E16-4 |
| «Совместимость с основными СУБД» | ¶389 vs ¶301 | conflict; PostgreSQL 16 + plpgsql triggers | recorded, no build |
| Scenario parameters: type, location | ¶239 REQ-2199 | scenario authoring (E10) | E10 |
| «управление ИИ-модулем» | ¶220 REQ-2185 | ML / generation | out of scope |
| Timer in the ДДС card screen | ¶271 REQ-2225 | the 112 console has the fill timer; the real ДДС interface has none (D3, `dds-header-strip.tsx`), so a ДДС timer contradicts the copied interface (manager, 2026-09-25) | Q-E13-5 |
| Grammar check after teacher edits of generated scenarios | ¶320 REQ-2263 | E10 generation flow | E10 |
| Fault tolerance, horizontal scaling, buffering while the DB is down | ¶287, ¶166, ¶305 | single box / E17 load | out of scope |
| Integration with local access control / monitoring | ¶146–147 REQ-2128/2129 | no system named | Q-E14-4 |

## 71.14 Conflicts between sources (analysis §4)

- ¶245 instructor isolation vs Q&A L786–789 and the E9a shared-groups decision: Q-E9b-4, no change
  (D-g).
- ¶369 «MP3 или WAV» vs ¶383 «MP3» vs ¶384 «WAV»: Q-E16-3.
- ¶389 «основные СУБД» vs ¶301 PostgreSQL and the plpgsql triggers: recorded.
- ¶363 JSON profiles vs SPEC §30 relational: Q-E16-4.
- ¶359/¶373 XML config vs SPEC §26/§36 `.env` + YAML: Q-E16-1.
- ¶151 charts «рекомендуется» vs Q&A L783–785 «в виде графиков, в виде таблиц»: Q-E12-2.
- ¶140/¶292 «многоуровневая» vs Q&A «двухфакторка» (§8.1, open): Q-E15-1.
- ¶293 «все передаваемые данные» vs plain SIP from real phones: Q-E15-2.
- The 2026-09-23 owner rule (both variants) vs the 2026-09-25 I4 rule (do not build discretion):
  resolved by D29 for I4.
- Mentor REQ-6017 (grammar at assessment only) vs a "live spell-check" reading of the owner's E11
  wording «орфография в карточке»: report-only (D35).

## 71.15 What cannot be verified on this machine

- TLS from a second physical device. The same box via the LAN IP is a faithful proxy for the
  secure-context rule, not for a real classroom network (S3).
- 6-month retention in real time. Only clock-injected tests are possible (S1).
- A daily backup over several days. Only a forced run plus a restore walk is possible (S2).
- Report generation within 30 s at real class volume. Only seeded data is possible (S9).
- Whether the organizers' 11 open questions (sent 2026-09-25) change the E9b/E12 norms.
- GPU load as seen from the backend container (S5 returns `null` if the heartbeat does not carry it).
- The Caddy image pull over the slow proxy. E27's first step, time-boxed (D32).

## 71.16 Names E24 chose, and gaps for the manager

Technical names the analysis did not give. All are in the delta; an implementing epic copies them.

- operationIds and paths:
  - `createUser`, `updateUser`, `resetUserPassword` (the analysis gave the paths);
  - `getBackupStatus` `GET /api/v1/admin/backup-status`;
  - the paths of `listAuditLog`, `getUsageStats`, `getServerLoad`, `getErrorReport` and
    `listAdminAlerts` under `/api/v1/admin/`;
  - `listSessionComments`, `createSessionComment`, `listLessonComments`, `createLessonComment`;
  - `archiveScenario`, `unarchiveScenario`, `getLessonBoard` (`…/lessons/{lesson_id}/board`);
  - `getTraineeStatisticsCsv`, `getLessonReportCsv`;
  - `getMyHistory` at `/api/v1/me/history`;
  - `uploadMaterial`, `listMaterials`, `getMaterialFile`, `archiveMaterial`.
- Problem codes:
  - 409: `USERNAME_TAKEN`, `SELF_MODIFICATION_FORBIDDEN`, `LAST_ADMIN_REQUIRED`, `BACKUP_REQUIRED`
    (named by the analysis);
  - 422: `MATERIAL_TYPE_NOT_ALLOWED`, `MATERIAL_TOO_LARGE`.
- The `audit_log` column set and CHECK lists (HLD 20 §20.11.1), and the `result_comments` link
  column `replaces_comment_id` ("edits as new rows").
- The `audit_log` table number is the next free §20.1 row when E25 builds it. The analysis said
  row 32, but row 32 is `dds_calls` today.
- Recordings live in the named volume `recordings-data`, not in a host `data/recordings`. The backup
  service mounts the volume.

For the manager (not decided by E24):
- ¶271 REQ-2225, the ДДС card-screen countdown, is marked "check; small" by the analysis and is in no
  slice. It needs a slice owner, or a note that E4b's list countdowns satisfy it.
- The brief's delta scope named E28, E29, E32, E33, E34 (and E25). E24 **also** put E31's contract
  changes in the delta (`timers` on `createSession`/`PlanEntry`, and `LessonReportI4`), because E31
  changes three existing operations and the analysis gives the fields.
- E35's report-section schema is **left out** of the delta: it depends on the open questions Q-E11-2
  and Q-E23-3/4.

## 71.17 Contract and schemes

- `docs/hld/contracts/i4-openapi-delta.yaml`: OpenAPI 3.1 fragment, same conventions as the I3
  delta (`x-epic`, `x-change`, `x-action`, `x-emits`).
- `docs/hld/puml/i4-audit-components.puml`: S1 components.
- `docs/hld/puml/i4-audit-sequence.puml`: one audited request, a login failure and the S5 read.
- `docs/hld/puml/i4-tls-edge-topology.puml`: S3, with the Caddy edge and the named fallback.
- `docs/hld/puml/i4-backup-restore.puml`: S2 backup loop, restore, and the S5 purge guard.

## 71.18.1 I5 E39 — Instructors see everything, change only their own

Sources: Q-E9b-4 (answer 2026-09-26, variant а); ТЗ ¶245; Q&A L786–789; I3 E9a (shared groups).

- Owner = the row's `created_by_user_id` (lessons, sessions, trainee groups — all `NOT NULL`).
  One rule, `app.application.auth.ownership.require_owner_or_admin`: ADMIN passes; an INSTRUCTOR
  passes on their own row or on a row with no recorded owner (`None`, the legacy/seed rule — no
  such row exists today, the branch is kept in the pure function); another INSTRUCTOR gets
  `403 NOT_RESOURCE_OWNER` (new `ProblemCode`, under `Forbidden`); a TRAINEE keeps
  `403 FORBIDDEN_FOR_ROLE`. The check runs after the row is loaded (`404` first) and before any
  state check or write.
- Guarded operations: `startSession`, `abortSession` (a `caller` keyword; the `LessonRunner` and
  `abortLesson`'s card cascade pass none), `continueToNextStage` (its instructor path only),
  `releaseReportToTrainee`, `rescoreSession` with `persist: true` (the dry run stays a read),
  `startLesson`, `abortLesson`, `releaseLessonReport`, `requestWeightProposals`,
  `acceptWeightProposals` (the lesson plan's only edit), `updateTraineeGroup`,
  `deleteTraineeGroup`. `startLesson`/`abortLesson`/weights already had a creator-or-ADMIN check
  answering `FORBIDDEN_FOR_ROLE`; it now answers `NOT_RESOURCE_OWNER`.
- Unchanged: every read (overview, reports, lists, CSV, weight proposals), the append-only result
  comments (E32), `createLesson`/`createSession`/`createTraineeGroup`, ADMIN, scenario
  archive/unarchive (no uploader is recorded) and `generateReportExplanation`.
- Timer override, participants and the plan are fixed at creation: no endpoint changes them after
  it, so none is guarded beyond `acceptWeightProposals`.
- Contract: `LessonDetail.created_by_user_id` (additive, required) so the UI knows the owner;
  `SessionDetail`, `SessionReport.session` and `TraineeGroup` already carried it. No migration.
- UI: `canChangeOwned` (`entities/session/ownership.ts`) mirrors the rule; for a non-owner the
  lesson page's start/abort/release and weight controls, the live overview's abort and the
  report's release are disabled with «Изменять может только преподаватель, создавший занятие»,
  and a group's edit/delete with «Изменять может только преподаватель, создавший группу».
- Tests: `backend/tests/api/ownership/test_resource_ownership.py` (every guarded operation × owner
  / other instructor / admin; reads and comments by another instructor; a refused change writes
  nothing), `backend/tests/unit/application/auth/test_ownership.py` (the rule, incl. no owner).

## 71.18.2 I5 E40 — MP3 download of a call recording (Q-E16-3 variant b)

**Purpose.** ТЗ ¶369 allows «MP3 или WAV» for a call recording download; the recording is WAV
today (served with HTTP `Range` for the report player, `getAudioSegment`, E16 R7). ¶383 requires
MP3 specifically. Owner answer 2026-09-26, **Q-E16-3 variant (б)**: add the MP3 download, keep the
WAV one — a second representation of the same `audio_segments` row, not a new resource.

**Design as built.**
- `getAudioSegmentMp3` `GET /api/v1/sessions/{session_id}/audio/{audio_segment_id}/mp3` — the same
  segment `getAudioSegment` serves, as a complete `audio/mpeg` download (no `Range`: this is a
  download, not a seekable stream).
- Format (this task's own decision, not a re-litigated owner question): mono, the segment's own
  sample rate (16 kHz in every recording this codebase writes today), 64 kbit/s CBR.
- Encoding: `lameenc` (a compiled binding of the LAME encoder), added as a new backend dependency
  (`backend/pyproject.toml`, `uv.lock`) because the container has no system `ffmpeg`/`lame` binary
  — only the owner's conda env does, out of scope for a container-run backend. **Licence: LAME is
  LGPL-2.1-or-later; `lameenc`'s own Python binding is MIT.** Recorded next to the dependency in
  `backend/pyproject.toml` and here.
- Cache: `<sha256>.mp3` written next to the segment's WAV file under
  `DATA_DIR/recordings/{session_id}/…`, the hash taken over the WAV representation
  `getAudioSegment` would answer a plain `200` with (44-byte header + PCM) — a second request for
  the same segment is a cache hit, never a re-encode.
- Authorization: identical to `getAudioSegment` (E16 R3/R7) by construction —
  `ServeAudioSegmentMp3` composes `ServeAudioSegment.resolve_audio` (this task's addition to that
  use case) for the lookup, visibility check and file read, so the two operations' access rule can
  never drift apart. A trainee refused the WAV gets the identical refusal for MP3.
- Frontend: a «Скачать MP3» button next to the report's `<audio>` playback controls
  (`features/report/transcript-audio-panel.tsx`), downloading whichever segment is currently
  loaded into the player.

**Data / DB.** None (no migration; the cache is files on disk, not a table).

**API** (additive, `docs/hld/openapi.yaml`): `getAudioSegmentMp3`, reusing every existing
`ProblemCode` the WAV endpoint uses (`NOT_FOUND`, `FORBIDDEN_FOR_ROLE`/`PARTICIPANT_NOT_ASSIGNED`/
`REPORT_NOT_RELEASED`, `AUDIO_PURGED`) — no new problem code.

**Acceptance (this task's tests).**
- A known WAV is encoded and the result is a valid MP3 (frame sync header) whose decoded duration
  is within 5% of the source's (`tests/unit/application/reports/test_serve_audio_segment_mp3.py`).
- A second request for the same segment hits the cache and never re-encodes
  (same file, plus an HTTP-level proof in `tests/api/reports/test_audio_segment_mp3.py` that makes
  a second `encode()` call fail the test outright).
- A trainee without access gets the same refusal as for WAV (403/410/404 parity, same file).

## 71.18.3 I5 E41 — КЛАДР streets + organizer materials seed

**Purpose.** Two owner answers of 2026-09-26 (`docs/owner-decisions.md`): Q-E23-2 (pull КЛАДР
alongside OSM for the §71.12 street directory) and Q-E13-2 (put the organizer's own materials into
the §71.11 reference base).

**CHANGE A — КЛАДР streets (Q-E23-2).**
- `base.7z` (ФНС open data, 61,067,244 bytes) fetched 2026-09-27 from
  `https://fias-file.nalog.ru/downloads/2026.07.07/base.7z` (URL read from `Kladr47ZUrl` at
  `https://fias.nalog.ru/WebServices/Public/GetLastDownloadFileInfo`, which changes per ФНС
  release) — well inside the 30-minute time-box (E23's own recon had already proved the URL
  reachable). The archive is **not committed**; `backend/tools/import_kladr_streets.py` extracts
  it with `py7zr` (new `tools`-group dependency, `pyproject.toml`) into
  `reference/streets/kladr_moscow_street_names.txt` (9,079 unique `"<NAME> <SOCR>"` values of every
  `STREET.DBF` row whose `CODE` starts with `77`, КЛАДР's region code for Moscow, ТиНАО included).
  `STREET.DBF` (dBase III, codepage 866) is read with a small stdlib parser
  (`_iter_dbf_records`) rather than a general dbf library — `py7zr` is the one dependency this
  epic adds.
- `app.infrastructure.reference.street_directory.StreetDirectory` now unions the OSM file
  (required, unchanged behaviour if the КЛАДР file is absent) with the new КЛАДР file (optional):
  a street is `KNOWN` if either has it, and `NEAR` suggestions are drawn from the union
  (manager decision, final — CHANGE A's own wording). `TextCheckerPort.street_list_sha256` is now
  `sha256(osm_bytes + kladr_bytes)` when the КЛАДР file is present, the same "concatenate, then
  hash" shape `dictionary_sha256` already used for its two-file lexicon — no port/API contract
  change.
- Both files, their sha256 and their licence notes are recorded in `reference/streets/SOURCES.txt`
  and pinned in `reference/manifest.json`.
- E23's own recon (§71.12) had already noted `base.7z` "outside E23's brief" and left Q-E23-1
  (apidata.mos.ru ОМК УМ classifier key) and Q-E23-3/Q-E23-4 (confused real street pairs; whether
  street names bypass the general spell check) untouched — this epic does not touch them either.

**CHANGE B — organizer materials seed (Q-E13-2).**
- `reference/materials/organizer.yaml`: a tracked list naming three files under
  `requirements/sources/` (read-only, never copied) with Russian titles — the ДДС ARM-112 memo PDF
  («Работа с АРМ-112 для ДДС от ОКр»), the incident classifier xlsx («Классификатор происшествий
  v_046_24…»), and «КАРТОЧКА 112» (the docx under `01-qna-session-telegram/files`, not the
  `05-organizer-materials` folder). Each entry pins the source's sha256 at listing time; the seed
  CLI refuses to upload a source that has since drifted.
- **Excluded**, and why: the tickets PDF («Билеты- задачи по C 112 . АГС_ГСИ (1).pdf») contains
  scenario answers; the presentation template («ЛЦТ2026 Шаблон презентации (1).pptx») is not a
  reference/instruction document; «9. Деп Обороны и ЧС (1).pdf»'s first page is the project's own
  ТЗ cover sheet ("Учебное программное обеспечение для подготовки оператора ДДС… Техническое
  задание"), not a 112/ДДС operational reference — checked and left out per this epic's own
  screening rule.
- `app.tools.seed_materials` (`python -m app.tools.seed_materials`, `make seed-materials`) reads
  `organizer.yaml` and uploads each entry through the I4 E34 `UploadMaterial` use case — the same
  allow-list, size limit and sha256 file-dedupe an instructor's own upload gets. It adds its own
  idempotency on top: existing `training_materials` rows are read first, and a source whose
  sha256 is already present is skipped, so a second run creates no duplicate row (`UploadMaterial`
  alone only dedupes the *file on disk*, not the row). Uploader: the seeded `admin` account
  (`app.tools.seed_users`) — "a system or admin account per the existing seed pattern" — a missing
  `admin` account refuses the run rather than silently picking another actor.

**Data / DB.** No migration; `training_materials` rows only, through the existing E34 schema.

**API.** No contract change — no new endpoint, problem code or schema field.

**Acceptance.**
- A street packaged only in the КЛАДР extract (not in the OSM file) is `KNOWN`; a street packaged
  only in the OSM file is still `KNOWN` (`backend/tests/unit/infrastructure/reference/
  test_text_checker.py`).
- The reference-pack manifest tests pass unchanged (`backend/tests/unit/reference/
  test_manifest_shas.py`, `test_reference_pack.py`).
- `make seed-materials` run twice against a scratch database yields each material exactly once
  (`backend/tests/integration/persistence/test_seed_materials.py`).

**Not built (owner questions, unchanged by this epic).**
- **Q-E23-1**: registering an apidata.mos.ru key for ОМК УМ.
- **Q-E23-3/Q-E23-4**: confused real street-name pairs; whether street names bypass the general
  spell check.
- **Q-E13-1**: whether materials are assigned per lesson/group — still every trainee sees every
  material (unchanged; this epic only adds rows to the same reference base).

## 71.18.4 I5 E36 — Norms, reaction time, trainee rating, workstation

**Purpose.** I5's owner answers of 2026-09-26 (`docs/owner-decisions.md`) close four E33 gaps this
epic left "not built": the ДДС's own 3-minute norm, the two reaction times, the trainee rating,
and «Рабочее место».

**Sources:** Q-E9b-2, Q-E12-1, Q-E12-2, Q-E12-3 (`docs/owner-decisions.md`).

**Design.**
- `application/reports/norms.py`:
  - a new `NormKind.DDS_FILL` (Q-E9b-2): per leg, the same measured interval as `ACCEPT`
    (`HANDOFF_RECEIVED` → the leg's first primary decision), against `timers.fill_within_ms`
    instead of `accept_within_ms` — listed beside `ACCEPT`, not instead of it (the module still
    also has the 112 desk's own `FILL`, unchanged). A service with no status by session end is
    `measured_ms: null` («—»), exactly like `ACCEPT`.
  - `card_reaction_times` (Q-E12-1): a new pure fold, per leg — (a) `HANDOFF_RECEIVED` → the leg's
    first `DDS_CARD_OPENED`, (b) `HANDOFF_RECEIVED` → its first primary decision (numerically
    `ACCEPT`/`DDS_FILL`'s own `measured_ms`, exposed again under its own name — no norm, no
    deviation, purely descriptive). `DDS_CARD_OPENED` joins `NORM_EVENT_TYPES`. Nothing new for the
    112 operator's own card (Q-E12-1's instruction: "keep what exists").
- `application/reports/assemble_report.py`: `SessionReportView` carries `reaction_times` (gated
  with the ДДС sections, like `ACCEPT`/`DDS_FILL`) and `workstations` (the session's participants'
  logins, `SessionDetailView.participants[].username`, Q-E12-3).
- `application/statistics/trainee_statistics.py`: two new averages, `reaction_to_open_ms_avg` /
  `reaction_to_status_ms_avg`, attributed exactly like `accept_deviation_ms_avg` (a leg's
  `bound_user_id`, or any DDS participant for an unbound leg, never a `SCRIPTED` one). No new
  `DDS_FILL` deviation average — it would repeat `ACCEPT`'s, not add information.
  `TraineeAccount`/`TraineeStatisticsRowView` gain `username` (Q-E12-3), CSV-only — not part of the
  JSON `TraineeStatisticsRow`.
- `application/statistics/trainee_rating.py` (new, Q-E12-2): `GetTraineeRating` — the same
  `statistics_row` per trainee, over the same `StatisticsFilter`, ranked by `average_percent`
  descending (ties by `display_name_ru`), ranks `1..N`; a trainee with no qualifying session has
  none. INSTRUCTOR/ADMIN only. `trainee_rating_csv` renders it as a file.
- Frontend: the lesson report table gets a «Рабочее место» column and the reaction times beside the
  norms; `/instructor/statistics` gets a «Рейтинг» table (`getTraineeRating` +
  `getTraineeRatingCsv`).

**Data / DB.** None (no migration).

**API** (additive, `docs/hld/openapi.yaml`):
- `NormView.kind` gains `DDS_FILL`.
- `LegReactionTimeView` (new) on `LessonReport.cards.items.reaction_times`.
- `LessonReport.cards.items.workstation` (new, `string`).
- `TraineeStatisticsRow` gains `reaction_to_open_ms_avg` / `reaction_to_status_ms_avg`.
- `getTraineeRating` `GET /api/v1/statistics/rating`, `getTraineeRatingCsv`
  `GET /api/v1/statistics/rating.csv` (new, INSTRUCTOR/ADMIN).

**Acceptance.**
- A service with no status by session end: `DDS_FILL` norm not met, `measured_ms: null`.
- A tie in the rating: both trainees ranked, sequential ranks, ordered by name.
- The lesson report CSV and the statistics CSV parse back to the same numbers, workstation column
  included.
- The existing "no score is recomputed by a report path" test still passes.

**Not built (owner questions).** None outstanding for this epic — Q-E9b-2, Q-E12-1, Q-E12-2 and
Q-E12-3 are now implemented (`docs/owner-decisions.md` marked "Сделано: I5 E36.").

## 71.18.5 I5 E38 — Configurable «сдал / не сдал»

**Purpose.** The owner's answer to Q-E9b-3 (variant г, 2026-09-26): a pass/fail verdict that
combines a score threshold, a limit of failed rules and critical errors, each switchable, with the
defaults and the level (lesson / session) left to the stage — decided by the manager as below.

**Sources:** Q-E9b-3 (`docs/owner-decisions.md`); ТЗ ¶241.

**Design.**
- `domain/session/pass_criteria.py` (new, pure): `PassCriteria` — `min_score_percent` (int
  0…100 or `null` = off), `max_failed_rules` (int ≥ 0 or `null` = off), `fail_on_critical` (bool);
  defaults `70`, `null`, `true`; all three off is `PassCriteriaError` (`422 VALIDATION_ERROR`).
  `pass_verdict(criteria, total_points, total_max_points, failed_rule_count, critical_error_count)`
  is PASS iff every enabled criterion holds, and names the ones that did not (`PassCriterion`:
  `MIN_SCORE_PERCENT`, `MAX_FAILED_RULES`, `CRITICAL_ERRORS`). The percent is `score_percent` —
  `100 · total / max` clamped to 0…100, the statistics' own percent (`session_percent` now calls
  it); no maximum → no percent → the threshold, when on, is not met. A failed rule is a stored
  result that did not pass; a critical error is a stored result with `critical_failure` (the
  lesson report's existing counters).
- Recorded like I4 E31's timers: `createSession(…, pass_criteria)` / `createLesson(…,
  pass_criteria)` (the lesson's criteria for every card) → `SESSION_CREATED.pass_criteria`
  (additive catalog key; `None` records the defaults). A log without the key (every session created
  before this epic) reads as the defaults (`application/reports/pass_verdict.recorded_pass_criteria`).
- Derived at report time, stored nowhere: `GetSessionReport` sets `SessionReportView.pass_verdict`
  over the **whole** stored report's totals/counters after `score_report`/`checksum` are fixed;
  `getLessonReport` carries it per scored card (an ABORTED card: none, «—»). The statistics
  (`statistics_row`) count `pass_count` / `pass_rate` (`100 · pass_count / session_count`) over the
  same sessions as every other number, each judged by its own recorded criteria; the rating carries
  the same two numbers as an additional column, the ranking unchanged. Nothing in
  `app.domain.scoring` imports the criteria (asserted), so a score, its checksum and a rescore are
  unchanged by construction.
- CSV: the lesson report gains «Итог» («Сдал» / «Не сдал»; empty for an unscored card, the file's
  "not measured" convention), after «Критических ошибок»; the statistics and rating files gain
  «Сдано» and «Доля сдачи, %».
- Frontend: both instructor forms (single session, lesson) get the three controls (checkbox +
  number for the threshold and the limit, checkbox for critical errors; defaults preselected; all
  off or a bad number disables «Создать»); a request at the defaults sends no `pass_criteria`. The
  session report header shows «Итог: Сдал / Не сдал», the failed criteria with their numbers and
  the criteria applied (`entities/pass-verdict`); the lesson report table gets an «Итог» column (an
  unscored card reads «Итог: —»); `/instructor/statistics` gets «Сдано» («N (P%)») in both tables.

**Data / DB.** None (no migration): the criteria are an additive `SESSION_CREATED` payload key.

**API** (additive, `docs/hld/openapi.yaml`, section `# --- I5 E38`):
- `PassCriteriaRequest` on `SessionCreateRequest.pass_criteria` and
  `LessonCreateRequest.pass_criteria` (omitted key = its default; explicit `null`/`false` = off).
- `PassVerdictView` (`passed`, `failed_criteria`, `criteria: PassCriteriaView`, `score_percent`,
  `failed_rule_count`, `critical_error_count`) on `SessionReport.pass_verdict` (required, nullable)
  and `LessonReport.cards.items.pass_verdict` (`null` for an unscored card).
- `TraineeStatisticsRow` and `TraineeRatingRow` gain `pass_count` / `pass_rate`.

**Acceptance.**
- Verdict matrix: each criterion alone, combined, all-off rejected
  (`tests/unit/domain/session/test_pass_criteria.py`).
- A session without recorded criteria is judged by the defaults, over HTTP
  (`tests/api/lessons/test_pass_verdict.py`).
- The same actions under two criteria: identical score rows and checksum, both rescores
  `identical_to_stored`, no score row moved by any verdict-bearing read
  (`tests/api/lessons/test_pass_verdict.py`, `tests/invariants/test_inv_09_pass_criteria.py`).
- The lesson report, statistics and rating CSVs parse back to the JSON's verdict and pass numbers.

**Choices recorded (technical).** The threshold compares the unrounded clamped percent
(`percent ≥ threshold`); the UI truncates (never rounds up) the percent it prints beside a failed
threshold. A request at the defaults sends no `pass_criteria` (the server records the same
defaults). The criteria are not shown on the lesson detail page (not asked for).

## 71.18.6 I5 E37 — Admin read audit, profile JSON export, settings XML export/import

**Purpose.** Three of I5's owner answers of 2026-09-26: ADMIN's read access to reports/
transcripts/recordings/lesson reports is audited by name and target (Q-E14-1 variant б); a
downloadable JSON profile per account (Q-E16-4, ТЗ ¶363); export/import of the effective settings
as XML (Q-E16-1).

**Sources:** Q-E14-1, Q-E16-4, Q-E16-1 (`docs/owner-decisions.md`).

**Design.**
- **Q-E14-1 (audit of ADMIN reads).** No new access grant: `report_visibility`
  (`app.application.reports.visibility`) already treats `ADMIN` exactly like `INSTRUCTOR`
  (`user.is_instructor_or_admin`) for `getSessionReport`, `getAudioSegment`, `getAudioSegmentMp3`
  and `getLessonReport`, and E25's `AuditMiddleware` already writes one `audit_log` row per HTTP
  request naming the caller (`user_id`, `role`) and the path's own parameters as `target_ids`
  (`app.api.main._record`/`_target_ids`) — every one of these four operations' path already
  carries its full target (`session_id`, plus `audio_segment_id` for the two audio downloads,
  `lesson_id` for the lesson report), so no code changed here; `tests/api/reports/
  test_admin_read_audit.py` and `tests/api/lessons/test_admin_read_audit.py` prove it, one test
  per operation, as the epic's `CHECK` asks.
- **Q-E16-4 (`exportUserProfile`).** `app.application.users.export_profile.ExportUserProfile`
  (new): the account fields `UserAccountI4` already carries (never `password_hash`, never
  `sip_ha1`, SPEC §41) plus the E33 history summary (`TraineeStatisticsRowView`, reusing
  `statistics_row`/`took_part`/`visible_to_trainee` from `trainee_statistics.py`, now in that
  module's `__all__`) for a `TRAINEE` account, `null` for `INSTRUCTOR`/`ADMIN`. Allowed for the
  account itself or `ADMIN` only — deliberately narrower than Q-E14-1's `is_instructor_or_admin`:
  an `INSTRUCTOR` reading another account's profile is `403 FORBIDDEN_FOR_ROLE`. `GET /api/v1/
  users/{user_id}/profile-export`, downloads as `profile-<username>.json`
  (`Content-Disposition`). Frontend: «Скачать профиль (JSON)» on the admin users tab (per row) and
  on the trainee's `/history` page (own profile).
- **Q-E16-1 (settings XML export/import).** `app.config.settings_xml` (new module):
  - `SECRET_FIELD_NAMES` is derived from `Settings.model_fields` — every field already marked
    `Field(repr=False)` (this task additionally marks `database_url`, `redis_url`, `jwt_secret`,
    `livekit_api_key`, `livekit_api_secret`; `sip_gateway_secret`/`sip_password` were marked
    already) — never a second, hand-kept list.
  - `export_settings_xml(settings)`: every non-secret field as
    `<settings version="1"><setting name="SIM_…">value</setting>…</settings>`, its real env var
    name (honouring a field's `validation_alias`, e.g. `tts_model_variant` ->
    `SIM_TTS_QWEN3_MODEL`), `bool` as `"true"`/`"false"`, `list`/`dict` as JSON (the same wire
    pydantic-settings' env source already expects), a `None` value omitted.
  - `settings_env_lines(xml_text)`: validates schema (root, version, `<setting name="…">` only),
    every name known and non-secret, and each value's *type* — proved by actually constructing a
    throwaway `Settings()` with the values overlaid on the environment inside a
    restore-on-exit `with` block (`_temporary_env`), never the real `get_settings()` singleton.
  - `exportSettingsXml` `GET /api/v1/admin/settings/export` (ADMIN only) serves the export; a
    «Экспорт настроек (XML)» button on `/admin`.
  - Import is **CLI only** (manager decision): `python -m app.cli settings_import --file <xml>
    [--out infra/.env.settings]` (`backend/app/cli/settings_import.py`, wired into
    `app.cli.__main__`), `make settings-import FILE=<xml> [OUT=...]`. Validates with the same
    `settings_env_lines`, writes `NAME=value` lines to `--out` (default `infra/.env.settings`) on
    success only, refuses any secret name, never touches the running process or `os.environ`
    outside its own restore-on-exit probe.

**Data / DB.** None (no migration).

**API** (additive, `docs/hld/openapi.yaml`): `exportUserProfile`
(`GET /api/v1/users/{user_id}/profile-export`, new schema `UserProfileExport`), `exportSettingsXml`
(`GET /api/v1/admin/settings/export`). No new `ProblemCode` — both reuse `FORBIDDEN_FOR_ROLE` /
`NOT_FOUND` already in the enum.

**Acceptance.**
- One audit test per ADMIN read operation (session report, WAV, MP3, lesson report), each proving
  the row names the admin and carries the full target.
- `exportUserProfile`'s JSON asserted on its **exact** property set (never `password_hash`/
  `sip_ha1`); `403` for an `INSTRUCTOR` or another `TRAINEE` reading someone else's profile.
- `exportSettingsXml`'s body contains no secret's env name, the secret set derived from `Settings`
  in the test itself, not retyped.
- `settings_env_lines`'s round trip: export -> import -> the written env file loads into `Settings`
  equal to the exported (non-secret) values, including a `None`-valued and an aliased field.
- `make settings-import` end to end (real CLI process, real file).

**Not built (owner questions).** None — Q-E14-1, Q-E16-4 and Q-E16-1 are now implemented
(`docs/owner-decisions.md` marked "Сделано: I5 E37.").

**HLD gaps.** `infra/docker-compose.yml`'s `backend` service now also loads `.env.settings`
(`required: false`, same pattern as `llama-server`'s `.env.profile`) so a compose deployment's
next restart picks up an import; a host run (`make run-api`) has only one `SIM_ENV_FILE`, so an
operator folds `infra/.env.settings` into their own `.env` by hand (documented in
`docs/RUNBOOK.md`) — a second `SIM_ENV_FILE`-like variable for a host run was judged out of scope
for this epic (a technical choice, not a product one).

## 71.19.43 I7 E43 — Audit journal «было → стало» (Q-E15-3; ТЗ ¶246, ¶296)

**Purpose.** The owner answered Q-E15-3: the journal must show values, e.g. «Иванов изменил оценку
с 42 на 50». E25's row (who, which operation, which target, status, time) now also carries what the
operation changed.

**Design (as built).**
- Application: port `application/ports/audit_changes.py`:
  - `AuditChangeCollector.record(entity, field, before, after)` and `record_secret(entity, field)`;
    `AuditChangeScope.open()` / `close(token)` for the middleware;
  - `AuditChange(field="<entity>.<field>[qualifier]", before, after)`; values normalised to JSON
    (`audit_value`: enum → value, id/date → string, pydantic model → JSON dump, collection → list);
  - a pair whose normalised values are equal is dropped (a create records only what it set; an
    idempotent repeat records nothing);
  - secrets: `record_secret` keeps the field with `before`/`after` `None` («изменён»), and `record`
    on a field whose name contains `password`/`hash`/`ha1`/`token`/`secret`/`key`/`credential`
    drops the values whatever the caller passed (`is_secret_field`; a `[qualifier]` is not part of
    the name);
  - `NO_AUDIT_CHANGES`, the null collector every instrumented use case defaults to.
- Infrastructure: `infrastructure/audit/context_change_collector.py` `ContextVarAuditChanges` — one
  mutable list per open scope in a `ContextVar`, so a copied context (thread-pool dependency, task
  group) appends to its request's list; outside a scope (runners, CLI) `record` is a no-op.
- API: `AuditMiddleware._http` opens a scope before the app and closes it after the response; the
  collected list goes into the request's single `audit_log` INSERT, only when the outcome is `OK`
  (status < 400) — a refused or failed request writes `changes = NULL`. The container holds one
  `ContextVarAuditChanges` as `audit_changes` (collector) and `audit_change_scope` (scope);
  `Container._audit_changes()` hands it to every instrumented use case (the null one while
  `__init__` still runs — the `LessonRunner`'s `StartSession`, which runs outside any request).
- The table stays append-only: nothing is ever updated after the INSERT; `audit_log_append_only`
  is untouched and still refuses UPDATE/DELETE (including an UPDATE of `changes`).

**Instrumented use cases** (field names as stored; recorded after the commit):

| Operation | Changes |
|:--|:--|
| `createUser` | `user.username`, `user.display_name_ru`, `user.user_role`, `user.is_active` (from `null`); `user.password` «изменён» |
| `updateUser` | `user.display_name_ru`, `user.user_role` (`UpdateUser`); `user.is_active` (`SetActive`, block / unblock) |
| `resetUserPassword` | `user.password` «изменён» — never the password, hash or HA1 |
| `createLesson` | `lesson.title_ru`, `session_mode`, `group_id`, `participants` (logins), `scenario_plan` (`[{position, scenario_version_id, weight}]`), `timers[<position>]` (the entry's override), `time_scale` (when ≠ 1), `pass_criteria` (when given) |
| `acceptWeightProposals` | `lesson.weight[<position>]` for each card whose weight moved |
| `startLesson` / `abortLesson` | `lesson.state`; abort also `lesson.aborted_cards` (count) — the cards' own aborts report nothing (their `SESSION_ABORTED` events carry it) |
| `releaseLessonReport` | `lesson.report_released`, `lesson.released_cards` (count) — the per-card releases report nothing |
| `create/update/deleteTraineeGroup` | `group.name_ru`, `group.members` (logins); delete → `null` |
| `importScenarioVersion` | `scenario.slug` (new scenario), `scenario_version.title`, `.version`, `.content_sha256` (new version); an idempotent re-import reports nothing |
| `archiveScenario` / `unarchiveScenario` | `scenario.archived` |
| `uploadMaterial` / `archiveMaterial` | `material.title_ru`, `file_name`, `content_type`, `size_bytes`; `material.archived` |
| `createSessionComment` / `createLessonComment` | `comment.text`; an edit (`replaces_comment_id`) shows the replaced text as `before` |
| `releaseReportToTrainee` | `report.released` (first release only) |
| `rescoreSession persist=true` | `score.total_points` (stored → recomputed; `null` when none was stored) and `score.rule_points[<rule_id>]` for each rule that moved; a dry run reports nothing |
| `startSession` / `abortSession` | `session.state` (cheap, from the aggregate) |
| `setDdsServiceStatus` | `dds_leg.response_status` (the leg's status before the command, `ADDED` included) |

Not instrumented: `createSession` (the session is created `READY`; its full content is
`SESSION_CREATED`), every other session command (operator card fields, ДДС picker, calls — each
event already carries its value in the session's log, D5), `requestWeightProposals` (stores a
proposal, changes no weight), `purgeRecordings` / `clearInferenceFatal` (operational, not listed by
the manager); settings import is CLI-only and not audited (§71.18.6).

**Data / DB.** Migration `0019_audit_changes` (down `0018_training_materials`): nullable
`audit_log.changes jsonb` (HLD 20, `audit_log`). SQL `NULL` (not JSON `null`) when empty.

**API** (additive): `listAuditLog` gains `with_changes` (boolean, «Только с изменениями»:
`changes IS NOT NULL`); `AuditEntryView.changes` (array of the new `AuditChangeView`
`{field, before, after}`, empty when none). No new problem code.

**UI.** `/admin` «Журнал» (`features/admin/audit-log-tab.tsx`): column «Изменения» with a toggle
«Показать изменения (N)» (`aria-expanded`) that opens a list «поле: было → стало» under the row;
`audit-changes.ts` maps each field to a Russian label (qualifier «(карточка №2)»), enum values to
the labels the rest of the UI uses (roles, modes, lesson/session states, memo statuses), booleans to
«да»/«нет», `null` to «—», a secret to «изменён». Checkbox «Только с изменениями» sets the filter.

**Acceptance (tests).**
- One API test per instrumented operation asserting the row's exact `changes`
  (`tests/api/admin/test_accounts_audit_changes.py`, `tests/api/lessons/test_lessons_audit_changes.py`,
  `tests/api/reports/test_reports_audit_changes.py`, `tests/api/dds/test_dds_audit_changes.py`,
  `tests/api/test_scenarios_audit_changes.py`, `tests/api/materials/test_materials_audit_changes.py`);
- secrets: neither the created/reset password nor its digest appears in any row; password fields
  carry `null`/`null` (API) and every secret-looking name is nulled (unit,
  `tests/unit/infrastructure/test_audit_change_collector.py`);
- `tests/integration/db/test_audit_changes_migration.py`: upgrade keeps old rows (`NULL`),
  downgrade/upgrade round-trip, an UPDATE adding `changes` is refused by the append-only trigger;
  `test_audit_log_table.py` unchanged and passing;
- vitest `audit-log-tab.test.tsx`: expand/collapse with Russian lines, the filter's query.
## 71.19.44 I7 E44 — SIP over TLS + SRTP

**Purpose.** The owner's answer to Q-E15-2 (2026-09-26): «SIP шифруем (TLS/SRTP)». ТЗ ¶293
REQ-2241 asks for «шифрование всех передаваемых данных»; E27 (§71.4) encrypted browser ↔ server
and left the SIP gateway plain.

**Sources:** Q-E15-2 (`docs/owner-decisions.md`), ТЗ ¶293; HLD 80 §80.2 (the gateway), §71.4 (the
local CA of `make certs`).

**Design** (manager decisions, final).
- **Signalling.** `SipEndpoint.listen_tls` (`transport/sip/dialog.py`) serves SIP over TLS on
  `SIM_SIP_TLS_PORT` (5061/tcp) with `server_tls_context`: the `make certs` server chain + key
  (`SIM_SIP_TLS_CERT` / `SIM_SIP_TLS_KEY`), TLS 1.2+, no client certificate (Digest stays the
  authentication). A TLS connection is a `Channel` of kind `TLS` (`reliable`, `secure`); Via,
  Contact (`;transport=tls`), the registrar's binding (`transport=TLS`) and the gateway's own
  requests on it (BYE, UAC INVITE/ACK) use the TLS port. `SIM_SIP_TRANSPORTS` (default
  `tls,udp,tcp`) picks the listeners; plain UDP/TCP on 5060 stays for phones without TLS
  (Q-I7-E44-1). `voice_agent.sip_gateway.resolve_tls`: a missing/unreadable certificate switches
  TLS off with a warning while a plain transport remains, and refuses to start when TLS is the only
  one.
- **Media.** `transport/sip/srtp.py`: SDES (RFC 4568) with the one suite
  `AES_CM_128_HMAC_SHA1_80` (30-byte `inline:` key+salt; lines with an MKI, several keys or a
  session parameter other than `WSH` are skipped); SRTP itself is `pylibsrtp` (libsrtp2, a new
  dependency of `sim-voice-agent`) — no cryptography in our code. The answerer's rule
  (`negotiate_answer`): INVITE over **TLS** ⇒ the offer must be `RTP/SAVP` with an acceptable
  crypto line, else `488`, and the answer is `RTP/SAVP` + our own fresh key under the offer's tag;
  over **plain SIP** ⇒ `RTP/AVP` is answered plain RTP (any `a=crypto` ignored), `RTP/SAVP` is `488`
  (a key in clear SIP protects nothing). `RtpSession` gains `srtp` (protect on send, authenticate +
  decrypt on receive; a failing packet is dropped, counted `srtp_dropped`, and never latches the
  far address) and `require_srtp` (a TLS call sends and accepts nothing until its keys are set).
  The gateway's UAC INVITE to a softphone registered over TLS offers SRTP and rings it only over
  that TLS connection (closed ⇒ `leg FAILED 480`, never plain UDP); an answer without SRTP ⇒ BYE
  and `leg FAILED 488`. A re-INVITE on an SRTP call must keep an acceptable crypto line (else
  `488`, keys unchanged); a new far key re-keys the inbound side. Keys never reach a log line
  (`CryptoAttribute` / `SdpMedia` reprs redact them).
- **Softphone** (`transport/sip/softphone.py`, CLI `voice_agent.tools.softphone`): `transport="tls"`
  (`--transport tls --ca infra/certs/ca.crt`, server certificate verified), SRTP offered by default
  over TLS (`srtp=` overrides), and incoming calls answered with the same rule as the gateway.
- **Config / infra.** `SipGatewayConfig` gains `tls`, `tls_port`, `tls_cert`, `tls_key`; the same
  keys on `Settings` (`sip_transports`, `sip_tls_port`, `sip_tls_cert`, `sip_tls_key`); compose
  publishes `5061:5061/tcp` and bind-mounts `infra/certs/server.{crt,key}` read-only with
  `create_host_path: false` (like `edge`; the CA key never enters the container) — so
  `--profile sip up` now needs `make certs` first. `.env.example` section «I7 E44»; RUNBOOK
  «Шифрование SIP» (server, softphone settings, symptoms).

**Data / DB.** None. **API.** None.

**Acceptance** (`workers/voice_agent/tests/sip/test_sip_srtp.py`, `test_sip_tls_srtp.py`).
- Unit: crypto-line parsing (tag/suite/key, lifetime, `WSH`; refusals: other suites, MKI, short
  key, bad base64, non-inline, several keys, session parameters); the answerer's decision (TLS +
  SAVP accepted with a fresh key; TLS + AVP / no crypto / unsupported suite ⇒ `488`; plain AVP ⇒
  RTP; plain SAVP ⇒ `488`); the offerer's check of an answer; libsrtp protect/unprotect, tamper,
  replay and wrong key refused, inbound re-key.
- Integration (certificate from `infra/scripts/make-certs.sh` into a temp dir): TLS REGISTER +
  407-challenged INVITE with SDES to the echo `999` completes; every RTP datagram on the wire
  differs from its plaintext, is 10 bytes longer, does not contain the G.711 payload and decrypts
  back to it through an independent `pylibsrtp` session under the SDP's key, both directions; a
  re-INVITE keeps the media; `RTP/AVP` over TLS ⇒ `488`; UDP beside TLS stays plain RTP and
  refuses `RTP/SAVP`; a client without the local CA cannot connect; the gateway rings a
  TLS-registered softphone with SRTP (UAC) and the room hears it; `SIM_SIP_TRANSPORTS` parsing and
  the entry point's TLS refusals.
- baresip interop: NOT_RUN (not installed on this machine).

**Not built (owner questions).** Q-I7-E44-1: whether plain SIP (5060) is turned off. A TLS client
certificate, SRTCP (the stack sends no RTCP), DTLS-SRTP / ZRTP and the `AES_CM_128_HMAC_SHA1_32` /
AES-256 / GCM suites are not offered (technical scope: the one mandatory SDES suite).
## 71.19.1 I7 E52 — No-GPU deployment (CPU profile)

Source: the I7 E52 brief (manager's design, `/tmp/teamwork-112-maxxing/reports/i7/E42-gaps.md` §2
item 1, gap G1); ТЗ ¶171–176 (client/server hardware lists no GPU); Q&A 09:20 «в основном это будут
все функции работы на центральном процессоре… проверка решений на стандартных бытовых
компьютерах».

- New model profile `backend/app/config/profiles/CPU.yaml`: `llm.n_gpu_layers: 0` (Qwen3.5-2B
  Q4_K_M, the same GGUF DEV_3060TI already pins, `parallel_slots: 1`); `asr`/`tts` reuse
  `DEV_3060TI_SHARED`'s already-MEASURED CPU path verbatim (gigaam `v3_e2e_ctc` `device: cpu`
  `compute_type: float32`, RTF 0.036; Piper `device: cpu`, RTF 0.023–0.052); `vad` stays
  `device: cpu` like every shipped profile. `hardware.*`/`vram_budget_mb`/`min_vram_margin_mb` are
  inert placeholders (`gpu_name_contains: "none"` deliberately matches no real GPU name — an empty
  string would match every name as a substring, so a bug that ever reached check #2 for real would
  fail loudly instead of falsely passing); `measured_peak_vram_mb: 0` is a structural fact (nothing
  in this profile ever loads onto a GPU), not a benchmark result, so `validate_vram_margin` passes
  with no "unmeasured" warning. `llm.request_timeout_ms` (20000 ms) and `warmup.timeout_ms`
  (120000 ms) are documented as generous, UNMEASURED placeholders — real CPU voice timing is
  excluded from this task (owner decision) and SPEC §27 forbids inventing a measured number.
- `infra/docker-compose.gpu.yml` (new): the override holding every `runtime: nvidia` +
  `deploy.resources.reservations.devices` block for `llama-server`, `voice-agent` and `tts-qwen3`
  — moved out of `infra/docker-compose.yml`, which now names no GPU requirement anywhere on its
  own. `Makefile`: `COMPOSE_FULL_CPU` is the base file alone; `COMPOSE_FULL` (`make up`'s compose
  invocation) layers the GPU override on top of it — today's behaviour, unchanged. New `make
  up-cpu`/`make down-cpu` use `COMPOSE_FULL_CPU` directly and default `SIM_MODEL_PROFILE` to `CPU`
  (a target-specific variable, overridable with `make up-cpu SIM_MODEL_PROFILE=...`).
  `make compose-check` now renders both variants (with and without the GPU override).
- `app.cli.preflight`: new `profile_requires_gpu(profile)` (true when `llm.n_gpu_layers != 0` or
  any of `asr`/`tts`/`vad`'s `device` is `cuda`). Checks #1 (`cuda_gpu_available`) and #2
  (`expected_gpu_detected`) PASS `"не требуется профилем"` outright for a profile like `CPU.yaml`
  — without ever calling the GPU probe — instead of FAILing a machine that correctly has neither a
  GPU nor the nvidia container runtime. Check #3 (`model_files_exist`) is unchanged: a CPU model
  not present locally is still reported by name in the FAIL detail, never a crash.
- README.md: a new Russian «Требования к оборудованию» section (no GPU: interface, cards, reports
  and text/fake-provider mode all work; real voice on the CPU profile is slower, with no measured
  number given since none was taken) plus one-line pointers to `make up-cpu` from the fresh-clone
  and full-stack sections.

**Data / DB.** None (no migration; `backend/alembic.ini` head stays `0018_training_materials`).

**API.** None (no contract change; `CPU` is a config value of the existing `SIM_MODEL_PROFILE`).

**Acceptance.**
- `make compose-check` renders both variants clean (verified: the base file alone has zero
  `runtime: nvidia` occurrences; base + `infra/docker-compose.gpu.yml` has exactly three, matching
  the pre-change count).
- `backend/tests/unit/cli/test_preflight.py`: `profile_requires_gpu` true/false cases, checks #1/#2
  PASS `"не требуется профилем"` for `CPU.yaml` without calling the GPU probe (an
  `AssertionError`-raising fake proves it), check #3 reports a missing CPU model by name.
- `backend/tests/unit/config/test_profile.py`: `CPU` added to the shipped-profile parametrize list;
  `CPU.yaml` needs no GPU (`n_gpu_layers == 0`, every device `cpu`); its VRAM margin check passes
  with no warning.
- A real fake-provider backend start with `SIM_MODEL_PROFILE=CPU` (`SIM_CALL_TRANSPORT=fake` etc.)
  reached `/api/v1/health/live` -> `200 {"status":"LIVE",...}` against a scratch migrated database
  and a free Redis index (both dropped afterward); `python -m app.cli preflight --profile CPU`
  against that same process printed `[PASS] 1. cuda_gpu_available: не требуется профилем` /
  `[PASS] 2. expected_gpu_detected: не требуется профилем`, with check #3 correctly listing the
  four model files as missing on this GPU-only worktree (no crash).

**Not built (owner questions).** None.

**Awaiting owner / deferred by this task's own design.** Real CPU voice-call latency was not
measured (owner exclusion, this epic's brief); `llm.request_timeout_ms`/`warmup.timeout_ms`/
`latency_targets.*` in `CPU.yaml` stay documented placeholders until `benchmarks/benchmark_llm.py`
/ `benchmark_vram.py --profile CPU` are actually run on a CPU-only box and the results are folded
back in, same as any other profile's measured fields.
## 71.19.1 I7 E50 — Incident list live refresh + «Статус службы» (G2/G3), trainee /history columns (G9)

**Purpose.** Three ТЗ gaps from `reports/i7/E42-gaps.md` §2 items 2 and 5: the ДДС «Список
происшествий» and 112 «реестр» never refreshed and had no status filter (memo p.11 «бегунок
«Автообновление»», memo p.40 «поиск по статусу»), and the trainee's own `/history` (ТЗ ¶265
REQ-2220, «время реакции», «оценки») carried no pass/fail, reaction times or text-quality count
even though the lesson report already computes all four per session.

**Sources:** `reports/i7/E42-gaps.md` G2, G3, G9.

**Design.**
- **G2 (live refresh).** `IncidentListScreen`'s `useQuery` gained `refetchInterval`: 3 s while
  `document.visibilityState === 'visible'`, `false` otherwise, itself gated by a new
  «Автообновление» checkbox (default on, persisted to `localStorage` under
  `i112.incidentList.autoRefresh`, every read/write wrapped in `try/catch` so a blocked/absent
  store still renders the checkbox checked). No lesson- or list-scoped WebSocket exists to
  invalidate this query from instead: the only socket is `WS /api/v1/ws/sessions/{session_id}`
  (`backend/app/api/routers/realtime.py`), one per session, never per lesson or per caller — so
  polling is this page's whole live mechanism. A visible tab regaining focus already re-triggers
  TanStack Query's own `refetchOnWindowFocus`, which resumes the interval loop on its own once the
  tab is visible again, so no extra visibility-change wiring was added.
- **G3 (status filter + «Статус службы»).** The backend already accepted `card_status` on
  `listMyIncidents` (I3 E4a) — only the ДДС/112 list screen never sent it. A native `<select>`
  («Статус», values = every `CardStatus`, «Все» = no filter) now does. The list's server-side item
  gained one additive pair: `IncidentListItemView.service_leg_status` /
  `.service_leg_status_at_offset_ms` (`ServiceResponseStatus | None`, `int | None`) — the ДДС
  viewer's own leg (the `DDSAssignment` whose `bound_user_id` is the viewer, found by loading
  `uow.dds_assignments.list_for_stage` off the session's DDS `RoleStage`; `None` when nobody is
  bound to exactly one leg — a session with no `assigned_service_id` binding has every leg
  unbound, and guessing "the" leg for a trainee who plays several would misattribute a status the
  memo never asked this column to guess). `IncidentListTable` renders «Статус службы» as its own
  column, shown only when `consoleBasePath === '/dds'` (hidden entirely for the 112 register, per
  the gap's own wording, not merely blanked).
- **G9 (trainee /history columns).** Four additive fields on `MyHistorySessionView`/
  `MyHistorySession`, all `None` until the report is visible to the caller (the same rule
  `score_percent` already follows): `passed` (`session_pass`, already computed for `pass_count`),
  `reaction_open_ms` / `reaction_first_status_ms` (the mean of `_attributed_reaction_times` over
  *this one session*, the same attribution `reaction_to_open_ms_avg` already uses across every
  session), `text_quality_issue_count` (`text_quality.flagged_issue_count`, new: counts a
  `text_quality_report`'s misspellings plus its non-`KNOWN` street lookups — the same one-row-per-
  item counting `frontend/src/entities/text-quality/format.ts`'s `flaggedTextQualityItems` already
  does on the client). Reused, not duplicated: `StatisticsReader.scored_sessions` now also reads
  each session's final `incident_cards.values` (`ScoredSession.card_values`, one more outer join
  in the existing set-based statement) and widens its event-type filter to
  `NORM_EVENT_TYPES | TEXT_QUALITY_EVENT_TYPES` (still one statement); `GetMyHistory` takes the
  same `TextCheckerPort | None` `GetSessionReport` already does, `None`-is-unavailable, never
  raises. `/history` renders «Результат» (Сдал/Не сдал/—), «Реакция: открытие, с», «Реакция:
  первый статус, с» (rounded whole seconds — the mean's own ms, never re-measured) and «Замечания
  к тексту». CSV export is unaffected (`getMyHistory` has none; `getTraineeStatisticsCsv`'s header
  is untouched).

**Data / DB.** None (no migration) — every new field is additive JSON on an existing read, not a
new column.

**API** (additive, `docs/hld/openapi.yaml`): `IncidentListItem.service_leg_status` /
`.service_leg_status_at_offset_ms`; `MyHistorySession.passed` / `.reaction_open_ms` /
`.reaction_first_status_ms` / `.text_quality_issue_count`. No new `ProblemCode`.

**Acceptance.**
- Backend: `test_the_incident_list_shows_arrived_cards_with_status_and_deadlines` extended for the
  unbound (null) case, plus a new `..._the_bound_dds_participants_own_leg_status` test for the
  bound case (`tests/api/lessons/test_lessons.py`); `flagged_issue_count` unit tests
  (`tests/unit/application/reports/test_text_quality.py`); `GetMyHistory`'s four fields, with and
  without a checker (`tests/unit/application/statistics/test_trainee_statistics.py`); one HTTP
  assertion per field (`tests/api/lessons/test_reports_statistics.py`).
- Frontend: `incident-list-screen.test.tsx` (new) — the 3 s poll fires while «Автообновление» is
  checked, stops once unchecked, the preference survives a remount, and the select sends
  `card_status`; `history-page.test.tsx` gained a case rendering all four new columns, «—» for an
  unreleased session.
- `npm run check:api` clean (schema regenerated); `mypy`, `ruff check`/`format --check`,
  `check_imports.py` clean on the touched backend packages.

**Not built (owner questions).** None — G2, G3 and G9 are manager-decided, not product-level
choices left open.

**HLD gaps.** None found.

#!/usr/bin/env bash
# One backup run (I4 E26, docs/hld/71-i4-wave4.md §71.3, D33): `pg_dump -Fc` plus a `tar.gz` of the
# recordings volume, rotated to SIM_BACKUP_KEEP, with a `last.json` status file written last.
#
# Used two ways:
#   - as the body of `backup-loop.sh` (the compose `backup` service, run once every
#     SIM_BACKUP_INTERVAL_SECONDS);
#   - directly by `make backup-now` (`docker compose ... exec backup /scripts/backup-once.sh`, or a
#     scratch-database dry run pointed at a different Postgres via the PG* env vars below).
#
# DB connection is the standard libpq env vars (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE) —
# nothing here is compose-specific, so the same script runs unmodified against the compose
# `postgres` service or against a scratch database on the test Postgres (:55432) for a recorded
# dry-run walk (docs/RUNBOOK.md "Резервное копирование").
#
# No python3 or jq in the `postgres:16` image (checked 2026-09-25), so `last.json` is built with a
# plain heredoc — every value written into it is either a controlled format (ISO-8601 timestamp,
# the literal "ok"/"failed", a hex sha256, an integer size, or a filename this script itself named)
# never arbitrary text, so no JSON-escaping library is needed here. `infra/scripts/backup_status.py`
# (run on the host, which does have Python) is the one place that PARSES it back.
set -euo pipefail

BACKUP_DIR="${SIM_BACKUP_DIR:-/backups}"
RECORDINGS_DIR="${SIM_RECORDINGS_DIR:-/recordings}"
KEEP="${SIM_BACKUP_KEEP:-14}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "${BACKUP_DIR}"

DUMP_FILE="sim-${TS}.dump"
RECORDINGS_FILE="recordings-${TS}.tar.gz"
STATUS="ok"
ERROR=""

if ! pg_dump -Fc -f "${BACKUP_DIR}/${DUMP_FILE}"; then
    STATUS="failed"
    ERROR="pg_dump failed"
fi

if [[ "${STATUS}" == "ok" ]]; then
    if [[ -d "${RECORDINGS_DIR}" ]] && [[ -n "$(ls -A "${RECORDINGS_DIR}" 2>/dev/null)" ]]; then
        if ! tar -czf "${BACKUP_DIR}/${RECORDINGS_FILE}" -C "${RECORDINGS_DIR}" .; then
            STATUS="failed"
            ERROR="recordings archive failed"
        fi
    else
        # No recordings yet (a fresh install, or a scratch dry run with no recordings volume at
        # all) — an empty archive, not a failure: ¶390 REQ-2321 asks for a daily backup to exist,
        # not for recordings to be non-empty.
        tar -czf "${BACKUP_DIR}/${RECORDINGS_FILE}" -T /dev/null
    fi
fi

DUMP_SIZE=0
DUMP_SHA="null"
REC_SIZE=0
REC_SHA="null"
if [[ -f "${BACKUP_DIR}/${DUMP_FILE}" ]]; then
    DUMP_SIZE=$(stat -c%s "${BACKUP_DIR}/${DUMP_FILE}")
    DUMP_SHA="\"$(sha256sum "${BACKUP_DIR}/${DUMP_FILE}" | cut -d' ' -f1)\""
fi
if [[ -f "${BACKUP_DIR}/${RECORDINGS_FILE}" ]]; then
    REC_SIZE=$(stat -c%s "${BACKUP_DIR}/${RECORDINGS_FILE}")
    REC_SHA="\"$(sha256sum "${BACKUP_DIR}/${RECORDINGS_FILE}" | cut -d' ' -f1)\""
fi
if [[ -n "${ERROR}" ]]; then
    ERROR_JSON="\"${ERROR}\""
else
    ERROR_JSON="null"
fi

cat > "${BACKUP_DIR}/last.json" <<JSON
{
  "ts": "${TS}",
  "status": "${STATUS}",
  "dump_file": "${DUMP_FILE}",
  "dump_size_bytes": ${DUMP_SIZE},
  "dump_sha256": ${DUMP_SHA},
  "recordings_file": "${RECORDINGS_FILE}",
  "recordings_size_bytes": ${REC_SIZE},
  "recordings_sha256": ${REC_SHA},
  "error": ${ERROR_JSON}
}
JSON

# Rotate: keep only the newest KEEP dumps (and their matching recordings archives).
mapfile -t OLD_DUMPS < <(ls -1t "${BACKUP_DIR}"/sim-*.dump 2>/dev/null | tail -n "+$((KEEP + 1))")
for f in "${OLD_DUMPS[@]:-}"; do
    [[ -n "${f}" ]] && rm -f "${f}"
done
mapfile -t OLD_RECS < <(ls -1t "${BACKUP_DIR}"/recordings-*.tar.gz 2>/dev/null | tail -n "+$((KEEP + 1))")
for f in "${OLD_RECS[@]:-}"; do
    [[ -n "${f}" ]] && rm -f "${f}"
done

if [[ "${STATUS}" != "ok" ]]; then
    echo "backup FAILED: ${ERROR}" >&2
    exit 1
fi
echo "backup ok: ${BACKUP_DIR}/${DUMP_FILE} (${DUMP_SIZE} bytes), ${BACKUP_DIR}/${RECORDINGS_FILE} (${REC_SIZE} bytes)"

#!/usr/bin/env bash
# Restore procedure (I4 E26, docs/hld/71-i4-wave4.md §71.3, D33): `pg_restore --clean` the named
# dump, restore the recordings archive, bracketed by stopping/starting the backend so nothing
# writes to the database mid-restore. See docs/RUNBOOK.md "Восстановление" for the recorded walk.
#
# Usage:
#   infra/scripts/restore.sh <dump-file> [<recordings-archive>]
#   make restore FILE=./backups/sim-<ts>.dump RECORDINGS=./backups/recordings-<ts>.tar.gz
#
# `pg_restore` runs INSIDE a postgres container (never assumed to be on the host, matching the
# repo's own "bash + python3 stdlib only, driven by make" posture) — by default the compose
# `postgres` service, reached via `docker compose ... exec`, with the dump copied in first via
# `docker compose cp` (custom-format (`-Fc`) dumps restore more reliably from a real file than
# piped through stdin).
#
# SIM_RESTORE_PG_CONTAINER=<name> restores into a DIFFERENT, already-running container instead —
# reached with plain `docker cp`/`docker exec`, never touching docker-compose at all — which is the
# mode a scratch-database dry run uses: point it at the test Postgres's own container (:55432) with
# PGDATABASE set to a scratch database, and set SIM_RESTORE_SKIP_SERVICE_CONTROL=1 so this script
# also never stops/starts the (unrelated) compose `backend` service or touches the recordings
# named volume — the recordings archive, if given, is extracted to SIM_RESTORE_RECORDINGS_DIR
# instead. docs/RUNBOOK.md "Восстановление" records exactly this dry run.
set -euo pipefail

FILE="${1:?usage: restore.sh <dump-file> [<recordings-archive>]}"
RECORDINGS="${2:-}"
SKIP_SERVICES="${SIM_RESTORE_SKIP_SERVICE_CONTROL:-0}"
PG_CONTAINER="${SIM_RESTORE_PG_CONTAINER:-}"
PGUSER="${PGUSER:-sim}"
: "${PGDATABASE:?PGDATABASE is required (the database to restore into)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE=(docker compose -f "${REPO_ROOT}/infra/docker-compose.yml" --env-file "${REPO_ROOT}/.env")
DUMP_IN_CONTAINER="/tmp/sim112-restore-$$.dump"

if [[ "${SKIP_SERVICES}" != "1" ]]; then
    echo "Stopping backend..."
    "${COMPOSE[@]}" stop backend
fi

echo "Restoring database ${PGDATABASE} from ${FILE}..."
if [[ -n "${PG_CONTAINER}" ]]; then
    docker cp "${FILE}" "${PG_CONTAINER}:${DUMP_IN_CONTAINER}"
    docker exec "${PG_CONTAINER}" pg_restore --clean --if-exists --no-owner \
        -U "${PGUSER}" -d "${PGDATABASE}" "${DUMP_IN_CONTAINER}"
    docker exec "${PG_CONTAINER}" rm -f "${DUMP_IN_CONTAINER}"
else
    "${COMPOSE[@]}" cp "${FILE}" "postgres:${DUMP_IN_CONTAINER}"
    "${COMPOSE[@]}" exec -T postgres pg_restore --clean --if-exists --no-owner \
        -U "${PGUSER}" -d "${PGDATABASE}" "${DUMP_IN_CONTAINER}"
    "${COMPOSE[@]}" exec -T postgres rm -f "${DUMP_IN_CONTAINER}"
fi

if [[ -n "${RECORDINGS}" ]]; then
    if [[ "${SKIP_SERVICES}" == "1" ]]; then
        RECORDINGS_DIR="${SIM_RESTORE_RECORDINGS_DIR:?SIM_RESTORE_RECORDINGS_DIR is required in skip-services mode}"
        echo "Restoring recordings from ${RECORDINGS} into ${RECORDINGS_DIR}..."
        mkdir -p "${RECORDINGS_DIR}"
        tar -xzf "${RECORDINGS}" -C "${RECORDINGS_DIR}"
    else
        echo "Restoring recordings from ${RECORDINGS} into the recordings-data volume..."
        docker run --rm \
            -v sim112dev_recordings-data:/data \
            -v "$(cd "$(dirname "${RECORDINGS}")" && pwd)":/backup:ro \
            alpine sh -c "rm -rf /data/* && tar -xzf /backup/$(basename "${RECORDINGS}") -C /data"
    fi
fi

if [[ "${SKIP_SERVICES}" != "1" ]]; then
    echo "Starting backend..."
    "${COMPOSE[@]}" start backend
fi

echo "restore complete"

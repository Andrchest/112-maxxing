#!/usr/bin/env bash
# Entrypoint of the compose `backup` service (I4 E26, docs/hld/71-i4-wave4.md §71.3, D33): runs
# backup-once.sh once immediately, then again every SIM_BACKUP_INTERVAL_SECONDS (default 24h).
#
# A heartbeat file at /tmp/backup-heartbeat is touched at start-up and after every attempt
# (success or failure) so the compose healthcheck has something to check between two daily runs —
# see infra/docker-compose.yml's `backup` service comment.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTERVAL="${SIM_BACKUP_INTERVAL_SECONDS:-86400}"

touch /tmp/backup-heartbeat

while true; do
    "${SCRIPT_DIR}/backup-once.sh" || echo "backup-loop: backup-once.sh exited non-zero, will retry next interval" >&2
    touch /tmp/backup-heartbeat
    sleep "${INTERVAL}"
done

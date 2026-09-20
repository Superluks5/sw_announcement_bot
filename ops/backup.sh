#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/sw_announcement_bot}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/swbot}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="${BACKUP_DIR}/swbot-${STAMP}.tar.gz"
LOCK_FILE="${BACKUP_DIR}/.backup.lock"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

sudo install -d -m 700 "$BACKUP_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "Another backup is already running." >&2; exit 1; }

# Use SQLite's online backup API so the database is consistent while the bot runs.
if [[ -f "$PROJECT_DIR/economy/economy.db" ]]; then
  "${PYTHON_BIN:-python3}" - "$PROJECT_DIR/economy/economy.db" "$TEMP_DIR/economy.db" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
destination = sqlite3.connect(sys.argv[2])
with destination:
    source.backup(destination)
destination.close()
source.close()
PY
fi

mkdir -p "$TEMP_DIR/project"
for path in guild_data bot_logs.json permissions_config.json command_toggles.json \
    server_config.json maintenance.json; do
  if [[ -e "$PROJECT_DIR/$path" ]]; then
    cp -a "$PROJECT_DIR/$path" "$TEMP_DIR/project/"
  fi
done
mkdir -p "$TEMP_DIR/project/economy"
if [[ -f "$TEMP_DIR/economy.db" ]]; then
  mv "$TEMP_DIR/economy.db" "$TEMP_DIR/project/economy/economy.db"
fi

tar -czf "$ARCHIVE" -C "$TEMP_DIR/project" .

find "$BACKUP_DIR" -type f -name 'swbot-*.tar.gz' -mtime "+${RETENTION_DAYS}" -delete
chmod 600 "$ARCHIVE"
echo "Created ${ARCHIVE}"

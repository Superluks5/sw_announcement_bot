#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/sw_announcement_bot}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/swbot}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="${BACKUP_DIR}/swbot-${STAMP}.tar.gz"

sudo install -d -m 700 "$BACKUP_DIR"

# Capture the live database and runtime configuration, never .env or private keys.
sudo tar --ignore-failed-read --wildcards -czf "$ARCHIVE" -C "$PROJECT_DIR" \
  economy/economy.db \
  guild_data \
  bot_logs.json \
  '*_data.json' \
  permissions_config.json command_toggles.json server_config.json maintenance.json \
  2>/dev/null || true

sudo find "$BACKUP_DIR" -type f -name 'swbot-*.tar.gz' -mtime "+${RETENTION_DAYS}" -delete
sudo chmod 600 "$ARCHIVE"
echo "Created ${ARCHIVE}"

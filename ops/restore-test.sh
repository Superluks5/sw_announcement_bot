#!/usr/bin/env bash
set -Eeuo pipefail

ARCHIVE="${1:?Usage: restore-test.sh /path/to/swbot-*.tar.gz}"
PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/sw_announcement_bot}"
VENV="${VENV:-${PROJECT_DIR}/venv}"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

tar -xzf "$ARCHIVE" -C "$TEMP_DIR"

if [[ -f "$TEMP_DIR/economy/economy.db" ]]; then
  "${VENV}/bin/python" - "$TEMP_DIR/economy/economy.db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
result = connection.execute("PRAGMA integrity_check").fetchone()[0]
connection.close()
if result != "ok":
    raise SystemExit(f"SQLite integrity check failed: {result}")
print("SQLite integrity check: ok")
PY
fi

find "$TEMP_DIR/guild_data" -type f -name '*.json' -print0 2>/dev/null | while IFS= read -r -d '' file; do
  "${VENV}/bin/python" -m json.tool "$file" >/dev/null
 done

# Validate all restored JSON independently, then import application modules
# without starting Discord or systemd services.
"${VENV}/bin/python" - "$TEMP_DIR" <<'PY'
import json
import os
import sys

root = sys.argv[1]
for directory, _, files in os.walk(os.path.join(root, "guild_data")):
    for filename in files:
        if filename.endswith(".json"):
            with open(os.path.join(directory, filename), encoding="utf-8") as handle:
                json.load(handle)
print("Runtime JSON validation: ok")
PY

cd "$PROJECT_DIR"
PYTHONPATH="$PROJECT_DIR" "${VENV}/bin/python" -c 'import bot; import dashboard.app; print("Application startup import: ok")'

printf 'Restore test passed for %s\n' "$ARCHIVE"

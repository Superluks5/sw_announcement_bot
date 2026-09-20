#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/sw_announcement_bot}"
VENV="${VENV:-${PROJECT_DIR}/venv}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5000/health}"
cd "$PROJECT_DIR"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean; refusing deployment." >&2
  git status --short >&2
  exit 1
fi

PREVIOUS_SHA="$(git rev-parse HEAD)"
BACKUP_PATH="$(${PROJECT_DIR}/ops/backup.sh | tail -n 1 | sed 's/^Created //')"
[[ -s "$BACKUP_PATH" ]] || { echo "Backup was not created; refusing deployment." >&2; exit 1; }
git fetch origin main
git pull --ff-only origin main

if [[ -x "${VENV}/bin/pip" ]]; then
  "${VENV}/bin/pip" install -r requirements.txt
fi
"${VENV}/bin/python" -m unittest discover -s tests -v
"${VENV}/bin/python" -m py_compile bot.py dashboard/app.py

sudo systemctl daemon-reload
sudo systemctl restart swbot swbot-dashboard
if ! curl --fail --silent --show-error --retry 5 --retry-delay 1 --max-time 10 "$HEALTH_URL" >/dev/null; then
  echo "Health check failed; rolling back to ${PREVIOUS_SHA}" >&2
  git reset --hard "$PREVIOUS_SHA"
  "${VENV}/bin/pip" install -r requirements.txt || true
  sudo systemctl restart swbot swbot-dashboard
  exit 1
fi

echo "Deployment succeeded at $(git rev-parse --short HEAD)"

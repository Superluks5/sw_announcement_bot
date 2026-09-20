#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/sw_announcement_bot}"
VENV="${VENV:-${PROJECT_DIR}/venv}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5000/health}"
cd "$PROJECT_DIR"

PREVIOUS_SHA="$(git rev-parse HEAD)"
"${PROJECT_DIR}/ops/backup.sh"
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
  sudo systemctl restart swbot swbot-dashboard
  exit 1
fi

echo "Deployment succeeded at $(git rev-parse --short HEAD)"

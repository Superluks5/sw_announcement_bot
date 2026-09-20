#!/usr/bin/env bash
set -Eeuo pipefail

ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5000/health}"
STATE_DIR="${STATE_DIR:-/var/lib/swbot-monitor}"
mkdir -p "$STATE_DIR"

alert() {
  local message="$1"
  logger -t swbot-monitor -- "$message"
  [[ "${MONITOR_OUTPUT_ONLY:-0}" == "1" ]] && printf '%s\n' "$message"
  if [[ -n "$ALERT_WEBHOOK_URL" ]]; then
    curl --fail --silent --show-error --max-time 10 \
      -H 'Content-Type: application/json' \
      -d "$(python3 -c 'import json,sys; print(json.dumps({"content": sys.argv[1]}))' "$message")" \
      "$ALERT_WEBHOOK_URL" >/dev/null || true
  fi
}

if [[ "${FORCE_BOT_OFFLINE:-0}" == "1" ]] || ! systemctl is-active --quiet swbot; then alert "ALERT: swbot.service is offline"; fi
if [[ "${FORCE_DASHBOARD_OFFLINE:-0}" == "1" ]] || ! systemctl is-active --quiet swbot-dashboard; then alert "ALERT: swbot-dashboard.service is offline"; fi
if [[ "${FORCE_HEALTH_FAILURE:-0}" == "1" ]] || ! curl --fail --silent --max-time 10 "$HEALTH_URL" >/dev/null; then alert "ALERT: dashboard health check failed"; fi

restarts="${FORCE_RESTARTS:-$(systemctl show swbot --property=NRestarts --value)}"
if [[ "${restarts:-0}" =~ ^[0-9]+$ && "$restarts" -gt 3 ]]; then
  alert "ALERT: swbot has restarted ${restarts} times since its last manager reset"
fi

if [[ "${FORCE_MEMORY_ALERT:-0}" == "1" ]]; then
  mem_total=100; mem_used=95; mem_available=5; swap_total=100; swap_used=90
else
read -r mem_total mem_used mem_available swap_total swap_used < <(
  free -m | awk '/^Mem:/ {m_total=$2; m_used=$3; m_avail=$7} /^Swap:/ {s_total=$2; s_used=$3} END {print m_total,m_used,m_avail,s_total,s_used}'
)
fi
if [[ "${mem_total:-0}" -gt 0 && $((mem_used * 100 / mem_total)) -ge 90 ]]; then
  alert "ALERT: memory usage is ${mem_used}MB/${mem_total}MB"
fi
if [[ "${swap_total:-0}" -gt 0 && $((swap_used * 100 / swap_total)) -ge 85 ]]; then
  alert "ALERT: swap usage is ${swap_used}MB/${swap_total}MB"
fi

oauth_failures="${FORCE_OAUTH_FAILURES:-$(journalctl -u swbot-dashboard --since '10 minutes ago' --no-pager 2>/dev/null | grep -Ec 'OAuth .*failed|OAuth callback rejected|OAuth token exchange failed' || true)}"
if [[ "$oauth_failures" -gt 5 ]]; then
  alert "ALERT: ${oauth_failures} failed OAuth attempts in the last 10 minutes"
fi

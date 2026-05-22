#!/bin/bash
# zeroclaw-slack-probe.sh — host-side Slack liveness watchdog for ZeroClaw.
#
# Two rules trigger a `docker restart zeroclaw`:
#
#   1. POST https://slack.com/api/apps.connections.open with the Socket Mode
#      app token (provided via $SLACK_APP_TOKEN). After 3 consecutive
#      failures, restart. Catches token revocation, Socket Mode disabled,
#      Slack outage, network partition. Detection window: ~9 minutes
#      (3 fails × 3-min timer interval).
#
#   2. Zombie-socket detection: if `docker logs --since 6h` shows zero
#      `websocket connected|disconnect|reconnecting` lines AND the
#      container is running, restart. Slack rotates the Socket Mode
#      websocket every ~5h, so 6h of total silence is provably abnormal —
#      this catches the exact bug observed 2026-05-03 (half-dead TCP that
#      the upstream Rust adapter cannot detect: no client ping, no read
#      timeout, no SO_KEEPALIVE).
#
# Deployed to /opt/zeroclaw/bin/ via infra/tasks/zeroclaw_probe.py.
# Fired every 3 minutes by zeroclaw-slack-probe.timer.

set -euo pipefail

STATE_DIR=/var/lib/zeroclaw-probe
STATE_FILE="$STATE_DIR/consecutive_failures"
LOG_FILE=/var/log/zeroclaw-probe.log
CONTAINER=zeroclaw
MAX_FAILURES=3
ZOMBIE_WINDOW=6h

mkdir -p "$STATE_DIR"
[ -f "$STATE_FILE" ] || echo 0 > "$STATE_FILE"
touch "$LOG_FILE"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"
}

container_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ]
}

restart_container() {
  if ! container_running; then
    log "SKIP restart ($1): container is stopped — leaving as operator intended"
    echo 0 > "$STATE_FILE"
    return
  fi
  log "RESTART triggered: $1"
  if docker restart "$CONTAINER" >> "$LOG_FILE" 2>&1; then
    log "RESTART ok"
  else
    log "RESTART FAILED — docker daemon issue?"
  fi
  echo 0 > "$STATE_FILE"
}

if [ -z "${SLACK_APP_TOKEN:-}" ]; then
  log "FATAL: SLACK_APP_TOKEN not set in environment"
  exit 1
fi

# --- Rule 1: apps.connections.open probe ---
tmp_resp=$(mktemp)
trap 'rm -f "$tmp_resp"' EXIT

http_code=$(curl -sS -o "$tmp_resp" -w '%{http_code}' -m 8 \
  -X POST \
  -H "Authorization: Bearer $SLACK_APP_TOKEN" \
  https://slack.com/api/apps.connections.open) || http_code="000"

body=$(cat "$tmp_resp" 2>/dev/null || true)

if [ "$http_code" = "200" ] && \
   printf '%s' "$body" | jq -e '.ok == true and (.url | startswith("wss://"))' >/dev/null 2>&1; then
  echo 0 > "$STATE_FILE"
  rule1_ok=1
else
  fails=$(cat "$STATE_FILE")
  fails=$((fails + 1))
  echo "$fails" > "$STATE_FILE"
  preview=$(printf '%s' "$body" | head -c 160 | tr -d '\n')
  log "PROBE-FAIL ($fails/$MAX_FAILURES) http=$http_code body=$preview"
  rule1_ok=0
  if [ "$fails" -ge "$MAX_FAILURES" ]; then
    restart_container "apps.connections.open failed $fails consecutive times"
    exit 0
  fi
fi

# --- Rule 2: zombie-socket detection ---
# Only run when Rule 1 succeeded — if upstream Slack is unhealthy we don't
# need a second reason to restart. Otherwise we'd thrash on Slack outages.
if [ "$rule1_ok" = "1" ] && container_running; then
  matches=$(docker logs "$CONTAINER" --since "$ZOMBIE_WINDOW" 2>&1 \
    | grep -cE 'websocket connected|received disconnect|reconnecting' || true)
  if [ "$matches" -eq 0 ]; then
    log "ZOMBIE detected: 0 socket events in $ZOMBIE_WINDOW; apps.connections.open succeeded"
    restart_container "no Slack socket activity in $ZOMBIE_WINDOW window"
  fi
fi

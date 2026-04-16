#!/usr/bin/env bash
# scripts/restore-from-backup.sh — restore Chaos config or workspace from a
# nightly backup. Two kinds of artifacts are produced by chaos_backup.py:
#
#   openclaw-YYYY-MM-DD.json       — seed-once config snapshot
#   workspace-YYYY-MM-DD.tar.gz    — full workspace archive (identity + skills)
#
# RUN ON THE SERVER (as overlord101), not on your laptop.
#
# Usage:
#   ./restore-from-backup.sh config                    # restore latest config
#   ./restore-from-backup.sh config 2026-04-14         # restore config from date
#   ./restore-from-backup.sh workspace                 # restore latest workspace
#   ./restore-from-backup.sh workspace 2026-04-14      # restore workspace from date
#   ./restore-from-backup.sh --list                    # list available backups
#   ./restore-from-backup.sh --list config             # list config snapshots only
#   ./restore-from-backup.sh --list workspace          # list workspace snapshots only

set -euo pipefail

BACKUP_DIR=/opt/openclaw/backups
CHAOS_DIR=/opt/openclaw/chaos
STATE_TARGET=${CHAOS_DIR}/state/openclaw.json
WORKSPACE_TARGET=${CHAOS_DIR}/workspace

usage() {
    sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

list_backups() {
    local kind="${1:-all}"
    case "$kind" in
        config)
            ls -lt "${BACKUP_DIR}"/openclaw-*.json 2>/dev/null || echo "No config backups."
            ;;
        workspace)
            ls -lt "${BACKUP_DIR}"/workspace-*.tar.gz 2>/dev/null || echo "No workspace backups."
            ;;
        all|"")
            echo "== Config snapshots =="
            ls -lt "${BACKUP_DIR}"/openclaw-*.json 2>/dev/null || echo "  (none)"
            echo ""
            echo "== Workspace snapshots =="
            ls -lt "${BACKUP_DIR}"/workspace-*.tar.gz 2>/dev/null || echo "  (none)"
            ;;
        *) echo "Unknown list kind: $kind" >&2; exit 2 ;;
    esac
}

if [[ "${1:-}" == "--list" ]]; then
    list_backups "${2:-all}"
    exit 0
fi

MODE="${1:-}"
DATE="${2:-}"

case "$MODE" in
    config)
        if [[ -n "$DATE" ]]; then
            SRC="${BACKUP_DIR}/openclaw-${DATE}.json"
        else
            SRC=$(ls -t "${BACKUP_DIR}"/openclaw-*.json 2>/dev/null | head -n1 || true)
        fi
        [[ -z "$SRC" || ! -f "$SRC" ]] && { echo "ERROR: config backup not found: ${SRC:-<none>}" >&2; exit 1; }

        echo "==> Restoring config from: $SRC"
        echo "    Into:                    $STATE_TARGET"
        read -r -p "Stop chaos, restore config, start again? [y/N] " ans
        [[ "$ans" == "y" ]] || { echo "Aborted."; exit 0; }

        cd "$CHAOS_DIR"
        sudo docker compose stop chaos
        sudo install -m 600 -o 1000 -g 1000 "$SRC" "$STATE_TARGET"
        sudo docker compose up -d chaos
        echo "==> Config restored. Watching logs (Ctrl-C to exit):"
        sudo docker compose logs -f chaos
        ;;

    workspace)
        if [[ -n "$DATE" ]]; then
            SRC="${BACKUP_DIR}/workspace-${DATE}.tar.gz"
        else
            SRC=$(ls -t "${BACKUP_DIR}"/workspace-*.tar.gz 2>/dev/null | head -n1 || true)
        fi
        [[ -z "$SRC" || ! -f "$SRC" ]] && { echo "ERROR: workspace backup not found: ${SRC:-<none>}" >&2; exit 1; }

        echo "==> Restoring workspace from: $SRC"
        echo "    Into:                      $WORKSPACE_TARGET"
        echo "    Current workspace will be MOVED to ${WORKSPACE_TARGET}.bak-$(date +%s) first."
        read -r -p "Stop chaos, restore workspace, start again? [y/N] " ans
        [[ "$ans" == "y" ]] || { echo "Aborted."; exit 0; }

        cd "$CHAOS_DIR"
        sudo docker compose stop chaos
        if [[ -d "$WORKSPACE_TARGET" ]]; then
            sudo mv "$WORKSPACE_TARGET" "${WORKSPACE_TARGET}.bak-$(date +%s)"
        fi
        sudo tar -xzf "$SRC" -C "$(dirname "$WORKSPACE_TARGET")"
        sudo chown -R 1000:1000 "$WORKSPACE_TARGET"
        sudo docker compose up -d chaos
        echo "==> Workspace restored. Watching logs (Ctrl-C to exit):"
        sudo docker compose logs -f chaos
        ;;

    ""|-h|--help)
        usage 0
        ;;
    *)
        echo "Unknown mode: $MODE" >&2
        usage 2
        ;;
esac

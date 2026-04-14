#!/usr/bin/env bash
# scripts/deploy.sh — repeatable deploy wrapper for Server 3 (OpenClaw Agents)
#
# Usage: ./scripts/deploy.sh
#
# What it does:
#   1. Activates the local Python venv
#   2. Loads .env into the environment
#   3. Validates required variables
#   4. Runs: pyinfra --sudo -v infra/inventory.py infra/deploy.py
#   5. Prints a post-deploy summary

set -euo pipefail

# Resolve the project root regardless of where the script is called from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

# ---------------------------------------------------------------------------
# 1. Venv check
# ---------------------------------------------------------------------------
if [[ ! -d ".venv" ]]; then
    echo "ERROR: .venv not found. Run ./scripts/setup-local.sh first." >&2
    exit 1
fi

source .venv/bin/activate

# ---------------------------------------------------------------------------
# 2. Load .env
# ---------------------------------------------------------------------------
if [[ ! -f ".env" ]]; then
    echo "ERROR: .env not found. Copy .env.example and fill in real values." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

# ---------------------------------------------------------------------------
# 3. Validate critical env vars
# ---------------------------------------------------------------------------
missing=()

[[ -z "${SERVER3_IP:-}" ]]                && missing+=("SERVER3_IP")
[[ -z "${SSH_KEY_PATH:-}" ]]              && missing+=("SSH_KEY_PATH")
[[ -z "${CHAOS_GATEWAY_TOKEN:-}" ]]       && missing+=("CHAOS_GATEWAY_TOKEN")
[[ -z "${CHAOS_SLACK_BOT_TOKEN:-}" ]]     && missing+=("CHAOS_SLACK_BOT_TOKEN")
[[ -z "${CHAOS_SLACK_APP_TOKEN:-}" ]]     && missing+=("CHAOS_SLACK_APP_TOKEN")

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: The following required variables are not set in .env:" >&2
    for var in "${missing[@]}"; do
        echo "  - ${var}" >&2
    done
    exit 1
fi

if [[ ! -f "${SSH_KEY_PATH}" ]]; then
    echo "ERROR: SSH key not found at ${SSH_KEY_PATH}" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. Run Pyinfra deploy
# ---------------------------------------------------------------------------
echo "==> Deploying to Server 3 (${SERVER3_IP})..."
echo "    Phases: base packages -> docker install -> app deploy"
echo "    This takes 3-8 minutes on a cold server (Docker image pull is the slow step)."
echo ""

DEPLOY_START=$(date +%s)

pyinfra --sudo -v infra/inventory.py infra/deploy.py

DEPLOY_END=$(date +%s)
DEPLOY_ELAPSED=$(( DEPLOY_END - DEPLOY_START ))

# ---------------------------------------------------------------------------
# 5. Post-deploy summary
# ---------------------------------------------------------------------------
SSH_PORT="${SSH_PORT:-2222}"
SSH_USER="${SSH_USER:-overlord101}"

echo ""
echo "==> Deploy complete in ${DEPLOY_ELAPSED}s."
echo ""
echo "    SSH:          ssh -i ${SSH_KEY_PATH} -p ${SSH_PORT} -o IdentitiesOnly=yes ${SSH_USER}@${SERVER3_IP}"
echo "    Health:       ssh ... 'curl -s http://127.0.0.1:18791/healthz'"
echo "    Logs:         ssh ... 'docker logs -f openclaw-chaos'"
echo "    Control UI:   ssh -N -L 18791:127.0.0.1:18791 -p ${SSH_PORT} -o IdentitiesOnly=yes -i ${SSH_KEY_PATH} ${SSH_USER}@${SERVER3_IP}"
echo "                  Then open http://localhost:18791"
echo ""

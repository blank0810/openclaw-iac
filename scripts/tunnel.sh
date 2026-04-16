#!/usr/bin/env bash
# scripts/tunnel.sh — open SSH tunnel to Chaos Control UI on localhost:18789.
#
# Usage: ./scripts/tunnel.sh
# Then in a browser: http://localhost:18789
# Ctrl-C to close.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${SERVER3_IP:?SERVER3_IP not set in .env}"
: "${SSH_KEY_PATH:?SSH_KEY_PATH not set in .env}"
: "${SSH_USER:=overlord101}"
: "${SSH_PORT:=2222}"

echo "==> Opening tunnel: localhost:18789 -> ${SERVER3_IP}:127.0.0.1:18789"
echo "    Browser: http://localhost:18789"
echo "    Ctrl-C to close."
echo ""

exec ssh -N -L 18789:127.0.0.1:18789 \
    -p "${SSH_PORT}" \
    -i "${SSH_KEY_PATH}" \
    -o IdentitiesOnly=yes \
    "${SSH_USER}@${SERVER3_IP}"

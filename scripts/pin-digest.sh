#!/usr/bin/env bash
# scripts/pin-digest.sh — pull a Docker image tag and print the tag+digest
# reference to paste into .env.
#
# Usage:
#   ./scripts/pin-digest.sh 2026.4.14
#     -> CHAOS_IMAGE=ghcr.io/openclaw/openclaw:2026.4.14@sha256:...
#
#   ./scripts/pin-digest.sh -r docker.io/searxng/searxng -v CHAOS_IMAGE=SEARXNG_IMAGE latest
#     -> SEARXNG_IMAGE=docker.io/searxng/searxng:latest@sha256:...

set -euo pipefail

REPO="ghcr.io/openclaw/openclaw"
VAR="CHAOS_IMAGE"

while getopts ":r:v:" opt; do
    case "${opt}" in
        r) REPO="${OPTARG}" ;;
        v) VAR="${OPTARG##*=}" ;;
        *) echo "Usage: $0 [-r repo] [-v VAR=NAME] <tag>" >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))

TAG="${1:?Usage: $0 [-r repo] [-v VAR=NAME] <tag>}"
IMG="${REPO}:${TAG}"

# Pre-flight: Docker daemon reachable.
if ! docker info &>/dev/null; then
    echo "ERROR: Docker daemon not running or not installed." >&2
    echo "       Start Docker Desktop or 'sudo systemctl start docker', then retry." >&2
    exit 1
fi

echo "==> Pulling ${IMG}..." >&2
docker pull "${IMG}" >&2

# RepoDigests is an array; grab the one matching our repo.
DIGEST=$(docker inspect --format='{{range .RepoDigests}}{{println .}}{{end}}' "${IMG}" \
    | grep "^${REPO}@sha256:" \
    | head -n1 \
    | sed 's/.*@//')

if [[ -z "${DIGEST}" ]] || [[ "${DIGEST}" == "<no value>" ]]; then
    echo "ERROR: No digest returned for ${IMG}." >&2
    echo "       Registry may have stripped the Docker-Content-Digest header," >&2
    echo "       or the image was served from a pull-through cache without it." >&2
    echo "       Try a direct pull from the registry and retry." >&2
    exit 1
fi

if ! [[ "${DIGEST}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "ERROR: Digest '${DIGEST}' is not a valid sha256." >&2
    exit 1
fi

echo ""
echo "${VAR}=${REPO}:${TAG}@${DIGEST}"

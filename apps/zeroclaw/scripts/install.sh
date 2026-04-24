#!/usr/bin/env bash
# ZeroClaw install — Ubuntu/Debian path.
#
# Installs rustup (if absent), clones the official repo, builds --release,
# installs zeroclaw to ~/.cargo/bin, and runs `zeroclaw onboard`.
#
# Safe to re-run; each step is idempotent.

set -euo pipefail

UPSTREAM_REPO="https://github.com/zeroclaw-labs/zeroclaw.git"
# Clone target inside apps/zeroclaw/upstream (gitignored).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
CLONE_DIR="$APP_DIR/upstream"

log() { printf "\033[1;34m[zeroclaw-install]\033[0m %s\n" "$*"; }
err() { printf "\033[1;31m[zeroclaw-install]\033[0m %s\n" "$*" >&2; exit 1; }

# 1. Rust toolchain
if ! command -v cargo >/dev/null 2>&1; then
  log "cargo not found — installing rustup (stable toolchain)"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
  # shellcheck disable=SC1091
  source "$HOME/.cargo/env"
else
  log "cargo already present: $(cargo --version)"
fi

command -v cargo >/dev/null 2>&1 || err "cargo still not on PATH after rustup install — open a new shell and retry"

# 2. System build deps (common Rust requirements + zeroclaw specifics).
# Skip the sudo step if all packages are already installed — keeps the script
# non-interactive when re-run after initial setup.
if command -v apt-get >/dev/null 2>&1; then
  APT_DEPS=(build-essential pkg-config libssl-dev ca-certificates git)
  missing=()
  for pkg in "${APT_DEPS[@]}"; do
    dpkg -l "$pkg" 2>/dev/null | grep -qE "^ii" || missing+=("$pkg")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    log "apt build deps already installed, skipping sudo step"
  else
    log "installing missing apt build deps: ${missing[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends "${missing[@]}"
  fi
fi

# 3. Clone or update upstream
if [[ -d "$CLONE_DIR/.git" ]]; then
  log "updating existing clone at $CLONE_DIR"
  git -C "$CLONE_DIR" fetch --tags --prune
  git -C "$CLONE_DIR" pull --ff-only
else
  log "cloning $UPSTREAM_REPO → $CLONE_DIR"
  git clone --depth 1 "$UPSTREAM_REPO" "$CLONE_DIR"
fi

# 4. Build + install binary to ~/.cargo/bin
log "building zeroclaw (release, locked) — this takes a few minutes"
cd "$CLONE_DIR"
cargo build --release --locked
cargo install --path . --force --locked

command -v zeroclaw >/dev/null 2>&1 || err "zeroclaw not on PATH — ensure ~/.cargo/bin is in PATH"
log "installed: $(zeroclaw --version 2>/dev/null || echo 'zeroclaw')"

# 5. Onboard (skip if SKIP_ONBOARD=1, e.g., for unattended/background installs)
if [[ "${SKIP_ONBOARD:-0}" == "1" ]]; then
  log "SKIP_ONBOARD=1 — binary installed, run 'zeroclaw onboard' manually when ready"
  exit 0
fi

log "launching \`zeroclaw onboard\` — follow prompts to configure workspace + provider"
exec zeroclaw onboard

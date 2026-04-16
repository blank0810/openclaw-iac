#!/usr/bin/env bash
set -euo pipefail

# Setup script for the Server 3 infrastructure project.
# Run this once after cloning. Safe to re-run.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[setup]${NC} $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $*"; }
error()   { echo -e "${RED}[error]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

# ---------------------------------------------------------------------------
# 1. Check Python 3.10+
# ---------------------------------------------------------------------------
info "Checking Python version..."

PYTHON_BIN=""
for candidate in python3 python3.12 python3.11 python3.10; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c 'import sys; print(sys.version_info[:2])')
        major=$("$candidate" -c 'import sys; print(sys.version_info.major)')
        minor=$("$candidate" -c 'import sys; print(sys.version_info.minor)')
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    die "Python 3.10+ is required but not found. Install it via your package manager."
fi

info "Using $PYTHON_BIN ($($PYTHON_BIN --version))"

# ---------------------------------------------------------------------------
# 2. Create .venv if it does not exist
# ---------------------------------------------------------------------------
if [ ! -d ".venv" ]; then
    info "Creating virtual environment at .venv/ ..."
    "$PYTHON_BIN" -m venv .venv
else
    info "Virtual environment already exists at .venv/ — skipping creation."
fi

# ---------------------------------------------------------------------------
# 3. Install requirements
# ---------------------------------------------------------------------------
info "Installing requirements..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
info "pyinfra installed: $(.venv/bin/pyinfra --version)"

# ---------------------------------------------------------------------------
# 4. Copy .env.example to .env if .env does not exist
# ---------------------------------------------------------------------------
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn ".env created from .env.example — fill in your real values before proceeding."
    warn "  Required: SERVER3_IP, SSH_KEY_PATH"
    warn "  Edit:     nano .env"
else
    info ".env already exists — skipping copy."
fi

# ---------------------------------------------------------------------------
# 5. Validate required env vars are non-empty
# ---------------------------------------------------------------------------
info "Validating .env variables..."

# Load .env without exporting to current shell (values may have inline comments)
# Strip comments and blank lines, then source
TMPENV=$(mktemp)
grep -v '^\s*#' .env | grep -v '^\s*$' | sed 's/[[:space:]]*#.*//' > "$TMPENV" || true
set -a
# shellcheck disable=SC1090
source "$TMPENV"
set +a
rm -f "$TMPENV"

MISSING=()

check_var() {
    local var="$1"
    local value="${!var:-}"
    if [ -z "$value" ]; then
        MISSING+=("$var")
    fi
}

check_var SERVER3_IP
check_var SSH_KEY_PATH

if [ ${#MISSING[@]} -gt 0 ]; then
    warn "The following required variables are empty in .env:"
    for v in "${MISSING[@]}"; do
        warn "  - $v"
    done
    warn "Fill them in before running pyinfra."
else
    info "All required variables are set."
fi

# ---------------------------------------------------------------------------
# 6. Print next steps
# ---------------------------------------------------------------------------
echo ""
echo "----------------------------------------------------------------------"
echo "  Setup complete."
echo ""
echo "  Next steps:"
echo ""
echo "  1. Fill in .env with real values (if not done already):"
echo "       nano .env"
echo ""
echo "  2. Activate the virtual environment:"
echo "       source .venv/bin/activate"
echo ""
echo "  3. First-time bootstrap (run once as root):"
echo "       source .env"
echo "       pyinfra --user root --port 22 --key \$SSH_KEY_PATH \$SERVER3_IP infra/bootstrap.py"
echo ""
echo "  4. Standard deployment (repeatable):"
echo "       source .venv/bin/activate"
echo "       set -a; source .env; set +a"
echo "       pyinfra --sudo -v infra/inventory.py infra/deploy.py"
echo ""
echo "  Dry-run (see what would change, touch nothing):"
echo "       pyinfra infra/inventory.py infra/deploy.py --dry"
echo ""
echo "  SSH tunnel for Control UI (localhost:18789):"
echo "       ssh -N -L 18789:127.0.0.1:18789 -p \$SSH_PORT -i \$SSH_KEY_PATH \\"
echo "           -o IdentitiesOnly=yes \$SSH_USER@\$SERVER3_IP"
echo "----------------------------------------------------------------------"

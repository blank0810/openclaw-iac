"""Deploy the ZeroClaw Orchestrator API onto the Docker host as a root systemd
service.

Runs in the BOOTSTRAP plane (operator laptop -> SSH into Server 3). Same style
as lib/deploy_runtime.py: module-level pyinfra operations, reads host.data.

Why root: the orchestrator chowns each agent's workspace dir to 65534 at
runtime so the container (UID 65534) can persist brain.db/sessions. A non-root
docker-group user cannot chown. docker-group access is already root-equivalent,
so running the unit as root is not materially less secure.

Sync strategy: we copy the specific top-level dirs and files the orchestrator
imports (apps/, lib/, templates/, requirements.txt, zeroclawctl.py) via one
files.sync per dir + files.put per file. We deliberately do NOT sync the repo
wholesale: agents/ holds secrets (_defaults.toml, per-agent tokens), .env/.pem
are credentials, and there is unrelated WIP at the root. Explicit per-path
copying keeps secrets off the wire by construction rather than relying on a
fragile exclude list.

Verify (no live host needed):
    pyinfra lib/inventory.py lib/deploy_orchestrator.py --dry
"""

from __future__ import annotations

from pyinfra.operations import apt, files, server, systemd

ORCH_DIR = "/opt/zeroclaw-orchestrator"
VENV = f"{ORCH_DIR}/.venv"


files.directory(
    name=f"Ensure {ORCH_DIR}",
    path=ORCH_DIR,
    present=True,
    user="root",
    group="root",
    mode="755",
    _sudo=True,
)

# The orchestrator renders each new agent's state to
# /opt/zeroclaw/states/<slug> at provision time (then chowns it to 65534).
# Pre-create the base dirs as root so the runtime never has to mkdir across the
# deploy/runtime boundary, and so the systemd unit's ProtectSystem=full leaves
# /opt writable for them.
for path in ("/opt/zeroclaw", "/opt/zeroclaw/states"):
    files.directory(
        name=f"Ensure {path}",
        path=path,
        present=True,
        user="root",
        group="root",
        mode="755",
        _sudo=True,
    )

# Copy only the source the orchestrator needs. We sync apps/orchestrator
# specifically, NOT all of apps/: apps/ also holds the multi-GB
# apps/zeroclaw/upstream Rust clone (~1.1G, incl. target/ build artifacts) and
# apps/slack-agent (~194M). Syncing apps/ wholesale transfers >1.3G over SFTP
# file-by-file and effectively hangs. apps/ is a namespace package (no
# __init__.py), so apps.orchestrator imports fine from the synced subdir alone.
# __pycache__ is excluded so stale local bytecode never lands on the host.
for subdir in ("lib", "templates", "apps/orchestrator"):
    files.sync(
        name=f"Sync {subdir}/ to {ORCH_DIR}",
        src=subdir,
        dest=f"{ORCH_DIR}/{subdir}",
        user="root",
        group="root",
        delete=True,
        exclude_dir=["__pycache__", "*/__pycache__"],
        exclude=["*.pyc"],
        _sudo=True,
    )

for filename in ("requirements.txt", "zeroclawctl.py"):
    files.put(
        name=f"Upload {filename} to {ORCH_DIR}",
        src=filename,
        dest=f"{ORCH_DIR}/{filename}",
        user="root",
        group="root",
        mode="644",
        _sudo=True,
    )

# CRITICAL: the orchestrator merges every new agent against agents/_defaults.toml
# (request-only creates KeyError on llm.model without it -- flagged in Unit C).
# _defaults.toml carries the default LLM api_key, so it is gitignored and is
# NEVER synced by this deploy. We only ensure the directory exists; the operator
# must place a real agents/_defaults.toml on the host BEFORE the first
# POST /agents:
#
#     scp agents/_defaults.toml \
#       overlord101@<host>:/opt/zeroclaw-orchestrator/agents/_defaults.toml
#
# (mode 600, root-owned). Do not commit or ship a defaults file with secrets.
files.directory(
    name=f"Ensure {ORCH_DIR}/agents (operator places _defaults.toml here)",
    path=f"{ORCH_DIR}/agents",
    present=True,
    user="root",
    group="root",
    mode="700",
    _sudo=True,
)

# venv creation needs python3-venv (ensurepip); without it `python3 -m venv`
# produces a pip-less, broken venv. Ensure it before creating the venv.
apt.packages(
    name="Ensure python3-venv is installed",
    packages=["python3-venv"],
    present=True,
    _sudo=True,
)

# Create the venv once. Guard on PIP (not just the python symlink): a prior
# run without python3-venv leaves a partial venv whose bin/python exists but
# bin/pip does not. Recreate from scratch when pip is missing so we never get
# stuck with a half-built venv.
server.shell(
    name="Create orchestrator venv if missing",
    commands=[
        f"test -x {VENV}/bin/pip || (rm -rf {VENV} && python3 -m venv {VENV})",
    ],
    _sudo=True,
)

server.shell(
    name="Install orchestrator Python dependencies",
    commands=[
        f"{VENV}/bin/pip install --upgrade pip",
        f"{VENV}/bin/pip install -r {ORCH_DIR}/requirements.txt",
    ],
    _sudo=True,
    _timeout=600,
)

files.template(
    name="Render zeroclaw-orchestrator systemd unit",
    src="templates/systemd/zeroclaw-orchestrator.service.j2",
    dest="/etc/systemd/system/zeroclaw-orchestrator.service",
    user="root",
    group="root",
    mode="644",
    _sudo=True,
)

systemd.daemon_reload(
    name="Reload systemd to pick up the orchestrator unit",
    _sudo=True,
)

systemd.service(
    name="Enable, start, and restart zeroclaw-orchestrator",
    service="zeroclaw-orchestrator.service",
    running=True,
    enabled=True,
    restarted=True,
    _sudo=True,
)

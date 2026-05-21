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

from pyinfra import host
from pyinfra.operations import files, server, systemd

ORCH_DIR = "/opt/zeroclaw-orchestrator"
VENV = f"{ORCH_DIR}/.venv"

deploy_user = host.data.get("deploy_user")


files.directory(
    name=f"Ensure {ORCH_DIR}",
    path=ORCH_DIR,
    present=True,
    user="root",
    group="root",
    mode="755",
    _sudo=True,
)

# Copy only the source the orchestrator needs. Each dir is synced individually;
# __pycache__ is excluded so stale local bytecode never lands on the host.
for subdir in ("apps", "lib", "templates"):
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

# Create the venv once (idempotent: skip if the interpreter already exists),
# then install/refresh deps. pip install is idempotent on its own.
server.shell(
    name="Create orchestrator venv if missing",
    commands=[
        f"test -x {VENV}/bin/python || python3 -m venv {VENV}",
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

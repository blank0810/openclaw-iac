"""
Create /opt/openclaw/chaos/ directory tree with correct ownership and permissions.

Idempotent: files.directory() only creates if missing, updates mode/owner if drifted.
"""

from pyinfra import host
from pyinfra.operations import files

deploy_user = host.data.deploy_user

# Parent dir owned by overlord101 — Pyinfra writes compose + env here.
files.directory(
    name="Ensure /opt/openclaw exists",
    path="/opt/openclaw",
    user=deploy_user,
    group=deploy_user,
    mode="755",
    present=True,
)

files.directory(
    name="Ensure /opt/openclaw/chaos exists",
    path="/opt/openclaw/chaos",
    user=deploy_user,
    group=deploy_user,
    mode="755",
    present=True,
)

# Workspace is mounted read-only into the container; owner can be deploy_user.
files.directory(
    name="Ensure /opt/openclaw/chaos/workspace exists",
    path="/opt/openclaw/chaos/workspace",
    user=deploy_user,
    group=deploy_user,
    mode="755",
    present=True,
)

# State dir is mounted writable into the container running as uid 1000.
# Must be owned by uid 1000, not deploy_user.
files.directory(
    name="Ensure /opt/openclaw/chaos/state exists (uid 1000)",
    path="/opt/openclaw/chaos/state",
    user="1000",
    group="1000",
    mode="700",
    present=True,
)

# SearXNG settings dir — root-owned per memory note (searxng needs cap_drop ALL
# compatibility; container writes nothing here, only reads settings.yml).
files.directory(
    name="Ensure /opt/openclaw/chaos/searxng exists",
    path="/opt/openclaw/chaos/searxng",
    user="root",
    group="root",
    mode="755",
    present=True,
)

# Backup dir for nightly openclaw.json snapshots.
files.directory(
    name="Ensure /opt/openclaw/backups exists",
    path="/opt/openclaw/backups",
    user=deploy_user,
    group=deploy_user,
    mode="700",
    present=True,
)

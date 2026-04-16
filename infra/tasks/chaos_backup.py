"""
Install a nightly cron job that snapshots Chaos's self-managed state.

Backs up:
  - /opt/openclaw/chaos/state/openclaw.json        -> backups/openclaw-YYYY-MM-DD.json
  - /opt/openclaw/chaos/workspace/                 -> backups/workspace-YYYY-MM-DD.tar.gz

Rationale: workspace is mounted read-write so Chaos can author its own
identity, skills, and model rules. That self-management power needs a
recovery path if a bad self-edit corrupts personality or introduces a
broken skill. The tarball captures every .md + skills/* in one artifact,
so `restore-from-backup.sh` can roll either the config or the workspace
back independently.

Requires _sudo=True (set globally in inventory) — crontab operation writes the
deploy_user's crontab file, which requires root on Ubuntu by default.
"""

import io

from pyinfra import host
from pyinfra.operations import crontab, files

deploy_user = host.data.deploy_user

backup_script = """#!/usr/bin/env bash
set -euo pipefail
STAMP=$(date +%Y-%m-%d)
BACKUP_DIR=/opt/openclaw/backups
STATE_SRC=/opt/openclaw/chaos/state/openclaw.json
WORKSPACE_SRC=/opt/openclaw/chaos/workspace

# Config snapshot — small JSON file, plain copy.
if [[ -f "$STATE_SRC" ]]; then
    cp -a "$STATE_SRC" "${BACKUP_DIR}/openclaw-${STAMP}.json"
fi

# Workspace snapshot — tar the whole dir (identity .md + any skills the bot
# has authored). Atomic: write to .partial, rename on success.
if [[ -d "$WORKSPACE_SRC" ]]; then
    TARBALL="${BACKUP_DIR}/workspace-${STAMP}.tar.gz"
    tar -czf "${TARBALL}.partial" -C "$(dirname "$WORKSPACE_SRC")" "$(basename "$WORKSPACE_SRC")"
    mv "${TARBALL}.partial" "$TARBALL"
fi

# Retention: keep last 30 days of each artifact type.
find "$BACKUP_DIR" -name 'openclaw-*.json'     -mtime +30 -delete
find "$BACKUP_DIR" -name 'workspace-*.tar.gz'  -mtime +30 -delete
"""

files.put(
    name="Upload chaos backup script",
    src=io.StringIO(backup_script),
    dest="/opt/openclaw/backup-chaos-config.sh",
    user=deploy_user,
    group=deploy_user,
    mode="755",
)

# Install crontab entry. cron_name is the identifier used in the crontab file —
# setting it explicitly makes re-runs idempotent (no duplicate lines if the
# command string changes) and allows targeted removal by name in rollback.
crontab.crontab(
    name="Nightly Chaos state + workspace backup",  # Pyinfra op display name
    command="/opt/openclaw/backup-chaos-config.sh",
    user=deploy_user,
    cron_name="chaos-backup",
    hour="3",
    minute="15",
)

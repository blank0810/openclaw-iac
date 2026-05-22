#!/usr/bin/env python3
"""ZeroClaw agent-state backup — runs ON the Docker host (Server 3), scheduled by
a systemd timer (the cron-equivalent). Stdlib only, so it uses the system
python3 and needs no venv.

For every agent state dir under STATES_BASE it writes a zip of that dir's
contents to BACKUPS_BASE/<slug>/<YYYY-MM-DD>/<slug>.zip, logs the location and
result, and prints each location to stdout. Backups contain config.toml (Slack /
Composio secrets), so BACKUPS_BASE must be root-owned mode 700 — created by the
pyinfra deploy, not here.

Per docs/plans/2026-05-22-backup-restore-design.md. Not part of the FastAPI
request flow (V1 keeps backup off the API).
"""
from __future__ import annotations

import datetime
import logging
import os
import sys
import zipfile
from pathlib import Path

STATES_BASE = Path(os.environ.get("ZEROCLAW_STATES_BASE", "/opt/zeroclaw/states"))
BACKUPS_BASE = Path(os.environ.get("ZEROCLAW_BACKUPS_BASE", "/opt/zeroclaw/backups"))
LOG_FILE = os.environ.get("ZEROCLAW_BACKUP_LOG", "/var/log/zeroclaw-backup.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("zeroclaw-backup")


def zip_state(src: Path, dest_zip: Path) -> None:
    """Zip the CONTENTS of ``src`` (arcnames relative to it, so the zip root is
    .zeroclaw/ + workspace/ — restore extracts straight into a state dir)."""
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(src):
            for name in files:
                fp = Path(root) / name
                zf.write(fp, fp.relative_to(src))


def main() -> int:
    date = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    if not STATES_BASE.is_dir():
        log.error("states base %s missing; nothing to back up", STATES_BASE)
        return 1
    rc = 0
    for state_dir in sorted(STATES_BASE.iterdir()):
        # skip non-dirs and our own work dirs (.restore-*, etc.)
        if not state_dir.is_dir() or state_dir.name.startswith("."):
            continue
        slug = state_dir.name
        dest = BACKUPS_BASE / slug / date / f"{slug}.zip"
        try:
            zip_state(state_dir, dest)
            log.info("backed up %s -> %s", slug, dest)
            print(dest)
        except Exception as e:  # noqa: BLE001 - one bad agent must not abort the rest
            log.error("backup FAILED for %s: %s", slug, e)
            rc = 1
    if rc == 0:
        log.info("backup run complete (%s)", date)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

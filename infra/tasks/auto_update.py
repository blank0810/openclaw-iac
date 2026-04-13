"""
Auto-update task — installs a nightly cron job that pulls the latest OpenClaw
image and restarts the container only if the image changed.

Runs as part of deploy.py (after app_deploy.py). Safe to re-run — cron file is
overwritten idempotently on each deploy.

Cron schedule: 4 AM server time (TZ controlled by TZ env var in docker-compose).
Log: /var/log/openclaw-update.log
"""

from io import StringIO

from pyinfra import host
from pyinfra.operations import files

deploy_path = host.data.deploy_path
deploy_user = host.data.deploy_user

cron_content = f"""# OpenClaw nightly auto-update — managed by Pyinfra
# Pulls latest images for both agents and restarts only if changed.
# Two staggered cron lines because Jarvis and Chaos live in separate compose
# projects after the 2026-04-09 separation refactor. Plain `up -d` (no
# --force-recreate) only recreates when something actually changed.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Jarvis (shared compose project at deploy_path)
0 4 * * * {deploy_user} cd {deploy_path} && docker compose pull --quiet && docker compose up -d --remove-orphans >> /var/log/openclaw-update.log 2>&1

# Chaos (isolated compose project at deploy_path/chaos, uses shared .env via --env-file)
5 4 * * * {deploy_user} cd {deploy_path}/chaos && docker compose --env-file ../.env pull --quiet && docker compose --env-file ../.env up -d --remove-orphans >> /var/log/openclaw-update.log 2>&1
"""

files.put(
    name="Install OpenClaw nightly auto-update cron",
    src=StringIO(cron_content),
    dest="/etc/cron.d/openclaw-update",
    user="root",
    group="root",
    mode="644",
)

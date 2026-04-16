"""
Standard deployment orchestrator — run as overlord101 on every deploy.

Execution order:
  1. base_packages.py         — ensure system packages are current
  2. docker_install.py        — ensure Docker Engine + Compose plugin are installed
  3. chaos_dirs.py            — create /opt/openclaw/chaos/ tree
  4. chaos_env.py             — render .env on server
  5. chaos_compose.py         — upload docker-compose.yml
  6. chaos_workspace.py       — sync 7 identity .md files
  7. chaos_searxng_config.py  — upload SearXNG settings.yml
  8. chaos_seed.py            — seed openclaw.json (first-run only)
  9. chaos_backup.py          — install nightly backup cron
 10. chaos_service.py         — docker compose pull + up -d

Usage:
  pyinfra infra/inventory.py infra/deploy.py
  pyinfra infra/inventory.py infra/deploy.py --dry
"""

from pyinfra import local

local.include("infra/tasks/base_packages.py")
local.include("infra/tasks/docker_install.py")
local.include("infra/tasks/chaos_dirs.py")
local.include("infra/tasks/chaos_env.py")
local.include("infra/tasks/chaos_compose.py")
local.include("infra/tasks/chaos_workspace.py")
local.include("infra/tasks/chaos_searxng_config.py")
local.include("infra/tasks/chaos_seed.py")
local.include("infra/tasks/chaos_backup.py")
local.include("infra/tasks/chaos_service.py")

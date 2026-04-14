"""
Standard deployment orchestrator — run as overlord101 on every deploy.

Execution order:
  1. base_packages.py  — ensure system packages are current
  2. docker_install.py — ensure Docker Engine + Compose plugin are installed
  3. app_deploy.py     — upload compose file, render config, pull image, start containers
  4. bot_identity.py   — seed workspace files (identity + skills), once only
  5. auto_update.py    — install nightly cron to pull latest image at 4 AM

Usage:
  pyinfra infra/inventory.py infra/deploy.py
  pyinfra infra/inventory.py infra/deploy.py --dry
"""

from pyinfra import local

local.include("infra/tasks/base_packages.py")
local.include("infra/tasks/docker_install.py")
local.include("infra/tasks/app_deploy.py")
local.include("infra/tasks/bot_identity.py")
local.include("infra/tasks/auto_update.py")

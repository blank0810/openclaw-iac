"""
Standard deployment orchestrator — run as overlord101 on every deploy.

Execution order:
  1. base_packages.py   — ensure system packages are current
  2. docker_install.py  — ensure Docker Engine + Compose plugin are installed
  3. chaos_deploy.py    — deploy the Chaos OpenClaw stack (compose up, /healthz, validate)

Safe to re-run: every step is idempotent.

Usage (from project root):
  pyinfra infra/inventories/deploy.py infra/deploy.py
  pyinfra infra/inventories/deploy.py infra/deploy.py --dry
"""

from pyinfra import local

local.include("infra/tasks/base_packages.py")
local.include("infra/tasks/docker_install.py")
local.include("infra/tasks/chaos_deploy.py")

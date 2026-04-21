"""
Standard deployment orchestrator — run as overlord101 on every deploy.

Execution order:
  1. base_packages.py   — ensure system packages are current
  2. docker_install.py  — ensure Docker Engine + Compose plugin are installed

Safe to re-run: every step is idempotent.

Usage (from project root):
  pyinfra infra/inventories/deploy.py infra/deploy.py
  pyinfra infra/inventories/deploy.py infra/deploy.py --dry

NOTE (2026-04-21): OpenClaw/Chaos is permanently out of scope. The
chaos_deploy task file remains in infra/tasks/ as historical reference
(commit 1e19c5c) but is NOT included here — the next deploy must not
re-provision a Chaos container.
"""

from pyinfra import local

local.include("infra/tasks/base_packages.py")
local.include("infra/tasks/docker_install.py")

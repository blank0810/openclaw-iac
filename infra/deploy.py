"""
Standard deployment orchestrator — run as overlord101 on every deploy.

Execution order:
  1. base_packages.py         — ensure system packages are current
  2. docker_install.py        — ensure Docker Engine + Compose plugin are installed

After this runs, the box is a hardened Docker host ready for whatever
agent/app gets dropped into docker/ next.

Usage (from project root):
  pyinfra infra/inventories/deploy.py infra/deploy.py
  pyinfra infra/inventories/deploy.py infra/deploy.py --dry
"""

from pyinfra import local

local.include("infra/tasks/base_packages.py")
local.include("infra/tasks/docker_install.py")

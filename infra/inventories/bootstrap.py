"""
Bootstrap inventory — connects as root on port 22.

Used ONLY with infra/bootstrap.py for one-time server hardening on a fresh
Hetzner Ubuntu box. After bootstrap succeeds, root SSH is disabled and
every subsequent run uses infra/inventories/deploy.py.

Usage (from project root):
    pyinfra infra/inventories/bootstrap.py infra/bootstrap.py
    pyinfra infra/inventories/bootstrap.py infra/bootstrap.py --dry

Env vars required (loaded from .env via `set -a; source .env; set +a`):
    SERVER3_IP     — the target Hetzner VPS IP
    SSH_KEY_PATH   — path to the private key authorized as root
"""

import os

server3 = [
    (
        os.environ["SERVER3_IP"],
        {
            "ssh_user": "root",
            "ssh_port": 22,
            "ssh_key": os.environ["SSH_KEY_PATH"],
            "ssh_key_only": True,
            # root does not need _sudo — it already is root.
        },
    )
]

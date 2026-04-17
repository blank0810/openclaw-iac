"""
Standard deploy inventory — connects as overlord101 on the hardened SSH port.

Used for all repeatable deploys (infra/deploy.py and any task under
infra/tasks/). Assumes the server has already been bootstrapped.

Usage:
    pyinfra --chdir infra inventories/deploy.py deploy.py
    pyinfra --chdir infra inventories/deploy.py deploy.py --dry

Env vars required (loaded from .env via `set -a; source .env; set +a`):
    SERVER3_IP     — the target Hetzner VPS IP
    SSH_KEY_PATH   — path to the private key authorized for overlord101
"""

import os

server3 = [
    (
        os.environ["SERVER3_IP"],
        {
            "ssh_user": "overlord101",
            "ssh_port": 2222,
            "ssh_key": os.environ["SSH_KEY_PATH"],
            "ssh_key_only": True,
            # overlord101 is a sudoer; deploy.py runs system-level operations
            # (apt, systemd, /etc edits) which all require root. Setting _sudo
            # globally here applies it as the default to every operation on
            # this host. Individual operations can still override with _sudo=False.
            "_sudo": True,
        },
    )
]

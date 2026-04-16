"""
Pyinfra v3 inventory for Server 3.

Reads connection details from environment variables. Uses os.environ[] (not
os.getenv()) so a missing variable raises a KeyError immediately with a clear
message — fail loudly rather than silently proceeding with wrong config.

Usage:
    # Standard deploy (post-bootstrap, custom port):
    pyinfra infra/inventory.py infra/deploy.py

    # Dry run:
    pyinfra infra/inventory.py infra/deploy.py --dry

    # Bootstrap (override at CLI, not via this inventory):
    pyinfra --user root --port 22 --key $SSH_KEY_PATH $SERVER3_IP infra/bootstrap.py
"""

import os

server3 = [
    (
        os.environ["SERVER3_IP"],
        {
            "ssh_user": os.environ["SSH_USER"],
            "ssh_key": os.environ["SSH_KEY_PATH"],
            "ssh_port": int(os.environ["SSH_PORT"]),
            "ssh_key_only": True,
            # overlord101 is a sudoer; deploy.py runs system-level operations
            # (apt, systemd, /etc edits) which all require root. Setting _sudo
            # globally here applies it as the default to every operation on
            # this host. Individual operations can still override with _sudo=False.
            "_sudo": True,
        },
    )
]

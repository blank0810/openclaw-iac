from __future__ import annotations

from pyinfra.operations import files, server


files.template(
    name="Render sshd hardening drop-in",
    src="templates/sshd_config.d/60-cloudesk.conf.j2",
    dest="/etc/ssh/sshd_config.d/60-cloudesk.conf",
    user="root",
    group="root",
    mode="0644",
)

server.shell(
    name="systemctl daemon-reload",
    commands=["systemctl daemon-reload"],
)

server.shell(
    name="Restart ssh.socket (Ubuntu 24.04 socket activation)",
    commands=["systemctl restart ssh.socket || systemctl restart ssh"],
)

server.shell(
    name="UFW remove port 22",
    commands=["ufw delete allow 22/tcp || true"],
)

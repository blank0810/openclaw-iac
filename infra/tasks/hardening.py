"""
hardening.py — SSH lockdown, UFW firewall, and fail2ban intrusion prevention.

Run as root during bootstrap (infra/bootstrap.py). Idempotent: safe to re-run.

Operations (order matters — sshd restart MUST be last):
  1.  Upload hardened sshd_config
  2.  Install ufw
  3.  Set UFW default policies (deny incoming, allow outgoing)
  4.  Open each port in allowed_tcp_ports
  5.  Enable UFW (--force skips interactive prompt)
  6.  Install fail2ban
  7.  Upload fail2ban jail.local
  8.  Enable and restart fail2ban
  9.  Restart sshd  ← LAST: root SSH dies after this
"""

from pyinfra import host
from pyinfra.operations import apt, files, server, systemd

# Pull shared config from group_data/all.py
allowed_tcp_ports = host.data.allowed_tcp_ports  # e.g. [2222, "18789:18800"]

# Paths relative to project root (where pyinfra is invoked from)
SSHD_CONFIG_SRC = "infra/files/sshd_config"
FAIL2BAN_JAIL_SRC = "infra/files/fail2ban_jail.local"

# ---------------------------------------------------------------------------
# 1. Upload hardened sshd_config
# ---------------------------------------------------------------------------
files.put(
    name="Upload hardened sshd_config",
    src=SSHD_CONFIG_SRC,
    dest="/etc/ssh/sshd_config",
    user="root",
    group="root",
    mode="644",
)

# ---------------------------------------------------------------------------
# 2. Install ufw
# ---------------------------------------------------------------------------
apt.packages(
    name="Install ufw",
    packages=["ufw"],
    present=True,
    update=True,
)

# ---------------------------------------------------------------------------
# 3. UFW default policies
# ---------------------------------------------------------------------------
server.shell(
    name="UFW default deny incoming",
    commands=["ufw default deny incoming"],
)

server.shell(
    name="UFW default allow outgoing",
    commands=["ufw default allow outgoing"],
)

# ---------------------------------------------------------------------------
# 4. Open allowed TCP ports
# ---------------------------------------------------------------------------
for port in allowed_tcp_ports:
    server.shell(
        name=f"UFW allow {port}/tcp",
        commands=[f"ufw allow {port}/tcp"],
    )

# ---------------------------------------------------------------------------
# 5. Enable UFW (--force avoids interactive confirmation prompt)
# ---------------------------------------------------------------------------
server.shell(
    name="Enable UFW",
    commands=["ufw --force enable"],
)

# ---------------------------------------------------------------------------
# 6. Install fail2ban
# ---------------------------------------------------------------------------
apt.packages(
    name="Install fail2ban",
    packages=["fail2ban"],
    present=True,
)

# ---------------------------------------------------------------------------
# 7. Upload fail2ban jail.local
# ---------------------------------------------------------------------------
files.put(
    name="Upload fail2ban jail.local",
    src=FAIL2BAN_JAIL_SRC,
    dest="/etc/fail2ban/jail.local",
    user="root",
    group="root",
    mode="644",
)

# ---------------------------------------------------------------------------
# 8. Enable and restart fail2ban
# ---------------------------------------------------------------------------
systemd.service(
    name="Enable and restart fail2ban",
    service="fail2ban",
    running=True,
    restarted=True,
    enabled=True,
)

# ---------------------------------------------------------------------------
# 9. Restart sshd — MUST be the last operation.
#    After this completes, port 22 is closed and root login is disabled.
#    All future access must use: ssh -p 2222 overlord101@<host>
# ---------------------------------------------------------------------------
systemd.service(
    name="Restart sshd (applies hardened config — root SSH disabled after this)",
    service="ssh",
    running=True,
    restarted=True,
    enabled=True,
)

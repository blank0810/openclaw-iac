# Shared non-secret configuration for all hosts.
# Imported by Pyinfra automatically when a group_data/all.py is present.
# Do NOT put secrets here — use .env (gitignored) for those.

# Admin user created during bootstrap. All post-bootstrap operations run as this user.
deploy_user = "overlord101"

# SSH port used after bootstrap hardens the server.
# bootstrap.py connects on port 22; deploy.py uses this port.
ssh_port = 2222

# UFW TCP ports to allow.
# 22 was reopened 2026-04-29 at team-lead request (alongside 2222). Both ports
# accept SSH; fail2ban watches both. Drop 22 again by removing it from this
# list AND from infra/files/sshd_config + infra/files/fail2ban_jail.local.
allowed_tcp_ports = [22, 2222]

# Server timezone.
timezone = "UTC"

# SSH public keys to install in overlord101's authorized_keys.
# Add each team member's public key as a string in this list.
# Example: "ssh-ed25519 AAAA... user@host"
team_ssh_keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB072+CL95BgZ7rPUcRBTWTJNMFiI03OKWP8fWZqPpsy team@cloudesk.co",
]

# ----------------------------------------------------------------------------
# ZeroClaw stack
# ----------------------------------------------------------------------------
# Directory on Server 3 that holds docker-compose.yml, config/, data/, and
# the remote .env. Owned by overlord101, mode 0750.
zeroclaw_dir = "/opt/zeroclaw"

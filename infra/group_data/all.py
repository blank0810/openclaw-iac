# Shared non-secret configuration for all hosts.
# Imported by Pyinfra automatically when a group_data/all.py is present.
# Do NOT put secrets here — use .env (gitignored) for those.

# Admin user created during bootstrap. All post-bootstrap operations run as this user.
deploy_user = "overlord101"

# SSH port used after bootstrap hardens the server.
# bootstrap.py connects on port 22; deploy.py uses this port.
ssh_port = 2222

# Server-side path where docker-compose.yml and .env are uploaded.
deploy_path = "/opt/openclaw"

# Docker Compose project name (used in container/network names).
compose_project = "openclaw"

# UFW TCP ports to allow. Only SSH is exposed — OpenClaw binds to loopback,
# so agent ports are not internet-facing. Access via SSH tunnel when needed.
allowed_tcp_ports = [2222]

# Server timezone.
timezone = "UTC"

# SSH public keys to install in overlord101's authorized_keys.
# Add each team member's public key as a string in this list.
# Example: "ssh-ed25519 AAAA... user@host"
team_ssh_keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB072+CL95BgZ7rPUcRBTWTJNMFiI03OKWP8fWZqPpsy team@cloudesk.co",
]

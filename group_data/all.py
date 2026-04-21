# Shared non-secret configuration for all hosts.
# Imported by Pyinfra automatically when a group_data/all.py is present.
# Do NOT put secrets here — use .env (gitignored) for those.

# Admin user created during bootstrap. All post-bootstrap operations run as this user.
deploy_user = "overlord101"

# SSH port used after bootstrap hardens the server.
# bootstrap.py connects on port 22; deploy.py uses this port.
ssh_port = 2222

# UFW TCP ports to allow.
allowed_tcp_ports = [2222]

# Server timezone.
timezone = "UTC"

# SSH public keys to install in overlord101's authorized_keys.
# Add each team member's public key as a string in this list.
# Example: "ssh-ed25519 AAAA... user@host"
team_ssh_keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB072+CL95BgZ7rPUcRBTWTJNMFiI03OKWP8fWZqPpsy team@cloudesk.co",
]

# ----------------------------------------------------------------------------
# Chaos (OpenClaw) stack
# ----------------------------------------------------------------------------
# Directory on Server 3 that holds docker-compose.yml, config/, state/,
# workspace/, and the remote .env. Owned by overlord101, mode 0750.
chaos_dir = "/opt/openclaw/chaos"

# Default image pin — reference only. The real value comes from the
# CHAOS_IMAGE env var (laptop .env -> remote .env -> compose substitution).
# Kept here so `group_data` documents the project's intended pin.
chaos_image = "ghcr.io/openclaw/openclaw:2026.4.14"

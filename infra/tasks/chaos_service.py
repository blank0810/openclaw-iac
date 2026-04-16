"""
Pull the pinned OpenClaw image and bring the compose stack up.

Idempotent: docker compose up -d is a no-op when all services are current.
--remove-orphans cleans up containers removed from compose.
"""

from pyinfra.operations import server

server.shell(
    name="Pull Chaos images",
    commands=[
        "cd /opt/openclaw/chaos && docker compose pull",
    ],
    _timeout=300,
)

server.shell(
    name="Bring Chaos stack up",
    commands=[
        "cd /opt/openclaw/chaos && docker compose up -d --remove-orphans",
    ],
    _timeout=120,
)

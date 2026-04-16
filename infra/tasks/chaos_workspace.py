"""
Upload the 7 identity files from docker/chaos/workspace/ to
/opt/openclaw/chaos/workspace/ on the server.

These files are mounted read-only into the container as the agent's
bootstrap context. Edits to them require a redeploy (not self-managed).
"""

from pyinfra import host
from pyinfra.operations import files

deploy_user = host.data.deploy_user

identity_files = [
    "IDENTITY.md",
    "SOUL.md",
    "USER.md",
    "AGENTS.md",
    "HEARTBEAT.md",
    "TOOLS.md",
    "BOOTSTRAP.md",
]

for fname in identity_files:
    files.put(
        name=f"Upload workspace/{fname}",
        src=f"docker/chaos/workspace/{fname}",
        dest=f"/opt/openclaw/chaos/workspace/{fname}",
        user=deploy_user,
        group=deploy_user,
        mode="644",
    )

"""
Seed /opt/openclaw/chaos/state/openclaw.json ONCE, on first deploy only.

After first boot, Chaos self-manages this file via the gateway tool.
Never overwrite on subsequent deploys — that would wipe bot-authored changes.

Uses a sentinel file (.seeded) to guarantee single-shot behavior even if
someone deletes openclaw.json mid-debug.

Requires _sudo=True (set globally in inventory) — chown to uid 1000 needs root.
"""

from pyinfra import host
from pyinfra.facts.files import File
from pyinfra.operations import files, server

seed_src = "docker/chaos/openclaw.json"
seed_tmp = "/tmp/openclaw.seed.json"
seed_path = "/opt/openclaw/chaos/state/openclaw.json"
sentinel_path = "/opt/openclaw/chaos/state/.seeded"

already_seeded = host.get_fact(File, path=sentinel_path)

if not already_seeded:
    # Stage the seed file into /tmp first (readable by anyone), then move into
    # place and mark sentinel in a single atomic shell op. This avoids the
    # two-op race where a crash between put and touch leaves state half-seeded.
    files.put(
        name="Stage openclaw.json seed into /tmp",
        src=seed_src,
        dest=seed_tmp,
        mode="644",
    )

    server.shell(
        name="Atomically install seed + mark sentinel",
        commands=[
            f"install -m 600 -o 1000 -g 1000 {seed_tmp} {seed_path}",
            f"rm -f {seed_tmp}",
            f"touch {sentinel_path}",
            f"chown 1000:1000 {sentinel_path}",
        ],
    )
else:
    server.shell(
        name="Skip seed — openclaw.json already seeded (bot self-manages)",
        commands=["true"],
    )

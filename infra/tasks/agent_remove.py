"""
agent_remove.py - Tear down one tenant.

Archives /opt/<name>/data/ to /opt/.archive/<name>-YYYYMMDD-HHMM/data/,
then removes the container, compose file, config, .env, and systemd probe
units. Operator data is recoverable from /opt/.archive/ until manually
cleaned up.

Reads AGENT_NAME from env. The wrapper enforces the type-the-name
confirmation before invoking this task.
"""

import os
import re

from pyinfra.operations import server, systemd

AGENT_NAME = os.environ.get("AGENT_NAME", "").strip()
SLUG_RE = re.compile(r"^agent-[a-z0-9]([a-z0-9-]{0,27}[a-z0-9])?$")

if not SLUG_RE.match(AGENT_NAME):
    raise RuntimeError(f"agent_remove.py - invalid AGENT_NAME: {AGENT_NAME!r}")

agent_dir = f"/opt/{AGENT_NAME}"

server.shell(
    name=f"[{AGENT_NAME}] disable probe timer (ignore errors if absent)",
    commands=[
        f"systemctl disable --now {AGENT_NAME}-slack-probe.timer 2>/dev/null || true",
    ],
)

server.shell(
    name=f"[{AGENT_NAME}] compose down",
    commands=[
        f"if [ -f {agent_dir}/docker-compose.yml ]; then "
        f"  cd {agent_dir} && docker compose down --remove-orphans || true; "
        f"fi"
    ],
    _timeout=120,
)

server.shell(
    name=f"[{AGENT_NAME}] archive data dir",
    commands=[
        f"if [ -d {agent_dir}/data ]; then "
        f"  ts=$(date -u +%Y%m%d-%H%M); "
        f"  archive=/opt/.archive/{AGENT_NAME}-$ts; "
        f"  mkdir -p \"$archive\"; "
        f"  mv {agent_dir}/data \"$archive/data\"; "
        f"  echo \"archived to $archive/data\"; "
        f"fi"
    ],
)

server.shell(
    name=f"[{AGENT_NAME}] remove tenant dir + probe units",
    commands=[
        f"rm -rf {agent_dir}",
        f"rm -f /etc/systemd/system/{AGENT_NAME}-slack-probe.service",
        f"rm -f /etc/systemd/system/{AGENT_NAME}-slack-probe.timer",
        f"rm -rf /var/lib/{AGENT_NAME}-probe",
    ],
)

systemd.daemon_reload(name=f"[{AGENT_NAME}] systemctl daemon-reload")

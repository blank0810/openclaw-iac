"""
migrate_zeroclaw_to_chaos.py - one-time migration of the legacy /opt/zeroclaw
deploy to the new tenant layout under /opt/agent-chaos.

Run once during a planned maintenance window, then run:
    scripts/agentctl new agent-chaos

This task:
  1. stops the legacy /opt/zeroclaw compose stack,
  2. renames /opt/zeroclaw to /opt/agent-chaos when safe,
  3. removes legacy zeroclaw-slack-probe systemd units.
"""

from pyinfra.operations import server, systemd

server.shell(
    name="legacy: compose down /opt/zeroclaw",
    commands=[
        "if [ -f /opt/zeroclaw/docker-compose.yml ]; then "
        "  cd /opt/zeroclaw && docker compose down --remove-orphans || true; "
        "fi"
    ],
    _timeout=120,
)

server.shell(
    name="legacy: rename /opt/zeroclaw -> /opt/agent-chaos",
    commands=[
        "if [ -d /opt/zeroclaw ] && [ ! -e /opt/agent-chaos ]; then "
        "  mv /opt/zeroclaw /opt/agent-chaos; "
        "fi"
    ],
)

server.shell(
    name="legacy: disable + remove zeroclaw-slack-probe units",
    commands=[
        "systemctl disable --now zeroclaw-slack-probe.timer 2>/dev/null || true",
        "rm -f /etc/systemd/system/zeroclaw-slack-probe.service",
        "rm -f /etc/systemd/system/zeroclaw-slack-probe.timer",
        "rm -rf /var/lib/zeroclaw-probe",
    ],
)

systemd.daemon_reload(name="legacy: daemon-reload after probe removal")

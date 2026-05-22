"""
zeroclaw_probe.py — Deploy the Slack-liveness watchdog to Server 3.

Runs every 3 minutes via systemd timer. Two rules trigger a
`docker restart zeroclaw`:

  1. Slack `apps.connections.open` REST call. 3 consecutive failures
     restart the container (~9 min detection).
  2. Zombie-socket detection: zero `websocket connected|disconnect|
     reconnecting` lines in `docker logs --since 6h` while the container
     is running. Catches half-dead TCP that the upstream Rust adapter
     cannot detect today (no client ping, no read timeout, no
     SO_KEEPALIVE — see crates/zeroclaw-channels/src/slack.rs:2596).

Idempotent. Safe to re-run. Requires SLACK_APP_TOKEN in the local .env
(already required by zeroclaw_deploy.py, which threads it into
config.toml).
"""

import os

from pyinfra import host
from pyinfra.operations import apt, files, systemd

deploy_user = host.data.deploy_user
zeroclaw_dir = host.data.zeroclaw_dir

slack_app_token = os.environ.get("SLACK_APP_TOKEN", "")
if not slack_app_token:
    raise RuntimeError(
        "zeroclaw_probe.py — SLACK_APP_TOKEN not set in the local .env. "
        "Required to deploy the Slack-liveness watchdog."
    )

# ---------------------------------------------------------------------------
# 1. Probe dependencies. curl is installed by base_packages.py; jq is needed
#    for parsing Slack's JSON response. apt.packages is idempotent.
# ---------------------------------------------------------------------------
apt.packages(
    name="Install jq for the Slack probe",
    packages=["jq"],
)

# ---------------------------------------------------------------------------
# 2. Filesystem layout. /opt/zeroclaw/bin holds the script; /var/lib/
#    zeroclaw-probe holds the consecutive-failure counter; /var/log/
#    zeroclaw-probe.log accumulates probe events. systemd hardening
#    (ProtectSystem=strict + ReadWritePaths) means the service can only
#    write to those two paths — locks the blast radius if the script is
#    ever subverted.
# ---------------------------------------------------------------------------
files.directory(
    name="Ensure /opt/zeroclaw/bin exists",
    path=f"{zeroclaw_dir}/bin",
    present=True,
    user=deploy_user,
    group=deploy_user,
    mode="750",
)
files.directory(
    name="Ensure /var/lib/zeroclaw-probe exists",
    path="/var/lib/zeroclaw-probe",
    present=True,
    user="root",
    group="root",
    mode="750",
)
# The service unit uses ProtectSystem=strict + ReadWritePaths=…, which
# requires the listed paths to exist BEFORE namespace setup. Pre-create
# the log file so the very first probe run doesn't fail with
# `status=226/NAMESPACE`. The script touches it again at runtime
# (idempotent), but systemd needs it ahead of exec.
files.file(
    name="Ensure /var/log/zeroclaw-probe.log exists",
    path="/var/log/zeroclaw-probe.log",
    present=True,
    user="root",
    group="root",
    mode="640",
)

# ---------------------------------------------------------------------------
# 3. Probe script. Owned by overlord101 (matches the rest of /opt/zeroclaw),
#    mode 0750. Root (the systemd service runs as root) can read+execute
#    regardless of unix bits, so this works without widening permissions.
# ---------------------------------------------------------------------------
files.put(
    name="Upload zeroclaw-slack-probe.sh",
    src="infra/files/zeroclaw-slack-probe.sh",
    dest=f"{zeroclaw_dir}/bin/zeroclaw-slack-probe.sh",
    user=deploy_user,
    group=deploy_user,
    mode="750",
)

# ---------------------------------------------------------------------------
# 4. systemd service unit (templated — SLACK_APP_TOKEN is baked in as an
#    Environment= line). Mode 0600 root-only: the token is already present
#    in /opt/zeroclaw/config/config.toml (mode 0640 nobody:nogroup), so
#    this adds one more on-disk copy with stricter permissions, not a new
#    secret surface.
# ---------------------------------------------------------------------------
files.template(
    name="Render zeroclaw-slack-probe.service",
    src="infra/files/zeroclaw-slack-probe.service.j2",
    dest="/etc/systemd/system/zeroclaw-slack-probe.service",
    user="root",
    group="root",
    mode="600",
    slack_app_token=slack_app_token,
)

# ---------------------------------------------------------------------------
# 5. systemd timer unit. Static — no secrets, no env-driven config.
# ---------------------------------------------------------------------------
files.put(
    name="Upload zeroclaw-slack-probe.timer",
    src="infra/files/zeroclaw-slack-probe.timer",
    dest="/etc/systemd/system/zeroclaw-slack-probe.timer",
    user="root",
    group="root",
    mode="644",
)

# ---------------------------------------------------------------------------
# 6. Reload daemon (units changed) + enable & start the timer. Note:
#    starting the *timer* is what we want — the .service is oneshot and
#    fires when the timer triggers, not at boot.
# ---------------------------------------------------------------------------
systemd.daemon_reload(
    name="systemctl daemon-reload (zeroclaw-slack-probe units)",
)
systemd.service(
    name="Enable + start zeroclaw-slack-probe.timer",
    service="zeroclaw-slack-probe.timer",
    running=True,
    enabled=True,
)

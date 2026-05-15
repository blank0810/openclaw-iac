from __future__ import annotations

import getpass
import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from lib.config import DeploymentConfig, load_config

AUDIT_LOG_PATH = "/opt/zeroclaw/audit.log"


def _format_ts(ts: datetime | None) -> str:
    if ts is None:
        ts = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def format_audit_line(
    *,
    actor: str,
    cmd: str,
    agent: str | None,
    image: str | None,
    result: str,
    ts: datetime | None = None,
) -> str:
    return (
        json.dumps(
            {
                "ts": _format_ts(ts),
                "actor": actor,
                "cmd": cmd,
                "agent": agent,
                "image": image,
                "result": result,
            },
            sort_keys=True,
        )
        + "\n"
    )


def append_audit_line(
    cfg: DeploymentConfig,
    *,
    actor: str,
    cmd: str,
    agent: str | None,
    image: str | None,
    result: str,
) -> None:
    """Append a JSONL audit record to the remote audit log.

    Failure is swallowed: audit-log failures must never fail the parent command.
    """
    line = format_audit_line(
        actor=actor, cmd=cmd, agent=agent, image=image, result=result
    )
    payload = line.rstrip("\n")
    remote_cmd = f"printf '%s\\n' {shlex.quote(payload)} >> {AUDIT_LOG_PATH}"
    try:
        subprocess.run(
            [
                "ssh",
                "-p",
                str(cfg.ssh_port),
                f"{cfg.deploy_user}@{cfg.server_host}",
                remote_cmd,
            ],
            check=False,
        )
    except Exception:
        return


def cmd_audit(
    *,
    agent: str | None = None,
    since: str | None = None,
    project_root: Path | None = None,
) -> int:
    cfg = load_config(project_root)
    command = "cat /opt/zeroclaw/audit.log"
    if agent:
        command += f" | grep '\"agent\": \"{agent}\"' || true"
    if since:
        command += f" | awk '$0 >= \"{since}\"'"
    return subprocess.run(
        [
            "ssh",
            "-p",
            str(cfg.ssh_port),
            f"{cfg.deploy_user}@{cfg.server_host}",
            command,
        ],
        check=False,
    ).returncode


def default_actor() -> str:
    return getpass.getuser()

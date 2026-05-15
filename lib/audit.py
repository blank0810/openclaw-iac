from __future__ import annotations

import getpass
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from lib.config import load_config


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
    tenant: str | None,
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
                "tenant": tenant,
                "image": image,
                "result": result,
            },
            sort_keys=True,
        )
        + "\n"
    )


def cmd_audit(
    *,
    tenant: str | None = None,
    since: str | None = None,
    project_root: Path | None = None,
) -> int:
    cfg = load_config(project_root)
    command = "cat /opt/zeroclaw/audit.log"
    if tenant:
        command += f" | grep '\"tenant\": \"{tenant}\"' || true"
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

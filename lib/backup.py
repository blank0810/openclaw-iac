from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from lib.audit import append_audit_line, default_actor
from lib.config import AgentDefinition, DeploymentConfig, load_config


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _agents(cfg: DeploymentConfig, name: str | None) -> list[AgentDefinition]:
    if name:
        return [agent for agent in cfg.agents if agent.name == name]
    return [agent for agent in cfg.agents if agent.enabled]


def cmd_backup(name: str | None, project_root: Path | None = None) -> int:
    project_root = Path(project_root) if project_root else Path.cwd()
    cfg = load_config(project_root)
    selected = _agents(cfg, name)
    if name and not selected:
        print(f"unknown agent: {name}")
        return 1
    for agent in selected:
        backup_dir = project_root / "backups" / agent.name
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{_ts()}.tar.gz"
        with backup_path.open("wb") as out:
            result = subprocess.run(
                [
                    "ssh",
                    "-i",
                    str(cfg.deploy_ssh_key_path),
                    "-p",
                    str(cfg.ssh_port),
                    f"{cfg.deploy_user}@{cfg.server_host}",
                    (
                        f"tar -C /opt/zeroclaw/states/{agent.state_dir} "
                        "-czf - --exclude=zeroclaw.env config.toml workspace/"
                    ),
                ],
                stdout=out,
                check=False,
            )
        append_audit_line(
            cfg,
            actor=default_actor(),
            cmd="backup",
            agent=agent.name,
            image=None,
            result="ok" if result.returncode == 0 else "fail",
        )
        if result.returncode:
            return result.returncode
    return 0

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from lib.config import DeploymentConfig, TenantDefinition, load_config


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _tenants(cfg: DeploymentConfig, name: str | None) -> list[TenantDefinition]:
    if name:
        return [tenant for tenant in cfg.tenants if tenant.name == name]
    return [tenant for tenant in cfg.tenants if tenant.enabled]


def cmd_backup(name: str | None, project_root: Path | None = None) -> int:
    project_root = Path(project_root) if project_root else Path.cwd()
    cfg = load_config(project_root)
    selected = _tenants(cfg, name)
    if name and not selected:
        print(f"unknown tenant: {name}")
        return 1
    for tenant in selected:
        backup_dir = project_root / "backups" / tenant.name
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{_ts()}.tar.gz"
        with backup_path.open("wb") as out:
            result = subprocess.run(
                [
                    "ssh",
                    "-p",
                    str(cfg.ssh_port),
                    f"{cfg.deploy_user}@{cfg.server_host}",
                    (
                        f"tar -C /opt/zeroclaw/states/{tenant.state_dir} "
                        "-czf - --exclude=zeroclaw.env config.toml workspace/"
                    ),
                ],
                stdout=out,
                check=False,
            )
        if result.returncode:
            return result.returncode
    return 0

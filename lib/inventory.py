from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.config import load_config


def build_inventory_data(
    project_root: Path | None = None,
    ssh_user: str = "overlord101",
    ssh_key: str | None = None,
) -> dict[str, Any]:
    cfg = load_config(project_root=project_root)
    tenants = [
        {
            "name": tenant.name,
            "state_dir": tenant.state_dir,
            "enabled": tenant.enabled,
            "host_port": tenant.host_port,
            "image": tenant.image or cfg.zeroclaw_image,
            "exec_enabled": tenant.exec_enabled,
        }
        for tenant in cfg.tenants
    ]
    return {
        "deploy_user": cfg.deploy_user,
        "ssh_port": cfg.ssh_port,
        "ssh_user": ssh_user,
        "ssh_key": ssh_key or str(cfg.deploy_ssh_key_path),
        "remote_base_dir": "/opt/zeroclaw",
        "remote_runtime_dir": "/opt/zeroclaw",
        "zeroclaw_image": cfg.zeroclaw_image,
        "tenants": tenants,
        "effective_tcp_ports": list(cfg.effective_tcp_ports),
        "config": cfg,
    }


def _server_inventory() -> tuple[list[tuple[str, dict[str, Any]]]]:
    data = build_inventory_data()
    cfg = data.pop("config")
    return ([(cfg.server_host, data)],)


def __getattr__(name: str):
    if name == "inventory":
        return _server_inventory()
    raise AttributeError(name)

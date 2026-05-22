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
    agents = [
        {
            "name": agent.name,
            "state_dir": agent.state_dir,
            "enabled": agent.enabled,
            "host_port": agent.host_port,
            "image": agent.image or cfg.zeroclaw_image,
            "exec_enabled": agent.exec_enabled,
        }
        for agent in cfg.agents
    ]
    return {
        "deploy_user": cfg.deploy_user,
        "ssh_port": cfg.ssh_port,
        "ssh_user": ssh_user,
        "ssh_key": ssh_key or str(cfg.deploy_ssh_key_path),
        "remote_base_dir": "/opt/zeroclaw",
        "remote_runtime_dir": "/opt/zeroclaw",
        "zeroclaw_image": cfg.zeroclaw_image,
        "agents": agents,
        "effective_tcp_ports": list(cfg.effective_tcp_ports),
        "config": cfg,
    }


def _server_inventory() -> list[tuple[str, dict[str, Any]]]:
    data = build_inventory_data()
    cfg = data.pop("config")
    return [(cfg.server_host, data)]


# Pyinfra discovers host groups by scanning module-level attributes via
# dir() — lazy __getattr__ is invisible to that scan, which silently
# yields a zero-host inventory and a no-op run. Expose the group eagerly.
# Tests import build_inventory_data directly and don't depend on this;
# the try/except keeps imports working in environments without a real
# .env (e.g. CI without secrets).
try:
    zeroclaw_servers = _server_inventory()
except Exception:
    zeroclaw_servers = []

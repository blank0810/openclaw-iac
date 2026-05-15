from __future__ import annotations

import subprocess
from pathlib import Path

from lib.config import AgentDefinition, DeploymentConfig, load_config
from lib.managed_policy import build_policy_block, inject_policy_block

REMOTE_BASE = "/opt/zeroclaw"


def _agent(cfg: DeploymentConfig, name: str) -> AgentDefinition:
    for agent in cfg.agents:
        if agent.name == name:
            return agent
    raise ValueError(f"unknown agent {name!r}")


def _ssh(cfg: DeploymentConfig, command: str, *, capture: bool = False):
    return subprocess.run(
        ["ssh", "-p", str(cfg.ssh_port), f"{cfg.deploy_user}@{cfg.server_host}", command],
        check=False,
        text=True,
        capture_output=capture,
    )


def _remote_workspace(agent: AgentDefinition) -> str:
    return f"{REMOTE_BASE}/states/{agent.state_dir}/workspace"


def cmd_status(name: str, project_root: Path | None = None) -> int:
    project_root = Path(project_root) if project_root else Path.cwd()
    cfg = load_config(project_root)
    agent = _agent(cfg, name)
    local_files = {p.name: p for p in (project_root / "agents" / name / "workspace").glob("*.md")}
    remote = _ssh(cfg, f"ls {_remote_workspace(agent)}/*.md 2>/dev/null || true", capture=True)
    remote_names = {Path(line).name for line in remote.stdout.splitlines() if line.strip()}
    for filename in sorted(set(local_files) | remote_names):
        if filename in local_files and filename not in remote_names:
            status = "local_only"
        elif filename not in local_files and filename in remote_names:
            status = "remote_only"
        else:
            status = "different"
        print(f"{filename} {status}")
    return 0


def cmd_fetch(name: str, project_root: Path | None = None, force: bool = False) -> int:
    project_root = Path(project_root) if project_root else Path.cwd()
    cfg = load_config(project_root)
    agent = _agent(cfg, name)
    dest = project_root / "agents" / name / "workspace"
    if dest.exists() and any(dest.glob("*.md")) and not force:
        print("local workspace files exist; use force to overwrite")
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            "scp",
            "-P",
            str(cfg.ssh_port),
            f"{cfg.deploy_user}@{cfg.server_host}:{_remote_workspace(agent)}/*.md",
            str(dest),
        ],
        check=False,
    ).returncode


def cmd_deploy(name: str, project_root: Path | None = None, force: bool = False) -> int:
    project_root = Path(project_root) if project_root else Path.cwd()
    cfg = load_config(project_root)
    agent = _agent(cfg, name)
    workspace = project_root / "agents" / name / "workspace"
    if not force:
        if input(f"Deploy workspace for {name}? Type {name}: ") != name:
            return 1
    agents_md = workspace / "AGENTS.md"
    if agents_md.exists():
        policy = build_policy_block(
            agent.policy.require_approval_for,
            agent.policy.denied_domains,
        )
        agents_md.write_text(inject_policy_block(agents_md.read_text(), policy))
    for path in sorted(workspace.glob("*.md")):
        result = subprocess.run(
            [
                "scp",
                "-P",
                str(cfg.ssh_port),
                str(path),
                f"{cfg.deploy_user}@{cfg.server_host}:{_remote_workspace(agent)}/{path.name}",
            ],
            check=False,
        )
        if result.returncode:
            return result.returncode
    return 0


def cmd_session_clear(name: str, project_root: Path | None = None) -> int:
    cfg = load_config(project_root)
    agent = _agent(cfg, name)
    workspace = _remote_workspace(agent)
    command = (
        f"mkdir -p {workspace}/sessions/archive && "
        f"find {workspace}/sessions -maxdepth 1 -name '*.jsonl' -exec sh -c "
        f"'for f; do mv \"$f\" \"{workspace}/sessions/archive/$(basename \"$f\").bak.$(date -u +%Y%m%dT%H%M%SZ)\"; done' sh {{}} + && "
        f"cd {REMOTE_BASE} && docker compose restart {agent.name}"
    )
    return _ssh(cfg, command).returncode

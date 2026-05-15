from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from lib.config import AgentDefinition, DeploymentConfig, SLUG_PATTERN, load_config
from lib.config_patch import default_exec_deny_patterns
from lib.managed_policy import build_policy_block, inject_policy_block
from lib.agent_env import build_agent_env


REMOTE_BASE = "/opt/zeroclaw"


def _agent_by_name(cfg: DeploymentConfig, name: str) -> AgentDefinition:
    for agent in cfg.agents:
        if agent.name == name:
            return agent
    raise ValueError(f"unknown agent {name!r}")


def _ssh_base(cfg: DeploymentConfig) -> list[str]:
    return ["ssh", "-p", str(cfg.ssh_port), f"{cfg.deploy_user}@{cfg.server_host}"]


def _scp_to(cfg: DeploymentConfig, local: Path, remote: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "scp",
            "-P",
            str(cfg.ssh_port),
            str(local),
            f"{cfg.deploy_user}@{cfg.server_host}:{remote}",
        ],
        check=False,
        text=True,
        capture_output=True,
    )


def _ssh(cfg: DeploymentConfig, command: str, *, capture: bool = False):
    return subprocess.run(
        _ssh_base(cfg) + [command],
        check=False,
        text=True,
        capture_output=capture,
    )


def _template_env(project_root: Path) -> Environment:
    search_paths = [str(project_root / "templates")]
    repo_templates = Path(__file__).resolve().parents[1] / "templates"
    if repo_templates != project_root / "templates":
        search_paths.append(str(repo_templates))
    return Environment(loader=FileSystemLoader(search_paths))


def cmd_create(name: str, project_root: Path | None = None) -> int:
    project_root = Path(project_root) if project_root else Path.cwd()
    if not SLUG_PATTERN.match(name):
        print(f"invalid agent slug: {name}")
        return 1
    src = project_root / "agents" / "_template"
    dest = project_root / "agents" / name
    if dest.exists():
        print(f"agent already exists: {name}")
        return 1
    shutil.copytree(src, dest)
    agent_toml = dest / "agent.toml"
    if agent_toml.exists():
        agent_toml.write_text(agent_toml.read_text().replace("REPLACE_ME", name))
    return 0


def cmd_deploy(name: str, project_root: Path | None = None, pull_image: bool = False) -> int:
    project_root = Path(project_root) if project_root else Path.cwd()
    cfg = load_config(project_root)
    agent = _agent_by_name(cfg, name)
    env = _template_env(project_root)
    staged = project_root / ".runtime-temp" / agent.name
    staged.mkdir(parents=True, exist_ok=True)

    env_text = env.get_template("zeroclaw.env.j2").render(env=build_agent_env(agent))
    config_text = env.get_template("config.toml.j2").render(
        agent=agent,
        exec_deny_patterns=default_exec_deny_patterns(),
    )
    (staged / "zeroclaw.env").write_text(env_text)
    (staged / "config.toml").write_text(config_text)

    remote_state = f"{REMOTE_BASE}/states/{agent.state_dir}"
    _ssh(cfg, f"mkdir -p {remote_state}/workspace {remote_state}/workspace/sessions")
    _scp_to(cfg, staged / "zeroclaw.env", f"{remote_state}/zeroclaw.env")
    _scp_to(cfg, staged / "config.toml", f"{remote_state}/config.toml")
    _ssh(cfg, f"chmod 0600 {remote_state}/zeroclaw.env && chmod 0644 {remote_state}/config.toml")

    existing_agents = _ssh(
        cfg,
        f"cat {remote_state}/workspace/AGENTS.md 2>/dev/null || true",
        capture=True,
    ).stdout
    policy = build_policy_block(
        approval_gates=agent.policy.require_approval_for,
        denied_domains=agent.policy.denied_domains,
    )
    (staged / "AGENTS.md").write_text(inject_policy_block(existing_agents or "", policy))
    _scp_to(cfg, staged / "AGENTS.md", f"{remote_state}/workspace/AGENTS.md")

    if pull_image:
        _ssh(cfg, f"cd {REMOTE_BASE} && docker pull {agent.image or cfg.zeroclaw_image}")
    return _ssh(
        cfg,
        f"cd {REMOTE_BASE} && docker compose up -d --force-recreate {agent.name}",
    ).returncode


def cmd_status(project_root: Path | None = None) -> int:
    cfg = load_config(project_root)
    result = _ssh(
        cfg,
        f"cd {REMOTE_BASE} && docker compose ps --format json || true",
        capture=True,
    )
    print(result.stdout, end="")
    return result.returncode


def cmd_shell(name: str, project_root: Path | None = None) -> int:
    cfg = load_config(project_root)
    return subprocess.run(
        _ssh_base(cfg) + ["-t", f"cd {REMOTE_BASE} && docker compose exec {name} bash"],
        check=False,
    ).returncode


def cmd_logs(name: str, follow: bool = False, project_root: Path | None = None) -> int:
    cfg = load_config(project_root)
    flag = " -f" if follow else ""
    return subprocess.run(
        _ssh_base(cfg) + ["-t", f"cd {REMOTE_BASE} && docker compose logs{flag} {name}"],
        check=False,
    ).returncode


def cmd_remove(name: str, project_root: Path | None = None) -> int:
    cfg = load_config(project_root)
    if input(f"Type {name} to remove: ") != name:
        return 1
    command = (
        f"cd {REMOTE_BASE} && docker compose stop {name} || true && "
        f"mkdir -p .archive && mv states/{name} .archive/{name}-$(date -u +%Y%m%dT%H%M%SZ) && "
        "docker compose up -d"
    )
    return _ssh(cfg, command).returncode


def cmd_fetch(name: str, project_root: Path | None = None, force: bool = False) -> int:
    cfg = load_config(project_root)
    agent = _agent_by_name(cfg, name)
    project_root = Path(project_root) if project_root else Path.cwd()
    dest = project_root / "agents" / name
    if dest.exists() and not force:
        print(f"local agent exists: {name}; use force to overwrite")
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "workspace").mkdir(exist_ok=True)
    return subprocess.run(
        [
            "scp",
            "-P",
            str(cfg.ssh_port),
            "-r",
            f"{cfg.deploy_user}@{cfg.server_host}:{REMOTE_BASE}/states/{agent.state_dir}/workspace/*.md",
            str(dest / "workspace"),
        ],
        check=False,
    ).returncode


def cmd_restore(name: str, ts: str | None = None, project_root: Path | None = None) -> int:
    cfg = load_config(project_root)
    archive = f".archive/{name}-{ts}" if ts else f"$(ls -dt .archive/{name}-* | head -1)"
    command = f"cd {REMOTE_BASE} && mv {archive} states/{name} && docker compose up -d {name}"
    return _ssh(cfg, command).returncode

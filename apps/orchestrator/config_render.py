from __future__ import annotations

import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from lib.agent_env import build_agent_env
from lib.config import AgentDefinition
from lib.config_patch import default_exec_deny_patterns
from lib.managed_policy import build_policy_block, inject_policy_block

_WORKSPACE_TEMPLATES = (
    "AGENTS.md.j2", "BOOTSTRAP.md.j2", "HEARTBEAT.md.j2", "IDENTITY.md.j2",
    "SOUL.md.j2", "TOOLS.md.j2", "USER.md.j2",
)


def _env(project_root: Path) -> Environment:
    paths = [str(project_root / "templates")]
    repo = Path(__file__).resolve().parents[2] / "templates"
    if str(repo) not in paths:
        paths.append(str(repo))
    return Environment(loader=FileSystemLoader(paths))


def render_agent_config(
    agent: AgentDefinition, state_dir: Path, *, project_root: Path | None = None
) -> dict[str, str]:
    """Render config.toml + workspace markdowns into state_dir, inject the
    managed policy block into AGENTS.md, and return the env dict for the
    container. Local filesystem only (orchestrator runs on the host)."""
    project_root = project_root or Path.cwd()
    jenv = _env(project_root)
    zc = state_dir / ".zeroclaw"
    ws = state_dir / "workspace"
    zc.mkdir(parents=True, exist_ok=True)
    ws.mkdir(parents=True, exist_ok=True)

    config_text = jenv.get_template("config.toml.j2").render(
        agent=agent, exec_deny_patterns=default_exec_deny_patterns()
    )
    (zc / "config.toml").write_text(config_text)
    # config.toml carries the Composio MCP key + Slack tokens; tighten the mode
    # at creation time so the secret-bearing file is never world-readable, not
    # even briefly. Ownership is set separately at provision time by
    # provisioner._chown_for_container (chown to 65534, the container UID) --
    # agents are created dynamically, so it can't be a static deploy step.
    os.chmod(zc / "config.toml", 0o640)

    for name in _WORKSPACE_TEMPLATES:
        try:
            tmpl = jenv.get_template(f"workspace/{name}")
        except Exception:
            continue
        (ws / name[: -len(".j2")]).write_text(tmpl.render(agent=agent))

    agents_md = ws / "AGENTS.md"
    if agents_md.exists():
        policy = build_policy_block(
            agent.policy.require_approval_for, agent.policy.denied_domains
        )
        agents_md.write_text(inject_policy_block(agents_md.read_text(), policy))

    # BOOTSTRAP.md Step 2 verifies MEMORY.md exists and is readable; it is not
    # one of the rendered templates (the memory log starts empty and ZeroClaw's
    # memory_store tool owns it thereafter). Create it empty if absent so the
    # first-session bootstrap does not pause. Empty is expected on first boot.
    memory_md = ws / "MEMORY.md"
    if not memory_md.exists():
        memory_md.write_text("")

    return build_agent_env(agent)

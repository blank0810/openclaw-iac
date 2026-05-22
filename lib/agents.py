from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from jinja2 import Environment, FileSystemLoader

from lib.audit import append_audit_line, default_actor
from lib.config import (
    AgentDefinition,
    DeploymentConfig,
    SLUG_PATTERN,
    _load_defaults,
    _parse_agent_toml,
    load_config,
)
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
    return [
        "ssh",
        "-i",
        str(cfg.deploy_ssh_key_path),
        "-p",
        str(cfg.ssh_port),
        f"{cfg.deploy_user}@{cfg.server_host}",
    ]


def _scp_base(cfg: DeploymentConfig) -> list[str]:
    return [
        "scp",
        "-i",
        str(cfg.deploy_ssh_key_path),
        "-P",
        str(cfg.ssh_port),
    ]


def _scp_to(cfg: DeploymentConfig, local: Path, remote: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        _scp_base(cfg) + [str(local), f"{cfg.deploy_user}@{cfg.server_host}:{remote}"],
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


_SECTION_RE_CACHE: dict[str, re.Pattern] = {}


def _section_re(section: str) -> re.Pattern:
    """Pattern matching a single `[section]` body up to next section or EOF."""
    if section not in _SECTION_RE_CACHE:
        _SECTION_RE_CACHE[section] = re.compile(
            rf'\[{re.escape(section)}\][\s\S]*?(?=\n\[|\Z)',
            re.DOTALL,
        )
    return _SECTION_RE_CACHE[section]


def _replace_in_section(text: str, section: str, body_pattern: str, replacement: str) -> str:
    """Find [section] block, run a sub within it. No-op if section absent or key not found."""
    match = _section_re(section).search(text)
    if not match:
        return text
    section_text = match.group(0)
    new_section, n = re.subn(body_pattern, lambda _m: replacement, section_text, count=1)
    if n == 0:
        return text
    return text[: match.start()] + new_section + text[match.end() :]


def _replace_string_in_section(text: str, section: str, key: str, value: str) -> str:
    return _replace_in_section(
        text, section, rf'{re.escape(key)}\s*=\s*"[^"]*"', f'{key} = "{value}"'
    )


def _replace_bool_in_section(text: str, section: str, key: str, value: bool) -> str:
    token = "true" if value else "false"
    return _replace_in_section(
        text, section, rf'{re.escape(key)}\s*=\s*(?:true|false)', f'{key} = {token}'
    )


def _append_to_section(text: str, section: str, line: str) -> str:
    """Append a line to the end of a [section] block. No-op if section absent."""
    match = _section_re(section).search(text)
    if not match:
        return text
    section_text = match.group(0).rstrip()
    new_section = f"{section_text}\n{line}\n"
    return text[: match.start()] + new_section + text[match.end() :]


def _set_string_in_section(text: str, section: str, key: str, value: str) -> str:
    """Set `key = "value"` in [section]. Replaces existing key, or appends if missing.
    Required for fields that inherit from _defaults.toml — an empty placeholder in
    the per-agent file would override the default."""
    replaced = _replace_string_in_section(text, section, key, value)
    if replaced != text:
        return replaced
    return _append_to_section(text, section, f'{key} = "{value}"')


def _set_bool_in_section(text: str, section: str, key: str, value: bool) -> str:
    replaced = _replace_bool_in_section(text, section, key, value)
    if replaced != text:
        return replaced
    token = "true" if value else "false"
    return _append_to_section(text, section, f"{key} = {token}")


def _redact(token: str, head: int = 8, tail: int = 6) -> str:
    if len(token) <= head + tail:
        return "***"
    return f"{token[:head]}...***{token[-tail:]}"


_WORKSPACE_TEMPLATES = (
    "AGENTS.md.j2",
    "BOOTSTRAP.md.j2",
    "HEARTBEAT.md.j2",
    "IDENTITY.md.j2",
    "SOUL.md.j2",
    "TOOLS.md.j2",
    "USER.md.j2",
)


def _render_workspace_templates(project_root: Path, dest: Path) -> None:
    """Render templates/workspace/*.j2 into dest/workspace using the freshly
    written agent.toml + _defaults.toml. Graceful: silently skips if the
    agent.toml can't parse the full schema (legacy minimal fixtures) or if
    no Jinja templates are found."""
    try:
        defaults = _load_defaults(project_root)
        agent_def = _parse_agent_toml(dest / "agent.toml", defaults)
    except Exception:
        return

    workspace_dir = dest / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    jenv = _template_env(project_root)
    rendered_any = False
    for name in _WORKSPACE_TEMPLATES:
        try:
            template = jenv.get_template(f"workspace/{name}")
        except Exception:
            continue
        out_name = name[: -len(".j2")]
        (workspace_dir / out_name).write_text(template.render(agent=agent_def))
        rendered_any = True

    if rendered_any:
        print(f"rendered: agents/{dest.name}/workspace/ (7 files from templates/workspace/)")


def cmd_create(
    name: str,
    *,
    slack: bool = False,
    composio: bool = False,
    display_name: str | None = None,
    slack_bot_token: str | None = None,
    slack_app_token: str | None = None,
    slack_channel_id: str | None = None,
    composio_mcp_key: str | None = None,
    project_root: Path | None = None,
    _input=input,
    _getpass=getpass.getpass,
) -> int:
    project_root = Path(project_root) if project_root else Path.cwd()
    if not SLUG_PATTERN.match(name):
        print(f"invalid agent slug: {name}")
        return 1
    src = project_root / "agents" / "_template"
    dest = project_root / "agents" / name
    if dest.exists():
        print(f"agent already exists: {name}")
        return 1

    # Activation: explicit boolean flag = interactive prompts;
    # any passthrough flag also activates the section but skips prompts.
    slack_active = slack or any(
        v is not None for v in (slack_bot_token, slack_app_token, slack_channel_id)
    )
    composio_active = composio or composio_mcp_key is not None
    slack_interactive = slack and not any(
        v is not None for v in (slack_bot_token, slack_app_token, slack_channel_id)
    )
    composio_interactive = composio and composio_mcp_key is None

    try:
        if display_name is None:
            if slack_interactive or composio_interactive:
                answer = _input(f"Display name [{name}]: ").strip()
                display_name = answer or name
            else:
                display_name = name

        if slack_interactive:
            if slack_bot_token is None:
                slack_bot_token = _getpass("Slack bot token (xoxb-...): ").strip()
                if slack_bot_token and not slack_bot_token.startswith("xoxb-"):
                    print("warning: bot token does not start with xoxb-")
            if slack_app_token is None:
                slack_app_token = _getpass("Slack app token (xapp-...): ").strip()
                if slack_app_token and not slack_app_token.startswith("xapp-"):
                    print("warning: app token does not start with xapp-")
            if slack_channel_id is None:
                slack_channel_id = _input(
                    "Slack channel ID to scope to (blank for all): "
                ).strip()

        if composio_interactive:
            composio_mcp_key = _getpass(
                "Composio MCP API key (ck_...) — required when --composio is set: "
            ).strip()
            if not composio_mcp_key:
                print(
                    "warning: no Composio MCP key provided; disabling Composio for "
                    "this agent (re-run with --composio-mcp-key or paste a ck_ value)"
                )
                composio_active = False
            elif not composio_mcp_key.startswith("ck_"):
                print("warning: Composio MCP key does not start with ck_")
    except (EOFError, KeyboardInterrupt):
        print("\naborted; no files created")
        return 1

    shutil.copytree(src, dest)
    agent_toml = dest / "agent.toml"
    if not agent_toml.exists():
        print(f"template missing agent.toml at {src}")
        shutil.rmtree(dest, ignore_errors=True)
        return 1

    text = agent_toml.read_text().replace("REPLACE_ME", name)
    text = _set_string_in_section(text, "identity", "display_name", display_name)
    if slack_active:
        text = _set_bool_in_section(text, "slack", "enabled", True)
        if slack_bot_token:
            text = _set_string_in_section(text, "slack", "bot_token", slack_bot_token)
        if slack_app_token:
            text = _set_string_in_section(text, "slack", "app_token", slack_app_token)
        if slack_channel_id:
            text = _set_string_in_section(text, "slack", "channel_id", slack_channel_id)
    if composio_active:
        text = _set_bool_in_section(text, "composio", "enabled", True)
        if composio_mcp_key:
            text = _set_string_in_section(
                text, "composio", "mcp_api_key", composio_mcp_key
            )

    agent_toml.write_text(text)
    try:
        os.chmod(agent_toml, 0o600)
    except OSError:
        pass

    _render_workspace_templates(project_root, dest)

    print(f"created: agents/{name}/agent.toml (mode 0600)")
    print(f"  display_name        {display_name}")
    if slack_active:
        print(f"  slack.enabled       true")
        if slack_bot_token:
            print(f"  slack.bot_token     {_redact(slack_bot_token)}")
        if slack_app_token:
            print(f"  slack.app_token     {_redact(slack_app_token)}")
        if slack_channel_id:
            print(f"  slack.channel_id    {slack_channel_id}")
    if composio_active:
        print(f"  composio.enabled    true")
        if composio_mcp_key:
            print(f"  composio.mcp_api_key {_redact(composio_mcp_key)}")
    print(f"\nNext:\n  zeroclawctl agents deploy --name {name}")
    if slack_active:
        print(f"  /invite @{display_name}  (in each Slack channel you want the bot in)")
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
    env_path = staged / "zeroclaw.env"
    # Open with mode 0600 atomically so the secrets file never exists at 0644.
    fd = os.open(str(env_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(env_text)
    (staged / "config.toml").write_text(config_text)

    rc = 1
    try:
        remote_state = f"{REMOTE_BASE}/states/{agent.state_dir}"
        # Idempotent dir setup. State dir owned by deploy user (writes happen
        # there over scp). .zeroclaw + workspace owned by container user 65534
        # — matches what upstream expects when resolving $HOME/.zeroclaw and
        # gives the container write access to brain.db / sessions / cron.
        _ssh(cfg, (
            f"sudo mkdir -p {remote_state}/.zeroclaw {remote_state}/workspace "
            f"{remote_state}/workspace/sessions {remote_state}/workspace/sessions/archive && "
            f"sudo chown {cfg.deploy_user}:{cfg.deploy_user} {remote_state} && "
            f"sudo chown -R 65534:65534 {remote_state}/.zeroclaw {remote_state}/workspace"
        ))

        # zeroclaw.env stays at state-dir level — it's a host-side env_file
        # for docker compose, never bind-mounted into the container.
        _scp_to(cfg, env_path, f"{remote_state}/zeroclaw.env")
        _ssh(cfg, f"chmod 0600 {remote_state}/zeroclaw.env")

        # config.toml goes into .zeroclaw/ (matches compose mount; container
        # needs to own it because the dir is 65534-owned). scp to /tmp first,
        # then sudo mv into the 65534-owned dir.
        _scp_to(cfg, staged / "config.toml", f"/tmp/zeroclawctl-{agent.name}-config.toml")
        _ssh(cfg, (
            f"sudo mv /tmp/zeroclawctl-{agent.name}-config.toml "
            f"{remote_state}/.zeroclaw/config.toml && "
            f"sudo chown 65534:65534 {remote_state}/.zeroclaw/config.toml && "
            f"sudo chmod 0640 {remote_state}/.zeroclaw/config.toml"
        ))

        # AGENTS.md lives inside the 65534-owned workspace — sudo for read + write.
        existing_agents = _ssh(
            cfg,
            f"sudo cat {remote_state}/workspace/AGENTS.md 2>/dev/null || true",
            capture=True,
        ).stdout
        policy = build_policy_block(
            approval_gates=agent.policy.require_approval_for,
            denied_domains=agent.policy.denied_domains,
        )
        (staged / "AGENTS.md").write_text(inject_policy_block(existing_agents or "", policy))
        _scp_to(cfg, staged / "AGENTS.md", f"/tmp/zeroclawctl-{agent.name}-AGENTS.md")
        _ssh(cfg, (
            f"sudo mv /tmp/zeroclawctl-{agent.name}-AGENTS.md "
            f"{remote_state}/workspace/AGENTS.md && "
            f"sudo chown 65534:65534 {remote_state}/workspace/AGENTS.md && "
            f"sudo chmod 0644 {remote_state}/workspace/AGENTS.md"
        ))

        if pull_image:
            _ssh(cfg, f"cd {REMOTE_BASE} && docker pull {agent.image or cfg.zeroclaw_image}")
        rc = _ssh(
            cfg,
            f"cd {REMOTE_BASE} && docker compose up -d --force-recreate {agent.name}",
        ).returncode
        return rc
    finally:
        # Never leave the rendered secrets file behind in .runtime-temp/.
        try:
            env_path.unlink()
        except FileNotFoundError:
            pass
        append_audit_line(
            cfg,
            actor=default_actor(),
            cmd="agents.deploy",
            agent=agent.name,
            image=agent.image or cfg.zeroclaw_image,
            result="ok" if rc == 0 else "fail",
        )


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
    rc = _ssh(cfg, command).returncode
    append_audit_line(
        cfg,
        actor=default_actor(),
        cmd="agents.remove",
        agent=name,
        image=None,
        result="ok" if rc == 0 else "fail",
    )
    return rc


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
    fetched = dest / ".fetched"
    fetched.mkdir(exist_ok=True)

    remote_state = f"{REMOTE_BASE}/states/{agent.state_dir}"

    # 1) Workspace markdowns (keep as the first scp — existing tests assert this).
    rc = subprocess.run(
        _scp_base(cfg) + [
            "-r",
            f"{cfg.deploy_user}@{cfg.server_host}:{remote_state}/workspace/*.md",
            str(dest / "workspace"),
        ],
        check=False,
    ).returncode
    if rc != 0:
        return rc

    # 2) Reference snapshots: config.toml + zeroclaw.env.
    remote_config = f"{cfg.deploy_user}@{cfg.server_host}:{remote_state}/config.toml"
    remote_env = f"{cfg.deploy_user}@{cfg.server_host}:{remote_state}/zeroclaw.env"
    rc = subprocess.run(
        _scp_base(cfg) + [remote_config, str(fetched / "config.toml")],
        check=False,
    ).returncode
    if rc != 0:
        return rc
    rc = subprocess.run(
        _scp_base(cfg) + [remote_env, str(fetched / "zeroclaw.env")],
        check=False,
    ).returncode
    if rc != 0:
        return rc

    # Lock the secrets snapshot down to 0600.
    env_snapshot = fetched / "zeroclaw.env"
    if env_snapshot.exists():
        os.chmod(env_snapshot, 0o600)

    # 3) Fetch timestamp.
    (fetched / "FETCH_TIMESTAMP").write_text(
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n"
    )

    # 4) Merge live values back into local agent.toml.
    try:
        _merge_fetched_into_agent_toml(
            agent_toml=dest / "agent.toml",
            fetched_config=fetched / "config.toml",
            fetched_env=fetched / "zeroclaw.env",
        )
    except FileNotFoundError:
        # Snapshot files might be missing in some edge cases; if so we still
        # consider the workspace fetch a partial success but skip merge.
        pass

    return 0


# ---------------------------------------------------------------------------
# TOML merge helpers (no external deps)
# ---------------------------------------------------------------------------


# Sections fully managed by zeroclawctl. When present in the existing
# agent.toml, we rewrite them from the merged tree on fetch. Anything outside
# these sections is preserved verbatim.
_MANAGED_SECTIONS = ("identity", "runtime", "llm", "slack", "composio", "exec", "policy")


def _parse_env_file(text: str) -> dict[str, str]:
    """Parse a KEY=VALUE env file. Ignores blanks and comments."""
    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip a single pair of surrounding quotes if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def _env_to_agent_overrides(env: dict[str, str]) -> dict[str, dict[str, object]]:
    """Inverse of lib.agent_env.build_agent_env: map env keys back to agent.toml fields."""
    overrides: dict[str, dict[str, object]] = {}
    provider = env.get("ZEROCLAW_PROVIDER")
    if provider:
        overrides.setdefault("llm", {})["provider"] = provider
    if "ZEROCLAW_MODEL" in env:
        overrides.setdefault("llm", {})["model"] = env["ZEROCLAW_MODEL"]
    if "ZEROCLAW_PROVIDER_TIMEOUT_SECS" in env:
        try:
            overrides.setdefault("llm", {})["timeout_secs"] = int(
                env["ZEROCLAW_PROVIDER_TIMEOUT_SECS"]
            )
        except ValueError:
            pass
    # api_key is provider-specific.
    if provider == "anthropic" and "ANTHROPIC_API_KEY" in env:
        overrides.setdefault("llm", {})["api_key"] = env["ANTHROPIC_API_KEY"]
    elif provider == "litellm" and "LITELLM_API_KEY" in env:
        overrides.setdefault("llm", {})["api_key"] = env["LITELLM_API_KEY"]
    else:
        # Fall back to whichever key is present (re-adoption of an orphaned server).
        if "ANTHROPIC_API_KEY" in env:
            overrides.setdefault("llm", {})["api_key"] = env["ANTHROPIC_API_KEY"]
        elif "LITELLM_API_KEY" in env:
            overrides.setdefault("llm", {})["api_key"] = env["LITELLM_API_KEY"]

    if "SLACK_BOT_TOKEN" in env:
        overrides.setdefault("slack", {})["bot_token"] = env["SLACK_BOT_TOKEN"]
    if "SLACK_APP_TOKEN" in env:
        overrides.setdefault("slack", {})["app_token"] = env["SLACK_APP_TOKEN"]
    if "SLACK_SIGNING_SECRET" in env:
        overrides.setdefault("slack", {})["signing_secret"] = env["SLACK_SIGNING_SECRET"]

    if "COMPOSIO_API_KEY" in env:
        overrides.setdefault("composio", {})["api_key"] = env["COMPOSIO_API_KEY"]

    return overrides


def _config_to_agent_overrides(remote_cfg: dict) -> dict[str, dict[str, object]]:
    """Pull whichever values templates/config.toml.j2 renders back into agent.toml shape."""
    overrides: dict[str, dict[str, object]] = {}

    identity = remote_cfg.get("identity") or {}
    if "display_name" in identity:
        overrides.setdefault("identity", {})["display_name"] = identity["display_name"]
    if "name" in identity:
        overrides.setdefault("identity", {})["name"] = identity["name"]

    llm = remote_cfg.get("llm") or {}
    for key in ("provider", "model", "timeout_secs"):
        if key in llm:
            overrides.setdefault("llm", {})[key] = llm[key]

    slack = remote_cfg.get("slack") or {}
    if "enabled" in slack:
        overrides.setdefault("slack", {})["enabled"] = bool(slack["enabled"])

    composio = remote_cfg.get("composio") or {}
    if "enabled" in composio:
        overrides.setdefault("composio", {})["enabled"] = bool(composio["enabled"])
    if "allowed_tools" in composio:
        overrides.setdefault("composio", {})["allowed_tools"] = list(
            composio["allowed_tools"]
        )

    policy = remote_cfg.get("policy") or {}
    if "require_approval_for" in policy:
        overrides.setdefault("policy", {})["require_approval_for"] = list(
            policy["require_approval_for"]
        )
    if "denied_domains" in policy:
        overrides.setdefault("policy", {})["denied_domains"] = list(
            policy["denied_domains"]
        )

    # exec.enabled does not appear directly in config.toml.j2 (it's used as a
    # render gate), but the server-side [security.exec] block hints at it.
    if "security" in remote_cfg and "exec" in remote_cfg["security"]:
        overrides.setdefault("exec", {})["enabled"] = True

    return overrides


def _format_toml_value(value: object) -> str:
    """Render a Python value as a TOML scalar/array literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        # Minimal escaping for double-quoted basic strings.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_toml_value(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML value type: {type(value).__name__}")


def _render_managed_section(name: str, body: dict[str, object]) -> str:
    """Emit a TOML section header + simple key=value lines."""
    out = [f"[{name}]"]
    for key, value in body.items():
        out.append(f"{key} = {_format_toml_value(value)}")
    return "\n".join(out) + "\n"


def _split_into_sections(text: str) -> list[tuple[str | None, str]]:
    """Split a TOML document into (section_name, block_text) chunks.

    The first chunk's section_name is None (preamble / comments before any
    header). Each subsequent chunk's block_text includes its own '[section]'
    header line and everything up to the next header. Order is preserved.
    """
    chunks: list[tuple[str | None, str]] = []
    current_name: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("[") and stripped.rstrip().endswith("]") and not stripped.startswith("[["):
            # New section header.
            if current_lines or current_name is not None:
                chunks.append((current_name, "".join(current_lines)))
            header = stripped.strip()[1:-1].strip()
            # We only track top-level sections; dotted names (e.g.
            # "security.exec") become their own preserved chunk.
            current_name = header
            current_lines = [line]
        else:
            current_lines.append(line)
    chunks.append((current_name, "".join(current_lines)))
    return chunks


def _merge_dicts(base: dict, override: dict) -> dict:
    """Shallow merge per top-level section: override wins on key clash."""
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for section, body in override.items():
        if isinstance(body, dict) and isinstance(out.get(section), dict):
            merged_section = dict(out[section])
            merged_section.update(body)
            out[section] = merged_section
        else:
            out[section] = body
    return out


def _merge_fetched_into_agent_toml(
    *,
    agent_toml: Path,
    fetched_config: Path,
    fetched_env: Path,
) -> None:
    existing_text = agent_toml.read_text() if agent_toml.exists() else ""
    existing_tree = tomllib.loads(existing_text) if existing_text else {}

    remote_cfg_tree = tomllib.loads(fetched_config.read_text())
    env_map = _parse_env_file(fetched_env.read_text())

    overrides = _config_to_agent_overrides(remote_cfg_tree)
    env_overrides = _env_to_agent_overrides(env_map)
    # env values (secrets, live provider) override config-derived values.
    for section, body in env_overrides.items():
        overrides.setdefault(section, {}).update(body)

    merged_tree = _merge_dicts(existing_tree, overrides)

    chunks = _split_into_sections(existing_text)
    seen_managed: set[str] = set()
    rendered: list[str] = []
    for section_name, block in chunks:
        if section_name is None:
            # preamble (comments) — preserve as-is
            rendered.append(block)
            continue
        top_level = section_name.split(".", 1)[0]
        if top_level in _MANAGED_SECTIONS and section_name == top_level:
            body = merged_tree.get(section_name, {})
            if isinstance(body, dict):
                rendered.append(_render_managed_section(section_name, body))
                seen_managed.add(section_name)
                continue
        # Unknown section (e.g. user's [notes], or dotted [security.exec]) —
        # preserve verbatim.
        rendered.append(block)

    # If the merged tree introduces a managed section that wasn't present
    # in the existing file, append it.
    for section in _MANAGED_SECTIONS:
        if section in merged_tree and section not in seen_managed:
            body = merged_tree[section]
            if isinstance(body, dict) and body:
                if rendered and not rendered[-1].endswith("\n"):
                    rendered.append("\n")
                rendered.append("\n" + _render_managed_section(section, body))

    new_text = "".join(rendered)
    # Ensure trailing newline.
    if not new_text.endswith("\n"):
        new_text += "\n"
    agent_toml.write_text(new_text)


def cmd_restore(name: str, ts: str | None = None, project_root: Path | None = None) -> int:
    cfg = load_config(project_root)
    archive = f".archive/{name}-{ts}" if ts else f"$(ls -dt .archive/{name}-* | head -1)"
    command = f"cd {REMOTE_BASE} && mv {archive} states/{name} && docker compose up -d {name}"
    rc = _ssh(cfg, command).returncode
    append_audit_line(
        cfg,
        actor=default_actor(),
        cmd="agents.restore",
        agent=name,
        image=None,
        result="ok" if rc == 0 else "fail",
    )
    return rc

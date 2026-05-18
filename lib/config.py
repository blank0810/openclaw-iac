from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from dotenv import dotenv_values


VALID_LLM_PROVIDERS = ("anthropic", "litellm")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    model: str
    api_key: str
    timeout_secs: int

    def __post_init__(self) -> None:
        if self.provider not in VALID_LLM_PROVIDERS:
            raise ValueError(
                f"llm.provider must be one of {VALID_LLM_PROVIDERS}, got {self.provider!r}"
            )


@dataclass(frozen=True)
class SlackConfig:
    enabled: bool
    bot_token: str
    app_token: str
    signing_secret: str
    channel_id: str
    allowed_users: tuple[str, ...]
    mention_only: bool
    thread_replies: bool
    use_markdown_blocks: bool
    stream_drafts: bool

    def __post_init__(self) -> None:
        if self.enabled and not self.bot_token:
            raise ValueError("slack.bot_token is required when slack.enabled = true")
        if self.enabled and not self.app_token:
            raise ValueError("slack.app_token is required when slack.enabled = true")


@dataclass(frozen=True)
class ComposioConfig:
    enabled: bool
    api_key: str
    allowed_tools: tuple[str, ...]
    mcp_url: str
    mcp_api_key: str
    mcp_transport: str
    mcp_auth_header: str

    def __post_init__(self) -> None:
        if self.enabled and self.mcp_url and not self.mcp_api_key:
            raise ValueError(
                "composio.mcp_api_key is required when composio.mcp_url is set"
            )
        if self.enabled and not self.mcp_url and not self.api_key:
            raise ValueError(
                "either composio.mcp_url+mcp_api_key (MCP path) or composio.api_key "
                "(native path) must be set when composio.enabled = true"
            )


@dataclass(frozen=True)
class AutonomyConfig:
    level: str
    auto_approve: tuple[str, ...]


@dataclass(frozen=True)
class PolicyConfig:
    require_approval_for: tuple[str, ...]
    denied_domains: tuple[str, ...]


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    display_name: str
    enabled: bool
    state_dir: str
    image: str | None
    host_port: int
    llm: LlmConfig
    slack: SlackConfig
    composio: ComposioConfig
    autonomy: AutonomyConfig
    exec_enabled: bool
    policy: PolicyConfig
    workspace_dir: Path
    agent_toml_path: Path

    def __post_init__(self) -> None:
        if not SLUG_PATTERN.match(self.name):
            raise ValueError(
                f"agent slug {self.name!r} must match {SLUG_PATTERN.pattern} "
                "(lowercase letters, digits, hyphen; must start with letter or digit)"
            )
        if self.host_port < 0 or self.host_port > 65535:
            raise ValueError(f"host_port must be 0..65535, got {self.host_port}")


@dataclass(frozen=True)
class DeploymentConfig:
    server_host: str
    deploy_user: str
    ssh_port: int
    deploy_ssh_key_path: Path
    root_ssh_key_path: Path
    zeroclaw_image: str
    agents: tuple[AgentDefinition, ...]
    effective_tcp_ports: tuple[int, ...]


DEFAULT_AUTO_APPROVE: tuple[str, ...] = (
    "file_read",
    "memory_recall",
    "memory_store",
    "calculator",
    "glob_search",
    "content_search",
    "tool_search",
)


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge `override` over `base`. Nested dicts recurse; everything else
    (lists, strings, bools, ints) is replaced wholesale. Explicit empty
    strings in override count as overrides, not absences."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_defaults(project_root: Path) -> dict:
    """Read agents/_defaults.toml if present. Empty dict if missing."""
    defaults_path = project_root / "agents" / "_defaults.toml"
    if not defaults_path.exists():
        return {}
    return tomllib.loads(defaults_path.read_text())


def _parse_agent_toml(path: Path, defaults: dict | None = None) -> AgentDefinition:
    agent_raw = tomllib.loads(path.read_text())
    raw = _deep_merge(defaults or {}, agent_raw)
    identity = raw.get("identity", {})
    runtime = raw.get("runtime", {})
    llm = raw.get("llm", {})
    slack = raw.get("slack", {})
    composio = raw.get("composio", {})
    autonomy = raw.get("autonomy", {})
    exec_ = raw.get("exec", {})
    policy = raw.get("policy", {})
    name = identity["name"]
    image = runtime.get("image") or None
    return AgentDefinition(
        name=name,
        display_name=identity.get("display_name", name),
        enabled=bool(identity.get("enabled", True)),
        state_dir=identity.get("state_dir", name),
        image=image,
        host_port=int(runtime.get("host_port", 0)),
        llm=LlmConfig(
            provider=llm.get("provider", "anthropic"),
            model=llm["model"],
            api_key=llm.get("api_key", ""),
            timeout_secs=int(llm.get("timeout_secs", 60)),
        ),
        slack=SlackConfig(
            enabled=bool(slack.get("enabled", False)),
            bot_token=slack.get("bot_token", ""),
            app_token=slack.get("app_token", ""),
            signing_secret=slack.get("signing_secret", ""),
            channel_id=slack.get("channel_id", ""),
            allowed_users=tuple(slack.get("allowed_users", ("*",))),
            mention_only=bool(slack.get("mention_only", True)),
            thread_replies=bool(slack.get("thread_replies", True)),
            use_markdown_blocks=bool(slack.get("use_markdown_blocks", True)),
            stream_drafts=bool(slack.get("stream_drafts", False)),
        ),
        composio=ComposioConfig(
            enabled=bool(composio.get("enabled", False)),
            api_key=composio.get("api_key", ""),
            allowed_tools=tuple(composio.get("allowed_tools", ())),
            mcp_url=composio.get("mcp_url", ""),
            mcp_api_key=composio.get("mcp_api_key", ""),
            mcp_transport=composio.get("mcp_transport", "http"),
            mcp_auth_header=composio.get("mcp_auth_header", "x-consumer-api-key"),
        ),
        autonomy=AutonomyConfig(
            level=autonomy.get("level", "supervised"),
            auto_approve=tuple(autonomy.get("auto_approve", DEFAULT_AUTO_APPROVE)),
        ),
        exec_enabled=bool(exec_.get("enabled", False)),
        policy=PolicyConfig(
            require_approval_for=tuple(policy.get("require_approval_for", ())),
            denied_domains=tuple(policy.get("denied_domains", ())),
        ),
        workspace_dir=path.parent / "workspace",
        agent_toml_path=path,
    )


def load_config(project_root: Path | None = None) -> DeploymentConfig:
    project_root = Path(project_root) if project_root else Path.cwd()
    env = dotenv_values(project_root / ".env")
    server_host = str(env["SERVER_HOST"])
    deploy_user = str(env.get("DEPLOY_USER", "overlord101"))
    ssh_port = int(str(env.get("SSH_PORT", "2222")))
    deploy_ssh_key_path = Path(str(env["DEPLOY_SSH_KEY_PATH"]))
    root_ssh_key_path = Path(str(env["ROOT_SSH_KEY_PATH"]))
    zeroclaw_image = str(env["ZEROCLAW_IMAGE"])

    defaults = _load_defaults(project_root)
    agents_dir = project_root / "agents"
    agent_list: list[AgentDefinition] = []
    if agents_dir.is_dir():
        for child in sorted(agents_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("_"):
                continue
            toml_path = child / "agent.toml"
            if not toml_path.exists():
                continue
            agent_list.append(_parse_agent_toml(toml_path, defaults))

    _validate_uniqueness(agent_list)

    effective_ports = {ssh_port}
    for agent in agent_list:
        if agent.enabled and agent.host_port:
            effective_ports.add(agent.host_port)

    return DeploymentConfig(
        server_host=server_host,
        deploy_user=deploy_user,
        ssh_port=ssh_port,
        deploy_ssh_key_path=deploy_ssh_key_path,
        root_ssh_key_path=root_ssh_key_path,
        zeroclaw_image=zeroclaw_image,
        agents=tuple(agent_list),
        effective_tcp_ports=tuple(sorted(effective_ports)),
    )


def _validate_uniqueness(agents: list[AgentDefinition]) -> None:
    seen_names: dict[str, str] = {}
    seen_state_dirs: dict[str, str] = {}
    seen_ports: dict[int, str] = {}
    for agent in agents:
        if agent.name in seen_names:
            raise ValueError(f"duplicate agent name {agent.name!r}")
        seen_names[agent.name] = agent.name
        if agent.state_dir in seen_state_dirs:
            raise ValueError(
                f"duplicate state_dir {agent.state_dir!r} "
                f"between {seen_state_dirs[agent.state_dir]} and {agent.name}"
            )
        seen_state_dirs[agent.state_dir] = agent.name
        if agent.enabled and agent.host_port:
            if agent.host_port in seen_ports:
                raise ValueError(
                    f"duplicate host_port {agent.host_port} "
                    f"between {seen_ports[agent.host_port]} and {agent.name}"
                )
            seen_ports[agent.host_port] = agent.name

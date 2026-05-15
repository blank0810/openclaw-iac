from __future__ import annotations

from pathlib import Path

import pytest

from lib.config import AgentDefinition, DeploymentConfig, LlmConfig, load_config
from lib.config import ComposioConfig, PolicyConfig, SlackConfig


def test_llm_config_accepts_anthropic_provider():
    cfg = LlmConfig(
        provider="anthropic",
        model="claude-sonnet-4-5",
        api_key="sk-ant-x",
        timeout_secs=60,
    )
    assert cfg.provider == "anthropic"


def test_llm_config_accepts_litellm_provider():
    cfg = LlmConfig(provider="litellm", model="gpt-4o", api_key="sk-x", timeout_secs=60)
    assert cfg.provider == "litellm"


def test_llm_config_rejects_unknown_provider():
    with pytest.raises(ValueError, match="provider"):
        LlmConfig(provider="bogus", model="m", api_key="k", timeout_secs=60)


def test_llm_config_is_frozen():
    cfg = LlmConfig(provider="anthropic", model="m", api_key="k", timeout_secs=60)
    with pytest.raises((AttributeError, Exception)):
        cfg.provider = "litellm"  # type: ignore[misc]


def test_slack_config_disabled_allows_empty_tokens():
    cfg = SlackConfig(enabled=False, bot_token="", app_token="", signing_secret="")
    assert cfg.enabled is False


def test_slack_config_enabled_requires_bot_token():
    with pytest.raises(ValueError, match="bot_token"):
        SlackConfig(enabled=True, bot_token="", app_token="xapp-x", signing_secret="s")


def test_composio_config_disabled_allows_empty_key():
    cfg = ComposioConfig(enabled=False, api_key="", allowed_tools=())
    assert cfg.enabled is False


def test_composio_config_enabled_requires_api_key():
    with pytest.raises(ValueError, match="api_key"):
        ComposioConfig(enabled=True, api_key="", allowed_tools=())


def test_composio_allowed_tools_is_tuple():
    cfg = ComposioConfig(enabled=True, api_key="x", allowed_tools=("gmail.send",))
    assert isinstance(cfg.allowed_tools, tuple)


def test_policy_config_defaults_empty():
    cfg = PolicyConfig(require_approval_for=(), denied_domains=())
    assert cfg.require_approval_for == ()


def _make_agent(**overrides):
    defaults = dict(
        name="acme",
        display_name="Acme",
        enabled=True,
        state_dir="acme",
        image=None,
        host_port=0,
        llm=LlmConfig(
            provider="anthropic",
            model="claude-sonnet-4-5",
            api_key="sk-ant-x",
            timeout_secs=60,
        ),
        slack=SlackConfig(enabled=False, bot_token="", app_token="", signing_secret=""),
        composio=ComposioConfig(enabled=False, api_key="", allowed_tools=()),
        exec_enabled=False,
        policy=PolicyConfig(require_approval_for=(), denied_domains=()),
        workspace_dir=Path("/tmp/agents/acme/workspace"),
        agent_toml_path=Path("/tmp/agents/acme/agent.toml"),
    )
    defaults.update(overrides)
    return AgentDefinition(**defaults)


def test_agent_definition_accepts_valid_slug():
    a = _make_agent(name="acme-corp-1")
    assert a.name == "acme-corp-1"


def test_agent_definition_rejects_invalid_slug_uppercase():
    with pytest.raises(ValueError, match="slug"):
        _make_agent(name="AcmeCorp")


def test_agent_definition_rejects_invalid_slug_special_chars():
    with pytest.raises(ValueError, match="slug"):
        _make_agent(name="acme_corp")


def test_agent_definition_rejects_negative_host_port():
    with pytest.raises(ValueError, match="host_port"):
        _make_agent(host_port=-1)


def test_agent_definition_rejects_port_above_65535():
    with pytest.raises(ValueError, match="host_port"):
        _make_agent(host_port=70000)


def test_agent_definition_zero_port_means_no_expose():
    a = _make_agent(host_port=0)
    assert a.host_port == 0


def _write_env(tmp_path: Path, **overrides) -> Path:
    defaults = dict(
        SERVER_HOST="1.2.3.4",
        DEPLOY_USER="overlord101",
        SSH_PORT="2222",
        DEPLOY_SSH_KEY_PATH=str(tmp_path / "fake-deploy.pem"),
        ROOT_SSH_KEY_PATH=str(tmp_path / "fake-root.pem"),
        ZEROCLAW_IMAGE="ghcr.io/example/zeroclaw:1.0",
    )
    defaults.update(overrides)
    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}={v}" for k, v in defaults.items()))
    (tmp_path / "fake-deploy.pem").write_text("")
    (tmp_path / "fake-root.pem").write_text("")
    return env


def _write_agent(tmp_path: Path, slug: str, **overrides) -> Path:
    agents_dir = tmp_path / "agents" / slug
    (agents_dir / "workspace").mkdir(parents=True)
    body_overrides = overrides.copy()
    enabled = body_overrides.pop("enabled", True)
    state_dir = body_overrides.pop("state_dir", slug)
    host_port = body_overrides.pop("host_port", 0)
    body = f"""
[identity]
name = "{slug}"
display_name = "{slug.title()}"
enabled = {str(enabled).lower()}
state_dir = "{state_dir}"

[runtime]
host_port = {host_port}

[llm]
provider = "anthropic"
model = "claude-sonnet-4-5"
api_key = "sk-ant-{slug}"
timeout_secs = 60

[slack]
enabled = false
bot_token = ""
app_token = ""
signing_secret = ""

[composio]
enabled = false
api_key = ""
allowed_tools = []

[exec]
enabled = false

[policy]
require_approval_for = []
denied_domains = []
"""
    (agents_dir / "agent.toml").write_text(body)
    return agents_dir


def test_load_config_with_no_agents(tmp_path, isolated_env):
    _write_env(tmp_path)
    cfg = load_config(project_root=tmp_path)
    assert isinstance(cfg, DeploymentConfig)
    assert cfg.server_host == "1.2.3.4"
    assert cfg.agents == ()


def test_load_config_reads_one_agent(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    cfg = load_config(project_root=tmp_path)
    assert len(cfg.agents) == 1
    assert cfg.agents[0].name == "acme"


def test_load_config_skips_underscore_prefixed_dirs(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    (tmp_path / "agents" / "_template").mkdir()
    (tmp_path / "agents" / "_template" / "agent.toml").write_text("# template")
    cfg = load_config(project_root=tmp_path)
    assert [a.name for a in cfg.agents] == ["acme"]


def test_load_config_rejects_duplicate_state_dirs(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme", state_dir="shared")
    _write_agent(tmp_path, "globex", state_dir="shared")
    with pytest.raises(ValueError, match="state_dir"):
        load_config(project_root=tmp_path)


def test_load_config_rejects_duplicate_nonzero_host_ports(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme", host_port=18791)
    _write_agent(tmp_path, "globex", host_port=18791)
    with pytest.raises(ValueError, match="host_port"):
        load_config(project_root=tmp_path)


def test_load_config_allows_multiple_zero_ports(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme", host_port=0)
    _write_agent(tmp_path, "globex", host_port=0)
    cfg = load_config(project_root=tmp_path)
    assert len(cfg.agents) == 2


def test_load_config_effective_tcp_ports_includes_ssh_and_agents(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme", host_port=18791)
    _write_agent(tmp_path, "globex", host_port=18792)
    cfg = load_config(project_root=tmp_path)
    assert 2222 in cfg.effective_tcp_ports
    assert 18791 in cfg.effective_tcp_ports
    assert 18792 in cfg.effective_tcp_ports

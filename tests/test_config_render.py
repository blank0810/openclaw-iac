from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader

from tests.test_agent_env import _agent, _composio, _slack


@pytest.fixture
def env():
    return Environment(loader=FileSystemLoader("templates"))


def test_config_toml_renders_provider_metadata(env):
    out = env.get_template("config.toml.j2").render(
        agent=_agent(), exec_deny_patterns=[]
    )
    assert 'default_provider = "anthropic"' in out
    assert 'default_model = "claude-sonnet-4-5"' in out
    assert "schema_version = 2" in out


def test_config_toml_renders_gateway_block(env):
    out = env.get_template("config.toml.j2").render(
        agent=_agent(), exec_deny_patterns=[]
    )
    assert "[gateway]" in out
    assert "port = 42617" in out


def test_config_toml_renders_memory_block(env):
    out = env.get_template("config.toml.j2").render(
        agent=_agent(), exec_deny_patterns=[]
    )
    assert "[memory]" in out
    assert 'backend = "sqlite"' in out


def test_config_toml_renders_autonomy_block(env):
    out = env.get_template("config.toml.j2").render(
        agent=_agent(), exec_deny_patterns=[]
    )
    assert "[autonomy]" in out
    assert 'level = "supervised"' in out
    assert '"memory_recall"' in out


def test_config_toml_omits_slack_block_when_disabled(env):
    out = env.get_template("config.toml.j2").render(
        agent=_agent(), exec_deny_patterns=[]
    )
    assert "[channels_config.slack]" not in out


def test_config_toml_renders_slack_scoping_when_enabled(env):
    agent = _agent(
        slack=_slack(
            enabled=True,
            bot_token="xoxb-X",
            app_token="xapp-X",
            allowed_users=("U1ABC",),
            mention_only=True,
            thread_replies=False,
        )
    )
    out = env.get_template("config.toml.j2").render(
        agent=agent, exec_deny_patterns=[]
    )
    assert "[channels_config.slack]" in out
    assert 'bot_token = "xoxb-X"' in out
    assert 'app_token = "xapp-X"' in out
    assert '"U1ABC"' in out
    assert "mention_only = true" in out
    assert "thread_replies = false" in out


def test_config_toml_renders_composio_mcp_when_url_set(env):
    agent = _agent(
        composio=_composio(
            enabled=True,
            mcp_url="https://connect.composio.dev/mcp",
            mcp_api_key="ck_TEST",
        )
    )
    out = env.get_template("config.toml.j2").render(
        agent=agent, exec_deny_patterns=[]
    )
    assert "[mcp]" in out
    assert "[[mcp.servers]]" in out
    assert 'url = "https://connect.composio.dev/mcp"' in out
    assert "ck_TEST" in out
    assert '"x-consumer-api-key"' in out
    # Native [composio] block must NOT be rendered when MCP path is used
    assert "[composio]" not in out


def test_config_toml_renders_native_composio_when_no_mcp_url(env):
    agent = _agent(
        composio=_composio(enabled=True, api_key="ck_NATIVE"),
    )
    out = env.get_template("config.toml.j2").render(
        agent=agent, exec_deny_patterns=[]
    )
    assert "[composio]" in out
    assert 'api_key = "ck_NATIVE"' in out
    assert "[mcp]" not in out


def test_config_toml_renders_exec_deny_when_enabled(env):
    agent = _agent(exec_enabled=True)
    out = env.get_template("config.toml.j2").render(
        agent=agent, exec_deny_patterns=["env", "printenv"]
    )
    assert "[security.exec]" in out
    assert '"env"' in out


def test_config_toml_omits_exec_section_when_disabled(env):
    out = env.get_template("config.toml.j2").render(
        agent=_agent(), exec_deny_patterns=[]
    )
    assert "[security.exec]" not in out

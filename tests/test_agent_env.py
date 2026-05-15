from __future__ import annotations

from pathlib import Path

from lib.config import (
    AgentDefinition,
    ComposioConfig,
    LlmConfig,
    PolicyConfig,
    SlackConfig,
)
from lib.agent_env import build_agent_env


def _agent(**overrides):
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
            api_key="sk-ant-SECRET",
            timeout_secs=60,
        ),
        slack=SlackConfig(enabled=False, bot_token="", app_token="", signing_secret=""),
        composio=ComposioConfig(enabled=False, api_key="", allowed_tools=()),
        exec_enabled=False,
        policy=PolicyConfig(require_approval_for=(), denied_domains=()),
        workspace_dir=Path("/tmp/x"),
        agent_toml_path=Path("/tmp/x.toml"),
    )
    defaults.update(overrides)
    return AgentDefinition(**defaults)


def test_anthropic_provider_sets_anthropic_api_key():
    env = build_agent_env(_agent())
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-SECRET"
    assert "LITELLM_API_KEY" not in env


def test_litellm_provider_sets_litellm_api_key():
    agent = _agent(
        llm=LlmConfig(
            provider="litellm",
            model="gpt-4o",
            api_key="sk-litellm-X",
            timeout_secs=60,
        )
    )
    env = build_agent_env(agent)
    assert env["LITELLM_API_KEY"] == "sk-litellm-X"
    assert "ANTHROPIC_API_KEY" not in env


def test_slack_disabled_omits_slack_tokens():
    env = build_agent_env(_agent())
    assert "SLACK_BOT_TOKEN" not in env


def test_slack_enabled_includes_all_slack_tokens():
    agent = _agent(
        slack=SlackConfig(
            enabled=True,
            bot_token="xoxb-X",
            app_token="xapp-X",
            signing_secret="sec",
        )
    )
    env = build_agent_env(agent)
    assert env["SLACK_BOT_TOKEN"] == "xoxb-X"
    assert env["SLACK_APP_TOKEN"] == "xapp-X"
    assert env["SLACK_SIGNING_SECRET"] == "sec"


def test_composio_disabled_omits_key():
    env = build_agent_env(_agent())
    assert "COMPOSIO_API_KEY" not in env


def test_composio_enabled_includes_key():
    agent = _agent(
        composio=ComposioConfig(
            enabled=True,
            api_key="comp-X",
            allowed_tools=("gmail.send",),
        )
    )
    env = build_agent_env(agent)
    assert env["COMPOSIO_API_KEY"] == "comp-X"


def test_provider_metadata_always_present():
    env = build_agent_env(_agent())
    assert env["ZEROCLAW_PROVIDER"] == "anthropic"
    assert env["ZEROCLAW_MODEL"] == "claude-sonnet-4-5"
    assert env["ZEROCLAW_WORKSPACE"] == "/zeroclaw/workspace"

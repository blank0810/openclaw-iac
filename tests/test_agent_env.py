from __future__ import annotations

from pathlib import Path

from lib.config import (
    AgentDefinition,
    AutonomyConfig,
    ComposioConfig,
    DEFAULT_AUTO_APPROVE,
    LlmConfig,
    PolicyConfig,
    SlackConfig,
)
from lib.agent_env import build_agent_env


def _slack(**overrides):
    defaults = dict(
        enabled=False,
        bot_token="",
        app_token="",
        signing_secret="",
        channel_id="",
        allowed_users=("*",),
        mention_only=True,
        thread_replies=True,
        use_markdown_blocks=True,
        stream_drafts=False,
    )
    defaults.update(overrides)
    return SlackConfig(**defaults)


def _composio(**overrides):
    defaults = dict(
        enabled=False,
        api_key="",
        allowed_tools=(),
        mcp_url="",
        mcp_api_key="",
        mcp_transport="http",
        mcp_auth_header="x-consumer-api-key",
    )
    defaults.update(overrides)
    return ComposioConfig(**defaults)


def _autonomy(**overrides):
    defaults = dict(level="supervised", auto_approve=DEFAULT_AUTO_APPROVE)
    defaults.update(overrides)
    return AutonomyConfig(**defaults)


def _agent(**overrides):
    defaults = dict(
        name="acme",
        display_name="Acme",
        user_id="u_test",
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
        slack=_slack(),
        composio=_composio(),
        autonomy=_autonomy(),
        exec_enabled=False,
        policy=PolicyConfig(require_approval_for=(), denied_domains=()),
        workspace_dir=Path("/tmp/x"),
        agent_toml_path=Path("/tmp/x.toml"),
    )
    defaults.update(overrides)
    return AgentDefinition(**defaults)


def test_anthropic_provider_sets_zeroclaw_api_key():
    env = build_agent_env(_agent())
    assert env["ZEROCLAW_API_KEY"] == "sk-ant-SECRET"


def test_litellm_provider_sets_zeroclaw_api_key():
    agent = _agent(
        llm=LlmConfig(
            provider="litellm",
            model="gpt-4o",
            api_key="sk-litellm-X",
            timeout_secs=60,
        )
    )
    env = build_agent_env(agent)
    assert env["ZEROCLAW_API_KEY"] == "sk-litellm-X"


def test_empty_api_key_omits_zeroclaw_api_key():
    agent = _agent(
        llm=LlmConfig(
            provider="anthropic",
            model="claude-sonnet-4-5",
            api_key="",
            timeout_secs=60,
        )
    )
    env = build_agent_env(agent)
    assert "ZEROCLAW_API_KEY" not in env


def test_slack_tokens_never_in_env():
    """Upstream ZeroClaw doesn't read SLACK_* from env; they live in config.toml.
    See apps/zeroclaw/upstream/crates/zeroclaw-config/src/schema.rs apply_env_overrides."""
    agent = _agent(
        slack=_slack(
            enabled=True,
            bot_token="xoxb-X",
            app_token="xapp-X",
            signing_secret="sec",
        )
    )
    env = build_agent_env(agent)
    assert "SLACK_BOT_TOKEN" not in env
    assert "SLACK_APP_TOKEN" not in env
    assert "SLACK_SIGNING_SECRET" not in env


def test_composio_key_never_in_env():
    """Upstream ZeroClaw doesn't read COMPOSIO_API_KEY from env; it lives in config.toml."""
    agent = _agent(
        composio=_composio(
            enabled=True,
            api_key="comp-X",
            allowed_tools=("gmail.send",),
        )
    )
    env = build_agent_env(agent)
    assert "COMPOSIO_API_KEY" not in env


def test_provider_metadata_always_present():
    env = build_agent_env(_agent())
    assert env["ZEROCLAW_PROVIDER"] == "anthropic"
    assert env["ZEROCLAW_MODEL"] == "claude-sonnet-4-5"
    # /zeroclaw-data/workspace matches the compose mount target.
    # /zeroclaw/workspace would land on the read-only container root and crash.
    assert env["ZEROCLAW_WORKSPACE"] == "/zeroclaw-data/workspace"
    assert env["ZEROCLAW_PROVIDER_TIMEOUT_SECS"] == "60"

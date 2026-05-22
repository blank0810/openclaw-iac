"""Secrets placement: enforce the real model documented in SECURITY.md §5.

Upstream ZeroClaw does not read Composio/Slack tokens from environment
variables (see apps/zeroclaw/upstream/crates/zeroclaw-config/src/schema.rs
apply_env_overrides). Those tokens MUST be rendered into config.toml so the
container can read them at startup. Only the LLM provider key flows through
env via ZEROCLAW_API_KEY.

This test enforces:
  - LLM provider key NEVER appears in rendered config.toml (env-only).
  - Slack + Composio tokens ARE rendered into config.toml when their
    respective sections are enabled (it's the only path).
  - The env dict carries the LLM key under ZEROCLAW_API_KEY, and does
    NOT carry SLACK_* or COMPOSIO_API_KEY.
"""
from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader

from lib.config import LlmConfig
from lib.agent_env import build_agent_env
from tests.test_agent_env import _agent, _composio, _slack


@pytest.fixture
def env():
    return Environment(loader=FileSystemLoader("templates"))


def _all_secrets_agent():
    return _agent(
        llm=LlmConfig(
            provider="anthropic",
            model="claude-sonnet-4-5",
            api_key="sk-ant-LEAK",
            timeout_secs=60,
        ),
        slack=_slack(
            enabled=True,
            bot_token="xoxb-LEAK",
            app_token="xapp-LEAK",
            signing_secret="signing-LEAK",
        ),
        composio=_composio(
            enabled=True,
            mcp_url="https://connect.composio.dev/mcp",
            mcp_api_key="ck_LEAK",
        ),
    )


def test_llm_key_never_in_config_toml(env):
    """Anthropic / LLM provider key is env-only. If it ever appears in
    rendered config.toml that's a security regression."""
    out = env.get_template("config.toml.j2").render(
        agent=_all_secrets_agent(), exec_deny_patterns=[]
    )
    assert "sk-ant-LEAK" not in out, (
        "SECURITY REGRESSION: LLM API key leaked into config.toml output"
    )


def test_slack_tokens_rendered_into_config_toml(env):
    """Slack tokens have no env-read path upstream; they're rendered here."""
    out = env.get_template("config.toml.j2").render(
        agent=_all_secrets_agent(), exec_deny_patterns=[]
    )
    assert "xoxb-LEAK" in out
    assert "xapp-LEAK" in out


def test_composio_mcp_key_rendered_into_config_toml(env):
    """Composio MCP x-consumer-api-key has no env-read path upstream."""
    out = env.get_template("config.toml.j2").render(
        agent=_all_secrets_agent(), exec_deny_patterns=[]
    )
    assert "ck_LEAK" in out


def test_env_dict_carries_llm_key_only():
    env_dict = build_agent_env(_all_secrets_agent())
    assert env_dict["ZEROCLAW_API_KEY"] == "sk-ant-LEAK"
    assert "SLACK_BOT_TOKEN" not in env_dict
    assert "SLACK_APP_TOKEN" not in env_dict
    assert "SLACK_SIGNING_SECRET" not in env_dict
    assert "COMPOSIO_API_KEY" not in env_dict

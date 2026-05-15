from __future__ import annotations

from pathlib import Path

from lib.config import (
    ComposioConfig,
    LlmConfig,
    PolicyConfig,
    SlackConfig,
    TenantDefinition,
)
from lib.tenant_env import build_tenant_env


def _tenant(**overrides):
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
        tenant_toml_path=Path("/tmp/x.toml"),
    )
    defaults.update(overrides)
    return TenantDefinition(**defaults)


def test_anthropic_provider_sets_anthropic_api_key():
    env = build_tenant_env(_tenant())
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-SECRET"
    assert "LITELLM_API_KEY" not in env


def test_litellm_provider_sets_litellm_api_key():
    tenant = _tenant(
        llm=LlmConfig(
            provider="litellm",
            model="gpt-4o",
            api_key="sk-litellm-X",
            timeout_secs=60,
        )
    )
    env = build_tenant_env(tenant)
    assert env["LITELLM_API_KEY"] == "sk-litellm-X"
    assert "ANTHROPIC_API_KEY" not in env


def test_slack_disabled_omits_slack_tokens():
    env = build_tenant_env(_tenant())
    assert "SLACK_BOT_TOKEN" not in env


def test_slack_enabled_includes_all_slack_tokens():
    tenant = _tenant(
        slack=SlackConfig(
            enabled=True,
            bot_token="xoxb-X",
            app_token="xapp-X",
            signing_secret="sec",
        )
    )
    env = build_tenant_env(tenant)
    assert env["SLACK_BOT_TOKEN"] == "xoxb-X"
    assert env["SLACK_APP_TOKEN"] == "xapp-X"
    assert env["SLACK_SIGNING_SECRET"] == "sec"


def test_composio_disabled_omits_key():
    env = build_tenant_env(_tenant())
    assert "COMPOSIO_API_KEY" not in env


def test_composio_enabled_includes_key():
    tenant = _tenant(
        composio=ComposioConfig(
            enabled=True,
            api_key="comp-X",
            allowed_tools=("gmail.send",),
        )
    )
    env = build_tenant_env(tenant)
    assert env["COMPOSIO_API_KEY"] == "comp-X"


def test_provider_metadata_always_present():
    env = build_tenant_env(_tenant())
    assert env["ZEROCLAW_PROVIDER"] == "anthropic"
    assert env["ZEROCLAW_MODEL"] == "claude-sonnet-4-5"
    assert env["ZEROCLAW_WORKSPACE"] == "/zeroclaw/workspace"

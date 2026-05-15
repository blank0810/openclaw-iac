"""Critical security test: assert no secrets leak into config.toml output."""
from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader

from lib.config import ComposioConfig, LlmConfig, SlackConfig
from lib.tenant_env import build_tenant_env
from tests.test_tenant_env import _tenant


@pytest.fixture
def env():
    return Environment(loader=FileSystemLoader("templates"))


def _all_secrets_tenant():
    return _tenant(
        llm=LlmConfig(
            provider="anthropic",
            model="claude-sonnet-4-5",
            api_key="sk-ant-LEAK",
            timeout_secs=60,
        ),
        slack=SlackConfig(
            enabled=True,
            bot_token="xoxb-LEAK",
            app_token="xapp-LEAK",
            signing_secret="signing-LEAK",
        ),
        composio=ComposioConfig(
            enabled=True,
            api_key="comp-LEAK",
            allowed_tools=("gmail.send",),
        ),
    )


def test_no_api_key_in_config_toml_output(env):
    out = env.get_template("config.toml.j2").render(
        tenant=_all_secrets_tenant(), exec_deny_patterns=[]
    )
    for needle in (
        "sk-ant-LEAK",
        "xoxb-LEAK",
        "xapp-LEAK",
        "signing-LEAK",
        "comp-LEAK",
    ):
        assert needle not in out, (
            f"SECURITY REGRESSION: {needle} leaked into config.toml output"
        )


def test_secrets_present_in_env_dict():
    env_dict = build_tenant_env(_all_secrets_tenant())
    assert env_dict["ANTHROPIC_API_KEY"] == "sk-ant-LEAK"
    assert env_dict["SLACK_BOT_TOKEN"] == "xoxb-LEAK"
    assert env_dict["COMPOSIO_API_KEY"] == "comp-LEAK"

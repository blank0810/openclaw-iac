from __future__ import annotations

import pytest

from lib.config import LlmConfig
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

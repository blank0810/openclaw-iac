from __future__ import annotations

import pytest

from lib.config import LlmConfig


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

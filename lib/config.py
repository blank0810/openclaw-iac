from __future__ import annotations

from dataclasses import dataclass


VALID_LLM_PROVIDERS = ("anthropic", "litellm")


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

    def __post_init__(self) -> None:
        if self.enabled and not self.api_key:
            raise ValueError("composio.api_key is required when composio.enabled = true")


@dataclass(frozen=True)
class PolicyConfig:
    require_approval_for: tuple[str, ...]
    denied_domains: tuple[str, ...]

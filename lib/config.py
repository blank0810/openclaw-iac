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

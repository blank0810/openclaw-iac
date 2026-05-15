from __future__ import annotations

from lib.config import AgentDefinition


def build_agent_env(agent: AgentDefinition) -> dict[str, str]:
    env: dict[str, str] = {
        "ZEROCLAW_PROVIDER": agent.llm.provider,
        "ZEROCLAW_MODEL": agent.llm.model,
        "ZEROCLAW_WORKSPACE": "/zeroclaw/workspace",
        "ZEROCLAW_PROVIDER_TIMEOUT_SECS": str(agent.llm.timeout_secs),
    }
    if agent.llm.provider == "anthropic":
        env["ANTHROPIC_API_KEY"] = agent.llm.api_key
    elif agent.llm.provider == "litellm":
        env["LITELLM_API_KEY"] = agent.llm.api_key

    if agent.slack.enabled:
        env["SLACK_BOT_TOKEN"] = agent.slack.bot_token
        env["SLACK_APP_TOKEN"] = agent.slack.app_token
        env["SLACK_SIGNING_SECRET"] = agent.slack.signing_secret

    if agent.composio.enabled:
        env["COMPOSIO_API_KEY"] = agent.composio.api_key

    return env

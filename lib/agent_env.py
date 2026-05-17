from __future__ import annotations

from lib.config import AgentDefinition


def build_agent_env(agent: AgentDefinition) -> dict[str, str]:
    """Env vars exported into the ZeroClaw container.

    Only includes vars that upstream ZeroClaw actually reads from env (see
    apps/zeroclaw/upstream/crates/zeroclaw-config/src/schema.rs apply_env_overrides).
    SLACK_*, COMPOSIO_API_KEY, and MCP server headers do NOT have env-read paths
    upstream — they must be rendered into config.toml directly. See SECURITY.md §5.
    """
    env: dict[str, str] = {
        "ZEROCLAW_PROVIDER": agent.llm.provider,
        "ZEROCLAW_MODEL": agent.llm.model,
        "ZEROCLAW_WORKSPACE": "/zeroclaw/workspace",
        "ZEROCLAW_PROVIDER_TIMEOUT_SECS": str(agent.llm.timeout_secs),
    }
    if agent.llm.api_key:
        env["ZEROCLAW_API_KEY"] = agent.llm.api_key
    return env

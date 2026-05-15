from __future__ import annotations

from lib.config import TenantDefinition


def build_tenant_env(tenant: TenantDefinition) -> dict[str, str]:
    env: dict[str, str] = {
        "ZEROCLAW_PROVIDER": tenant.llm.provider,
        "ZEROCLAW_MODEL": tenant.llm.model,
        "ZEROCLAW_WORKSPACE": "/zeroclaw/workspace",
        "ZEROCLAW_PROVIDER_TIMEOUT_SECS": str(tenant.llm.timeout_secs),
    }
    if tenant.llm.provider == "anthropic":
        env["ANTHROPIC_API_KEY"] = tenant.llm.api_key
    elif tenant.llm.provider == "litellm":
        env["LITELLM_API_KEY"] = tenant.llm.api_key

    if tenant.slack.enabled:
        env["SLACK_BOT_TOKEN"] = tenant.slack.bot_token
        env["SLACK_APP_TOKEN"] = tenant.slack.app_token
        env["SLACK_SIGNING_SECRET"] = tenant.slack.signing_secret

    if tenant.composio.enabled:
        env["COMPOSIO_API_KEY"] = tenant.composio.api_key

    return env

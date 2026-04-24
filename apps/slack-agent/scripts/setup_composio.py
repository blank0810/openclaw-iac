#!/usr/bin/env python3
"""Create or find Composio-managed auth configs for Gmail and Google Calendar.

Uses Composio's shared OAuth apps (verified by Google), so users see
'Composio' on the consent screen — no CASA needed on our side.
"""
import os

from composio import Composio
from dotenv import load_dotenv

load_dotenv()

TOOLKITS = ["gmail", "googlecalendar"]


def find_or_create_auth_config(client: Composio, toolkit_slug: str):
    # Look for an existing composio-managed config for this toolkit
    existing = client.auth_configs.list(
        toolkit_slug=toolkit_slug, is_composio_managed=True
    )
    items = getattr(existing, "items", None) or getattr(existing, "data", None) or []
    for cfg in items:
        # Return the first active one
        return cfg
    # None found → create
    return client.auth_configs.create(
        toolkit=toolkit_slug,
        options={
            "type": "use_composio_managed_auth",
            "name": f"slack-agent {toolkit_slug}",
        },
    )


def main() -> None:
    client = Composio()
    results: dict[str, str] = {}
    for toolkit in TOOLKITS:
        print(f"Resolving auth config for {toolkit}...")
        cfg = find_or_create_auth_config(client, toolkit)
        cfg_id = getattr(cfg, "id", None) or getattr(cfg, "nanoid", None)
        if not cfg_id:
            raise SystemExit(
                f"Could not resolve auth config id for {toolkit}. Got: {cfg!r}"
            )
        results[toolkit] = cfg_id
        print(f"  {toolkit} auth config: {cfg_id}")

    print("\nPaste into slack-agent/.env:")
    print(f"GMAIL_AUTH_CONFIG_ID={results['gmail']}")
    print(f"CALENDAR_AUTH_CONFIG_ID={results['googlecalendar']}")


if __name__ == "__main__":
    main()

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_agent_slack_manifest_has_socket_mode_events_and_scopes():
    manifest = yaml.safe_load((REPO_ROOT / "slack/agent-app-manifest.yaml").read_text())

    assert manifest["settings"]["socket_mode_enabled"] is True
    assert manifest["features"]["app_home"]["messages_tab_enabled"] is True

    events = manifest["settings"]["event_subscriptions"]["bot_events"]
    assert "app_mention" in events
    assert "message.im" in events

    scopes = manifest["oauth_config"]["scopes"]["bot"]
    assert "chat:write" in scopes
    assert "app_mentions:read" in scopes
    assert "im:history" in scopes

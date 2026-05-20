import sys

from apps.orchestrator.models import CreateAgentRequest
from apps.orchestrator.pipeline import build_create_cmd, build_commands


def test_create_cmd_includes_flags():
    req = CreateAgentRequest(
        name="acme", display_name="Acme",
        slack={"bot_token": "xoxb-x", "app_token": "xapp-x", "channel_id": "C1"},
        composio={"mcp_api_key": "ck_x"},
    )
    cmd = build_create_cmd(req)
    assert cmd[:4] == [sys.executable, "zeroclawctl.py", "agents", "create"]
    assert "--name" in cmd and "acme" in cmd
    assert "--display-name" in cmd and "Acme" in cmd
    assert "--slack-bot-token" in cmd and "xoxb-x" in cmd
    assert "--slack-app-token" in cmd and "xapp-x" in cmd
    assert "--slack-channel-id" in cmd and "C1" in cmd
    assert "--composio-mcp-key" in cmd and "ck_x" in cmd


def test_create_cmd_omits_absent_optionals():
    req = CreateAgentRequest(name="acme")
    cmd = build_create_cmd(req)
    assert "--slack-bot-token" not in cmd
    assert "--composio-mcp-key" not in cmd
    assert "--display-name" not in cmd


def test_build_commands_order():
    req = CreateAgentRequest(name="acme")
    cmds = build_commands(req)
    assert [c[2:4] for c in cmds] == [
        ["agents", "create"],
        ["server", "deploy"],
        ["agents", "deploy"],
    ]

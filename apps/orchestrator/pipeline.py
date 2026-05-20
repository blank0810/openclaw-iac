from __future__ import annotations

import sys

from apps.orchestrator.models import CreateAgentRequest

CLI = "zeroclawctl.py"


def build_create_cmd(req: CreateAgentRequest) -> list[str]:
    cmd = [sys.executable, CLI, "agents", "create", "--name", req.name]
    if req.display_name:
        cmd += ["--display-name", req.display_name]
    if req.slack:
        cmd += ["--slack-bot-token", req.slack.bot_token,
                "--slack-app-token", req.slack.app_token]
        if req.slack.channel_id:
            cmd += ["--slack-channel-id", req.slack.channel_id]
    if req.composio and req.composio.mcp_api_key:
        cmd += ["--composio-mcp-key", req.composio.mcp_api_key]
    return cmd


def build_commands(req: CreateAgentRequest) -> list[list[str]]:
    return [
        build_create_cmd(req),
        [sys.executable, CLI, "server", "deploy"],
        [sys.executable, CLI, "agents", "deploy", "--name", req.name],
    ]

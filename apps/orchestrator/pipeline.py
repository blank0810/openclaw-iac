from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from apps.orchestrator.jobs import JobStore
from apps.orchestrator.models import AgentResult, CreateAgentRequest

# apps/orchestrator/pipeline.py -> apps/orchestrator -> apps -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = str(_REPO_ROOT / "zeroclawctl.py")
GATEWAY_PORT = 42617
_STEP_NAMES = ["create", "server_deploy", "agent_deploy"]


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


def _fetch_status(req: CreateAgentRequest) -> str:
    """Best-effort: parse `zeroclawctl agents status` JSON for this container."""
    try:
        proc = subprocess.run(
            [sys.executable, CLI, "agents", "status"],
            check=False, capture_output=True, text=True,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            obj = json.loads(line)
            if obj.get("Name") == f"zeroclaw-{req.name}":
                return obj.get("State") or obj.get("Status") or "unknown"
    # Intentionally best-effort: status is a cosmetic field, so a failed/garbled
    # probe must never fail the job. Do not "fix" this into raising.
    except Exception:
        pass
    return "started"


def run_pipeline(store: JobStore, job_id: str, req: CreateAgentRequest, *, server_ip: str) -> None:
    # Runs as a fire-and-forget background task: the 202 has already been sent,
    # so any escaping exception would strand the job in "running" forever and the
    # GET /jobs/{id} poller would never terminate. Trap everything into a terminal
    # failed state so the async contract (every job ends succeeded OR failed) holds.
    try:
        for name, cmd in zip(_STEP_NAMES, build_commands(req)):
            store.start_step(job_id, name)
            proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if proc.returncode != 0:
                store.finish_step(job_id, name, ok=False, error=(proc.stderr or proc.stdout).strip())
                return
            store.finish_step(job_id, name, ok=True)

        store.succeed(job_id, AgentResult(
            name=req.name,
            container_name=f"zeroclaw-{req.name}",
            server_ip=server_ip,
            host=server_ip,
            gateway_port=GATEWAY_PORT,
            status=_fetch_status(req),
        ))
    except Exception as e:  # noqa: BLE001 - any unexpected error must land in job state
        store.fail(job_id, error=f"unexpected pipeline error: {e}")

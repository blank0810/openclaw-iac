from __future__ import annotations

from pathlib import Path

import docker
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException

from apps.orchestrator.jobs import JobStore
from apps.orchestrator.models import CreateAgentRequest, JobState
from apps.orchestrator.provisioner import GATEWAY_PORT, provision_agent
from lib.config import AgentDefinition, load_config

# apps/orchestrator/main.py -> apps/orchestrator -> apps -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_STATES_BASE = Path("/opt/zeroclaw/states")


def verify_request() -> None:
    """Auth seam — no-op for the local MVP. Swap for Firebase JWT later."""
    return None


def _server_ip() -> str:
    return load_config().server_host


def _toml_str(value: str) -> str:
    """Escape a string for a TOML basic (double-quoted) string. Tokens may
    contain arbitrary characters, so never interpolate raw into the file."""
    out = value.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{out}"'


def _render_agent_toml(req: CreateAgentRequest) -> str:
    """Serialize a CreateAgentRequest into an agent.toml. Thin: emit only what
    the request provides. Everything else (model/provider/api_key defaults,
    slack scoping, composio mcp_url/transport, autonomy) inherits from
    agents/_defaults.toml via lib.config's deep merge — the orchestrator carries
    no LLM/tool defaults of its own."""
    display_name = req.display_name or req.name
    lines = [
        "[identity]",
        f"name = {_toml_str(req.name)}",
        f"display_name = {_toml_str(display_name)}",
        "enabled = true",
        f"state_dir = {_toml_str(req.name)}",
        "",
        "[runtime]",
        "host_port = 0",
    ]
    if req.llm and (req.llm.provider or req.llm.model):
        lines += ["", "[llm]"]
        if req.llm.provider:
            lines.append(f"provider = {_toml_str(req.llm.provider)}")
        if req.llm.model:
            lines.append(f"model = {_toml_str(req.llm.model)}")
    if req.slack:
        lines += [
            "",
            "[slack]",
            "enabled = true",
            f"bot_token = {_toml_str(req.slack.bot_token)}",
            f"app_token = {_toml_str(req.slack.app_token)}",
        ]
        if req.slack.channel_id:
            lines.append(f"channel_id = {_toml_str(req.slack.channel_id)}")
    if req.composio:
        lines += ["", "[composio]", "enabled = true"]
        if req.composio.mcp_api_key:
            lines.append(f"mcp_api_key = {_toml_str(req.composio.mcp_api_key)}")
    return "\n".join(lines) + "\n"


def build_agent_definition(
    req: CreateAgentRequest, *, project_root: Path
) -> AgentDefinition:
    """Persist agent.toml from the request, then return the AgentDefinition that
    load_config produces for it — which applies the agents/_defaults.toml merge
    and all of lib.config's validation. The written file is the source of truth.

    The orchestrator has no agent.toml on disk for a new agent, so we write one
    (request fields only) and let lib.config fill the rest. This keeps a single
    code path for merge/validation shared with the CLI.
    """
    agent_dir = project_root / "agents" / req.name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.toml").write_text(_render_agent_toml(req))

    cfg = load_config(project_root)
    for agent in cfg.agents:
        if agent.name == req.name:
            return agent
    # load_config silently skips dirs it can't parse; surface that as an error
    # rather than returning None so the caller's job lands in a failed state.
    raise ValueError(f"agent definition for {req.name!r} not found after write")


def create_app(store: JobStore | None = None) -> FastAPI:
    app = FastAPI(title="ZeroClaw Orchestrator")
    app.state.store = store or JobStore()
    app.state.project_root = _REPO_ROOT
    app.state.states_base = _DEFAULT_STATES_BASE
    app.state.docker_client_factory = docker.from_env

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/agents", status_code=202, dependencies=[Depends(verify_request)])
    def create_agent(req: CreateAgentRequest, bg: BackgroundTasks) -> dict:
        store: JobStore = app.state.store
        if store.active_job_for(req.name) is not None:
            raise HTTPException(
                status_code=409, detail=f"create already in flight for {req.name}"
            )
        agent = build_agent_definition(req, project_root=app.state.project_root)
        image = agent.image or load_config(app.state.project_root).zeroclaw_image
        client = app.state.docker_client_factory()
        job = store.create(slug=req.name)
        bg.add_task(
            provision_agent,
            client,
            store,
            job.job_id,
            agent,
            image=image,
            states_base=app.state.states_base,
            project_root=app.state.project_root,
            server_ip=_server_ip(),
        )
        return {"job_id": job.job_id}

    @app.get("/jobs/{job_id}", response_model=JobState)
    def get_job(job_id: str) -> JobState:
        job = app.state.store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    return app

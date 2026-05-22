from __future__ import annotations

import re
from pathlib import Path

import docker
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException

from apps.orchestrator import providers
from apps.orchestrator.jobs import JobStore
from apps.orchestrator.models import (
    BackupResult,
    CreateAgentRequest,
    DeleteResult,
    JobState,
    RestoreRequest,
    SetProviderRequest,
)
from apps.orchestrator.provisioner import (
    backup_agent,
    provision_agent,
    reprovision_agent,
    restore_agent,
)
from lib.config import SLUG_PATTERN, AgentDefinition, load_config

# apps/orchestrator/main.py -> apps/orchestrator -> apps -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_STATES_BASE = Path("/opt/zeroclaw/states")
_DEFAULT_BACKUPS_BASE = Path("/opt/zeroclaw/backups")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def verify_request() -> None:
    """Auth seam — no-op for the local MVP. Swap for Firebase JWT later."""
    return None


def _server_ip() -> str:
    return load_config().server_host


def _container_exists(client, slug: str) -> bool:
    """True if a ``zeroclaw-<slug>`` container already exists on the daemon.

    Only ``NotFound`` is treated as absence; any other docker error (daemon
    down, permission) propagates so the request fails loudly rather than
    silently provisioning over a half-broken state."""
    try:
        client.containers.get(f"zeroclaw-{slug}")
        return True
    except docker.errors.NotFound:
        return False


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
        f"user_id = {_toml_str(req.user_id)}",
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
    app.state.backups_base = _DEFAULT_BACKUPS_BASE
    app.state.docker_client_factory = docker.from_env

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/v1/agent/create", status_code=202, dependencies=[Depends(verify_request)])
    def create_agent(req: CreateAgentRequest, bg: BackgroundTasks) -> dict:
        store: JobStore = app.state.store
        # Guard order matters: cheap in-memory check, then resolve the docker
        # client (fails loudly if the daemon is down), then the container check
        # — all BEFORE build_agent_definition writes any agent.toml, so a 409
        # or a daemon-down 500 never leaves a stray file on disk.
        if store.active_job_for(req.name) is not None:
            raise HTTPException(
                status_code=409, detail=f"create already in flight for {req.name}"
            )
        client = app.state.docker_client_factory()
        if _container_exists(client, req.name):
            raise HTTPException(
                status_code=409, detail=f"agent {req.name} already exists"
            )
        agent = build_agent_definition(req, project_root=app.state.project_root)
        image = agent.image or load_config(app.state.project_root).zeroclaw_image
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

    @app.get("/v1/agent/job/{job_id}", response_model=JobState)
    def get_job(job_id: str) -> JobState:
        job = app.state.store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.delete(
        "/v1/agent/delete/{name}",
        response_model=DeleteResult,
        dependencies=[Depends(verify_request)],
    )
    def delete_agent(name: str) -> DeleteResult:
        # The agent name is the stable handle: every container is named
        # zeroclaw-<slug>, so we resolve the target by name (we do not set a
        # separate Docker hostname). Validate the slug so the lookup can never
        # be built from arbitrary input.
        if not SLUG_PATTERN.match(name):
            raise HTTPException(status_code=422, detail=f"invalid agent name: {name}")
        client = app.state.docker_client_factory()
        cname = f"zeroclaw-{name}"
        try:
            container = client.containers.get(cname)
        except docker.errors.NotFound:
            raise HTTPException(
                status_code=404, detail=f"no such agent container: {cname}"
            )
        container_id = getattr(container, "id", None)
        container.stop(timeout=10)
        # v=True removes any anonymous volumes bound to the container. Our
        # containers use host bind-mounts (the state dir under
        # /opt/zeroclaw/states/<slug>), which Docker never deletes regardless;
        # this only sweeps anonymous volumes so none are orphaned.
        container.remove(v=True)
        # Best-effort removal of the per-agent bridge network. Leave it if the
        # daemon still reports endpoints (another container attached) or it is
        # already gone — deleting the container is the contract, the network is
        # cleanup.
        network_removed = None
        try:
            net = client.networks.get(f"zc-{name}")
            net.remove()
            network_removed = f"zc-{name}"
        except docker.errors.NotFound:
            pass
        except docker.errors.APIError:
            pass
        return DeleteResult(
            removed=cname,
            container_id=container_id,
            network_removed=network_removed,
        )

    @app.get("/v1/providers", dependencies=[Depends(verify_request)])
    def list_providers() -> dict:
        root = app.state.project_root
        return {
            "default": providers.current_default(root),
            "profiles": providers.masked_profiles(root),
        }

    @app.put("/v1/config/provider", dependencies=[Depends(verify_request)])
    def set_default_provider(req: SetProviderRequest) -> dict:
        """Point the global default (`_defaults.toml [llm]`) at a registry
        profile. Affects NEW agents only — existing containers keep their baked
        config until re-created or switched per-agent."""
        try:
            new_default = providers.set_default_provider(req.profile, app.state.project_root)
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"unknown provider profile: {req.profile}"
            )
        return {"default": new_default}

    @app.put(
        "/v1/agent/{name}/provider",
        status_code=202,
        dependencies=[Depends(verify_request)],
    )
    def set_agent_provider(name: str, req: SetProviderRequest, bg: BackgroundTasks) -> dict:
        """Switch one running agent's provider live: write the profile into its
        agent.toml, then re-provision (stop+remove+recreate) so the new env/config
        takes effect. State (workspace/brain.db) is a bind-mount and survives."""
        if not SLUG_PATTERN.match(name):
            raise HTTPException(status_code=422, detail=f"invalid agent name: {name}")
        store: JobStore = app.state.store
        if store.active_job_for(name) is not None:
            raise HTTPException(
                status_code=409, detail=f"a job is already in flight for {name}"
            )
        client = app.state.docker_client_factory()
        if not _container_exists(client, name):
            raise HTTPException(
                status_code=404, detail=f"no such agent container: zeroclaw-{name}"
            )
        try:
            providers.set_agent_provider(req.profile, name, app.state.project_root)
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"unknown provider profile: {req.profile}"
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"no agent.toml for {name} on the orchestrator"
            )
        # Re-derive the AgentDefinition from the now-updated agent.toml.
        cfg = load_config(app.state.project_root)
        agent = next((a for a in cfg.agents if a.name == name), None)
        if agent is None:
            raise HTTPException(
                status_code=500, detail=f"agent {name} not found after provider write"
            )
        image = agent.image or cfg.zeroclaw_image
        job = store.create(slug=name)
        bg.add_task(
            reprovision_agent,
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

    @app.post(
        "/v1/agent/restore/{date}",
        status_code=202,
        dependencies=[Depends(verify_request)],
    )
    def restore_agent_endpoint(
        date: str, req: RestoreRequest, bg: BackgroundTasks
    ) -> dict:
        """Restore an agent's state from its backup zip for ``date`` then
        recreate the container. Both the backup file and the agent definition
        must exist (validated here, before any mutation) — and the zip path is
        built server-side from name+date, so a restore can only ever touch that
        agent's own backup."""
        if not _DATE_RE.match(date):
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
        name = req.name
        store: JobStore = app.state.store
        if store.active_job_for(name) is not None:
            raise HTTPException(
                status_code=409, detail=f"a job is already in flight for {name}"
            )
        backup_zip = Path(app.state.backups_base) / name / date / f"{name}.zip"
        if not backup_zip.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"no backup for {name} on {date} ({backup_zip})",
            )
        cfg = load_config(app.state.project_root)
        agent = next((a for a in cfg.agents if a.name == name), None)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail=f"no agent definition for {name} on the orchestrator; "
                "restore needs its agent.toml to rebuild the container",
            )
        image = agent.image or cfg.zeroclaw_image
        client = app.state.docker_client_factory()
        job = store.create(slug=name)
        bg.add_task(
            restore_agent,
            client,
            store,
            job.job_id,
            agent,
            backup_zip=backup_zip,
            image=image,
            states_base=app.state.states_base,
            backups_base=Path(app.state.backups_base),
            server_ip=_server_ip(),
        )
        return {"job_id": job.job_id}

    @app.post(
        "/v1/agent/{name}/backup",
        response_model=BackupResult,
        dependencies=[Depends(verify_request)],
    )
    def backup_agent_endpoint(name: str) -> BackupResult:
        """Manual on-demand backup of one agent's state dir -> a zip on the host,
        returning the file location. Synchronous (just a filesystem zip, no docker)
        — FastAPI runs it in a threadpool so it doesn't block other requests. The
        path/layout match the daily timer and what restore reads."""
        if not SLUG_PATTERN.match(name):
            raise HTTPException(status_code=422, detail=f"invalid agent name: {name}")
        try:
            dest, size, date = backup_agent(
                name,
                states_base=Path(app.state.states_base),
                backups_base=Path(app.state.backups_base),
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"no state dir for {name} on the host (nothing to back up)",
            )
        return BackupResult(name=name, date=date, location=str(dest), size_bytes=size)

    return app

from __future__ import annotations

import os
from pathlib import Path

from docker.types import LogConfig, Ulimit

from apps.orchestrator.config_render import render_agent_config
from apps.orchestrator.jobs import JobStore
from apps.orchestrator.models import AgentResult
from lib.config import AgentDefinition

GATEWAY_PORT = 42617
_CONTAINER_DATA = "/zeroclaw-data"


def _chown_for_container(state_dir: Path, uid: int = 65534, gid: int = 65534) -> None:
    """chown the per-agent state so the UID-65534 container can read config and
    write workspace. Requires root (orchestrator is a root systemd unit).

    config.toml is mounted ro (the container only reads it); workspace is
    mounted rw (the container writes brain.db + sessions there), so every file
    and dir under it must be owned by 65534 or the container crash-loops on
    EACCES. Agents are created dynamically, so this CANNOT be done at deploy
    time -- it must happen here, at provision time, as root."""
    zc = state_dir / ".zeroclaw"
    os.chown(zc, uid, gid)
    os.chown(zc / "config.toml", uid, gid)
    for root, _dirs, files in os.walk(state_dir / "workspace"):
        os.chown(root, uid, gid)
        for name in files:
            os.chown(os.path.join(root, name), uid, gid)


def build_container_spec(
    agent: AgentDefinition, *, env: dict, state_dir: str, image: str
) -> dict:
    """Pure map of an agent to docker-py ``containers.run(...)`` kwargs.

    Every container is locked down: read-only rootfs, all caps dropped,
    no-new-privileges, runs as nobody (65534), with memory/pids/cpu caps
    and a per-agent bridge network. No I/O happens here.
    """
    spec = {
        "image": image,
        "name": f"zeroclaw-{agent.name}",
        "detach": True,
        "environment": env,
        "read_only": True,
        "tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"},
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "user": "65534:65534",
        "mem_limit": "512m",
        "pids_limit": 256,
        "nano_cpus": 1_000_000_000,
        "restart_policy": {"Name": "unless-stopped"},
        "network": f"zc-{agent.name}",
        "ulimits": [Ulimit(name="nofile", soft=1024, hard=2048)],
        "log_config": LogConfig(
            type="json-file", config={"max-size": "10m", "max-file": "5"}
        ),
        "volumes": {
            f"{state_dir}/.zeroclaw/config.toml": {
                "bind": f"{_CONTAINER_DATA}/.zeroclaw/config.toml",
                "mode": "ro",
            },
            f"{state_dir}/workspace": {
                "bind": f"{_CONTAINER_DATA}/workspace",
                "mode": "rw",
            },
        },
    }
    if agent.host_port:
        spec["ports"] = {f"{GATEWAY_PORT}/tcp": ("127.0.0.1", agent.host_port)}
    return spec


def _ensure_network(client, name: str) -> None:
    """Create the per-agent ``zc-<slug>`` bridge network unless it exists.

    The per-agent bridge provides tenant-to-tenant L2 isolation: agents on
    distinct ``zc-<slug>`` networks cannot see each other's traffic. It does
    NOT confine egress -- this is a normal bridge (not ``internal=True``), so
    the container still reaches the host route and LiteLLM at 10.0.0.4:4000,
    which is intentional. Do not assume these networks sandbox outbound access.
    """
    if not client.networks.list(names=[name]):
        client.networks.create(name, driver="bridge")


def provision_agent(
    client,
    store: JobStore,
    job_id: str,
    agent: AgentDefinition,
    *,
    image: str,
    states_base: Path,
    project_root: Path,
    server_ip: str,
) -> None:
    """Provision one agent against the local Docker daemon, tracking each step
    in the job store. Any unexpected error is recorded as a terminal job
    failure so a job is never left stranded in a running state."""
    try:
        state_dir = states_base / agent.state_dir

        store.start_step(job_id, "render_config")
        env = render_agent_config(agent, state_dir, project_root=project_root)
        # chown the rendered state to the container UID (65534) so the ro config
        # mount is readable and the rw workspace mount is writable. Inside the
        # try so a chown failure (e.g. not running as root) fails the job.
        _chown_for_container(state_dir)
        store.finish_step(job_id, "render_config", ok=True)

        store.start_step(job_id, "ensure_network")
        _ensure_network(client, f"zc-{agent.name}")
        store.finish_step(job_id, "ensure_network", ok=True)

        store.start_step(job_id, "pull_image")
        client.images.pull(image)
        store.finish_step(job_id, "pull_image", ok=True)

        store.start_step(job_id, "run_container")
        spec = build_container_spec(
            agent, env=env, state_dir=str(state_dir), image=image
        )
        container = client.containers.run(**spec)
        store.finish_step(job_id, "run_container", ok=True)

        store.succeed(
            job_id,
            AgentResult(
                user_id=agent.user_id,
                name=agent.name,
                display_name=agent.display_name,
                container_name=f"zeroclaw-{agent.name}",
                container_id=container.id,
                image=image,
                server_ip=server_ip,
                host=server_ip,
                gateway_port=GATEWAY_PORT,
                status=getattr(container, "status", "created"),
            ),
        )
    except Exception as e:  # noqa: BLE001 - any error must land in job state
        store.fail(job_id, error=f"provision error: {e}")

from __future__ import annotations

import datetime
import os
import shutil
import zipfile
from pathlib import Path

import docker
from docker.types import LogConfig, Ulimit

from apps.orchestrator.config_render import render_agent_config
from apps.orchestrator.jobs import JobStore
from apps.orchestrator.models import AgentResult
from lib.agent_env import build_agent_env
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


def reprovision_agent(
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
    """Stop+remove the existing container (if any) then provision fresh — the
    mechanism behind a live per-agent provider switch. Docker can't change a
    running container's env (the LLM key flows via ZEROCLAW_API_KEY), so the
    container is recreated. The per-agent state dir is a host bind-mount, so
    workspace/brain.db/memory survive the swap; only the container blips."""
    try:
        existing = client.containers.get(f"zeroclaw-{agent.name}")
        existing.stop(timeout=10)
        existing.remove(v=True)
    except docker.errors.NotFound:
        pass
    except Exception as e:  # noqa: BLE001
        store.fail(job_id, error=f"reprovision pre-remove error: {e}")
        return
    provision_agent(
        client,
        store,
        job_id,
        agent,
        image=image,
        states_base=states_base,
        project_root=project_root,
        server_ip=server_ip,
    )


def _zip_dir_contents(src: Path, dest_zip: Path) -> None:
    """Zip the contents of ``src`` (arcnames relative to it). Matches the host
    backup script so a restore extracts straight into a state dir."""
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(src):
            for name in files:
                fp = Path(root) / name
                zf.write(fp, fp.relative_to(src))


def backup_agent(
    name: str, *, states_base: Path, backups_base: Path, date: str | None = None
) -> tuple[Path, int, str]:
    """Zip an agent's state dir -> backups_base/<name>/<date>/<name>.zip and
    return (location, size_bytes, date). Pure filesystem (no docker), so the
    API can call it synchronously. Mirrors the host backup script's layout so a
    restore for the same date resolves this exact file. Raises FileNotFoundError
    if the agent has no state dir."""
    date = date or datetime.datetime.utcnow().strftime("%Y-%m-%d")
    state_dir = states_base / name
    if not state_dir.is_dir():
        raise FileNotFoundError(state_dir)
    dest = backups_base / name / date / f"{name}.zip"
    _zip_dir_contents(state_dir, dest)
    return dest, dest.stat().st_size, date


def restore_agent(
    client,
    store: JobStore,
    job_id: str,
    agent: AgentDefinition,
    *,
    backup_zip: Path,
    image: str,
    states_base: Path,
    backups_base: Path,
    server_ip: str,
) -> None:
    """Restore an agent's state dir from a backup zip, then recreate its
    container. The caller has already validated that ``backup_zip`` and the
    agent definition exist. Snapshot-current-first makes a wrong restore
    recoverable; the extract is atomic (temp dir then swap) so a partial unzip
    never corrupts live state. The restored config.toml is kept as-is (no
    re-render); the env/api_key come from the current agent definition."""
    try:
        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        state_dir = states_base / agent.state_dir

        store.start_step(job_id, "snapshot_current")
        if state_dir.exists():
            snap = backups_base / agent.name / f"_pre-restore-{ts}" / f"{agent.name}.zip"
            _zip_dir_contents(state_dir, snap)
        store.finish_step(job_id, "snapshot_current", ok=True)

        store.start_step(job_id, "stop_remove")
        try:
            existing = client.containers.get(f"zeroclaw-{agent.name}")
            existing.stop(timeout=10)
            existing.remove(v=True)
        except docker.errors.NotFound:
            pass
        store.finish_step(job_id, "stop_remove", ok=True)

        store.start_step(job_id, "extract")
        # Atomic: unzip into a temp dir, then swap it into the state dir, so a
        # failed extract can never leave half-restored state behind.
        tmp = states_base / f".restore-{agent.name}-{ts}"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        with zipfile.ZipFile(backup_zip, "r") as zf:
            zf.extractall(tmp)
        if state_dir.exists():
            shutil.rmtree(state_dir)
        shutil.move(str(tmp), str(state_dir))
        store.finish_step(job_id, "extract", ok=True)

        store.start_step(job_id, "chown")
        _chown_for_container(state_dir)
        store.finish_step(job_id, "chown", ok=True)

        store.start_step(job_id, "ensure_network")
        _ensure_network(client, f"zc-{agent.name}")
        store.finish_step(job_id, "ensure_network", ok=True)

        store.start_step(job_id, "run_container")
        spec = build_container_spec(
            agent, env=build_agent_env(agent), state_dir=str(state_dir), image=image
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
        store.fail(job_id, error=f"restore error: {e}")

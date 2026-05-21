from __future__ import annotations

from docker.types import LogConfig, Ulimit

from lib.config import AgentDefinition

GATEWAY_PORT = 42617
_CONTAINER_DATA = "/zeroclaw-data"


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

from __future__ import annotations

from pyinfra import host
from pyinfra.operations import apt, files, server, systemd

from lib.slack_probe import install_probes


deploy_user = host.data.deploy_user
remote_base_dir = host.data.get("remote_base_dir", "/opt/zeroclaw")
agents = host.data.get("agents", ())


server.shell(
    name="Stop unattended-upgrades to release apt lock",
    commands=[
        "systemctl stop unattended-upgrades || true",
        "kill -9 $(lsof /var/lib/dpkg/lock-frontend 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true",
        "kill -9 $(lsof /var/lib/apt/lists/lock 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true",
        "rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock /var/lib/apt/lists/lock",
        "DEBIAN_FRONTEND=noninteractive dpkg --configure -a",
    ],
    _sudo=True,
    _timeout=60,
)

apt.update(name="Refresh apt package index", _sudo=True)

apt.packages(
    name="Install base packages",
    packages=[
        "git",
        "ca-certificates",
        "curl",
        "gnupg",
        "apt-transport-https",
        "unattended-upgrades",
    ],
    present=True,
    _sudo=True,
)

server.shell(
    name="Install Docker apt repository if missing",
    commands=[
        "if ! command -v docker >/dev/null 2>&1; then "
        "sudo install -m 0755 -d /etc/apt/keyrings && "
        "curl -fsSL https://download.docker.com/linux/ubuntu/gpg "
        "| sudo gpg --dearmor --batch --yes -o /etc/apt/keyrings/docker.gpg && "
        "sudo chmod a+r /etc/apt/keyrings/docker.gpg && "
        'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] '
        'https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" '
        "| sudo tee /etc/apt/sources.list.d/docker.list >/dev/null && "
        "sudo apt-get update && "
        "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin; "
        "fi",
    ],
    _timeout=300,
)

server.group(
    name="Ensure docker group exists",
    group="docker",
    present=True,
    _sudo=True,
)

server.user(
    name=f"Add {deploy_user} to docker group",
    user=deploy_user,
    groups=["docker"],
    append=True,
    _sudo=True,
)

for path in (remote_base_dir, f"{remote_base_dir}/states", f"{remote_base_dir}/.archive"):
    files.directory(
        name=f"Ensure {path}",
        path=path,
        present=True,
        user=deploy_user,
        group=deploy_user,
        mode="750",
        _sudo=True,
    )

for agent in agents:
    state_dir = agent["state_dir"]
    for relpath in ("", ".zeroclaw", "workspace", "workspace/sessions", "workspace/sessions/archive"):
        path = f"{remote_base_dir}/states/{state_dir}"
        if relpath:
            path = f"{path}/{relpath}"
        container_owned = relpath.startswith("workspace") or relpath == ".zeroclaw"
        files.directory(
            name=f"Ensure agent directory {path}",
            path=path,
            present=True,
            user="65534" if container_owned else deploy_user,
            group="65534" if container_owned else deploy_user,
            mode="755" if container_owned else "750",
            _sudo=True,
        )

# Template expects a `config` namespace with .agents + .zeroclaw_image
# (matching how tests render it via `env.get_template(...).render(config=cfg)`).
# Pyinfra's _server_inventory pops the full DeploymentConfig out of host.data
# before serializing it, so we rebuild a dict-shaped equivalent here.
_compose_config = type("_C", (), {
    "agents": agents,
    "zeroclaw_image": host.data.get("zeroclaw_image"),
})()

files.template(
    name="Render shared ZeroClaw docker-compose.yml",
    src="templates/docker-compose.yml.j2",
    dest=f"{remote_base_dir}/docker-compose.yml",
    user=deploy_user,
    group=deploy_user,
    mode="0644",
    config=_compose_config,
    _sudo=True,
)

for agent in agents:
    if not agent["enabled"]:
        continue
    server.shell(
        name=f"Pull image for {agent['name']}",
        commands=[f"cd {remote_base_dir} && docker pull {agent['image']}"],
    )

install_probes(agents)

systemd.service(
    name="Enable and start Docker service",
    service="docker.service",
    running=True,
    enabled=True,
    _sudo=True,
)

systemd.service(
    name="Re-enable unattended-upgrades",
    service="unattended-upgrades",
    running=True,
    enabled=True,
    _sudo=True,
)

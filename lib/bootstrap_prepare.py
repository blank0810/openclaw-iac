from __future__ import annotations

from io import StringIO

from pyinfra import host
from pyinfra.operations import apt, files, server, systemd


deploy_user = host.data.deploy_user
team_ssh_keys = getattr(host.data, "team_ssh_keys", ())
timezone = getattr(host.data, "timezone", "UTC")

if not team_ssh_keys:
    raise RuntimeError(
        "team_ssh_keys is empty; add at least one public key before bootstrap."
    )


server.user(
    name=f"Create user {deploy_user}",
    user=deploy_user,
    present=True,
    home=f"/home/{deploy_user}",
    shell="/bin/bash",
    ensure_home=True,
)

server.group(
    name="Ensure sudo group exists",
    group="sudo",
    present=True,
)

server.user(
    name=f"Add {deploy_user} to sudo group",
    user=deploy_user,
    groups=["sudo"],
    append=True,
)

files.directory(
    name=f"Create /home/{deploy_user}/.ssh",
    path=f"/home/{deploy_user}/.ssh",
    present=True,
    user=deploy_user,
    group=deploy_user,
    mode="700",
)

files.put(
    name=f"Upload authorized_keys for {deploy_user}",
    src=StringIO("\n".join(team_ssh_keys) + "\n"),
    dest=f"/home/{deploy_user}/.ssh/authorized_keys",
    user=deploy_user,
    group=deploy_user,
    mode="600",
)

files.put(
    name=f"Write sudoers drop-in for {deploy_user}",
    src=StringIO(f"{deploy_user} ALL=(ALL) NOPASSWD:ALL\n"),
    dest=f"/etc/sudoers.d/{deploy_user}",
    user="root",
    group="root",
    mode="440",
)

server.shell(
    name="Stop unattended-upgrades to release apt lock",
    commands=[
        "systemctl stop unattended-upgrades || true",
        "kill -9 $(lsof /var/lib/dpkg/lock-frontend 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true",
        "kill -9 $(lsof /var/lib/apt/lists/lock 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true",
        "rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock /var/lib/apt/lists/lock",
        "DEBIAN_FRONTEND=noninteractive dpkg --configure -a",
    ],
    _timeout=60,
)

apt.update(name="Refresh apt package index")

apt.packages(
    name="Install base packages",
    packages=[
        "git",
        "ufw",
        "fail2ban",
        "ca-certificates",
        "curl",
        "gnupg",
        "apt-transport-https",
        "unattended-upgrades",
    ],
    present=True,
)

server.shell(
    name="Set timezone",
    commands=[f"timedatectl set-timezone {timezone}"],
)

server.shell(
    name="Install Docker apt repository if missing",
    commands=[
        "if ! command -v docker >/dev/null 2>&1; then "
        "install -m 0755 -d /etc/apt/keyrings && "
        "curl -fsSL https://download.docker.com/linux/ubuntu/gpg "
        "| gpg --dearmor --batch --yes -o /etc/apt/keyrings/docker.gpg && "
        "chmod a+r /etc/apt/keyrings/docker.gpg && "
        'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] '
        'https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" '
        "| tee /etc/apt/sources.list.d/docker.list >/dev/null && "
        "apt-get update && "
        "DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin; "
        "fi",
    ],
    _timeout=300,
)

server.group(
    name="Ensure docker group exists",
    group="docker",
    present=True,
)

server.user(
    name=f"Add {deploy_user} to docker group",
    user=deploy_user,
    groups=["docker"],
    append=True,
)

for path in ("/opt/zeroclaw", "/opt/zeroclaw/states"):
    files.directory(
        name=f"Ensure {path}",
        path=path,
        present=True,
        user=deploy_user,
        group=deploy_user,
        mode="750",
    )

files.template(
    name="Render fail2ban jail.local",
    src="templates/jail.local.j2",
    dest="/etc/fail2ban/jail.local",
    user="root",
    group="root",
    mode="644",
)

server.shell(name="UFW default deny incoming", commands=["ufw default deny incoming"])
server.shell(name="UFW default allow outgoing", commands=["ufw default allow outgoing"])
server.shell(name="UFW allow 22/tcp", commands=["ufw allow 22/tcp"])
server.shell(
    name="UFW allow deploy SSH port",
    commands=[f"ufw allow {host.data.ssh_port}/tcp"],
)
server.shell(name="Enable UFW", commands=["ufw --force enable"])

systemd.service(
    name="Enable and restart fail2ban",
    service="fail2ban",
    running=True,
    restarted=True,
    enabled=True,
)

systemd.service(
    name="Enable and start Docker service",
    service="docker.service",
    running=True,
    enabled=True,
)

systemd.service(
    name="Re-enable unattended-upgrades",
    service="unattended-upgrades",
    running=True,
    enabled=True,
)

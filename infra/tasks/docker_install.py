from pyinfra import host
from pyinfra.operations import apt, server, systemd

deploy_user = host.data.deploy_user

# Stop unattended-upgrades before touching apt. On a fresh Ubuntu 24.04 server
# the service starts immediately after install and holds the dpkg lock for
# 10-20 minutes while applying pending updates — long enough to deadlock our
# Docker install. We stop it here, install Docker, then re-enable it below.
server.shell(
    name="Stop unattended-upgrades to release apt lock",
    commands=[
        # Stop the service first (may already be stopped — || true is intentional).
        "systemctl stop unattended-upgrades || true",
        # Kill any apt/dpkg processes that grabbed the lock before we stopped the service.
        "kill -9 $(lsof /var/lib/dpkg/lock-frontend 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true",
        "kill -9 $(lsof /var/lib/apt/lists/lock 2>/dev/null | awk 'NR>1{print $2}') 2>/dev/null || true",
        # Remove stale lock files left behind by killed processes.
        "rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock /var/lib/apt/lists/lock",
        # Repair any dpkg state interrupted mid-install by a kill.
        # DEBIAN_FRONTEND=noninteractive prevents dpkg from trying to use a tty.
        "DEBIAN_FRONTEND=noninteractive dpkg --configure -a",
    ],
    _timeout=60,
)

# Add Docker's official GPG key using the modern signed-by approach.
# The key is written to a dedicated keyring file, not the deprecated apt-key store.
server.shell(
    name="Create /etc/apt/keyrings directory",
    commands=["install -m 0755 -d /etc/apt/keyrings"],
)

server.shell(
    name="Download Docker GPG key",
    commands=[
        "curl -fsSL https://download.docker.com/linux/ubuntu/gpg"
        " | gpg --dearmor --batch --yes -o /etc/apt/keyrings/docker.gpg",
        "chmod a+r /etc/apt/keyrings/docker.gpg",
    ],
    _timeout=60,
)

# Add Docker's apt repository pinned to the host's Ubuntu codename.
# apt.repo() writes src literally — shell subshells won't expand.
# Use server.shell() with tee to get proper shell expansion.
server.shell(
    name="Add Docker apt repository",
    commands=[
        'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg]'
        " https://download.docker.com/linux/ubuntu"
        ' $(. /etc/os-release && echo $VERSION_CODENAME) stable"'
        " | tee /etc/apt/sources.list.d/docker.list > /dev/null",
    ],
)

apt.update(
    name="Refresh apt index after adding Docker repo",
)

apt.packages(
    name="Install Docker Engine and Compose plugin",
    packages=[
        "docker-ce",
        "docker-ce-cli",
        "containerd.io",
        "docker-compose-plugin",
    ],
)

# Ensure the docker group exists, then add the deploy user to it.
# append=True preserves all existing group memberships.
server.group(
    name="Ensure docker group exists",
    group="docker",
)

server.user(
    name=f"Add {deploy_user} to docker group",
    user=deploy_user,
    groups=["docker"],
    append=True,
)

systemd.service(
    name="Enable and start Docker service",
    service="docker.service",
    running=True,
    enabled=True,
)

# Re-enable unattended-upgrades now that Docker is installed. We stopped it at
# the start of this task to avoid apt lock contention. It must be running so
# security patches continue to apply automatically.
systemd.service(
    name="Re-enable unattended-upgrades",
    service="unattended-upgrades",
    running=True,
    enabled=True,
)

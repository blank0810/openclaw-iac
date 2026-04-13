from pyinfra import host
from pyinfra.operations import apt, server

timezone = host.data.timezone

apt.update(
    name="Refresh apt package index",
)

apt.packages(
    name="Install base packages",
    packages=[
        "curl",
        "git",
        "htop",
        "unattended-upgrades",
        "apt-transport-https",
        "ca-certificates",
        "gnupg",
    ],
)

server.shell(
    name="Set timezone to UTC",
    commands=[f"timedatectl set-timezone {timezone}"],
)

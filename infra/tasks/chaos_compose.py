"""
Upload docker/chaos/docker-compose.yml to /opt/openclaw/chaos/docker-compose.yml.

Idempotent: files.put hashes src, uploads only on diff.
"""

from pyinfra import host
from pyinfra.operations import files

deploy_user = host.data.deploy_user

files.put(
    name="Upload Chaos docker-compose.yml",
    src="docker/chaos/docker-compose.yml",
    dest="/opt/openclaw/chaos/docker-compose.yml",
    user=deploy_user,
    group=deploy_user,
    mode="644",
)

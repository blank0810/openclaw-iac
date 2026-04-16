"""
Render /opt/openclaw/chaos/.env from local environment variables.

Reads via os.environ[] (fail loudly on missing). Mode 600, owned by deploy_user.
Docker reads this via `env_file: .env` in compose; container uses ${VAR}
substitution in openclaw.json to pull tokens from the same env.
"""

import io
import os

from pyinfra import host
from pyinfra.operations import files

deploy_user = host.data.deploy_user

# Required — fail the deploy loudly if any are missing from local .env.
required_vars = [
    "CHAOS_IMAGE",
    "CHAOS_GATEWAY_TOKEN",
    "CHAOS_LITELLM_BASE_URL",
    "CHAOS_LITELLM_API_KEY",
    "CHAOS_SLACK_BOT_TOKEN",
    "CHAOS_SLACK_APP_TOKEN",
    "CHAOS_SLACK_SIGNING_SECRET",
    "SEARXNG_IMAGE",
    "SEARXNG_SECRET_KEY",
]

env_lines = [f"TZ={os.environ.get('TZ', 'UTC')}"]
for var in required_vars:
    env_lines.append(f"{var}={os.environ[var]}")

env_content = "\n".join(env_lines) + "\n"

files.put(
    name="Upload /opt/openclaw/chaos/.env",
    src=io.StringIO(env_content),
    dest="/opt/openclaw/chaos/.env",
    user=deploy_user,
    group=deploy_user,
    mode="600",
)

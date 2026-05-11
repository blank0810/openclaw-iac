"""
agent_new.py - Deploy or update one tenant.

Reads AGENT_NAME from env (set by the agentctl wrapper). The wrapper also
sources tenants/<name>/.env on top of the root .env before invoking pyinfra,
so per-tenant SLACK_BOT_TOKEN / ANTHROPIC_API_KEY / etc. are visible here.

Idempotent: re-running this task on an existing tenant re-renders config,
re-syncs workspace, and `compose up --force-recreate`.
"""

import os
import re
from io import StringIO

from pyinfra import host
from pyinfra.operations import apt, files, server, systemd

AGENT_NAME = os.environ.get("AGENT_NAME", "").strip()
SLUG_RE = re.compile(r"^agent-[a-z0-9]([a-z0-9-]{0,27}[a-z0-9])?$")

if not SLUG_RE.match(AGENT_NAME):
    raise RuntimeError(
        f"agent_new.py - invalid AGENT_NAME: {AGENT_NAME!r}. "
        f"Must match {SLUG_RE.pattern}."
    )

agent_dir = f"/opt/{AGENT_NAME}"
deploy_user = host.data.deploy_user

provider = os.environ.get("ZEROCLAW_PROVIDER", "anthropic").strip().lower()
if provider not in ("anthropic", "litellm"):
    raise RuntimeError(
        f"ZEROCLAW_PROVIDER must be anthropic or litellm, got {provider!r}"
    )

if provider == "litellm":
    REQUIRED_ENV = ["ZEROCLAW_IMAGE", "LITELLM_BASE_URL", "LITELLM_API_KEY"]
else:
    REQUIRED_ENV = ["ZEROCLAW_IMAGE", "ANTHROPIC_API_KEY"]

missing = [key for key in REQUIRED_ENV if not os.environ.get(key)]
if missing:
    raise RuntimeError(
        "agent_new.py - missing required env vars: "
        + ", ".join(missing)
        + ". Populate them in tenants/<name>/.env and re-run."
    )

zeroclaw_image = os.environ["ZEROCLAW_IMAGE"]
zeroclaw_model = os.environ.get("ZEROCLAW_MODEL", "claude-haiku-4-5")
tz = os.environ.get("TZ", "UTC")
agent_chat_name = os.environ.get("AGENT_NAME_DISPLAY", AGENT_NAME).strip() or AGENT_NAME

anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
litellm_base_url = os.environ.get("LITELLM_BASE_URL", "")
litellm_api_key = os.environ.get("LITELLM_API_KEY", "")

slack_bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
slack_app_token = os.environ.get("SLACK_APP_TOKEN", "")
slack_channel_id = os.environ.get("SLACK_CHANNEL_ID", "")
slack_allowed_users = os.environ.get("SLACK_ALLOWED_USERS", "")

_slack_mention_only_raw = os.environ.get("SLACK_MENTION_ONLY", "false").strip().lower()
slack_mention_only = (
    "true" if _slack_mention_only_raw in ("true", "yes", "on", "1") else "false"
)
_slack_thread_replies_raw = os.environ.get("SLACK_THREAD_REPLIES", "true").strip().lower()
slack_thread_replies = (
    "false"
    if _slack_thread_replies_raw in ("false", "no", "off", "0")
    else "true"
)
_slack_use_md_raw = os.environ.get("SLACK_USE_MARKDOWN_BLOCKS", "true").strip().lower()
slack_use_markdown_blocks = (
    "false" if _slack_use_md_raw in ("false", "no", "off", "0") else "true"
)
_slack_stream_drafts_raw = os.environ.get("SLACK_STREAM_DRAFTS", "false").strip().lower()
slack_stream_drafts = (
    "true" if _slack_stream_drafts_raw in ("true", "yes", "on", "1") else "false"
)

composio_api_key = os.environ.get("COMPOSIO_API_KEY", "")
composio_entity_id = os.environ.get("COMPOSIO_ENTITY_ID", "default")
composio_mcp_url = os.environ.get("COMPOSIO_MCP_URL", "")
composio_mcp_transport = os.environ.get("COMPOSIO_MCP_TRANSPORT", "sse")
composio_mcp_auth_header = os.environ.get("COMPOSIO_MCP_AUTH_HEADER", "Authorization")
composio_mcp_api_key = os.environ.get("COMPOSIO_MCP_API_KEY", "")

apt.packages(
    name=f"[{AGENT_NAME}] install jq for slack probe",
    packages=["jq"],
)

DIR_LAYOUT = [
    ("", deploy_user, deploy_user, "750"),
    ("/config", deploy_user, deploy_user, "755"),
    ("/data", "nobody", "nogroup", "750"),
    ("/data/.zeroclaw", "nobody", "nogroup", "750"),
    ("/data/workspace", "nobody", "nogroup", "750"),
]
for sub, owner, grp, mode in DIR_LAYOUT:
    files.directory(
        name=f"[{AGENT_NAME}] ensure {agent_dir}{sub}",
        path=f"{agent_dir}{sub}",
        present=True,
        user=owner,
        group=grp,
        mode=mode,
    )

files.template(
    name=f"[{AGENT_NAME}] render config.toml",
    src="docker/agent/config/config.toml.j2",
    dest=f"{agent_dir}/config/config.toml",
    user="nobody",
    group="nogroup",
    mode="640",
    provider=provider,
    anthropic_api_key=anthropic_api_key,
    litellm_base_url=litellm_base_url,
    litellm_api_key=litellm_api_key,
    zeroclaw_model=zeroclaw_model,
    slack_bot_token=slack_bot_token,
    slack_app_token=slack_app_token,
    slack_channel_id=slack_channel_id,
    slack_allowed_users=slack_allowed_users,
    slack_mention_only=slack_mention_only,
    slack_thread_replies=slack_thread_replies,
    slack_use_markdown_blocks=slack_use_markdown_blocks,
    slack_stream_drafts=slack_stream_drafts,
    composio_api_key=composio_api_key,
    composio_entity_id=composio_entity_id,
    composio_mcp_url=composio_mcp_url,
    composio_mcp_transport=composio_mcp_transport,
    composio_mcp_auth_header=composio_mcp_auth_header,
    composio_mcp_api_key=composio_mcp_api_key,
)

workspace_src = "docker/agent/workspace"
for fname in sorted(os.listdir(workspace_src)) if os.path.isdir(workspace_src) else []:
    if fname == "MEMORY.md":
        continue
    is_template = fname.endswith(".md.j2")
    if not (fname.endswith(".md") or is_template):
        continue
    dest_name = fname[:-3] if is_template else fname
    src_path = f"{workspace_src}/{fname}"
    dest_path = f"{agent_dir}/data/workspace/{dest_name}"
    if is_template:
        files.template(
            name=f"[{AGENT_NAME}] render workspace/{dest_name}",
            src=src_path,
            dest=dest_path,
            user="nobody",
            group="nogroup",
            mode="640",
            provider=provider,
            composio_mcp_url=composio_mcp_url,
            agent_name=agent_chat_name,
        )
    else:
        files.put(
            name=f"[{AGENT_NAME}] upload workspace/{fname}",
            src=src_path,
            dest=dest_path,
            user="nobody",
            group="nogroup",
            mode="640",
        )

files.template(
    name=f"[{AGENT_NAME}] render docker-compose.yml",
    src="docker/agent/docker-compose.yml.j2",
    dest=f"{agent_dir}/docker-compose.yml",
    user=deploy_user,
    group=deploy_user,
    mode="640",
    agent_name=AGENT_NAME,
)

remote_env = "\n".join(
    [
        f"# Generated by agent_new.py for {AGENT_NAME} - do not edit.",
        f"ZEROCLAW_IMAGE={zeroclaw_image}",
        f"TZ={tz}",
        "",
    ]
)
files.put(
    name=f"[{AGENT_NAME}] upload remote .env",
    src=StringIO(remote_env),
    dest=f"{agent_dir}/.env",
    user=deploy_user,
    group=deploy_user,
    mode="600",
)

server.shell(
    name=f"[{AGENT_NAME}] docker compose pull",
    commands=[f"cd {agent_dir} && docker compose pull"],
    _sudo=True,
    _timeout=300,
)

server.shell(
    name=f"[{AGENT_NAME}] docker compose up -d --force-recreate",
    commands=[f"cd {agent_dir} && docker compose up -d --force-recreate"],
    _sudo=True,
    _timeout=180,
)

healthcheck_cmd = (
    "for i in $(seq 1 48); do "
    f"  status=$(docker inspect -f '{{{{.State.Health.Status}}}}' {AGENT_NAME} "
    "2>/dev/null || echo missing); "
    "  if [ \"$status\" = healthy ]; then echo healthy; exit 0; fi; "
    "  sleep 5; "
    "done; "
    f"echo '{AGENT_NAME} never reached healthy after 240s' >&2; "
    f"docker logs --tail=100 {AGENT_NAME} >&2 || true; "
    "exit 1"
)
server.shell(
    name=f"[{AGENT_NAME}] wait for healthy (up to 240s)",
    commands=[healthcheck_cmd],
    _sudo=True,
    _timeout=300,
)

files.directory(
    name=f"[{AGENT_NAME}] ensure {agent_dir}/bin",
    path=f"{agent_dir}/bin",
    present=True,
    user=deploy_user,
    group=deploy_user,
    mode="750",
)
files.directory(
    name=f"[{AGENT_NAME}] ensure /var/lib/{AGENT_NAME}-probe",
    path=f"/var/lib/{AGENT_NAME}-probe",
    present=True,
    user="root",
    group="root",
    mode="750",
)
files.file(
    name=f"[{AGENT_NAME}] ensure /var/log/{AGENT_NAME}-probe.log",
    path=f"/var/log/{AGENT_NAME}-probe.log",
    present=True,
    user="root",
    group="root",
    mode="640",
)
files.put(
    name=f"[{AGENT_NAME}] upload slack-probe.sh",
    src="infra/files/agent-slack-probe.sh",
    dest=f"{agent_dir}/bin/slack-probe.sh",
    user=deploy_user,
    group=deploy_user,
    mode="750",
)
files.template(
    name=f"[{AGENT_NAME}] render probe service unit",
    src="infra/files/agent-slack-probe.service.j2",
    dest=f"/etc/systemd/system/{AGENT_NAME}-slack-probe.service",
    user="root",
    group="root",
    mode="600",
    agent_name=AGENT_NAME,
    slack_app_token=slack_app_token,
)
files.template(
    name=f"[{AGENT_NAME}] render probe timer unit",
    src="infra/files/agent-slack-probe.timer.j2",
    dest=f"/etc/systemd/system/{AGENT_NAME}-slack-probe.timer",
    user="root",
    group="root",
    mode="644",
    agent_name=AGENT_NAME,
)
systemd.daemon_reload(name=f"[{AGENT_NAME}] systemctl daemon-reload")
systemd.service(
    name=f"[{AGENT_NAME}] enable + start probe timer",
    service=f"{AGENT_NAME}-slack-probe.timer",
    running=True,
    enabled=True,
)

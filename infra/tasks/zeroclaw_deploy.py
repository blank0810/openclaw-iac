"""
zeroclaw_deploy.py — Deploy the ZeroClaw runtime to Server 3.

Run as overlord101 during the standard deploy (infra/deploy.py).
Idempotent: safe to re-run after any change to docker-compose.yml,
config.toml.j2, or the workspace seed files under docker/zeroclaw/workspace/.

Steps:
  1. Ensure /opt/zeroclaw/{config,data,data/workspace} exist, owned by
     overlord101, mode 0750.
  2. Render docker/zeroclaw/config/config.toml.j2 -> /opt/zeroclaw/config/
     config.toml (mode 0640) using values from the local .env.
  3. Sync docker/zeroclaw/workspace/ -> /opt/zeroclaw/data/workspace/
     (re-render every deploy; IaC is the source of truth for the agent's
     identity, autonomy posture, and security guardrails).
  4. Upload docker/zeroclaw/docker-compose.yml.
  5. Render + upload remote .env (mode 0600).
  6. docker compose pull + docker compose up -d.
  7. Poll docker container health up to 240s — fail loudly on timeout.

Required local env vars (read from the laptop's .env via `set -a; source
.env; set +a`). Missing vars raise RuntimeError and abort the run:
  ZEROCLAW_IMAGE
  ANTHROPIC_API_KEY  (when ZEROCLAW_PROVIDER=anthropic)
  LITELLM_BASE_URL   (when ZEROCLAW_PROVIDER=litellm)
  LITELLM_API_KEY    (when ZEROCLAW_PROVIDER=litellm)

Optional (defaults shown):
  ZEROCLAW_PROVIDER  (default: "anthropic"; "litellm" routes via Server 2)
  ZEROCLAW_MODEL     (default: "claude-haiku-4-5")
  TZ                 (default: "UTC")
"""

import os
from io import StringIO

from pyinfra import host
from pyinfra.operations import files, server

deploy_user = host.data.deploy_user           # "overlord101"
zeroclaw_dir = host.data.zeroclaw_dir         # "/opt/zeroclaw"

provider = os.environ.get("ZEROCLAW_PROVIDER", "anthropic").strip().lower()
if provider not in ("anthropic", "litellm"):
    raise RuntimeError(
        f"zeroclaw_deploy.py — ZEROCLAW_PROVIDER must be 'anthropic' or "
        f"'litellm', got {provider!r}."
    )

if provider == "litellm":
    REQUIRED_ENV = ["ZEROCLAW_IMAGE", "LITELLM_BASE_URL", "LITELLM_API_KEY"]
else:
    REQUIRED_ENV = ["ZEROCLAW_IMAGE", "ANTHROPIC_API_KEY"]

missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
if missing:
    raise RuntimeError(
        "zeroclaw_deploy.py — missing required env vars: "
        + ", ".join(missing)
        + ". Populate them in the local .env and re-run."
    )

zeroclaw_image = os.environ["ZEROCLAW_IMAGE"]
zeroclaw_model = os.environ.get("ZEROCLAW_MODEL", "claude-haiku-4-5")
tz = os.environ.get("TZ", "UTC")

# Display name the agent uses in chat (Slack, etc.). Default "ZeroClaw"
# preserves prior behavior. Set AGENT_NAME=Chaos (or any string) to align
# the agent's self-identification with the Slack app name the operator
# interacts with. Threaded through every workspace .md.j2 template via
# the {{ agent_name }} variable. The runtime/binary/repo/IaC stay
# "ZeroClaw" — only the chat persona changes.
agent_name = os.environ.get("AGENT_NAME", "ZeroClaw").strip() or "ZeroClaw"

# Provider-specific creds. The template only references the variable that
# matches the active provider — passing both is harmless and keeps the
# render step branch-free here.
anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
litellm_base_url = os.environ.get("LITELLM_BASE_URL", "")
litellm_api_key = os.environ.get("LITELLM_API_KEY", "")

# Slack channel (optional — only rendered into config.toml when SLACK_BOT_TOKEN
# is set). app_token enables Socket Mode; channel_id scopes listening to a
# single channel/DM; allowed_users is a TOML array literal as a string (e.g.
# '["U01ABC", "U02DEF"]'). When unset, the template falls back to ["*"], which
# is permissive — set SLACK_ALLOWED_USERS the moment you know the operator's
# Slack user ID.
slack_bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
slack_app_token = os.environ.get("SLACK_APP_TOKEN", "")
slack_channel_id = os.environ.get("SLACK_CHANNEL_ID", "")
slack_allowed_users = os.environ.get("SLACK_ALLOWED_USERS", "")
# mention_only=true: bot ignores channel messages unless @-mentioned. DMs
# always pass through. Normalize loose env values (true/yes/on/1) to TOML
# bool literals so the rendered config is always valid.
_slack_mention_only_raw = os.environ.get("SLACK_MENTION_ONLY", "false").strip().lower()
slack_mention_only = "true" if _slack_mention_only_raw in ("true", "yes", "on", "1") else "false"
# thread_replies=true (upstream default): replies post in-thread.
# thread_replies=false: each reply posts as a new top-level message.
_slack_thread_replies_raw = os.environ.get("SLACK_THREAD_REPLIES", "true").strip().lower()
slack_thread_replies = "false" if _slack_thread_replies_raw in ("false", "no", "off", "0") else "true"
# use_markdown_blocks=true: emit Slack's newer `markdown` block type
# (renders GFM **bold**, - lists, etc. correctly). false = legacy mrkdwn
# only (Slack-flavored *bold*). Default to true since most LLM output is GFM.
_slack_use_md_raw = os.environ.get("SLACK_USE_MARKDOWN_BLOCKS", "true").strip().lower()
slack_use_markdown_blocks = "false" if _slack_use_md_raw in ("false", "no", "off", "0") else "true"
# stream_drafts=false (upstream default): bot posts a single complete reply
# instead of progressively editing a draft via chat.update. Quieter UX in
# group channels and avoids the visual flicker of partial messages. Set
# SLACK_STREAM_DRAFTS=true if you want progressive draft streaming back.
_slack_stream_drafts_raw = os.environ.get("SLACK_STREAM_DRAFTS", "false").strip().lower()
slack_stream_drafts = "true" if _slack_stream_drafts_raw in ("true", "yes", "on", "1") else "false"

# Composio managed-OAuth tools (optional — only rendered into config.toml when
# COMPOSIO_API_KEY is set). The composio tool is intentionally NOT auto-
# approved; every connect/execute call requires per-invocation operator
# approval under supervised autonomy.
composio_api_key = os.environ.get("COMPOSIO_API_KEY", "")
composio_entity_id = os.environ.get("COMPOSIO_ENTITY_ID", "default")

# Composio MCP path (optional — only rendered into config.toml when
# COMPOSIO_MCP_URL is set). Connects ZeroClaw's MCP client to Composio's
# hosted MCP server; each toolkit tool becomes a first-class tool with
# prefix `composio__<name>`. Auth is provided via a single configurable
# header (e.g. "x-consumer-api-key" for Composio, or "Authorization"
# with value "Bearer <token>" for a generic OAuth bearer flow).
composio_mcp_url = os.environ.get("COMPOSIO_MCP_URL", "")
composio_mcp_transport = os.environ.get("COMPOSIO_MCP_TRANSPORT", "sse")
composio_mcp_auth_header = os.environ.get("COMPOSIO_MCP_AUTH_HEADER", "Authorization")
composio_mcp_api_key = os.environ.get("COMPOSIO_MCP_API_KEY", "")

# ---------------------------------------------------------------------------
# 1. Ensure host directories exist with correct ownership/mode.
#    Bind mounts pass through host ownership unchanged, so each path must
#    match who reads/writes it inside the container:
#      - /opt/zeroclaw           overlord101 owns (compose + .env live here)
#      - /opt/zeroclaw/config    overlord101 owns; mode 0755 so the
#                                container UID can traverse to read config.toml
#      - /opt/zeroclaw/data      nobody:nogroup (UID/GID 65534) — the
#                                container runs as 65534 (USER 65534:65534
#                                in apps/zeroclaw/upstream/Dockerfile.debian)
#                                and writes sqlite + workspace state here.
#      - /opt/zeroclaw/data/.zeroclaw  pre-created so the read-only bind
#                                mount of config.toml at
#                                /zeroclaw-data/.zeroclaw/config.toml lands
#                                inside a 65534-owned dir; otherwise Docker
#                                materialises the parent as root and the
#                                container's `Failed to create config
#                                directory` crash loop returns.
#      - /opt/zeroclaw/data/workspace  same UID/GID as /data
# ---------------------------------------------------------------------------
DIR_LAYOUT = [
    # (relative path, owner, group, mode)
    ("",                deploy_user, deploy_user, "750"),
    ("/config",         deploy_user, deploy_user, "755"),
    ("/data",           "nobody",    "nogroup",   "750"),
    ("/data/.zeroclaw", "nobody",    "nogroup",   "750"),
    ("/data/workspace", "nobody",    "nogroup",   "750"),
]
for sub, owner, grp, mode in DIR_LAYOUT:
    files.directory(
        name=f"Ensure {zeroclaw_dir}{sub} exists",
        path=f"{zeroclaw_dir}{sub}",
        present=True,
        user=owner,
        group=grp,
        mode=mode,
    )

# ---------------------------------------------------------------------------
# 2. Render config.toml from Jinja template. The template branches on
#    `provider`: "anthropic" wires ZeroClaw straight to the Anthropic
#    Messages API, "litellm" wires it to Cloudesk's LiteLLM proxy on
#    Server 2 (custom:<base_url> with a virtual key). Flip
#    ZEROCLAW_PROVIDER in .env and re-run this deploy to swap the live
#    route — the toml is re-rendered atomically, the container picks it
#    up on the compose-up step below.
# ---------------------------------------------------------------------------
files.template(
    name="Render zeroclaw config.toml",
    src="docker/zeroclaw/config/config.toml.j2",
    dest=f"{zeroclaw_dir}/config/config.toml",
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

# ---------------------------------------------------------------------------
# 3. Sync the workspace seed files. These are the agent's effective system
#    prompt (SOUL/IDENTITY/AGENTS/TOOLS/BOOTSTRAP/HEARTBEAT). Re-rendered
#    every deploy on purpose: any drift from the IaC source of truth is a
#    security regression. MEMORY.md is intentionally NOT seeded — the
#    runtime owns it.
#
#    Files ending in `.j2` are rendered through Jinja with `provider` and
#    related context so the agent's self-description (IDENTITY/USER) stays
#    in lockstep with config.toml. Plain `.md` files are uploaded verbatim.
# ---------------------------------------------------------------------------
workspace_src = "docker/zeroclaw/workspace"
for fname in sorted(os.listdir(workspace_src)) if os.path.isdir(workspace_src) else []:
    if fname == "MEMORY.md":
        continue
    is_template = fname.endswith(".md.j2")
    if not (fname.endswith(".md") or is_template):
        continue
    dest_name = fname[:-3] if is_template else fname  # strip ".j2"
    src_path = f"{workspace_src}/{fname}"
    dest_path = f"{zeroclaw_dir}/data/workspace/{dest_name}"
    if is_template:
        files.template(
            name=f"Render workspace/{dest_name}",
            src=src_path,
            dest=dest_path,
            user="nobody",
            group="nogroup",
            mode="640",
            provider=provider,
            composio_mcp_url=composio_mcp_url,
            agent_name=agent_name,
        )
    else:
        files.put(
            name=f"Upload workspace/{fname}",
            src=src_path,
            dest=dest_path,
            user="nobody",
            group="nogroup",
            mode="640",
        )

# ---------------------------------------------------------------------------
# 4. Upload docker-compose.yml.
# ---------------------------------------------------------------------------
files.put(
    name="Upload zeroclaw docker-compose.yml",
    src="docker/zeroclaw/docker-compose.yml",
    dest=f"{zeroclaw_dir}/docker-compose.yml",
    user=deploy_user,
    group=deploy_user,
    mode="640",
)

# ---------------------------------------------------------------------------
# 5. Render + upload remote .env (mode 0600). Compose reads this from the
#    same dir as docker-compose.yml. ZEROCLAW_IMAGE drives the image pin;
#    TZ drives the container timezone. LiteLLM creds are NOT needed in
#    the container env — they live in config.toml only.
# ---------------------------------------------------------------------------
remote_env = "\n".join([
    "# Generated by infra/tasks/zeroclaw_deploy.py — do not edit by hand.",
    "# Re-run `pyinfra infra/inventories/deploy.py infra/deploy.py` to regenerate.",
    "",
    f"ZEROCLAW_IMAGE={zeroclaw_image}",
    f"TZ={tz}",
    "",
])
files.put(
    name="Upload rendered .env for zeroclaw",
    src=StringIO(remote_env),
    dest=f"{zeroclaw_dir}/.env",
    user=deploy_user,
    group=deploy_user,
    mode="600",
)

# ---------------------------------------------------------------------------
# 6. docker compose pull + up -d. Run via sudo so the deploy succeeds on the
#    very first run against a fresh server: docker_install.py adds overlord101
#    to the docker group earlier in this same pyinfra invocation, but the
#    existing SSH session inherits the pre-add group set, so a non-sudo
#    `docker compose pull` would hit EACCES on /var/run/docker.sock. Sudo runs
#    as root, which accesses the socket directly and is invariant to group
#    membership. overlord101 is still in the docker group for human ergonomics
#    (interactive `docker ps` over SSH without sudo).
# ---------------------------------------------------------------------------
server.shell(
    name="Pull zeroclaw image",
    commands=[f"cd {zeroclaw_dir} && docker compose pull"],
    _sudo=True,
    _timeout=300,
)

server.shell(
    name="Bring zeroclaw stack up (compose up -d --force-recreate)",
    commands=[f"cd {zeroclaw_dir} && docker compose up -d --force-recreate"],
    _sudo=True,
    _timeout=180,
)
# --force-recreate is intentional: config.toml + workspace seeds are
# bind-mounted, so content changes are invisible to compose's normal
# change detection (no image/env/volume-spec drift). Recreating on every
# deploy is the only reliable way to make the container re-read config —
# the cost is a ~2s blip per deploy, which is acceptable for an IaC tool
# that runs deliberately.

# ---------------------------------------------------------------------------
# 7. Poll Docker's healthcheck up to 240s. ZeroClaw exposes
#    `zeroclaw status --format=exit-code` as the in-container probe.
# ---------------------------------------------------------------------------
healthcheck_cmd = (
    "for i in $(seq 1 48); do "
    "  status=$(docker inspect -f '{{.State.Health.Status}}' zeroclaw 2>/dev/null || echo missing); "
    "  if [ \"$status\" = healthy ]; then echo healthy; exit 0; fi; "
    "  sleep 5; "
    "done; "
    "echo 'zeroclaw container never reached healthy state after 240s' >&2; "
    "docker logs --tail=100 zeroclaw >&2 || true; "
    "exit 1"
)
server.shell(
    name="Wait for zeroclaw container healthy (up to 240s)",
    commands=[healthcheck_cmd],
    _sudo=True,
    _timeout=300,
)

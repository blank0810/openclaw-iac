> **⚠️ SUPERSEDED 2026-04-21** — OpenClaw is scratched as a project
> direction. Do NOT execute this plan. Kept as a historical artifact of
> the brainstorm + plan-writing process.

# Chaos — Slack + Full Tool Surface Implementation Plan

> ~~**For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.~~ (superseded — do not execute)

**Goal:** Wire the deployed `chaos` agent to Slack (Socket Mode) and enable full OpenClaw tool surface (minus `fs.delete` + `elevated`) with a SearXNG sidecar for web search and three agents for `/model` routing. Fills the scaffolding slots carved by commit `1e19c5c`.

**Architecture:** No architecture changes — we're filling empty slots. Chaos compose gains a `searxng` sibling service on `chaos_net`. `openclaw.json` flips `channels: {}` → populated Slack block, `tools.allow` from `["gateway"]` → full surface, `plugins.enabled: true` with `searxng` entry. Pyinfra task extends with settings upload + extra health poll.

**Tech Stack:** Pyinfra 3.x (IaC, runs local, SSH into server), Docker Compose (server runtime), OpenClaw 2026.4.14 (agent image), SearXNG (web-search sidecar), Slack Socket Mode (outbound WebSocket, no public URL).

**Design doc:** `docs/plans/2026-04-21-chaos-slack-and-tools-design.md` (commit `e3e1fc8`).

**Starting state:** commit `1e19c5c` on `main`, Chaos gateway-only container live and healthy on Server 3 since 2026-04-19.

---

## Phase 0 — Pre-deploy manual gates (non-code, block implementation)

These must all pass before any code is edited. Each is a 1-2 minute check; all are reversible/idempotent.

### Task 0.1: Verify LiteLLM aliases on Server 2

**Why:** `/model complex` and `/model local` will fail unless Server 2 serves those aliases. We'd rather know now than discover it post-deploy.

**Step 1: SSH to Server 2 and check the LiteLLM config**

```bash
ssh <server2-user>@<server2-ip>
# find the LiteLLM config — path varies but commonly:
sudo cat /opt/litellm/config.yaml 2>/dev/null || sudo docker exec litellm cat /app/config.yaml
```

**Step 2: Grep for the three aliases**

Expected: each of `simple-chaos`, `complex-chaos`, `local` appears as a `model_name` entry with a valid backend (`litellm_params.model: ...`).

**Step 3: Decide based on result**

- **All three exist** → proceed to Task 0.2.
- **Only `simple-chaos` exists** → stop the plan; either add the other two to LiteLLM first (separate task, outside this plan) or amend the design doc to drop `chaos-complex` / `chaos-local` agents. Prefer adding them if the Server-2 config is editable.
- **None exist** → the currently-deployed gateway-only chaos is already broken; stop and investigate before doing anything else.

### Task 0.2: Verify Slack app dashboard (OpenClaw-Test)

**Why:** Socket Mode requires specific toggles and scopes. Missing any means the bot never connects, which looks identical to "our config is wrong" in logs.

**Step 1: Open https://api.slack.com/apps and select the OpenClaw-Test app**

**Step 2: Verify these toggles on the left sidebar**

- **Socket Mode**: ON. If off, flip on — it generates an `xapp-...` App-Level Token with `connections:write`. Copy it if newly generated.
- **Agents & AI Apps**: "Agent or Assistant" toggle ON. Required for DMs to route correctly.
- **App Home → Messages Tab**: ON, with "Allow users to send Slash commands and messages" checked.
- **Event Subscriptions**: ON. Subscribe to bot events: `app_mention`, `message.channels`, `message.groups`, `message.im`.

**Step 3: Verify OAuth & Permissions → Bot Token Scopes (18)**

All of these must be present:
```
app_mentions:read, channels:history, channels:read, chat:write,
commands, files:read, files:write, groups:history, groups:read,
im:history, im:read, im:write, mpim:history, mpim:read, mpim:write,
reactions:read, reactions:write, users:read
```

Note: `assistant:write` is auto-added by Slack when "Agents & AI Apps" is on — don't add manually.

**Step 4: Copy the two tokens**

- Bot Token (`xoxb-...`) from OAuth & Permissions page.
- App-Level Token (`xapp-...`) from Basic Information → App-Level Tokens section.

Keep them in a password manager, not a chat buffer.

### Task 0.3: Choose the SearXNG image pin

**Why:** `:latest` violates repo convention and the design doc. We need `tag + digest`.

**Step 1: Pull the image locally to grab its digest**

```bash
docker pull searxng/searxng:2026.3.1
docker inspect searxng/searxng:2026.3.1 --format '{{index .RepoDigests 0}}'
```

Expected output: `searxng/searxng@sha256:<64-hex-chars>`.

**Step 2: Construct the pinned reference**

Combine tag + digest:

```
searxng/searxng:2026.3.1@sha256:<digest>
```

Hold this value — it becomes `CHAOS_SEARXNG_IMAGE` in `.env` in Task 0.5.

**Substitute `2026.3.1`** with whatever the current stable SearXNG tag is if that one is already outdated at implementation time. Check https://hub.docker.com/r/searxng/searxng/tags.

### Task 0.4: Generate SearXNG secret key

**Step 1: Generate a 32-byte hex string**

```bash
openssl rand -hex 32
```

**Step 2: Copy the output**

Will become `CHAOS_SEARXNG_SECRET_KEY` in `.env` in Task 0.5.

### Task 0.5: Populate local `.env` with all required + new vars

**Step 1: Edit the local `.env` at the project root**

Add / update these lines:

```bash
# SearXNG (new)
CHAOS_SEARXNG_IMAGE=searxng/searxng:2026.3.1@sha256:<digest-from-0.3>
CHAOS_SEARXNG_SECRET_KEY=<hex-string-from-0.4>
CHAOS_SEARXNG_BASE_URL=http://searxng:8080

# Slack (fill from 0.2)
CHAOS_SLACK_BOT_TOKEN=xoxb-...
CHAOS_SLACK_APP_TOKEN=xapp-...
CHAOS_SLACK_SIGNING_SECRET=<from-Slack-dashboard-Basic-Information>
```

Existing `CHAOS_IMAGE`, `CHAOS_GATEWAY_TOKEN`, `CHAOS_LITELLM_BASE_URL`, `CHAOS_LITELLM_API_KEY` should already be populated (from the 2026-04-19 successful deploy). Leave them as-is.

**Step 2: Verify `.env` is still gitignored**

```bash
git check-ignore -v .env
```

Expected: `.gitignore:<line>:/.env  .env` (confirms the file is ignored).

**Step 3: Smoke-test env loading**

```bash
set -a; source .env; set +a
printenv | grep CHAOS_ | wc -l
```

Expected: `9` (CHAOS_IMAGE, CHAOS_GATEWAY_TOKEN, CHAOS_LITELLM_*×2, CHAOS_SLACK_*×3, CHAOS_SEARXNG_*×3 = 10 — correct count is **10**, use `10` as expected).

Actually count: IMAGE(1) + GATEWAY_TOKEN(1) + LITELLM×2(2) + SLACK×3(3) + SEARXNG×3(3) = **10**. If output is 10, proceed. If less, find the missing var in your `.env`.

### Phase 0 gate

**Do NOT proceed to Phase 1 until all of 0.1–0.5 pass.** If any fail, the plan doesn't know enough to execute safely.

---

## Phase 1 — SearXNG sidecar artifacts

All file creations/edits in this phase are local-only. No server changes yet. One commit at the end.

### Task 1.1: Create SearXNG settings.yml

**Files:**
- Create: `docker/chaos/config/searxng/settings.yml`

**Step 1: Create the containing directory**

```bash
mkdir -p docker/chaos/config/searxng
```

**Step 2: Write settings.yml exactly as below**

Use the Write tool to create `docker/chaos/config/searxng/settings.yml` with this content:

```yaml
# SearXNG settings.yml — rendered + uploaded by infra/tasks/chaos_deploy.py
# to /opt/openclaw/chaos/config/searxng/settings.yml on Server 3.
# The ${CHAOS_SEARXNG_SECRET_KEY} placeholder is substituted at Pyinfra
# render-time (StringIO), NOT at container runtime — SearXNG's native env
# interpolation varies by release.

use_default_settings: true

server:
  secret_key: "${CHAOS_SEARXNG_SECRET_KEY}"
  limiter: false
  image_proxy: false
  method: "GET"

search:
  safe_search: 0
  autocomplete: ""
  formats:
    # ⚠️  Default settings.yml has only [html] and returns HTTP 403 on
    # ?format=json at the format gate. OpenClaw's web-search tool requires
    # json. See memory: searxng_json_format_gotcha.md.
    - html
    - json

general:
  debug: false
  instance_name: "chaos-searxng"

ui:
  query_in_title: false
  infinite_scroll: false

engines: []
```

**Step 3: Verify the file parses as YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('docker/chaos/config/searxng/settings.yml'))"
```

Expected: no output, exit 0. Any error means the YAML is malformed — fix before continuing.

### Task 1.2: Add searxng service to docker-compose.yml

**Files:**
- Modify: `docker/chaos/docker-compose.yml`

**Step 1: Read the current file and identify insertion point**

Current file ends with the `networks:` block at the bottom. Insert the `searxng` service **before** the `networks:` block (as a sibling of `chaos` under `services:`).

**Step 2: Use the Edit tool to insert the new service**

Target the `old_string` as the blank line + `networks:` block at the end. Specifically:

`old_string`:
```
      start_period: 240s

networks:
  chaos_net:
    driver: bridge
```

`new_string`:
```
      start_period: 240s

  searxng:
    image: ${CHAOS_SEARXNG_IMAGE}
    container_name: searxng
    init: true
    restart: unless-stopped
    environment:
      SEARXNG_BASE_URL: "http://searxng:8080/"
      INSTANCE_NAME: "chaos-searxng"
      UWSGI_WORKERS: "2"
      UWSGI_THREADS: "2"
    ports:
      # Loopback-only. For SSH-tunnel debugging:
      #   ssh -L 18790:127.0.0.1:18790 -p 2222 overlord101@<SERVER3_IP>
      - "127.0.0.1:18790:8080"
    volumes:
      - ./config/searxng/settings.yml:/etc/searxng/settings.yml:ro
    networks: [chaos_net]
    cap_drop: [ALL]
    # SearXNG's startup drops privileges internally; needs these caps for that.
    # Revisit if a fully rootless SearXNG image becomes available.
    cap_add: [CHOWN, SETUID, SETGID]
    security_opt:
      - "no-new-privileges:true"
    read_only: true
    tmpfs:
      - /var/cache/searxng:size=50m,mode=0755
      - /var/log/searxng:size=10m,mode=0755
      - /etc/searxng/generated:size=10m,mode=0755
    mem_limit: 256m
    memswap_limit: 256m
    cpus: "0.5"
    pids_limit: 100
    logging:
      driver: json-file
      options:
        max-size: "5m"
        max-file: "3"
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:8080/healthz || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s

networks:
  chaos_net:
    driver: bridge
```

**Step 3: Validate compose file locally**

```bash
cd docker/chaos && docker compose config --quiet && cd -
```

Expected: no output, exit 0. Compose parses and the `${VAR}` refs resolve against the environment you sourced in Task 0.5.

Note: `docker compose config` will show a warning for any unset variables. If `CHAOS_SEARXNG_IMAGE` shows blank, re-source `.env` (`set -a; source .env; set +a`).

### Task 1.3: Update `docker/chaos/.env.example` with SearXNG slots

**Files:**
- Modify: `docker/chaos/.env.example`

**Step 1: Add three new vars after the existing SearXNG section**

Use Edit tool with:

`old_string`:
```
# ============================================
# SearXNG — scaffolding slot, empty on day one.
# Fill when adding the searxng service per design's follow-ups.
# ============================================
CHAOS_SEARXNG_BASE_URL=
```

`new_string`:
```
# ============================================
# SearXNG — sidecar container on chaos_net.
# ============================================

# Image pin — tag + digest, e.g. searxng/searxng:2026.3.1@sha256:<digest>
CHAOS_SEARXNG_IMAGE=

# server.secret_key for SearXNG — generate with: openssl rand -hex 32
CHAOS_SEARXNG_SECRET_KEY=

# Base URL reachable by Chaos (internal DNS on chaos_net).
CHAOS_SEARXNG_BASE_URL=http://searxng:8080
```

### Task 1.4: Update root `.env.example` with SearXNG slots

**Files:**
- Modify: `.env.example` (project root)

**Step 1: Mirror the same three additions**

Use Edit tool with:

`old_string`:
```
# ============================================
# SearXNG — scaffolding slot, empty on day one.
# Fill when adding the searxng service per design's follow-ups.
# ============================================
CHAOS_SEARXNG_BASE_URL=
```

`new_string`:
```
# ============================================
# SearXNG — sidecar container on chaos_net.
# ============================================

# Image pin — tag + digest, e.g. searxng/searxng:2026.3.1@sha256:<digest>
CHAOS_SEARXNG_IMAGE=

# server.secret_key for SearXNG — generate with: openssl rand -hex 32
CHAOS_SEARXNG_SECRET_KEY=

# Base URL reachable by Chaos (internal DNS on chaos_net).
CHAOS_SEARXNG_BASE_URL=http://searxng:8080
```

### Task 1.5: Final local check + Phase 1 commit

**Step 1: Re-run compose validation with env sourced**

```bash
set -a; source .env; set +a
cd docker/chaos && docker compose config > /tmp/compose-validated.yml && cd -
```

Expected: `/tmp/compose-validated.yml` shows both `chaos` and `searxng` services fully expanded with all env vars substituted. No unset-variable warnings.

**Step 2: Review git diff**

```bash
git status --short
git diff --stat
```

Expected changes:
- `A  docker/chaos/config/searxng/settings.yml` (new)
- `M  docker/chaos/docker-compose.yml`
- `M  docker/chaos/.env.example`
- `M  .env.example`

**Step 3: Commit**

```bash
git add docker/chaos/config/searxng/settings.yml \
        docker/chaos/docker-compose.yml \
        docker/chaos/.env.example \
        .env.example
git commit -m "$(cat <<'EOF'
feat(chaos): add searxng sidecar for web search

Sibling service on chaos_net; reached by chaos at http://searxng:8080.
settings.yml enables json format (default is html-only, which returns
HTTP 403 on ?format=json).

Not yet wired into openclaw.json (tools.allow still gateway-only).
Pyinfra task does not yet upload settings.yml. Both follow in
subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit lands. `git log --oneline -1` shows `feat(chaos): add searxng sidecar for web search`.

---

## Phase 2 — openclaw.json rewrite

Single big config edit. Validated locally before commit via `jq`. One commit at the end.

### Task 2.1: Rewrite openclaw.json with full target config

**Files:**
- Modify: `docker/chaos/config/openclaw.json`

**Step 1: Use the Write tool to replace the file with the full target config**

Note: we're replacing wholesale rather than doing 5 surgical Edits because most of the file changes. Write the file with this exact content:

```json
{
  "gateway": {
    "bind": "lan",
    "port": 18789,
    "auth": { "mode": "token", "token": "${CHAOS_GATEWAY_TOKEN}" },
    "tls": { "enabled": false }
  },
  "models": {
    "providers": {
      "litellm": {
        "api": "openai-completions",
        "baseUrl": "${CHAOS_LITELLM_BASE_URL}",
        "apiKey": "${CHAOS_LITELLM_API_KEY}",
        "models": [
          { "id": "simple-chaos",  "name": "Simple Chaos",  "input": ["text"], "contextWindow": 200000, "maxTokens": 8192 },
          { "id": "complex-chaos", "name": "Complex Chaos", "input": ["text"], "contextWindow": 200000, "maxTokens": 8192 },
          { "id": "local",         "name": "Local",         "input": ["text"], "contextWindow": 32000,  "maxTokens": 4096 }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "workspace": "/home/node/.openclaw/workspace",
      "skills": [],
      "model": { "primary": "litellm/simple-chaos", "fallbacks": [] }
    },
    "list": [
      { "id": "chaos",         "default": true, "name": "Chaos",         "identity": { "name": "Chaos",         "emoji": "spider_web" },
        "model": { "primary": "litellm/simple-chaos",  "fallbacks": [] } },
      { "id": "chaos-complex",                  "name": "Chaos Complex", "identity": { "name": "Chaos Complex", "emoji": "brain" },
        "model": { "primary": "litellm/complex-chaos", "fallbacks": [] } },
      { "id": "chaos-local",                    "name": "Chaos Local",   "identity": { "name": "Chaos Local",   "emoji": "house" },
        "model": { "primary": "litellm/local",         "fallbacks": [] } }
    ]
  },
  "session": {
    "scope": "per-sender",
    "dmScope": "per-channel-peer",
    "reset": { "mode": "idle", "idleMinutes": 240 }
  },
  "channels": {
    "slack": {
      "enabled": true,
      "mode": "socket",
      "botToken":      "${CHAOS_SLACK_BOT_TOKEN}",
      "appToken":      "${CHAOS_SLACK_APP_TOKEN}",
      "signingSecret": "${CHAOS_SLACK_SIGNING_SECRET}",
      "dmPolicy": "open",
      "allowFrom": ["*"],
      "groupPolicy": "open",
      "channels": {},
      "capabilities": { "interactiveReplies": true },
      "streaming": { "mode": "partial", "nativeTransport": true },
      "ackReaction": "eyes",
      "typingReaction": "hourglass_flowing_sand"
    }
  },
  "tools": {
    "profile": "messaging",
    "allow": [
      "gateway", "cron", "image",
      "group:fs", "group:memory", "group:web",
      "group:runtime", "group:ui",
      "exec", "sessions_spawn"
    ],
    "deny":  ["fs.delete", "elevated"],
    "web": {
      "search": { "enabled": true, "provider": "searxng", "maxResults": 5 },
      "fetch":  { "enabled": true, "maxChars": 50000 }
    }
  },
  "commands": { "native": "auto", "restart": true, "ownerAllowFrom": [], "useAccessGroups": true },
  "cron":     { "enabled": true },
  "memory":   { "backend": "builtin", "citations": "auto" },
  "plugins":  {
    "enabled": true,
    "entries": {
      "searxng": {
        "enabled": true,
        "config": {
          "webSearch": { "baseUrl": "${CHAOS_SEARXNG_BASE_URL}" }
        }
      }
    }
  },
  "messages": {}
}
```

### Task 2.2: Local JSON validation

**Step 1: Parse with jq**

```bash
jq -e . docker/chaos/config/openclaw.json > /dev/null && echo "valid JSON" || echo "INVALID"
```

Expected: `valid JSON`. Any error means syntax is off — fix before continuing.

**Step 2: Sanity-check key fields**

```bash
jq '.agents.list | length' docker/chaos/config/openclaw.json
# expected: 3

jq '.channels.slack.mode' docker/chaos/config/openclaw.json
# expected: "socket"

jq '.tools.deny' docker/chaos/config/openclaw.json
# expected: ["fs.delete","elevated"]

jq '.cron.enabled' docker/chaos/config/openclaw.json
# expected: true

jq '.plugins.entries.searxng.config.webSearch.baseUrl' docker/chaos/config/openclaw.json
# expected: "${CHAOS_SEARXNG_BASE_URL}"
```

All five should match. If not, re-check the Write output.

### Task 2.3: Phase 2 commit

**Step 1: Review diff**

```bash
git diff docker/chaos/config/openclaw.json
```

Expected: ~40 lines added/changed. The `gateway` and `models` blocks stay identical.

**Step 2: Commit**

```bash
git add docker/chaos/config/openclaw.json
git commit -m "$(cat <<'EOF'
feat(chaos): wire slack + full tool surface in openclaw.json

- channels.slack: socket mode, dmPolicy open, groupPolicy open
  (channel messages are mention-gated by default)
- agents: 3 entries (chaos/chaos-complex/chaos-local) for /model routing
- tools.allow: full surface except fs.delete + elevated
- cron.enabled: true, plugins.enabled: true with searxng entry
- session.dmScope: per-channel-peer
- memory.backend: builtin (qmd not shipped in 4.14 image)

Not yet deployed — pyinfra task still only knows about gateway-only
shape. Next commit extends chaos_deploy.py for searxng settings upload
and the updated remote .env.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Extend chaos_deploy.py

### Task 3.1: Add imports already present — just verify

**Files:**
- Read: `infra/tasks/chaos_deploy.py:33-37`

**Step 1: Confirm `os` and `StringIO` are already imported**

```bash
sed -n '33,37p' infra/tasks/chaos_deploy.py
```

Expected:
```
import os
from io import StringIO

from pyinfra import host
from pyinfra.operations import files, server
```

Both `os` and `StringIO` are there. No import changes needed.

### Task 3.2: Extend REQUIRED_ENV and env_values

**Files:**
- Modify: `infra/tasks/chaos_deploy.py:46-74`

**Step 1: Use Edit to extend REQUIRED_ENV**

`old_string`:
```python
REQUIRED_ENV = [
    "CHAOS_IMAGE",
    "CHAOS_GATEWAY_TOKEN",
    "CHAOS_LITELLM_BASE_URL",
    "CHAOS_LITELLM_API_KEY",
]
```

`new_string`:
```python
REQUIRED_ENV = [
    "CHAOS_IMAGE",
    "CHAOS_GATEWAY_TOKEN",
    "CHAOS_LITELLM_BASE_URL",
    "CHAOS_LITELLM_API_KEY",
    # Slack — all three required once slack channel is enabled in openclaw.json.
    "CHAOS_SLACK_BOT_TOKEN",
    "CHAOS_SLACK_APP_TOKEN",
    "CHAOS_SLACK_SIGNING_SECRET",
    # SearXNG — sidecar service, required once compose references it.
    "CHAOS_SEARXNG_IMAGE",
    "CHAOS_SEARXNG_SECRET_KEY",
    "CHAOS_SEARXNG_BASE_URL",
]
```

**Step 2: Update env_values dict — promote Slack + SearXNG to required**

`old_string`:
```python
env_values = {
    "CHAOS_IMAGE":                os.environ["CHAOS_IMAGE"],
    "TZ":                         os.environ.get("TZ", "UTC"),
    "CHAOS_GATEWAY_TOKEN":        os.environ["CHAOS_GATEWAY_TOKEN"],
    "CHAOS_LITELLM_BASE_URL":     os.environ["CHAOS_LITELLM_BASE_URL"],
    "CHAOS_LITELLM_API_KEY":      os.environ["CHAOS_LITELLM_API_KEY"],
    "CHAOS_SLACK_BOT_TOKEN":      os.environ.get("CHAOS_SLACK_BOT_TOKEN", ""),
    "CHAOS_SLACK_APP_TOKEN":      os.environ.get("CHAOS_SLACK_APP_TOKEN", ""),
    "CHAOS_SLACK_SIGNING_SECRET": os.environ.get("CHAOS_SLACK_SIGNING_SECRET", ""),
    "CHAOS_SEARXNG_BASE_URL":     os.environ.get("CHAOS_SEARXNG_BASE_URL", ""),
}
```

`new_string`:
```python
env_values = {
    "CHAOS_IMAGE":                os.environ["CHAOS_IMAGE"],
    "TZ":                         os.environ.get("TZ", "UTC"),
    "CHAOS_GATEWAY_TOKEN":        os.environ["CHAOS_GATEWAY_TOKEN"],
    "CHAOS_LITELLM_BASE_URL":     os.environ["CHAOS_LITELLM_BASE_URL"],
    "CHAOS_LITELLM_API_KEY":      os.environ["CHAOS_LITELLM_API_KEY"],
    "CHAOS_SLACK_BOT_TOKEN":      os.environ["CHAOS_SLACK_BOT_TOKEN"],
    "CHAOS_SLACK_APP_TOKEN":      os.environ["CHAOS_SLACK_APP_TOKEN"],
    "CHAOS_SLACK_SIGNING_SECRET": os.environ["CHAOS_SLACK_SIGNING_SECRET"],
    "CHAOS_SEARXNG_IMAGE":        os.environ["CHAOS_SEARXNG_IMAGE"],
    "CHAOS_SEARXNG_SECRET_KEY":   os.environ["CHAOS_SEARXNG_SECRET_KEY"],
    "CHAOS_SEARXNG_BASE_URL":     os.environ["CHAOS_SEARXNG_BASE_URL"],
}
```

**Step 3: Extend remote_env_lines to include SearXNG image + secret key**

`old_string`:
```python
    f"CHAOS_SEARXNG_BASE_URL={env_values['CHAOS_SEARXNG_BASE_URL']}",
    "",
]
```

`new_string`:
```python
    f"CHAOS_SEARXNG_IMAGE={env_values['CHAOS_SEARXNG_IMAGE']}",
    f"CHAOS_SEARXNG_SECRET_KEY={env_values['CHAOS_SEARXNG_SECRET_KEY']}",
    f"CHAOS_SEARXNG_BASE_URL={env_values['CHAOS_SEARXNG_BASE_URL']}",
    "",
]
```

### Task 3.3: Add SearXNG settings upload step

**Files:**
- Modify: `infra/tasks/chaos_deploy.py` (insert between steps 4 and 5)

**Step 1: Find insertion point**

The existing step 5 begins at line ~180:
```
# ---------------------------------------------------------------------------
# 5. docker compose pull + up -d.
```

Insert the new step immediately before it.

**Step 2: Use Edit to insert the new step**

`old_string`:
```python
files.put(
    name="Upload rendered .env for chaos",
    src=StringIO(remote_env_content),
    dest=f"{chaos_dir}/.env",
    user=deploy_user,
    group=deploy_user,
    mode="600",
)

# ---------------------------------------------------------------------------
# 5. docker compose pull + up -d.
```

`new_string`:
```python
files.put(
    name="Upload rendered .env for chaos",
    src=StringIO(remote_env_content),
    dest=f"{chaos_dir}/.env",
    user=deploy_user,
    group=deploy_user,
    mode="600",
)

# ---------------------------------------------------------------------------
# 4b. Ensure searxng config dir + upload settings.yml with secret_key
#     substituted. The dir is root-owned (0755) so the cap_drop:ALL
#     container can read it.  settings.yml is rendered in memory from the
#     local template — the secret never lands on disk on the laptop or
#     server outside the chaos .env.
# ---------------------------------------------------------------------------
files.directory(
    name=f"Ensure {chaos_dir}/config/searxng exists",
    path=f"{chaos_dir}/config/searxng",
    present=True,
    user="root",
    group="root",
    mode="755",
    _sudo=True,
)

with open("docker/chaos/config/searxng/settings.yml") as _f:
    _searxng_tmpl = _f.read()
_searxng_rendered = _searxng_tmpl.replace(
    "${CHAOS_SEARXNG_SECRET_KEY}",
    env_values["CHAOS_SEARXNG_SECRET_KEY"],
)
files.put(
    name="Upload searxng settings.yml",
    src=StringIO(_searxng_rendered),
    dest=f"{chaos_dir}/config/searxng/settings.yml",
    user="root",
    group="root",
    mode="644",
    _sudo=True,
)

# ---------------------------------------------------------------------------
# 5. docker compose pull + up -d.
```

### Task 3.4: Add SearXNG healthz poll

**Files:**
- Modify: `infra/tasks/chaos_deploy.py` (insert between steps 6 and 7)

**Step 1: Use Edit to insert after the chaos /healthz poll**

`old_string`:
```python
server.shell(
    name="Wait for chaos /healthz (up to 240s)",
    commands=[healthcheck_cmd],
    _sudo=False,
    _timeout=300,
)

# ---------------------------------------------------------------------------
# 7. Validate the baked openclaw.json against the in-container schema.
```

`new_string`:
```python
server.shell(
    name="Wait for chaos /healthz (up to 240s)",
    commands=[healthcheck_cmd],
    _sudo=False,
    _timeout=300,
)

# ---------------------------------------------------------------------------
# 6b. Poll searxng /healthz separately so failure attribution is clear.
#     Published on 127.0.0.1:18790 by docker-compose.
# ---------------------------------------------------------------------------
searxng_healthcheck_cmd = (
    "for i in $(seq 1 18); do "
    "  if curl -fsS http://127.0.0.1:18790/healthz >/dev/null 2>&1; then "
    "    echo searxng-healthy; exit 0; "
    "  fi; "
    "  sleep 5; "
    "done; "
    "echo 'searxng /healthz never became green after 90s' >&2; "
    "docker logs --tail=100 searxng >&2 || true; "
    "exit 1"
)

server.shell(
    name="Wait for searxng /healthz (up to 90s)",
    commands=[searxng_healthcheck_cmd],
    _sudo=False,
    _timeout=120,
)

# ---------------------------------------------------------------------------
# 7. Validate the baked openclaw.json against the in-container schema.
```

### Task 3.5: Update the file's module docstring

**Files:**
- Modify: `infra/tasks/chaos_deploy.py:1-31`

**Step 1: Update the docstring to reflect new steps + required vars**

Use Edit with:

`old_string`:
```python
"""
chaos_deploy.py — Deploy the Chaos OpenClaw stack to Server 3.

Run as overlord101 during the standard deploy (infra/deploy.py).
Idempotent: safe to re-run after any change to docker-compose.yml,
openclaw.json, or .env values.

Steps (all idempotent):
  1. Ensure /opt/openclaw/chaos/ exists, overlord101:overlord101, mode 0750.
  2. Upload docker-compose.yml.
  3. Upload config/openclaw.json (mode 0640).
  4. Render + upload remote .env (mode 0600) from local os.environ.
  5. docker compose pull + docker compose up -d.
  6. Poll http://127.0.0.1:18789/healthz up to 240s — fail loudly on timeout.
  7. docker compose exec chaos openclaw config validate — fail loudly on
     schema drift.

Required local env vars (read from the laptop's .env via `set -a; source
.env; set +a`). Missing vars raise KeyError and abort the run:
  CHAOS_IMAGE
  CHAOS_GATEWAY_TOKEN
  CHAOS_LITELLM_BASE_URL
  CHAOS_LITELLM_API_KEY

Optional (defaults shown):
  TZ                         (default: "UTC")
  CHAOS_SLACK_BOT_TOKEN      (default: "")
  CHAOS_SLACK_APP_TOKEN      (default: "")
  CHAOS_SLACK_SIGNING_SECRET (default: "")
  CHAOS_SEARXNG_BASE_URL     (default: "")
"""
```

`new_string`:
```python
"""
chaos_deploy.py — Deploy the Chaos OpenClaw stack (+ SearXNG sidecar) to Server 3.

Run as overlord101 during the standard deploy (infra/deploy.py).
Idempotent: safe to re-run after any change to docker-compose.yml,
openclaw.json, settings.yml, or .env values.

Steps (all idempotent):
  1.  Ensure /opt/openclaw/chaos/ exists, overlord101:overlord101, mode 0750.
  2.  Upload docker-compose.yml.
  3.  Upload config/openclaw.json (mode 0640).
  4.  Render + upload remote .env (mode 0600) from local os.environ.
  4b. Ensure /opt/openclaw/chaos/config/searxng/ (root:root, 0755) + upload
      settings.yml (root:root, 0644) with secret_key substituted.
  5.  docker compose pull + docker compose up -d (both services).
  6.  Poll http://127.0.0.1:18789/healthz up to 240s (chaos).
  6b. Poll http://127.0.0.1:18790/healthz up to 90s (searxng).
  7.  docker compose exec chaos openclaw config validate — fail loudly on
      schema drift.

Required local env vars (read from the laptop's .env via `set -a; source
.env; set +a`). Missing vars raise KeyError and abort the run:
  CHAOS_IMAGE
  CHAOS_GATEWAY_TOKEN
  CHAOS_LITELLM_BASE_URL
  CHAOS_LITELLM_API_KEY
  CHAOS_SLACK_BOT_TOKEN
  CHAOS_SLACK_APP_TOKEN
  CHAOS_SLACK_SIGNING_SECRET
  CHAOS_SEARXNG_IMAGE
  CHAOS_SEARXNG_SECRET_KEY
  CHAOS_SEARXNG_BASE_URL

Optional (defaults shown):
  TZ (default: "UTC")
"""
```

### Task 3.6: Syntax-check the Pyinfra task locally

**Step 1: Python parse only (no execution — pyinfra needs its CLI for full eval)**

```bash
python3 -c "compile(open('infra/tasks/chaos_deploy.py').read(), 'chaos_deploy.py', 'exec')"
```

Expected: no output, exit 0. Any `SyntaxError` means a typo — fix before moving on.

**Step 2: Dry-run pyinfra to verify the task plans correctly**

```bash
set -a; source .env; set +a
pyinfra infra/inventories/deploy.py infra/deploy.py --dry 2>&1 | tee /tmp/pyinfra-dry.log
```

Expected: log ends with `--> Pyinfra: Dry completed` (or equivalent), showing new operations:
- `Ensure /opt/openclaw/chaos/config/searxng exists`
- `Upload searxng settings.yml`
- `Wait for searxng /healthz (up to 90s)`

If pyinfra aborts at task-load time with a `KeyError` on an env var, re-check Task 0.5.
If the dry-run shows unexpected operations, read the diff and reconcile before proceeding.

### Task 3.7: Phase 3 commit

```bash
git add infra/tasks/chaos_deploy.py
git commit -m "$(cat <<'EOF'
feat(infra): extend chaos_deploy for searxng sidecar

- Promote CHAOS_SLACK_* + CHAOS_SEARXNG_* to REQUIRED_ENV
- Add step 4b: upload searxng settings.yml (root-owned for cap_drop ALL)
  with secret_key rendered in-memory from CHAOS_SEARXNG_SECRET_KEY
- Add step 6b: poll searxng /healthz (90s bound)
- Extend remote .env rendering with SEARXNG_IMAGE + SECRET_KEY
- Update docstring

Dry-run verified. Ready for live deploy.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — Live deploy + verification

This is where we hit the real server. Each step has an explicit pass/fail test.

### Task 4.1: Final dry-run

```bash
set -a; source .env; set +a
pyinfra infra/inventories/deploy.py infra/deploy.py --dry 2>&1 | tail -30
```

Expected: clean dry-run; operations listed match Phase 3 additions. No errors.

**If this fails:** do NOT proceed to Task 4.2 until the dry-run is clean.

### Task 4.2: Live deploy

```bash
pyinfra infra/inventories/deploy.py infra/deploy.py 2>&1 | tee /tmp/pyinfra-live.log
```

Expected: all operations report `Success`. Final line shows `Pyinfra complete` or equivalent.

**Failure modes and first response:**

| Symptom | First action |
|---|---|
| `openclaw config validate` rejects a key | Read the error — validator names the bad field. Edit `openclaw.json` to fix, commit the fix, re-run Pyinfra. |
| `docker compose pull` fails on `searxng` image | Re-check `CHAOS_SEARXNG_IMAGE` pin in `.env`. Digest mismatch likely. |
| `searxng /healthz` times out | `ssh overlord101@<server3> 'docker logs --tail=100 searxng'` → likely `cap_add` insufficient or `settings.yml` malformed. |
| Pyinfra cannot connect | You may be fail2ban-blocked from prior failed attempts. `maxretry=5, bantime=10m`. Wait 10m or unban via Hetzner console. |

### Task 4.3: Container health

```bash
ssh -p 2222 overlord101@<SERVER3_IP> 'docker ps'
```

Expected: both `chaos` and `searxng` containers listed with `Up` status and `(healthy)`.

### Task 4.4: Gateway healthz via SSH tunnel

```bash
# Open tunnel (in separate terminal, or background it):
ssh -L 18789:127.0.0.1:18789 -p 2222 overlord101@<SERVER3_IP>
# In another terminal:
curl -fsS http://127.0.0.1:18789/healthz
```

Expected: `{"status":"ok"}` or equivalent green payload.

### Task 4.5: SearXNG JSON works (the gotcha fix proof)

```bash
ssh -p 2222 overlord101@<SERVER3_IP> \
  'docker exec chaos wget -qO- "http://searxng:8080/search?q=test&format=json" | head -c 300'
```

Expected: starts with `{"query":"test"`. NOT HTML. NOT `403`.

**If 403:** settings.yml `formats: [html, json]` didn't land correctly — inspect `/opt/openclaw/chaos/config/searxng/settings.yml` on server.

### Task 4.6: Slack connection established

```bash
ssh -p 2222 overlord101@<SERVER3_IP> 'docker logs --tail=200 chaos 2>&1 | grep -iE "slack|socket"'
```

Expected: lines showing Socket Mode connection opened, no auth errors (no `invalid_auth`, no `not_allowed_token_type`).

### Task 4.7: End-to-end DM test

**Step 1: DM the bot**

Open Slack, find the `OpenClaw-Test` app in the Apps list, send DM: `hi`.

**Step 2: Expect a reply within ~5–10 seconds**

The reply should be a natural-language LLM response (not an error). First message may take slightly longer as the session initializes.

**Step 3: Tail logs to verify the request path**

```bash
ssh -p 2222 overlord101@<SERVER3_IP> 'docker logs --tail=50 chaos'
```

Expected: you see the inbound message, a LiteLLM call, and an outbound Slack response.

### Task 4.8: Channel mention test

**Step 1: Invite the bot to a test channel**

In Slack, `/invite @Chaos` in any channel (create `#chaos-test` if needed).

**Step 2: Post a non-mention message: `hello`**

Expected: **no reply**. Channel messages are mention-gated by default.

**Step 3: Post a mention: `@Chaos what time is it`**

Expected: reply within ~5–10 seconds.

### Task 4.9: Optional tool exercises

Skip if 4.1–4.8 all pass — this only validates the tool surface, which will expose other bugs independently.

**Web search:** DM `search for the latest news about openclaw` → should return results citing SearXNG.

**Memory:** DM `remember my favorite color is chartreuse`, then in a new thread (or after `/reset`) DM `what is my favorite color?` → should recall.

**`/model` switch:** In DM, send `/model chaos-complex`, then send a message. Check LiteLLM logs on Server 2 to confirm the request hit the `complex-chaos` alias.

### Task 4.10: Post-deploy commit (optional: README update)

**Step 1: Update `docker/chaos/README.md` to reflect the new state**

Use Edit to replace the "What's intentionally absent" section:

`old_string`:
```
## What's intentionally absent

Slack, SearXNG, fs/web tools, public exposure, TLS, backups, and a second
agent are all out of scope for day one. Each has a scaffolding slot
(compose network, workspace volume, `CHAOS_*` env placeholders, empty
`channels` / `plugins` in config) so future diffs are config-only. See
the design doc's "Follow-ups" section.
```

`new_string`:
```
## What's intentionally absent

Public exposure, TLS, backups, per-user access tightening, and cron
guardrails are all out of scope. Each has a scaffolding slot or explicit
flag to flip when you decide you need them. See the 2026-04-21 design
doc's "Follow-up slots" section.
```

**Step 2: Commit**

```bash
git add docker/chaos/README.md
git commit -m "$(cat <<'EOF'
docs(chaos): update README after slack + tool surface deploy

Slack, SearXNG, and full tool surface are now live. Remaining absences
are public exposure, TLS, backups, access tightening, cron guardrails.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5 — Rollback (only if Phase 4 fails unrecoverably)

Don't execute this unless Tasks 4.3–4.6 keep failing after one round of fixes.

### Task 5.1: Revert openclaw.json to gateway-only shape

```bash
git revert <commit-hash-of-Task-2.3> --no-edit
# Or, if you prefer a fresh commit:
git show 1e19c5c:docker/chaos/config/openclaw.json > docker/chaos/config/openclaw.json
git add docker/chaos/config/openclaw.json
git commit -m "chore(chaos): rollback openclaw.json to gateway-only"
```

### Task 5.2: Revert compose + task changes

```bash
git revert <commit-hash-of-Task-3.7> --no-edit
git revert <commit-hash-of-Task-1.5> --no-edit
```

### Task 5.3: Re-deploy

```bash
set -a; source .env; set +a
pyinfra infra/inventories/deploy.py infra/deploy.py
```

Expected: Chaos back to the gateway-only healthy state from 2026-04-19.

---

## Execution handoff

Plan complete and saved to `docs/plans/2026-04-21-chaos-slack-and-tools-plan.md`.

**Two execution options:**

1. **Subagent-Driven (this session)** — dispatch a fresh subagent per Phase/Task group, review between tasks, fast iteration. REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

2. **Parallel Session (separate)** — open a new Claude Code session, point it at this plan, it uses `superpowers:executing-plans` with batched checkpoints.

For IaC work where each phase builds on the last and we want tight review, subagent-driven works well. For a "let me watch it happen turn-by-turn" experience, parallel session.

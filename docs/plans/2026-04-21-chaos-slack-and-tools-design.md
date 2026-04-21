# Chaos — Slack Wiring + Full Tool Surface (IaC Design)

**Date:** 2026-04-21
**Status:** Design approved, pending implementation
**Target:** Server 3 (Hetzner, hardened Docker host)
**Agent image:** `ghcr.io/openclaw/openclaw:2026.4.14` (tag + digest pin, unchanged)
**Builds on:** `docs/plans/2026-04-18-chaos-gateway-only-design.md`

## Goal

Wire the deployed-but-gateway-only `chaos` agent to Slack (Socket Mode) and
enable the full OpenClaw tool surface (minus destructive ops), including a
SearXNG sidecar for web search and three agents with `/model` routing.
Fills the scaffolding slots carved by the 2026-04-18 design rather than
redesigning the stack.

## Context

- **Current state**: gateway-only `chaos` deployed + healthy on Server 3 as
  of 2026-04-19 (see prior design doc `6ce6a96`). Implementation files
  (`docker/chaos/**`, `infra/tasks/chaos_deploy.py`, edits to
  `infra/deploy.py`, `group_data/all.py`, `.env.example`) are **still
  unstaged** — deploy worked but never committed.
- **Prerequisite**: those unstaged files should be committed as their own
  change before this work layers on top. Two clean commits beat one
  history-blending blob.
- Server 1 (Ollama) untouched. Server 2 (LiteLLM) must expose
  `simple-chaos`, `complex-chaos`, `local` aliases; if `complex-chaos` /
  `local` aren't defined, drop those two agents from this design or add
  them to LiteLLM first.

## Decisions (brainstormed 2026-04-21)

| # | Fork | Choice |
|---|------|--------|
| 1 | Slack connection mode | Socket Mode (outbound WebSocket, no public URL) |
| 2 | Scope | DMs open + channels respond only to `@chaos` mentions |
| 3 | Tool purpose | Full — fs + web + memory + rest of OpenClaw's surface |
| 4 | Non-useful destructive groups | Deny only `fs.delete` and `elevated`; everything else allowed |
| 5 | Access policy | `allowFrom: ["*"]` — anyone in the Slack workspace |
| 6 | Slack app | Reuse existing `OpenClaw-Test`; tokens as-is (no rotation) |
| 7 | SearXNG shape | Sidecar in `docker/chaos/docker-compose.yml` on `chaos_net` |
| 8 | Cron | Enabled, no guardrails (risk accepted — see Risks) |
| 9 | Model binding | `litellm/simple-chaos` primary; three agents + `/model` routing |

## Architecture

```
Slack workspace (OpenClaw-Test app, Socket Mode)
   │  (outbound WebSocket only — no inbound public surface)
   ▼
┌─────────────── Server 3 (Hetzner) ────────────────┐
│                                                   │
│  ┌────── chaos_net (bridge) ──────┐               │
│  │                                 │               │
│  │  chaos container                │               │
│  │    3 agents: simple/complex/    │               │
│  │      local (each → one alias)   │               │
│  │    tools: fs, web, memory,      │               │
│  │      runtime, ui, exec, cron,   │               │
│  │      image, sessions_spawn      │               │
│  │    deny: fs.delete, elevated    │               │
│  │    gateway: 127.0.0.1:18789     │               │
│  │                                 │               │
│  │  searxng container              │               │
│  │    internal: searxng:8080       │               │
│  │    debug: 127.0.0.1:18790       │               │
│  └────────────────────────────────┘               │
│                                                   │
│  SSH tunnel (existing): 18789 → laptop            │
└───────────────────────────────────────────────────┘
                      │
         LiteLLM (10.0.0.4:4000, private network)
                      │
            Server 1 (Ollama) or external providers
```

No new public inbound ports. Slack reaches Chaos outbound via WebSocket.
SearXNG is internal to `chaos_net`; its loopback port `18790` exists for
SSH-tunnel debugging only.

## Changes — file by file

### `docker/chaos/config/openclaw.json`

**Agents section — three agents for `/model` routing:**

```json
"agents": {
  "defaults": {
    "workspace": "/home/node/.openclaw/workspace",
    "skills": [],
    "model": { "primary": "litellm/simple-chaos", "fallbacks": [] }
  },
  "list": [
    { "id": "chaos",         "default": true, "name": "Chaos",
      "identity": {"name": "Chaos", "emoji": "spider_web"},
      "model": { "primary": "litellm/simple-chaos", "fallbacks": [] } },
    { "id": "chaos-complex", "name": "Chaos Complex",
      "identity": {"name": "Chaos Complex", "emoji": "brain"},
      "model": { "primary": "litellm/complex-chaos", "fallbacks": [] } },
    { "id": "chaos-local",   "name": "Chaos Local",
      "identity": {"name": "Chaos Local", "emoji": "house"},
      "model": { "primary": "litellm/local", "fallbacks": [] } }
  ]
}
```

**Channels — populate the empty `{}`:**

```json
"channels": {
  "slack": {
    "enabled": true,
    "mode": "socket",
    "botToken": "${CHAOS_SLACK_BOT_TOKEN}",
    "appToken": "${CHAOS_SLACK_APP_TOKEN}",
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
}
```

**Note on mention-gating:** OpenClaw docs state channel messages are
mention-gated by default. `groupPolicy: "open"` means Chaos responds only
to `@chaos` mentions unless a per-channel `requireMention: false` overrides.
No `"mention-only"` enum value exists in the schema.

**Tools — full allow, destructive denies:**

```json
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
}
```

**Session:**

```json
"session": {
  "scope": "per-sender",
  "dmScope": "per-channel-peer",
  "reset": { "mode": "idle", "idleMinutes": 240 }
}
```

**Memory — explicit builtin** (qmd binary isn't shipped in the 4.14 image
per `openclaw_4_14_schema_ground_truth.md`; selecting `qmd` soft-falls-back
to builtin with a log warning per agent):

```json
"memory": { "backend": "builtin", "citations": "auto" }
```

**Cron + plugins flipped on:**

```json
"cron":    { "enabled": true },
"plugins": {
  "enabled": true,
  "entries": {
    "searxng": {
      "enabled": true,
      "config": { "webSearch": { "baseUrl": "${CHAOS_SEARXNG_BASE_URL}" } }
    }
  }
}
```

SearXNG URL lives here, **not** under `tools.web.search.baseUrl` — `tools`
only references the provider name. Ground-truth constraint.

`gateway`, `models.providers`, `commands` sections unchanged from the
currently-deployed config.

### `docker/chaos/docker-compose.yml`

Append a `searxng` service on `chaos_net`. Chaos service itself unchanged
except it already shares the network.

```yaml
  searxng:
    image: ${CHAOS_SEARXNG_IMAGE}        # pinned tag + digest
    container_name: searxng
    init: true
    restart: unless-stopped
    environment:
      SEARXNG_BASE_URL: "http://searxng:8080/"
      INSTANCE_NAME: "chaos-searxng"
      UWSGI_WORKERS: "2"
      UWSGI_THREADS: "2"
    ports:
      - "127.0.0.1:18790:8080"           # loopback-only, for SSH-tunnel debug
    volumes:
      - ./config/searxng/settings.yml:/etc/searxng/settings.yml:ro
    networks: [chaos_net]
    cap_drop: [ALL]
    cap_add: [CHOWN, SETUID, SETGID]     # needed by SearXNG's startup; revisit if rootless image available
    security_opt: ["no-new-privileges:true"]
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
      options: { max-size: "5m", max-file: "3" }
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:8080/healthz || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s
```

### New file: `docker/chaos/config/searxng/settings.yml`

The critical gotcha fix — default settings.yml has `formats: [html]` only,
which returns HTTP 403 on `?format=json` requests. Chaos's web search tool
requires JSON.

```yaml
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
    - html
    - json                                # ← critical gotcha fix

general:
  debug: false
  instance_name: "chaos-searxng"

ui:
  query_in_title: false
  infinite_scroll: false

engines: []                               # inherit all defaults from the image
```

Secret key substitution happens at Pyinfra render-time, not container
runtime — SearXNG's native `${VAR}` support isn't guaranteed.

### `docker/chaos/.env.example`

Append:

```bash
# SearXNG image pin — e.g. searxng/searxng:2026.3.1@sha256:<digest>
CHAOS_SEARXNG_IMAGE=

# SearXNG server.secret_key — generate with: openssl rand -hex 32
CHAOS_SEARXNG_SECRET_KEY=

# SearXNG base URL reachable by Chaos (internal DNS on chaos_net)
CHAOS_SEARXNG_BASE_URL=http://searxng:8080
```

Existing `CHAOS_SLACK_*` slots get populated (no new slots needed).
Root `.env.example` mirrors the same additions.

### `infra/tasks/chaos_deploy.py`

Two new steps + one extended step. Task stays single-file and idempotent.

**Extend** the remote `.env` render step to include the three new SearXNG
vars + the three Slack vars (all sourced from `os.environ[...]` — fail
loudly if any missing).

**New step** (before `docker compose pull`):

```python
# Ensure searxng config dir — root-owned so cap_drop: ALL container can read.
files.directory(
    name="Ensure searxng config dir",
    path=f"{chaos_dir}/config/searxng",
    user="root", group="root", mode="755", present=True,
    _sudo=True,
)

# Render settings.yml with secret_key substituted in-memory; upload as root-owned RO.
with open("docker/chaos/config/searxng/settings.yml") as f:
    tmpl = f.read()
rendered = tmpl.replace(
    "${CHAOS_SEARXNG_SECRET_KEY}",
    os.environ["CHAOS_SEARXNG_SECRET_KEY"],
)
files.put(
    name="Upload searxng settings.yml",
    src=StringIO(rendered),
    dest=f"{chaos_dir}/config/searxng/settings.yml",
    user="root", group="root", mode="644",
    _sudo=True,
)
```

**New step** (after existing chaos `/healthz` poll):

```python
# Poll searxng /healthz separately so failure attribution is clear.
server.shell(
    name="Wait for searxng /healthz",
    commands=[
        "timeout 90 sh -c 'until wget -qO- http://127.0.0.1:18790/healthz >/dev/null 2>&1; do sleep 3; done'"
    ],
)
```

`infra/deploy.py` and `group_data/all.py` need no changes — the single
include already drives both services, `chaos_dir` is shared.

## Pre-deploy gates (manual, before `pyinfra deploy`)

1. **LiteLLM on Server 2** has `simple-chaos`, `complex-chaos`, `local`
   aliases wired to real providers. If missing, either add them on Server 2
   or drop the corresponding agents from the config.
2. **Slack app dashboard**: Socket Mode ON; Agents & AI Apps ON; 18 bot
   scopes granted; event subscriptions ON with `app_mention`, `message.im`,
   `message.channels`, `message.groups`.
3. **Local environment** has every `CHAOS_*` var populated (including the
   three new SearXNG vars). Missing any aborts Pyinfra on render step.
4. **SearXNG image** pinned at tag + digest (no `:latest`).

## Deploy sequence

```bash
pyinfra infra/inventories/deploy.py infra/deploy.py --dry   # review
pyinfra infra/inventories/deploy.py infra/deploy.py         # apply
```

Order Pyinfra runs:

1. Ensure `/opt/openclaw/chaos/` dirs.
2. Upload `docker-compose.yml`, rendered `.env`, `openclaw.json`,
   `searxng/settings.yml`.
3. `docker compose pull` — pulls both images.
4. `docker compose up -d`.
5. Poll `chaos` `/healthz` (up to 240s).
6. Poll `searxng` `/healthz` (up to 90s).
7. Run `openclaw config validate` inside `chaos` container.

Step 7 is the safety net for any schema wrongness not caught by research —
it aborts the deploy and names the rejected field.

## Post-deploy verification

1. `docker ps` on Server 3 — both `chaos` and `searxng` show `(healthy)`.
2. From laptop via SSH tunnel: `curl http://127.0.0.1:18789/healthz` green.
3. `docker exec chaos wget -qO- 'http://searxng:8080/search?q=test&format=json' | head -c 200`
   returns JSON, not HTML and not 403.
4. `docker logs chaos | grep -i slack` shows Socket Mode connected, no
   auth errors.
5. DM `@chaos` in Slack with "hi" — reply within ~5–10s.
6. `@chaos` mention in a channel replies; non-mention message in the same
   channel does NOT.
7. Optional tool exercises: web search via SearXNG, memory recall,
   `/model complex` routing.

## Rollback

- **Crash-loop or won't start**: `docker compose down` on server, revert
  `openclaw.json` to gateway-only shape (prior design `6ce6a96`), re-run
  Pyinfra. State returns to 2026-04-19 healthy.
- **Slack connects but malformed replies**: disable `channels.slack.enabled`
  via `config.patch` through the gateway (the "config via bot not SSH"
  pattern). Debug from container logs.
- **SearXNG returns 403 on JSON**: re-check `settings.yml` was uploaded
  with `formats: [html, json]`. Most likely cause.

## Risks accepted

1. **Workspace-open + full tool surface.** Any Slack workspace member can
   make Chaos run shell commands, hit URLs, write files. Mitigation:
   unprivileged container, `cap_drop: ALL`, `read_only: true`, 1 GB RAM
   cap, 200 PID limit, no host bind mounts outside `./workspace` +
   `./state`.
2. **Cron on with no guardrails.** 2026-04-15 token-drain incident
   (Chaos self-scheduled 3 recurring jobs) can repeat. Mitigation: none at
   config level; depend on LiteLLM usage dashboards on Server 2.
3. **Unverified `tools.allow` tokens.** `group:ui`, `group:runtime`,
   `sessions_spawn`, `exec` pulled from the memory's deny-side example.
   Validator step catches any rejection at deploy.
4. **Token hygiene deferred.** Prior `CHAOS_GATEWAY_TOKEN` +
   `CHAOS_LITELLM_API_KEY` never rotated; now adding three Slack tokens
   to the same `.env`.
5. **`CHAOS_SLACK_SIGNING_SECRET` semantics in Socket Mode** unclear —
   may be unused or required-but-empty. Validator will surface.
6. **SearXNG `cap_add: [CHOWN, SETUID, SETGID]`** drifts from Chaos's
   posture. Needed for service startup; revisit if rootless image appears.

## Out of scope for this change

- Commit of unstaged 2026-04-18 gateway-only rebuild files (should land as
  its own commit before this work).
- Token rotation.
- Backup strategy for `./state` / `./workspace`.
- Observability beyond `docker logs` + `/healthz`.
- Public gateway exposure with TLS.
- NemoClaw (NVIDIA's OpenShell-wrapped OpenClaw) — explicitly deferred.

## Follow-up slots this design preserves

- Tighten access (`allowFrom: ["*"]` → specific user IDs) — single config edit.
- Cron guardrails (owner-only creation; job count ceiling) — schema permitting.
- Multi-provider fallbacks — Server-2 LiteLLM-side change.
- TLS + public gateway (`gateway.bind: "auto"`, Caddy/Traefik).

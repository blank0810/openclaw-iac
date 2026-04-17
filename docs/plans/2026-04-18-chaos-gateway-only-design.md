# Chaos — Gateway-Only, Read-Only Rebuild (IaC Design)

**Date:** 2026-04-18
**Status:** Design approved, pending implementation
**Target:** Server 3 (Hetzner, hardened Docker host)
**Agent image:** `ghcr.io/openclaw/openclaw:2026.4.14` (tag + digest pin)

## Goal

Stand up a single OpenClaw container (`chaos`) on Server 3 that talks to the
existing LiteLLM proxy on Server 2, accessible only via SSH tunnel. Minimal
tool surface. Scaffolded so adding channels, web search, or a second agent
later is a config-only change.

## Context

- Server 1: Ollama (`:11434`), untouched.
- Server 2: LiteLLM (`:4000`), exposes `local`, `simple-chaos`, `complex-chaos`. Untouched.
- Server 3: this repo. Previously ran multi-agent Chaos on OpenClaw 4.14.
  Wiped 2026-04-17; repo reset to hardened-host scope only (commits
  `bd6af69`, `adb3af8`). This design is the first agent stack post-wipe.

## Decisions (brainstormed 2026-04-18)

| Fork | Choice |
|------|--------|
| Container shape | One OpenClaw container, one agent |
| Channel | Gateway only — no Slack on day one |
| Version pin | `2026.4.14` (schema documented in memory) |
| Tool surface | Minimal — only `gateway`; all groups denied |
| UI access | SSH tunnel to `127.0.0.1:18789`, no public port |
| Name / paths | `chaos` / `/opt/openclaw/chaos/` (keep prior convention) |
| Purpose | Scaffolding for future expansion (slots present, empty) |
| Model binding | `litellm/simple-chaos` (others declared, not bound) |

## Architecture

```
Laptop ──SSH tunnel (2222)──► Server 3 :127.0.0.1:18789
                                    │
                                    ▼
                              chaos container (OpenClaw gateway)
                                    │
                                    └──HTTPS──► Server 2 :4000 (LiteLLM)
                                                      │
                                                      └──► simple-chaos
```

- No inbound internet traffic to Chaos. UFW stays at "only 2222 open."
- Chaos calls LiteLLM outbound over public internet with bearer token.
- Auth on gateway is the bearer token (defense-in-depth, not primary control).

### Scaffolding slots (present, empty on day one)

- `chaos_net` Docker network — second service joins later with one line.
- `./workspace` RW volume mounted — flipping fs tool surface to RW later is config-only.
- `CHAOS_*` env namespace — Slack/SearXNG vars sit as empty placeholders.
- `channels: {}` and `plugins: {}` in config — placeholders, validator-clean.

## Repo layout changes

```
docker/chaos/
  docker-compose.yml              # NEW — the stack
  config/
    openclaw.json                 # NEW — baked agent config
  .env.example                    # NEW — remote-side env template
  README.md                       # NEW — what/how to deploy

infra/
  tasks/
    chaos_deploy.py               # NEW — upload files, up -d, healthcheck
  files/chaos/                    # NEW — static uploads
  deploy.py                       # EDIT — append local.include("tasks/chaos_deploy.py")

group_data/
  deploy.py                       # EDIT — add chaos_dir, chaos_image

.env.example                      # EDIT — re-add CHAOS_* placeholders
```

### Two `.env` files on purpose

- **Local `.env`** (repo root, gitignored) — inputs for Pyinfra: server IP, SSH
  port, image digest, LiteLLM creds, gateway token. Never uploaded as-is.
- **Remote `.env`** (`/opt/openclaw/chaos/.env`, mode 0600, `overlord101`) —
  uploaded by `chaos_deploy.py`, read by compose via `env_file: .env`.
  Values sourced from Pyinfra's `os.environ`.

### `chaos_deploy.py` steps (all idempotent)

1. Ensure `/opt/openclaw/chaos/` exists, `overlord101:overlord101`, mode 0750.
2. Upload `docker-compose.yml`.
3. Upload `openclaw.json` → `config/openclaw.json`, mode 0640.
4. Render + upload `.env`, mode 0600, values from `os.environ`.
5. `docker compose pull` + `docker compose up -d`.
6. Poll `http://127.0.0.1:18789/healthz` up to 240s — fail loudly on timeout.
7. `docker compose exec chaos openclaw config validate` — fail loudly on schema drift.

## Compose shape

```yaml
services:
  chaos:
    image: ${CHAOS_IMAGE}
    container_name: chaos
    init: true
    restart: unless-stopped
    user: "1000:1000"
    env_file: .env
    environment:
      TZ: ${TZ:-UTC}
      OPENCLAW_CONFIG_DIR: /home/node/.openclaw
      OPENCLAW_WORKSPACE_DIR: /home/node/.openclaw/workspace
    ports:
      - "127.0.0.1:18789:18789"           # gateway — localhost-only
    volumes:
      - ./state:/home/node/.openclaw
      - ./workspace:/home/node/.openclaw/workspace
      - ./config/openclaw.json:/home/node/.openclaw/openclaw.json:ro
    networks: [chaos_net]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    read_only: true
    tmpfs:
      - /tmp:size=100m,mode=1777
      - /home/node/.cache:size=100m,mode=0755,uid=1000,gid=1000
    mem_limit: 1g
    memswap_limit: 1g
    cpus: "1.0"
    pids_limit: 200
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:18789/healthz || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 240s

networks:
  chaos_net:
    driver: bridge
```

### Trade-off noted

Workspace volume is RW on the host. Defense against unwanted writes is the
tool surface (denied in `openclaw.json`), not the mount mode. If strict
belt-and-suspenders is wanted later, switch `./workspace:...` to `...:ro` —
costs the scaffolding promise.

## `openclaw.json` shape

Schema per `openclaw_4_14_schema_ground_truth` memory.

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
        "apiKey":  "${CHAOS_LITELLM_API_KEY}",
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
      { "id": "chaos", "default": true, "name": "Chaos", "identity": { "name": "Chaos", "emoji": "spider_web" } }
    ]
  },
  "session":  { "scope": "per-sender", "reset": { "mode": "idle", "idleMinutes": 240 } },
  "channels": {},
  "tools": {
    "profile": "messaging",
    "allow":   ["gateway"],
    "deny":    ["exec", "fs.delete", "group:fs", "group:web", "group:runtime", "group:ui", "group:memory", "cron", "elevated", "sessions_spawn"]
  },
  "commands": { "native": "auto", "restart": true, "ownerAllowFrom": [], "useAccessGroups": true },
  "cron":     { "enabled": false },
  "memory":   { "backend": "builtin", "citations": "auto" },
  "plugins":  { "enabled": false, "entries": {} },
  "messages": {}
}
```

Key points:
- Agent can only reply through the gateway. No fs (even read), no web, no
  shell, no memory persistence across restarts, no cron.
- Three LiteLLM models are declared; only `simple-chaos` is bound to the
  single `chaos` agent.
- `memory.backend: builtin` avoids the known `qmd` fallback warning.
- `channels`, `plugins`, `messages` are empty but present as scaffolding.

## Access flow (cold repo → usable UI)

1. `scripts/setup-local.sh` — venv + copy `.env.example` → `.env`.
2. Fill local `.env`: `SERVER3_IP`, `SSH_PORT=2222`, `CHAOS_IMAGE`,
   `CHAOS_LITELLM_BASE_URL`, `CHAOS_LITELLM_API_KEY`, `CHAOS_GATEWAY_TOKEN`.
3. `pyinfra inventories/bootstrap.py bootstrap.py` — skip if host already hardened.
4. `pyinfra inventories/deploy.py deploy.py` — now includes chaos_deploy.
5. `ssh -L 18789:127.0.0.1:18789 -p 2222 overlord101@<SERVER3_IP>`.
6. Browse `http://localhost:18789`, paste bearer token → UI.

## Secret handling

- `CHAOS_GATEWAY_TOKEN`, `CHAOS_LITELLM_API_KEY`: **only** in local `.env`
  and remote `/opt/openclaw/chaos/.env` (0600, `overlord101`). Never git,
  memory files, or logs.
- The token pasted during brainstorming is burned — rotate on Server 2
  before first deploy, put the new one in `.env`, re-run `deploy.py`.
- `.env.example` has empty placeholders only.

## Failure modes

| Symptom | Likely cause | Signal |
|---|---|---|
| `docker compose up -d` non-zero exit | bad image digest, bad compose | Pyinfra fails step 5 |
| Container crash-loops within 240s | `openclaw config validate` rejected a key | `docker logs chaos` |
| `/healthz` never becomes green | container up but gateway not binding | Pyinfra healthcheck poll times out |
| Prompts hang or 401 | wrong LITELLM base URL or token | `docker logs chaos`, curl LiteLLM from server |

One-line recovery for each lives in `docker/chaos/README.md`.

## Out of scope (deliberate)

- Slack / any channel wiring
- SearXNG / any web tool
- `fs` tools (even read)
- Public exposure, TLS, reverse proxy
- Multi-agent (`chaos-complex`, `chaos-local` stay as LiteLLM aliases only)
- Observability beyond `docker logs` + `/healthz`
- Backups — nothing durable to back up until memory is wired

## Follow-ups (future diffs, not this PR)

- Flip `memory.backend` to `qmd` once the binary ships in a future image.
- Attach SearXNG: add service to compose, set `plugins.entries.searxng`, flip
  `group:web` from deny to allow.
- Wire Slack: fill `CHAOS_SLACK_*` in `.env`, add `channels.slack` block,
  unblock the bot's outbound token.
- Second agent (`chaos-complex`): add to `agents.list`, bind to
  `litellm/complex-chaos`. No compose changes needed.

# Cloudesk AI Project — Server 3 (OpenClaw Agents)

## What This Is

Infrastructure-as-Code for deploying OpenClaw AI agents to a Hetzner VPS.
Pyinfra runs locally, SSHes into the server, hardens it, installs Docker, and deploys OpenClaw containers.

## Architecture

- **Server 1**: Ollama (Model Server) — Qwen 2.5 7B + LLaMA 3.1 8B on port 11434
- **Server 2**: LiteLLM Proxy (API Gateway) — routing, rate limits, fallbacks on port 4000
- **Server 3**: OpenClaw Agents (this repo) — Gateway on 18789, Bridge on 18790

All server IPs are in `.env` (gitignored). See `.env.example` for the template.
OpenClaw agents call Server 2 (LiteLLM) for all LLM requests — no API keys on Server 3.

## Project Structure

```
infra/              # Pyinfra (runs locally, SSHes into server)
  bootstrap.py      # One-time root setup: create overlord101, harden, UFW
  deploy.py         # Repeatable: install Docker, deploy OpenClaw
  inventory.py      # Reads server connection from env vars
  group_data/       # Shared non-secret config
  tasks/            # One file per concern (hardening, docker, app deploy)
  files/            # Static configs uploaded to server (sshd_config, fail2ban)
docker/             # Docker artifacts (uploaded to server by Pyinfra)
  chaos/            # Chaos agent — docker-compose.yml + openclaw.json seed
  workspace/        # Identity/personality files seeded into Chaos workspace
scripts/            # Developer convenience (setup, deploy wrappers)
docs/plans/         # Implementation plans
```

## Key Conventions

- **No real IPs or secrets in committed files.** Everything goes in `.env` (gitignored).
- **One Pyinfra task file per concern.** Each file in `infra/tasks/` is independently runnable with `pyinfra --dry`.
- **Bootstrap vs. Deploy separation.** `bootstrap.py` runs once as root. `deploy.py` runs repeatedly as `overlord101`.
- **SSH user:** `overlord101` (sudo, key-based auth only after bootstrap)
- **SSH key:** `hetzner-cloudesk.pem` at project root (gitignored via `*.pem`)

## Terminology

| Term | Meaning |
|------|---------|
| **OpenClaw** | Open-source autonomous AI agent platform. Runs locally, connects to messaging apps (WhatsApp, Telegram, Slack, etc.), and executes tasks via tools (shell, files, browser). 247k+ GitHub stars. |
| **Gateway** | OpenClaw's central process — serves WebSocket control plane, OpenAI-compatible HTTP API, and Control UI all on a single port (default 18789). |
| **Bridge** | OpenClaw's secondary port (default 18790) for cross-service communication. |
| **LiteLLM** | Open-source LLM proxy that sits between OpenClaw and model providers. Handles routing, rate limiting, fallbacks, and cost tracking. Exposes an OpenAI-compatible API on port 4000. |
| **Ollama** | Local LLM inference server. Runs open-source models (Qwen, LLaMA, etc.) and exposes an API on port 11434. |
| **Pyinfra** | Python-based Infrastructure-as-Code tool. Runs locally, connects to remote servers via SSH, and executes operations (install packages, upload files, manage services). Alternative to Ansible. |
| **Bootstrap** | One-time server provisioning step. Connects as root, creates `overlord101` user, hardens SSH, enables firewall. After bootstrap, root SSH is disabled permanently. |
| **Deploy** | Repeatable deployment step. Connects as `overlord101`, ensures Docker is installed, uploads compose + config, starts/updates containers. Safe to re-run (idempotent). |
| **Hardening** | Server security configuration: disable root SSH, key-only auth, custom SSH port, UFW firewall, fail2ban intrusion prevention, unattended security updates. |
| **UFW** | Uncomplicated Firewall — Ubuntu's default firewall interface. We use it to block all incoming traffic except SSH and OpenClaw agent ports. |
| **fail2ban** | Intrusion prevention tool that monitors SSH login attempts and temporarily bans IPs with repeated failures. |
| **overlord101** | The admin user created on Server 3 during bootstrap. Has sudo access, SSH key-based auth only. All post-bootstrap operations run as this user. |
| **`openclaw.json`** | OpenClaw's runtime config file (lives at `~/.openclaw/openclaw.json` inside the container). Configures which LLM provider to use — in our case, points `baseUrl` to LiteLLM on Server 2. |
| **`CHAOS_GATEWAY_TOKEN`** | Auth token required when OpenClaw's Gateway binds to LAN (non-loopback). Protects the WebSocket/HTTP API from unauthorized access. Generate with `openssl rand -hex 32`. |
| **IaC** | Infrastructure-as-Code — managing server configuration through version-controlled scripts instead of manual SSH commands. |
| **Idempotent** | An operation that produces the same result whether you run it once or multiple times. All Pyinfra tasks and `docker compose up` are idempotent. |
| **Council** / **Council of Agents** | Refers to the team of specialized AI agents available in this project. When the user says "ask the council", "let the council decide", or "call the agents", dispatch the appropriate agent(s) from the tables below. Use project-scope agents first; fall back to global agents for cross-cutting concerns. |

## Tech Stack

- **Pyinfra** (>=3, <4) — IaC tool, runs locally, orchestrates server setup over SSH
- **Docker + Docker Compose** — container runtime on the server
- **OpenClaw** — `ghcr.io/openclaw/openclaw:latest` — AI agent platform
- **LiteLLM** — LLM proxy on Server 2 that OpenClaw connects to via `openclaw.json`

## OpenClaw Specifics

- Official image: `ghcr.io/openclaw/openclaw:latest` (pin to specific version for production)
- Gateway port: 18789 — **bound to loopback only** (not internet-facing)
- Bridge port: 18790 — **bound to loopback only**
- Health check: `GET http://127.0.0.1:18789/healthz`
- Auth: `CHAOS_GATEWAY_TOKEN` required
- LLM config: `~/.openclaw/openclaw.json` — currently Gemini (direct), target is LiteLLM on Server 2 when ready
- Config model: **seed-once** — Pyinfra uploads `openclaw.json` only on first deploy, then OpenClaw self-manages
- Tokens use `${ENV_VAR}` syntax in config — substituted at runtime from container env
- Persistent state: mount `~/.openclaw` as a Docker volume
- Slack: Socket Mode (outbound-only, no inbound ports needed)
- Channels: Slack, Telegram, Discord, WhatsApp pre-configured — add tokens to `.env` to enable
- Self-management: `gateway` + `cron` tools enabled — bot can add channels, change settings, schedule tasks from chat
- Access Control UI: via SSH tunnel (`ssh -N -L 18789:127.0.0.1:18789 ...`)
- Force config reset: delete `openclaw.json` on server, redeploy

## Security Rules

- Never commit `.env`, `.pem`, or any credential files
- Never hardcode server IPs in source files — use env var references
- UFW: deny all incoming by default, **only SSH (port 2222) is open** — agent ports are loopback-only
- SSH: key-only auth, root login disabled, fail2ban active (maxretry 5, bantime 10m)
- `.env` on server: mode 600, owned by overlord101
- `openclaw.json` on server: mode 600, owned by uid 1000 (node)
- Docker container: `cap_drop: ALL`, `no-new-privileges`, `read_only: true`, resource limits
- Slack: `dmPolicy: "pairing"` (users must be approved), `requireMention: true` in channels
- Tools: `messaging` profile base + `gateway`, `cron`, `group:memory`, `group:web`, `image` allowed
- Hard denied: `exec`, `group:fs`, `group:runtime`, `group:ui`, `elevated`, `sessions_spawn`
- Session isolation: `per-channel-peer` (no context leakage between users)
- No ClawHub skills without manual source audit — 12% of marketplace skills found to be malware (Feb 2026)
- See `docs/plans/2026-04-01-master-deployment-plan.md` for full security/hardening/channels reference

## Pyinfra Patterns

- Use `os.environ[]` (not `os.getenv()`) in inventory — fail loudly on missing vars
- Use `files.put()` for static configs, `files.template()` for templated ones
- Use `local.include()` in orchestrator files (bootstrap.py, deploy.py) to sequence tasks
- All `apt.*` and `server.*` operations are idempotent — safe to re-run

## The Council (Available Agents)

When the user mentions "council", "council of agents", or "agents", use these specialized agents.
**Project-scope agents take priority.** Fall back to global agents for broader concerns.

### Project-Scope Agents (`.claude/agents/`)

| Agent | Role | Model | When to Use |
|-------|------|-------|-------------|
| **infra-engineer** | Server 3 infrastructure specialist | Opus | Pyinfra tasks, Docker configs, shell scripts, server hardening — any implementation work in this project |
| **openclaw-expert** | OpenClaw operations expert | Opus | openclaw.json config, channel setup, tool permissions, troubleshooting, security audits, backup/recovery, CLI commands, model provider config |

### Global Agents (`~/.claude/agents/`)

| Agent | Role | Model | When to Use |
|-------|------|-------|-------------|
| **lead-engineer** | Full-stack architect | Opus | System design, architecture decisions, tech stack evaluation, cross-server concerns |
| **backend-engineer** | Backend implementation | Opus | Server-side features, APIs, business logic (if project expands beyond infra) |
| **frontend-engineer** | Frontend & UX | Sonnet | UI components, if a management dashboard is added later |
| **qa-engineer** | Quality assurance | Sonnet | Tests, code review for correctness, validation |
| **devops-engineer** | Infrastructure generalist | Sonnet | CI/CD, monitoring, security concerns outside this project's scope |
| **hiring-closer** | Hiring evaluator | Opus | CV/portfolio review (not relevant to this project) |

### How to Dispatch

- **"Ask the council"** — pick the most relevant agent(s) for the task
- **"Let the council review"** — use lead-engineer for architecture, qa-engineer for code
- **"Council, implement this"** — use infra-engineer (project-scope) for infra work
- **Multiple agents** — run in parallel when tasks are independent

## Plans

- `docs/plans/2026-04-01-master-deployment-plan.md` — **master plan** (security + channels + seed-once config)
- `docs/plans/2026-03-31-server3-implementation-plan.md` — original phased implementation (Phases 1-4 complete)

Current scope: Chaos agent only (single OpenClaw instance). Using Gemini directly; will switch to LiteLLM/Ollama when Servers 1+2 are ready.

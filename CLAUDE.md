# Cloudesk AI Project — Server 3 (Hardened Docker Host)

## What This Is

Infrastructure-as-Code for a Hetzner VPS that will host AI agent workloads.
Pyinfra runs locally, SSHes into the server, hardens it, and installs Docker.

The agent layer was previously OpenClaw (Chaos). It was removed
(2026-04-17), briefly rebuilt gateway-only (2026-04-19, commit
`1e19c5c`), then **permanently scratched 2026-04-21**. OpenClaw is no
longer a project direction. Server 3 stays a hardened Docker host for
future unrelated workloads. Do not reintroduce OpenClaw or Chaos
without an explicit decision to reverse course.

## Architecture

- **Server 1**: Ollama (Model Server) — Qwen 2.5 7B + LLaMA 3.1 8B on port 11434
- **Server 2**: LiteLLM Proxy (API Gateway) — routing, rate limits, fallbacks on port 4000
- **Server 3**: This repo — hardened Docker host, agent stack TBD

All server IPs are in `.env` (gitignored). See `.env.example` for the template.

## Project Structure

```
infra/                 # Pyinfra (runs locally, SSHes into server)
  bootstrap.py         # One-time root setup: create overlord101, harden, UFW
  deploy.py            # Repeatable: ensure base packages + Docker
  inventories/
    bootstrap.py       # Connects as root on port 22
    deploy.py          # Connects as overlord101 on port 2222
  files/               # Static configs uploaded to server (sshd_config, fail2ban)
  tasks/               # One file per concern
    base_packages.py
    deploy_user.py
    docker_install.py
    hardening.py
group_data/            # Shared non-secret config (deploy_user, ssh_port, etc.)
docker/                # Empty — drop new agent compose stacks here
scripts/
  setup-local.sh       # Local venv + .env bootstrap
docs/plans/            # Historical implementation plans (Chaos era, kept for reference)
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
| **Pyinfra** | Python-based Infrastructure-as-Code tool. Runs locally, connects to remote servers via SSH, executes operations (install packages, upload files, manage services). |
| **Bootstrap** | One-time server provisioning. Connects as root, creates `overlord101`, hardens SSH, enables firewall. After bootstrap, root SSH is disabled permanently. |
| **Deploy** | Repeatable step. Connects as `overlord101`, ensures Docker is installed. Safe to re-run (idempotent). |
| **Hardening** | Disable root SSH, key-only auth, custom SSH port (2222), UFW firewall, fail2ban, unattended security updates. |
| **UFW** | Uncomplicated Firewall. Default deny incoming, only port 2222 (SSH) open. |
| **fail2ban** | Monitors SSH login attempts and bans IPs with repeated failures. |
| **overlord101** | Admin user created during bootstrap. Sudo + docker group, key-only SSH. |
| **IaC** | Infrastructure-as-Code — managing servers via version-controlled scripts, not ad-hoc SSH. |
| **Idempotent** | An operation that produces the same result every time. All Pyinfra tasks are idempotent. |
| **Council** | The set of specialized agents available in this repo (see below). When the user says "ask the council" or "call the agents", dispatch the relevant one. |

## Tech Stack

- **Pyinfra** (>=3, <4) — IaC tool, runs locally, orchestrates server setup over SSH
- **Docker + Docker Compose** — container runtime on the server (installed by `deploy.py`)

## Security Rules

- Never commit `.env`, `.pem`, or any credential files
- Never hardcode server IPs in source files — use env var references
- UFW: deny all incoming by default, **only SSH (port 2222) is open**
- SSH: key-only auth, root login disabled, fail2ban active (maxretry 5, bantime 10m)
- `.env` on server: mode 600, owned by overlord101
- Future agent containers should default to `cap_drop: ALL`, `no-new-privileges`, `read_only: true`, resource limits

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

### Global Agents (`~/.claude/agents/`)

| Agent | Role | Model | When to Use |
|-------|------|-------|-------------|
| **lead-engineer** | Full-stack architect | Opus | System design, architecture decisions, tech stack evaluation, cross-server concerns |
| **backend-engineer** | Backend implementation | Opus | Server-side features, APIs, business logic |
| **frontend-engineer** | Frontend & UX | Sonnet | UI components, if a dashboard is added later |
| **qa-engineer** | Quality assurance | Sonnet | Tests, code review for correctness, validation |
| **devops-engineer** | Infrastructure generalist | Sonnet | CI/CD, monitoring, security concerns outside this project's scope |
| **hiring-closer** | Hiring evaluator | Opus | CV/portfolio review (not relevant to this project) |

### How to Dispatch

- **"Ask the council"** — pick the most relevant agent(s) for the task
- **"Let the council review"** — use lead-engineer for architecture, qa-engineer for code
- **"Council, implement this"** — use infra-engineer (project-scope) for infra work
- **Multiple agents** — run in parallel when tasks are independent

## Plans

- `docs/plans/` — historical Chaos-era implementation plans, kept as reference for what worked and what to avoid in the next agent build.

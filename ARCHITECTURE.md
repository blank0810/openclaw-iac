# OpenClaw Infrastructure Architecture

**Status:** Draft — updated with system architecture and OpenClaw Docker findings
**Date:** 2026-03-31
**Scope:** Pyinfra-based server hardening + Docker Compose deployment on Hetzner VPS (Server 3)

## System Overview

This repo manages **Server 3** only. The full system has 3 servers.
All server IPs are stored in `.env` (gitignored) — see `.env.example` for the template.

```
SERVER 1 (Model Server)          SERVER 2 (API Gateway)         SERVER 3 (Agent Server)
─────────────────────            ──────────────────────         ───────────────────────
Ollama                           LiteLLM Proxy :4000            OpenClaw Gateway :18789
└─ Qwen 2.5 7B :11434  <──────── └─ Routing                <── OpenClaw Bridge  :18790
└─ LLaMA 3.1 8B                    Rate limits              <── (+ more instances via
                        <────────   Fallbacks                     scale-agents.sh)
                                    Cost tracking
                            │
                            ▼
                        Cloud APIs (Fallback)
                        └─ Anthropic
                        └─ OpenAI
```

**Server 3 agents call Server 2 (LiteLLM) for all LLM requests.** OpenClaw does not hold LLM API keys directly — LiteLLM handles routing, rate limiting, fallbacks, and cost tracking.

### OpenClaw Docker Details

- **Official image:** `ghcr.io/openclaw/openclaw:latest` (no need to build from source)
- **Ports per instance:** `18789` (Gateway: WebSocket + HTTP API + Control UI) + `18790` (Bridge)
- **LLM config:** Via `~/.openclaw/openclaw.json` (not env vars) — `baseUrl` points to LiteLLM on Server 2
- **Auth:** `OPENCLAW_GATEWAY_TOKEN` required when binding to LAN — generate with `openssl rand -hex 32`
- **Persistent state:** Mount `~/.openclaw` as a volume per instance
- **Health check:** `GET http://127.0.0.1:18789/healthz`

### Server Access

- **Admin user:** `overlord101` (sudo)
- **SSH key:** `.pem` key at project root (gitignored via `*.pem`)
- **Bootstrap flow:** Root → create `overlord101` → disable root SSH → harden
- **Hardening template:** Reusing team's shared Pyinfra Ubuntu hardening (UFW, unattended-upgrades, optional fail2ban)

---

## 1. Project Directory Structure

```
ai-project/
├── ARCHITECTURE.md              # This document
├── .gitignore                   # Ignore .env, __pycache__, *.pyc, .venv/
├── .env.example                 # Template showing required variables (no real values)
├── .env                         # Real secrets — NEVER committed (gitignored)
├── requirements.txt             # Python deps: pyinfra
│
├── infra/                       # Everything Pyinfra touches
│   ├── bootstrap.py             # First-time only: run as root, creates deploy user
│   ├── deploy.py                # Main entry point — orchestrates the full run
│   ├── inventory.py             # Hetzner VPS host definitions
│   ├── group_data/
│   │   └── all.py               # Shared variables: SSH port, deploy user, paths
│   │
│   ├── tasks/                   # Pyinfra task modules (one concern per file)
│   │   ├── __init__.py
│   │   ├── hardening.py         # SSH lockdown, UFW, fail2ban, disable root
│   │   ├── base_packages.py     # unattended-upgrades, curl, git, htop
│   │   ├── docker_install.py    # Docker Engine + Compose plugin
│   │   ├── deploy_user.py       # Create deploy user, SSH keys, sudoers
│   │   └── app_deploy.py        # Upload compose file, pull images, compose up
│   │
│   └── files/                   # Static config files uploaded to the server
│       ├── sshd_config          # Hardened sshd configuration
│       └── fail2ban_jail.local  # fail2ban jail overrides
│
├── docker/                      # Everything Docker-related
│   ├── docker-compose.yml       # Production compose file (base service definition)
│   └── openclaw.json.tpl        # OpenClaw config template (LiteLLM connection)
│
└── scripts/                     # Developer convenience
    ├── setup-local.sh           # Create venv, install deps, validate .env
    ├── pin-digest.sh            # Capture tag+digest for .env (OpenClaw or SearXNG)
    ├── restore-from-backup.sh   # On-server recovery: restore config or workspace
    └── recovery.md              # Crash-loop runbook
```

### Why this layout

**`infra/` and `docker/` are separate top-level directories.** Pyinfra is a local-side orchestration tool — its code never runs on the server. Docker Compose files are server-side artifacts that Pyinfra uploads. Separating them makes ownership clear: `infra/` is what runs on your laptop; `docker/` is what ends up on the server.

**One task file per concern in `infra/tasks/`.** Each file is independently testable with `pyinfra --dry`, independently skippable, and independently reviewable. When someone asks "what does the hardening do?" the answer is: read `hardening.py`.

**`infra/files/` holds static config files** rather than inlining them as heredocs in Python. Keeps Pyinfra task code focused on orchestration logic, keeps server configs readable and diffable as standalone files.

---

## 2. Pyinfra Modules

### `bootstrap.py` — First-Time Setup (run as root)

Separate entry point for initial server provisioning. Run once, then never again.

- Creates the deploy user with home directory
- Adds all team members' SSH public keys to the deploy user's `authorized_keys`
- Grants passwordless sudo (or scoped sudo for docker/systemctl only)
- Performs initial hardening (SSH port change, disable root login, disable password auth)
- Installs UFW, configures it, enables it
- Installs fail2ban with custom jail config

**Why separate from `deploy.py`:** The first run *must* connect as root because the deploy user does not exist yet. Every subsequent run connects as the deploy user. Mixing this into one script means conditional logic in every task module. Two clear entry points is cleaner.

### `deploy.py` — Standard Deployment (run as deploy user)

Imports and calls each task module in order. Contains no server operations itself — purely a sequencing file.

```
Execution order:
  1. tasks/base_packages.py     — ensure system packages are current
  2. tasks/docker_install.py    — ensure Docker is installed and running
  3. tasks/app_deploy.py        — upload compose file, pull images, start containers
```

Hardening and user creation are NOT in this flow — they belong to bootstrap and should not re-run on every deploy.

### `inventory.py` — Host Definitions

Defines the Hetzner VPS connection:
- Host IP or hostname (read from environment variable, not hardcoded)
- SSH user (`deploy` for normal runs, `root` for bootstrap)
- SSH key path (from environment variable)
- SSH port (`22` for bootstrap, custom port for subsequent deploys)

The `.py` format over a static inventory file is preferred because it can call `os.environ[]`, keeping secrets and machine-specific paths out of version control.

### `group_data/all.py` — Shared Configuration

Non-secret values shared across all task modules:
- Deploy username: `overlord101`
- Custom SSH port after hardening (e.g., `2222`)
- Server-side deploy path (e.g., `/opt/openclaw`)
- Docker Compose project name
- List of allowed SSH public keys for the team
- `PYINFRA_ALLOWED_TCP_PORTS` — set to include `18789:18800` for agent port range

### Task Module Details

| Module | What it does | Idempotency notes |
|--------|-------------|-------------------|
| `deploy_user.py` | Create non-root user, add SSH keys, configure sudo | `server.user()` and `files.put()` are naturally idempotent |
| `hardening.py` | Upload `sshd_config`, configure UFW rules, install/configure fail2ban, restart sshd | Changing SSH port mid-run can break the connection — see Section 5 |
| `base_packages.py` | `apt.update()`, install curl/git/htop/unattended-upgrades, set timezone to UTC | All `apt.*` operations skip if already satisfied |
| `docker_install.py` | Add Docker GPG key + apt repo, install docker-ce/compose plugin, add user to docker group, enable systemd service | `apt.packages()` and `server.group()` skip if already satisfied |
| `app_deploy.py` | Create `/opt/openclaw/`, upload compose + .env, `docker compose pull`, `docker compose up -d --remove-orphans` | `docker compose up` only recreates containers whose config changed |

---

## 3. Docker Compose Structure

The compose file defines **one OpenClaw service**. Instances are scaled dynamically via a deploy script — not by hardcoding multiple services. The diagram showing 3 agents on ports 18789–18791 is an example of what 3 running instances look like, not a fixed requirement.

### How scaling works

Instances use a **port range starting at `AGENT_BASE_PORT`** (default `18789`). The deploy script manages the count:

```bash
# Start/scale to N instances
./scripts/scale-agents.sh 3    # runs agents on 18789, 18790, 18791

# Scale down
./scripts/scale-agents.sh 1    # removes agents 2 and 3, keeps agent 1

# Add one more (UI "create instance" button calls this)
./scripts/scale-agents.sh +1
```

### `docker/docker-compose.yml`

Base service definition. The `scale-agents.sh` script uses this as a template for launching instances.

```yaml
services:
  openclaw:
    image: ghcr.io/openclaw/openclaw:latest
    init: true
    restart: unless-stopped
    command: ["node", "dist/index.js", "gateway", "--bind", "lan", "--port", "18789"]
    ports:
      - "18789:18789"    # Gateway (WebSocket + HTTP API + Control UI)
      - "18790:18790"    # Bridge
    volumes:
      - openclaw_data:/home/node/.openclaw
    environment:
      - OPENCLAW_GATEWAY_TOKEN=${OPENCLAW_GATEWAY_TOKEN}
      - TZ=${TZ:-UTC}
    networks:
      - openclaw_net
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:18789/healthz')"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 20s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

networks:
  openclaw_net:
    driver: bridge

volumes:
  openclaw_data:
```

### `docker/openclaw.json.tpl`

Config template uploaded into each instance's volume. Connects OpenClaw to LiteLLM on Server 2.
Real `LITELLM_BASE_URL` and `LITELLM_API_KEY` values come from `.env`.

```json
{
  "models": {
    "providers": {
      "litellm": {
        "baseUrl": "${LITELLM_BASE_URL}",
        "apiKey": "${LITELLM_API_KEY}",
        "api": "openai-completions",
        "models": [
          { "id": "qwen2.5:7b", "name": "Qwen 2.5 7B (Ollama)" },
          { "id": "llama3.1:8b", "name": "LLaMA 3.1 8B (Ollama)" }
        ]
      }
    }
  }
}
```

### `scripts/scale-agents.sh`

The script:
1. Reads current running instance count
2. Calculates target count (absolute number or `+N`/`-N`)
3. For each instance, runs `docker run` with:
   - Unique container name (`openclaw-agent-N`)
   - Gateway port pair: `18789+(N-1)*2` (gateway), `18790+(N-1)*2` (bridge)
   - Unique volume for `~/.openclaw` state
   - Templated `openclaw.json` with LiteLLM connection
4. Removes containers that exceed the target count
5. Prints a summary: instance name, ports, status

**Port allocation per instance (2 ports each):**

| Instance | Gateway | Bridge |
|----------|---------|--------|
| Agent 1 | 18789 | 18790 |
| Agent 2 | 18791 | 18792 |
| Agent 3 | 18793 | 18794 |

UFW port range `18789:18800` gives headroom for up to 6 instances.

### Design decisions

- **`ghcr.io/openclaw/openclaw:latest`:** Official pre-built image. No Dockerfile needed.
- **`OPENCLAW_GATEWAY_TOKEN`:** Required for LAN-bound instances. Generated once, shared across all agents.
- **Per-instance volume:** Each agent gets its own `~/.openclaw` mount for config (`openclaw.json`) and any local state.
- **LLM config via `openclaw.json`, not env vars:** OpenClaw uses a JSON config for LLM provider setup. The template references `${LITELLM_BASE_URL}` which the deploy script substitutes from `.env`.
- **UFW port range `18789:18800`:** 6 instance pairs without re-running Pyinfra.
- **Log rotation per container:** 6 containers max at `10m x 3 files` = up to 180MB total logs.

---

## 4. Execution Flow

### First-time setup (developer machine)

```bash
# 1. Clone the repo
# 2. Run local setup
./scripts/setup-local.sh
# 3. Fill in .env with real values
cp .env.example .env
nano .env
```

### First server provisioning (once)

```bash
source .venv/bin/activate
pyinfra --user root --key ~/.ssh/id_ed25519 <HETZNER_IP> infra/bootstrap.py
```

Connects as root, creates deploy user, hardens server, exits. After this, root SSH is disabled. All future access uses the deploy user on the custom SSH port.

### Standard deployment (repeatable)

```bash
source .venv/bin/activate
set -a; source .env; set +a
pyinfra --sudo -v infra/inventory.py infra/deploy.py
```

Connects as deploy user on custom port, ensures packages and Docker are current, uploads compose file + `.env`, runs `docker compose up -d`.

### Running a single task (targeted)

```bash
# Just redeploy the app, skip package checks:
pyinfra infra/inventory.py infra/tasks/app_deploy.py

# Dry run (see what would change, touch nothing):
pyinfra infra/inventory.py infra/deploy.py --dry
```

### What happens on the server (standard deploy)

```
[SSH in as deploy user on custom port]
  → Ensure base packages are installed and up-to-date
  → Ensure Docker is installed and running
  → Upload docker-compose.yml + .env to /opt/openclaw/
  → docker compose pull
  → docker compose up -d --remove-orphans
  → [OpenClaw running, accessible on configured port]
```

Re-running is safe. Pyinfra operations are idempotent.

---

## 5. Key Decisions and Trade-offs

### Why Pyinfra over Ansible

| Concern | Pyinfra | Ansible |
|---------|---------|---------|
| Language | Pure Python — debug with normal tooling | YAML + Jinja2 DSL |
| Dependencies | `pip install pyinfra` — one package | Ansible core + collections |
| Speed | Direct SSH, no agent, parallel by default | SSH-based but higher per-task overhead |
| Learning curve | Low if you write Python | Low-medium; YAML type coercion bites |
| Ecosystem | Smaller, fewer pre-built roles | Massive Galaxy ecosystem |

**The trade-off:** Pyinfra is right for a small team managing 1-3 servers where everyone writes Python. If the fleet grows past ~20 servers, reconsider. The one-task-per-file structure maps nearly 1:1 to Ansible roles, so migration is straightforward.

### Secrets management

**Chosen approach:** `.env` file, gitignored, uploaded by Pyinfra at deploy time.

- `.env.example` committed to document every required variable with placeholders
- `.env` with real values never committed
- Pyinfra uploads `.env` to the server with permissions `600`, owned by deploy user
- Docker Compose reads it via `env_file:`

**Rejected alternatives:**
- Docker Secrets — requires Swarm mode, overkill for one server
- HashiCorp Vault — adds a service to operate
- SOPS/age — good middle ground; recommend as "next step" if secrets need to live in git or CI/CD

### Idempotency — the two hard parts

1. **SSH port change during bootstrap.** If interrupted between writing `sshd_config` and restarting sshd, neither port may work. **Mitigation:** Accept that bootstrap is "run once, verify manually" — don't over-engineer its resumability.

2. **Mutable Docker image tags.** If using `latest`, `docker compose pull` always pulls and may unnecessarily restart containers. **Mitigation:** Use immutable tags (version numbers or SHA digests) in production.

### Bootstrap vs. deploy separation

The first run *must* connect as root. Every subsequent run uses the deploy user. Two entry points (`bootstrap.py` and `deploy.py`) is the cleanest separation vs. alternatives like auto-detection or manual `--user` flags.

---

## 6. Open Questions

### Resolved

| # | Question | Answer |
|---|----------|--------|
| 1 | Docker image source | **`ghcr.io/openclaw/openclaw:latest`** — official pre-built image |
| 2 | What ports? | **18789** (Gateway) + **18790** (Bridge) per instance, allocated in pairs |
| 3 | LLM API keys? | **None on Server 3** — LLM calls go through LiteLLM on Server 2 via `openclaw.json` |
| 4 | Server IPs | All 3 server IPs known — stored in `.env` (gitignored) |
| 5 | SSH access | User `overlord101`, `.pem` key, team hardening template available |
| 6 | Persistent storage? | **Yes** — `~/.openclaw` mount needed for config + state per instance |

### Remaining — decide before production use

1. **UFW rule scope for agent ports.** Should `18789:18800` be open to the internet, or restricted to Server 2's IP only?
2. **Resource limits.** Multiple agent containers sharing one VPS — set `deploy.resources.limits` in compose.
3. **`LITELLM_API_KEY`** — does your LiteLLM proxy require an API key, or is it open on the private network?
4. **Model list for `openclaw.json`** — currently configured with `qwen2.5:7b` and `llama3.1:8b` (matching Server 1). Confirm these are the right model IDs as registered in LiteLLM.

### Can defer

5. **CI/CD pipeline.** Manual `pyinfra infra/inventory.py infra/deploy.py` for now, automate later.
6. **Monitoring.** Uptime-kuma or similar — add as a compose service later.
7. **Domain + TLS.** Only if agents need to be accessed over the public internet.

---

## Appendix A: File Dependency Map

```
Developer Machine                       Hetzner VPS
==================                      ====================

.env ──────────────────── upload ──────> /opt/openclaw/.env
docker/docker-compose.yml  upload ──────> /opt/openclaw/docker-compose.yml
infra/files/sshd_config ── upload ──────> /etc/ssh/sshd_config
infra/files/fail2ban_jail.local ────────> /etc/fail2ban/jail.local

infra/inventory.py ─── reads from ─────> .env (for HETZNER_IP, SSH_KEY_PATH)
infra/deploy.py ────── imports ────────> infra/tasks/*.py
infra/tasks/*.py ───── reads from ─────> infra/group_data/all.py
```

## Appendix B: Minimum `.env.example`

```bash
# ============================================
# Server IPs — NEVER commit real values
# ============================================
SERVER1_IP=                              # Ollama (Model Server)
SERVER2_IP=                              # LiteLLM Proxy (API Gateway)
SERVER3_IP=                              # OpenClaw Agents (this server)

# ============================================
# SSH / Pyinfra connection (Server 3)
# ============================================
SSH_KEY_PATH=./hetzner-cloudesk.pem
SSH_USER=overlord101
SSH_PORT=22                              # Changes to custom port after bootstrap

# ============================================
# OpenClaw deployment
# ============================================
OPENCLAW_GATEWAY_TOKEN=                  # Generate: openssl rand -hex 32
TZ=UTC

# ============================================
# LiteLLM Proxy (Server 2)
# ============================================
LITELLM_BASE_URL=                        # http://<SERVER2_IP>:4000
LITELLM_API_KEY=                         # If LiteLLM requires auth (leave blank if open)
```

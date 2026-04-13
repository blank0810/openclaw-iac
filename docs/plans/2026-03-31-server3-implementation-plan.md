# Server 3 (OpenClaw Agents) -- Implementation Plan

**Date:** 2026-03-31
**Source:** `ARCHITECTURE.md` (approved)

---

## Overview

This plan implements the full Infrastructure-as-Code stack for deploying OpenClaw AI agents to a Hetzner VPS (Server 3). It is broken into 6 phases, ordered so that each step is independently testable before moving to the next.

**Total files to create:** 18
**Estimated implementation time:** One focused session per phase

---

## Phase 1: Project Scaffolding and Local Tooling

**Goal:** A developer can clone the repo, run one script, and have a working local environment with all dependencies. No server contact yet.

### Step 1.1 -- Create `requirements.txt`

- **File:** `requirements.txt`
- **What it does:** Declares Python dependencies. Only `pyinfra>=3,<4` is needed.
- **Test:** `pip install -r requirements.txt && pyinfra --version` succeeds.
- **Dependencies:** None.

### Step 1.2 -- Create `.env.example`

- **File:** `.env.example`
- **What it does:** Documents every required environment variable with placeholder values. Copy from ARCHITECTURE.md Appendix B. Single source of truth for what `.env` must contain.
- **Test:** File contains no real secrets, all variable names match what `inventory.py` will read.
- **Dependencies:** None.

### Step 1.3 -- Create `scripts/setup-local.sh`

- **File:** `scripts/setup-local.sh`
- **What it does:**
  1. Checks Python 3.10+ is available
  2. Creates `.venv` if it does not exist
  3. Activates venv and runs `pip install -r requirements.txt`
  4. Checks if `.env` exists; if not, copies `.env.example` and prints a reminder to fill it in
  5. Validates that required `.env` variables are non-empty (SERVER3_IP, SSH_KEY_PATH, OPENCLAW_GATEWAY_TOKEN)
  6. Prints success message with next steps
- **Test:** Run `bash scripts/setup-local.sh` on a clean checkout. Should create `.venv/`, install pyinfra, and warn about missing `.env` values.
- **Dependencies:** Step 1.1.

### Step 1.4 -- Create directory structure

- **Files:**
  - `infra/tasks/__init__.py` (empty)
  - `infra/group_data/` (directory)
  - `infra/files/` (directory)
  - `docker/` (directory)
- **Test:** `find . -type d` matches the layout in ARCHITECTURE.md.
- **Dependencies:** None.

### Step 1.5 -- Verify `.gitignore`

- **File:** `.gitignore` (already exists)
- **What it does:** Confirm it covers `*.pem`, `.env`, `__pycache__/`, `*.pyc`, `.venv/`, `.DS_Store`.
- **Test:** `git status` does not show `.env`, `.pem`, or `.venv/` as untracked.
- **Dependencies:** None.

---

## Phase 2: Pyinfra Inventory and Shared Configuration

**Goal:** Pyinfra can parse the inventory and group data without errors. Still no server contact.

### Step 2.1 -- Create `infra/group_data/all.py`

- **File:** `infra/group_data/all.py`
- **What it does:** Non-secret shared variables:
  - `deploy_user = "overlord101"`
  - `ssh_port = 2222` (post-bootstrap custom port)
  - `deploy_path = "/opt/openclaw"`
  - `compose_project = "openclaw"`
  - `allowed_tcp_ports = [2222, "18789:18800"]`
  - `team_ssh_keys = [...]` (public key strings for authorized_keys)
  - `timezone = "UTC"`
- **Test:** `python -c "import infra.group_data.all as g; print(g.deploy_user)"` prints `overlord101`.
- **Dependencies:** Step 1.4.

### Step 2.2 -- Create `infra/inventory.py`

- **File:** `infra/inventory.py`
- **What it does:** Reads `SERVER3_IP`, `SSH_KEY_PATH`, `SSH_USER`, `SSH_PORT` from environment variables. Uses `os.environ[]` (not `os.getenv()`) so missing vars cause immediate, clear errors.
- **Test:** `source .env && pyinfra infra/inventory.py --dry fact os.Home` -- parses inventory without connecting.
- **Dependencies:** Step 1.2, Step 2.1.

---

## Phase 3: Bootstrap (First-Time Root Setup)

**Goal:** Run `bootstrap.py` once as root. After completion: `overlord101` exists, SSH is hardened, UFW is active, fail2ban is running, root SSH is disabled.

### Step 3.1 -- Create `infra/files/sshd_config`

- **File:** `infra/files/sshd_config`
- **What it does:** Hardened OpenSSH server config:
  - `Port 2222`
  - `PermitRootLogin no`
  - `PasswordAuthentication no`
  - `PubkeyAuthentication yes`
  - `AllowUsers overlord101`
  - `X11Forwarding no`
  - `MaxAuthTries 3`
  - `ClientAliveInterval 300`
  - `ClientAliveCountMax 2`
- **Test:** Visual review. Validated on server when sshd restarts.
- **Dependencies:** Step 2.1 (must agree on port and username).

### Step 3.2 -- Create `infra/files/fail2ban_jail.local`

- **File:** `infra/files/fail2ban_jail.local`
- **What it does:** fail2ban jail override for custom SSH port:
  - `[sshd]` jail enabled
  - `bantime = 1h`, `findtime = 10m`, `maxretry = 3`
  - `backend = systemd`
- **Test:** Visual review. Validated when fail2ban starts.
- **Dependencies:** Step 3.1 (same SSH port).

### Step 3.3 -- Create `infra/tasks/deploy_user.py`

- **File:** `infra/tasks/deploy_user.py`
- **What it does:**
  1. `server.user()` -- create `overlord101` with home dir and bash shell
  2. `server.group()` -- add to `sudo` group
  3. `files.directory()` -- create `~overlord101/.ssh/` with mode `700`
  4. `files.put()` -- write `authorized_keys` from `team_ssh_keys`, mode `600`
  5. `files.put()` -- write sudoers drop-in to `/etc/sudoers.d/overlord101`
- **Test:** `pyinfra --user root --key $SSH_KEY_PATH $SERVER3_IP infra/tasks/deploy_user.py --dry`
- **Dependencies:** Step 2.1.

### Step 3.4 -- Create `infra/tasks/hardening.py`

- **File:** `infra/tasks/hardening.py`
- **What it does:**
  1. Upload `sshd_config` to `/etc/ssh/sshd_config`
  2. Install `ufw`
  3. Set UFW defaults (deny incoming, allow outgoing)
  4. Loop `allowed_tcp_ports`: `ufw allow <port>/tcp`
  5. `ufw --force enable`
  6. Install `fail2ban`
  7. Upload `fail2ban_jail.local` to `/etc/fail2ban/jail.local`
  8. Restart `fail2ban`
  9. Restart `sshd` (**last operation** -- root SSH dies after this)
- **Test:** After run: SSH on port 22 as root refused; SSH on 2222 as overlord101 works. `ufw status` shows rules. `fail2ban-client status sshd` shows jail.
- **Dependencies:** Steps 3.1, 3.2, 2.1.

### Step 3.5 -- Create `infra/bootstrap.py`

- **File:** `infra/bootstrap.py`
- **What it does:** Orchestrates first-time setup:
  1. `local.include("infra/tasks/deploy_user.py")`
  2. `local.include("infra/tasks/hardening.py")`
- **Invocation:** `pyinfra --user root --port 22 --key $SSH_KEY_PATH $SERVER3_IP infra/bootstrap.py`
- **Test:**
  1. Dry run first
  2. Real run on VPS (once only!)
  3. Verify: `ssh -i $SSH_KEY_PATH -p 2222 overlord101@$SERVER3_IP "whoami && sudo ufw status"`
- **Dependencies:** Steps 3.3, 3.4.

---

## Phase 4: Deploy Pipeline (Repeatable)

**Goal:** Run `deploy.py` as `overlord101`. After completion: Docker installed, OpenClaw container running.

### Step 4.1 -- Create `infra/tasks/base_packages.py`

- **File:** `infra/tasks/base_packages.py`
- **What it does:**
  1. `apt.update()`
  2. `apt.packages()` -- install `curl`, `git`, `htop`, `unattended-upgrades`, `apt-transport-https`, `ca-certificates`, `gnupg`
  3. Set timezone to UTC
- **Test:** Dry run. Real run: `ssh ... "dpkg -l | grep htop"` confirms.
- **Dependencies:** Phase 3 complete.

### Step 4.2 -- Create `infra/tasks/docker_install.py`

- **File:** `infra/tasks/docker_install.py`
- **What it does:**
  1. Add Docker GPG key
  2. Add Docker apt repository
  3. `apt.update()`
  4. `apt.packages()` -- install `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-compose-plugin`
  5. Add `overlord101` to `docker` group
  6. Enable and start Docker service
- **Test:** `ssh ... "docker --version && docker compose version"`
- **Dependencies:** Step 4.1.

### Step 4.3 -- Create `docker/openclaw.json.tpl`

- **File:** `docker/openclaw.json.tpl`
- **What it does:** OpenClaw config template with `${LITELLM_BASE_URL}` and `${LITELLM_API_KEY}` placeholders. Substituted at deploy time via `files.template()` or `envsubst`.
- **Test:** Visual review. Validated when OpenClaw starts and reaches LiteLLM.
- **Dependencies:** None.

### Step 4.4 -- Create `docker/docker-compose.yml`

- **File:** `docker/docker-compose.yml`
- **What it does:** Base service definition for single OpenClaw instance. Uses `ghcr.io/openclaw/openclaw:latest`, ports 18789/18790, volume mount, health check, log rotation.
- **Test:** `docker compose -f docker/docker-compose.yml config` validates syntax.
- **Dependencies:** None.

### Step 4.5 -- Create `infra/tasks/app_deploy.py`

- **File:** `infra/tasks/app_deploy.py`
- **What it does:**
  1. Create `/opt/openclaw/` owned by `overlord101`
  2. Upload `docker-compose.yml` to `/opt/openclaw/`
  3. Upload `.env` to `/opt/openclaw/.env` with mode `600`
  4. Render and upload `openclaw.json` from template
  5. `docker compose pull`
  6. `docker compose up -d --remove-orphans`
  7. Wait for start_period, then check health
- **Test:** `ssh ... "docker ps"` shows container. `ssh ... "curl -s http://127.0.0.1:18789/healthz"` returns healthy.
- **Dependencies:** Steps 4.2, 4.3, 4.4.

### Step 4.6 -- Create `infra/deploy.py`

- **File:** `infra/deploy.py`
- **What it does:** Orchestrates standard deploy:
  1. `local.include("infra/tasks/base_packages.py")`
  2. `local.include("infra/tasks/docker_install.py")`
  3. `local.include("infra/tasks/app_deploy.py")`
- **Invocation:** `pyinfra infra/inventory.py infra/deploy.py`
- **Dependencies:** Steps 4.1, 4.2, 4.5.

---

## Phase 5: Scaling Script

**Goal:** Dynamically add/remove OpenClaw agent instances with stable port pairs.

### Step 5.1 -- Create `scripts/scale-agents.sh`

- **File:** `scripts/scale-agents.sh`
- **What it does:** Bash script that runs on the **server**:
  1. Parse argument: absolute count (`3`), relative delta (`+1`, `-1`), or no arg (show status)
  2. Read current state via `docker ps --filter "name=openclaw-agent-"`
  3. Calculate target count (validate range 0-6)
  4. **Scale up:** For each new instance N:
     - Gateway port: `18789 + (N-1) * 2`
     - Bridge port: `18790 + (N-1) * 2`
     - Create volume, render `openclaw.json`, `docker run` with explicit ports
  5. **Scale down:** `docker stop` + `docker rm` excess instances (preserve volumes)
  6. Print summary table: name, gateway port, bridge port, status
- **Test:**
  - `./scale-agents.sh` -- prints current status
  - `./scale-agents.sh 1` -- starts agent on 18789/18790
  - `./scale-agents.sh 3` -- scales to 3
  - `./scale-agents.sh 0` -- stops all
- **Dependencies:** Phase 4 complete.

### Step 5.2 -- Update `infra/tasks/app_deploy.py`

- **File:** `infra/tasks/app_deploy.py` (edit)
- **What it does:** Add upload of `scale-agents.sh` to `/opt/openclaw/scale-agents.sh` with mode `755`. Also upload `openclaw.json.tpl` so scale script can render per-instance configs.
- **Dependencies:** Step 5.1.

---

## Phase 6: Developer Convenience Wrapper

**Goal:** One-command deploy from a developer's laptop.

### Step 6.1 -- Create `scripts/deploy.sh`

- **File:** `scripts/deploy.sh`
- **What it does:**
  1. Check `.venv/` exists; if not, tell user to run `setup-local.sh`
  2. `source .venv/bin/activate`
  3. Load `.env` via `set -a; source .env; set +a`
  4. Validate critical env vars
  5. Run `pyinfra infra/inventory.py infra/deploy.py`
  6. Print post-deploy summary
- **Test:** `bash scripts/deploy.sh` performs a full deploy.
- **Dependencies:** All prior phases.

---

## File Creation Summary

| # | File | Phase | New/Edit |
|---|------|-------|----------|
| 1 | `requirements.txt` | 1 | New |
| 2 | `.env.example` | 1 | New |
| 3 | `scripts/setup-local.sh` | 1 | New |
| 4 | `infra/tasks/__init__.py` | 1 | New |
| 5 | `.gitignore` | 1 | Verify |
| 6 | `infra/group_data/all.py` | 2 | New |
| 7 | `infra/inventory.py` | 2 | New |
| 8 | `infra/files/sshd_config` | 3 | New |
| 9 | `infra/files/fail2ban_jail.local` | 3 | New |
| 10 | `infra/tasks/deploy_user.py` | 3 | New |
| 11 | `infra/tasks/hardening.py` | 3 | New |
| 12 | `infra/bootstrap.py` | 3 | New |
| 13 | `infra/tasks/base_packages.py` | 4 | New |
| 14 | `infra/tasks/docker_install.py` | 4 | New |
| 15 | `docker/openclaw.json.tpl` | 4 | New |
| 16 | `docker/docker-compose.yml` | 4 | New |
| 17 | `infra/tasks/app_deploy.py` | 4 | New |
| 18 | `infra/deploy.py` | 4 | New |
| 19 | `scripts/scale-agents.sh` | 5 | New |
| 20 | `infra/tasks/app_deploy.py` | 5 | Edit |
| 21 | `scripts/deploy.sh` | 6 | New |

---

## Temporary LLM Configuration

**Current state (2026-03-31):** OpenClaw is using **Gemini (`google/gemini-2.5-flash`)** directly as a temporary workaround.

**Why:**
- Server 1 (Ollama at 178.104.120.185:11434) is unreachable — needs Jake to fix firewall/access
- Server 2 (LiteLLM at 116.203.77.235:4000) is not running — needs Ralph to set up

**When to switch back to original architecture:**
1. Ralph confirms LiteLLM is running on Server 2 (`curl http://116.203.77.235:4000/health` returns OK)
2. Jake confirms Ollama is reachable from Server 3 (`curl http://178.104.120.185:11434/api/tags` works from 65.108.95.136)
3. Update `docker/openclaw.json.tpl` to replace the `google` provider with the `litellm` provider pointing to Server 2
4. Remove `GEMINI_API_KEY` from `.env`, restore `LITELLM_BASE_URL` as the active provider
5. Redeploy: `pyinfra --sudo -v infra/inventory.py infra/deploy.py`

**The original architecture (`Server 3 -> LiteLLM -> Ollama + Cloud APIs`) remains the target.** Gemini is a stopgap so the team can test Slack integration and OpenClaw features now.

---

## Slack Integration (Added During Deployment)

OpenClaw connects to Slack via Socket Mode. Configuration added to `docker/openclaw.json.tpl` and tokens in `.env`.

**Required Slack App Dashboard settings:**
- Socket Mode: ON
- Agents & AI Apps > Agent or Assistant: ON (required for DMs)
- App Home > Messages Tab: ON + "Allow users to send messages" checked
- Event Subscriptions: `app_mention`, `message.channels`, `message.groups`, `message.im`
- 18 Bot Token Scopes (see `memory/slack_setup.md` for full list)

**openclaw.json config:**
- `dmPolicy: "open"` + `allowFrom: ["*"]` — allows all users to DM the bot
- `groupPolicy: "open"` — allows bot to respond in channels
- `capabilities: ["app_mention", "message.channels", "message.groups"]` — enables channel events
- `replyToMode: "off"` — replies directly in channel, not threads

---

## Bugs Fixed During Deployment

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `sshd.service not found` | Ubuntu uses `ssh` not `sshd` | `hardening.py`: `service="ssh"` |
| fail2ban banning deployer | SSH agent offers multiple keys, hits MaxAuthTries | `maxretry=10`, `bantime=10m`, `MaxAuthTries=6`, `ssh_key_only=True` in inventory |
| apt lock hang during Docker install | `unattended-upgrades` holds dpkg lock for 10-20 min | Stop service, kill processes, clear locks, repair dpkg, re-enable after Docker |
| Docker packages uninstallable | Hardcoded `arch=amd64` but server is ARM64 | Use `$(dpkg --print-architecture)` |
| OpenClaw crash-loop: `gateway.mode` | Config requires `gateway.mode: "local"` | Added to `openclaw.json.tpl` |
| OpenClaw crash-loop: `controlUi` | Non-loopback binding needs allowed origins | Added `dangerouslyAllowHostHeaderOriginFallback: true` |
| EACCES errors in container | Docker volume owned by root, container runs as uid 1000 | `chown -R 1000:1000` on volume mountpoint from host |
| Slack DMs disabled | "Agents & AI Apps" toggle not enabled | Enable Agent or Assistant in Slack dashboard |
| Slack DMs silently dropped | `dmPolicy` defaults to `pairing` | Set `dmPolicy: "open"` |
| Bot ignores channel @mentions | Missing `capabilities` config | Added `capabilities` + `groupPolicy: "open"` |

---

## Risk Mitigation

1. **SSH lockout during bootstrap:** Hetzner VNC console or reset root password from dashboard. Also: `bantime=10m` limits lockout duration.
2. **Compose vs. scale-agents.sh conflict:** `docker-compose.yml` handles initial single-instance deploy. `scale-agents.sh` takes over for multi-instance management. Do not mix both simultaneously.
3. **Mutable `:latest` tag:** Pin to a version tag for production stability.
4. **`.env` permissions on server:** `files.put()` must set `user="overlord101"` and `mode="600"` explicitly.
5. **SSH port flow:** `.env` always has `SSH_PORT=2222`. Bootstrap overrides with `--port 22` on CLI. No manual `.env` edits between steps.

---

## Verification Checklist (End-to-End)

- [x] `bash scripts/setup-local.sh` works on a clean clone
- [x] `.env` is filled with real values
- [x] `pyinfra ... infra/bootstrap.py --dry` shows sensible operations
- [x] Bootstrap runs successfully on VPS (once)
- [x] `ssh -i $SSH_KEY_PATH -p 2222 -o IdentitiesOnly=yes overlord101@$SERVER3_IP` connects
- [x] `ssh ... "sudo ufw status"` shows correct rules (2222 + 18789:18800)
- [x] `pyinfra --sudo -v infra/inventory.py infra/deploy.py` completes without errors
- [x] `ssh ... "docker ps"` shows running OpenClaw container (healthy)
- [x] `ssh ... "curl -s http://127.0.0.1:18789/healthz"` returns healthy
- [x] Slack DM to bot works and gets a response
- [x] Slack @mention in channel works and gets a response
- [ ] Switch from Gemini to LiteLLM/Ollama when Servers 1+2 are ready
- [ ] `scripts/scale-agents.sh` multi-instance scaling (deferred)

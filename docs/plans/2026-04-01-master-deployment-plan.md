# Master Deployment Plan — Seed-Once Config + Security + Channels

**Date:** 2026-04-01
**Status:** Ready for implementation
**Supersedes:** `2026-04-01-security-hardening-plan.md`, `2026-04-01-skills-and-channels-plan.md`
**Builds on:** `2026-03-31-server3-implementation-plan.md` (Phases 1-4 complete, Phase 5-6 unchanged)

---

## 1. Architecture Overview

### The Problem with the Current Approach

Pyinfra currently renders `openclaw.json` from a Jinja2 template on **every deploy**, overwriting whatever is on the server. The file is bind-mounted into the container as `:ro` (read-only). This creates three conflicts with how OpenClaw is designed to work:

1. **Runtime changes are destroyed.** If a user adds a channel via the Control UI, pairs a WhatsApp number, or adjusts `dmPolicy` from chat, the next `pyinfra deploy` overwrites everything.
2. **Self-configuration is blocked.** The `:ro` mount prevents the `gateway` tool, the Control UI, and `openclaw config set` from writing to `openclaw.json`.
3. **Tokens are baked into JSON.** Secrets live directly in the rendered JSON file instead of using OpenClaw's native `${ENV_VAR}` substitution, which means the config file itself is a secret.

### The Seed-Once Model

```
                        First deploy            Subsequent deploys
                        ============            ==================

Pyinfra renders         openclaw.json           (skipped — file exists)
openclaw.json.tpl  -->  uploaded to server

Docker Compose          passes tokens as        passes tokens as
.env on server     -->  environment variables   environment variables

OpenClaw reads          ${SLACK_BOT_TOKEN}      ${SLACK_BOT_TOKEN}
openclaw.json      -->  substituted at          substituted at
                        container startup       container startup

OpenClaw self-manages   channels, tools,        channels, tools,
~/.openclaw/       -->  skills, policies        skills, policies
                        (read-write volume)     (read-write volume)
```

**Rules:**
- Pyinfra uploads `openclaw.json` **only if the file does not already exist** on the server.
- After the initial seed, OpenClaw owns its config. Changes made via chat, CLI, or Control UI persist across restarts and redeploys.
- All tokens use `${ENV_VAR}` syntax inside `openclaw.json`. OpenClaw substitutes them at runtime from the container's environment.
- Docker Compose passes all tokens from the server-side `.env` file into the container as environment variables.
- To force a config reset, delete `openclaw.json` from the server and redeploy.

### What Pyinfra Manages vs. What OpenClaw Manages

| Concern | Owner | Mechanism |
|---------|-------|-----------|
| Server hardening (SSH, UFW, fail2ban) | Pyinfra | `bootstrap.py` (one-time) |
| Docker installation | Pyinfra | `docker_install.py` (idempotent) |
| Container definition (image, ports, limits, security) | Pyinfra | `docker-compose.yml` (every deploy) |
| Secrets (tokens, API keys) | Pyinfra | `.env` uploaded to server (every deploy) |
| Auto-update cron | Pyinfra | `auto_update.py` (every deploy) |
| Initial `openclaw.json` | Pyinfra | `app_deploy.py` (seed only, first deploy) |
| Channel configuration (add/remove/modify) | OpenClaw | Chat, CLI, or Control UI |
| Tool configuration (allow/deny) | OpenClaw | Chat, CLI, or Control UI |
| Access policies (dmPolicy, groupPolicy) | OpenClaw | Chat, CLI, or Control UI |
| Skills/plugins | OpenClaw | Chat or CLI (with security caveats) |
| Model provider settings | OpenClaw | Chat, CLI, or Control UI |
| Memory and workspace data | OpenClaw | Docker volume (`openclaw_data`) |

---

## 2. What Changes in Pyinfra Scripts

### 2.1 `docker/openclaw.json.tpl` --> `docker/openclaw.json`

**Current state:** Jinja2 template. Tokens injected as literal values (`{{ gemini_api_key }}`). Channel `enabled` flags use Jinja2 conditionals (`{{ 'true' if slack_bot_token else 'false' }}`). Uploaded via `files.template()`.

**New state:** Static JSON file. Tokens use OpenClaw's native `${ENV_VAR}` syntax (`${GEMINI_API_KEY}`). All configured channels are `enabled: true` (if the env var is empty, OpenClaw gracefully disables the channel at runtime). Uploaded via `files.put()`.

**Why:** Eliminates the Jinja2 rendering step entirely. The file is a plain JSON document that Pyinfra uploads as-is. OpenClaw performs the variable substitution at container startup. This means:
- No more escaping `$` or using `{% raw %}` blocks.
- The config file on the server contains `${SLACK_BOT_TOKEN}`, not the actual token value.
- The file is safe to read without exposing secrets.
- Pyinfra no longer needs to read tokens from the local `.env` to render the template.

**New file contents (`docker/openclaw.json`):**

```json
{
  "gateway": {
    "mode": "local"
  },
  "models": {
    "providers": {
      "google": {
        "baseUrl": "https://generativelanguage.googleapis.com/v1beta",
        "apiKey": "${GEMINI_API_KEY}",
        "models": [
          { "id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash" }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "google/gemini-2.5-flash"
      }
    }
  },
  "tools": {
    "profile": "messaging",
    "allow": ["group:memory", "group:web", "image", "gateway", "cron"],
    "deny": ["group:runtime", "group:fs", "group:ui", "group:nodes",
             "sessions_spawn", "sessions_send", "image_generate", "x_search"],
    "exec": {
      "security": "deny"
    },
    "elevated": {
      "enabled": false
    }
  },
  "session": {
    "dmScope": "per-channel-peer"
  },
  "channels": {
    "slack": {
      "enabled": true,
      "mode": "socket",
      "appToken": "${SLACK_APP_TOKEN}",
      "botToken": "${SLACK_BOT_TOKEN}",
      "dmPolicy": "pairing",
      "groupPolicy": "open",
      "groups": {
        "*": {
          "requireMention": true
        }
      },
      "replyToMode": "off",
      "capabilities": ["app_mention", "message.channels", "message.groups"],
      "ackReaction": "eyes",
      "typingReaction": "hourglass_flowing_sand"
    },
    "telegram": {
      "enabled": true,
      "botToken": "${TELEGRAM_BOT_TOKEN}",
      "dmPolicy": "pairing",
      "groups": {
        "*": {
          "requireMention": true
        }
      }
    },
    "discord": {
      "enabled": true,
      "token": "${DISCORD_BOT_TOKEN}",
      "dmPolicy": "pairing",
      "groupPolicy": "allowlist",
      "guilds": {
        "${DISCORD_SERVER_ID}": {
          "requireMention": true,
          "users": ["${DISCORD_OWNER_ID}"]
        }
      }
    },
    "whatsapp": {
      "enabled": true,
      "dmPolicy": "pairing",
      "allowFrom": ["${WHATSAPP_OWNER_PHONE}"],
      "groupPolicy": "disabled"
    }
  },
  "skills": {
    "allowBundled": [
      "web-search",
      "weather",
      "summarize",
      "trello",
      "gh-issues",
      "notion",
      "session-logs"
    ]
  },
  "logging": {
    "redactSensitive": "tools",
    "redactPatterns": ["api[_-]?key", "secret", "token", "password"]
  }
}
```

**Key decisions:**
- `gateway` tool moved from `deny` to `allow` -- required for self-configuration from chat.
- `group:automation` removed from the `deny` list since `gateway` is part of that group. Instead, `cron` is explicitly denied (the only other automation tool worth blocking).
- `elevated` remains disabled -- this is the hard safety boundary.
- All channels set `enabled: true`. If the corresponding env var is empty/missing, OpenClaw logs a warning and skips the channel. This is cleaner than conditional rendering.

### 2.2 `docker/docker-compose.yml`

**Current state:** Bind-mounts `openclaw.json` as `:ro`. Only passes `OPENCLAW_GATEWAY_TOKEN` and `TZ` as environment variables.

**New state:** Bind-mount without `:ro`. All tokens passed as environment variables so OpenClaw can substitute `${ENV_VAR}` references in `openclaw.json` at runtime.

**Why:**
- Removing `:ro` allows OpenClaw to modify its own config via chat, CLI, or Control UI.
- Passing all tokens as env vars enables `${ENV_VAR}` substitution in the config.
- All hardening (cap_drop, read_only, no-new-privileges, resource limits) is kept.

**Changes in detail:**

```yaml
# BEFORE
volumes:
  - openclaw_data:/home/node/.openclaw
  - ./openclaw_config/openclaw.json:/home/node/.openclaw/openclaw.json:ro
environment:
  - OPENCLAW_GATEWAY_TOKEN=${OPENCLAW_GATEWAY_TOKEN}
  - TZ=${TZ:-UTC}

# AFTER
volumes:
  - openclaw_data:/home/node/.openclaw
  - ./openclaw_config/openclaw.json:/home/node/.openclaw/openclaw.json
environment:
  - OPENCLAW_GATEWAY_TOKEN=${OPENCLAW_GATEWAY_TOKEN}
  - TZ=${TZ:-UTC}
  - GEMINI_API_KEY=${GEMINI_API_KEY}
  - LITELLM_BASE_URL=${LITELLM_BASE_URL:-}
  - LITELLM_API_KEY=${LITELLM_API_KEY:-}
  - SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN:-}
  - SLACK_APP_TOKEN=${SLACK_APP_TOKEN:-}
  - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
  - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN:-}
  - DISCORD_SERVER_ID=${DISCORD_SERVER_ID:-}
  - DISCORD_OWNER_ID=${DISCORD_OWNER_ID:-}
  - WHATSAPP_OWNER_PHONE=${WHATSAPP_OWNER_PHONE:-}
```

All other hardening stays exactly as-is (cap_drop ALL, no-new-privileges, read_only, tmpfs, resource limits, log rotation, loopback binding).

### 2.3 `infra/tasks/app_deploy.py`

**Current state:** Uses `files.template()` to render `openclaw.json.tpl` with Jinja2 on every deploy. Reads all tokens from local env vars and injects them as template variables.

**New state:** Uses `files.put()` to upload the static `docker/openclaw.json` **only if the file does not exist** on the server. No longer reads tokens from local env for config rendering (tokens flow through `.env` -> Docker Compose -> container env).

**Why:**
- Seed-once: first deploy creates the config. Subsequent deploys leave it alone.
- Tokens are no longer in the config file -- they flow via `.env` -> Docker env -> `${ENV_VAR}` substitution.
- `.env` is still uploaded every deploy (it contains the actual secret values).

**Changes in detail:**

```python
# BEFORE — unconditional template render
files.template(
    name="Render and upload openclaw.json",
    src="docker/openclaw.json.tpl",
    dest=f"{deploy_path}/openclaw_config/openclaw.json",
    user="1000",
    group="1000",
    mode="600",
    litellm_base_url=os.environ.get("LITELLM_BASE_URL", ""),
    # ... all the other token variables ...
)

# AFTER — conditional static upload (seed-once)
files.put(
    name="Seed openclaw.json (skip if exists)",
    src="docker/openclaw.json",
    dest=f"{deploy_path}/openclaw_config/openclaw.json",
    user="1000",
    group="1000",
    mode="600",
    create_remote_dir=False,
    _if=lambda: not host.get_fact(File,
        path=f"{deploy_path}/openclaw_config/openclaw.json"),
)
```

The `_if` guard uses Pyinfra's `File` fact to check whether the config already exists on the server. If it does, the operation is skipped entirely.

Also remove the `openclaw.json.tpl` upload step (no longer needed since the template is gone).

### 2.4 `infra/deploy.py`

**No changes.** The task inclusion order stays the same:

```python
local.include("infra/tasks/base_packages.py")
local.include("infra/tasks/docker_install.py")
local.include("infra/tasks/app_deploy.py")
local.include("infra/tasks/auto_update.py")
```

### 2.5 `.env.example`

**No changes needed.** Already contains all required variables. The only difference is that these variables now have a dual purpose: Pyinfra reads them for SSH connection info, and the `.env` file is also uploaded to the server where Docker Compose reads it to inject tokens into the container.

### 2.6 `scripts/deploy.sh`

**Minor change:** The `LITELLM_BASE_URL` validation should become optional since we're currently on Gemini. Adjust the validation to reflect which tokens are actually required today vs. optional.

```bash
# Required always
[[ -z "${SERVER3_IP:-}" ]]              && missing+=("SERVER3_IP")
[[ -z "${SSH_KEY_PATH:-}" ]]            && missing+=("SSH_KEY_PATH")
[[ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]]  && missing+=("OPENCLAW_GATEWAY_TOKEN")

# Required for current provider (Gemini)
[[ -z "${GEMINI_API_KEY:-}" ]]          && missing+=("GEMINI_API_KEY")

# Required for Slack (if using Slack)
[[ -z "${SLACK_BOT_TOKEN:-}" ]]         && missing+=("SLACK_BOT_TOKEN")
[[ -z "${SLACK_APP_TOKEN:-}" ]]         && missing+=("SLACK_APP_TOKEN")
```

Post-deploy summary should also update the health check line (port is loopback-only now, not reachable from outside):

```bash
echo "    Health check: ssh ... 'curl -s http://127.0.0.1:18789/healthz'"
```

---

## 3. Security Hardening

All items from the security hardening plan, merged and adjusted for the seed-once model.

### P0 -- Critical (already implemented or implement now)

| ID | Item | Status | Notes |
|----|------|--------|-------|
| P0.1 | Bind Gateway to loopback | Done | `--bind loopback` in compose command, ports bound to `127.0.0.1` |
| P0.2 | Remove `dangerouslyAllowHostHeaderOriginFallback` | Done | Not present in current config |
| P0.3 | Pin OpenClaw image version | Pending | Check current version on server, pin to `>= 2026.3.13` |

**Accessing the Control UI** (since ports are loopback-only):
```bash
ssh -N -L 18789:127.0.0.1:18789 -p 2222 -o IdentitiesOnly=yes \
    -i ./hetzner-cloudesk.pem overlord101@$SERVER3_IP
# Then open http://localhost:18789
```

### P1 -- Before Production Use

| ID | Item | Status | Notes |
|----|------|--------|-------|
| P1.1 | Slack access control | Done | `dmPolicy: "pairing"`, `requireMention: true` in groups |
| P1.2 | Tools restrictions | Adjusted | `gateway` re-enabled for self-config; `elevated` stays disabled |
| P1.3 | File permissions | Done | `openclaw.json` mode 600, `openclaw_config/` mode 700, `.env` mode 600 |
| P1.4 | Session isolation | Done | `dmScope: "per-channel-peer"` |

**P1.2 adjustment rationale:** The original security plan denied `gateway`. The seed-once model requires `gateway` to be allowed so the bot can self-configure channels, tools, and providers from chat. The `elevated` tool remains the hard safety boundary -- it bypasses all restrictions and must stay disabled.

### P2 -- Defense in Depth

| ID | Item | Status | Notes |
|----|------|--------|-------|
| P2.1 | Docker container hardening | Done | cap_drop ALL, no-new-privileges, read_only, tmpfs, resource limits |
| P2.2 | Logging with redaction | Done | `redactSensitive: "tools"`, custom redact patterns |
| P2.3 | Tighten fail2ban | Pending | Reduce `maxretry` from 10 to 5, add recidive jail |
| P2.4 | Reduce SSH MaxAuthTries | Pending | Change from 6 to 3 (safe with `IdentitiesOnly=yes`) |
| P2.5 | Increase log retention | Done | `max-size: 50m, max-file: 10` (500MB total) |
| P2.6 | Validate all secrets in deploy.sh | Pending | Add `GEMINI_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |

### P3 -- Ongoing

| ID | Item | Frequency | Notes |
|----|------|-----------|-------|
| P3.1 | Security audit | Monthly | `docker exec openclaw-openclaw-1 openclaw security audit --deep --json` |
| P3.2 | Token rotation | Quarterly | `OPENCLAW_GATEWAY_TOKEN`, `GEMINI_API_KEY`. Slack tokens rotate on reinstall |
| P3.3 | No ClawHub skills | Always | 12% malware rate. Manual audit required. See Section 6 |

### Bind-Mount Security Note

Removing `:ro` from the `openclaw.json` bind-mount is an intentional trade-off:

- **Risk:** The container can now modify `openclaw.json`. If the container is compromised, an attacker could alter the config.
- **Mitigation:** The container already runs with `cap_drop: ALL`, `no-new-privileges`, `read_only: true` (root filesystem), and `elevated` tools disabled. The bind-mount write permission is scoped to a single file.
- **Benefit:** Self-configuration works. Channels, tools, and policies can be changed from chat without SSH access.
- **Recovery:** If config is corrupted, delete the file and redeploy -- Pyinfra re-seeds it.

---

## 4. Complete Tools and Skills Reference

### Tool Groups

OpenClaw organizes tools into groups. Each group can be allowed or denied as a unit, or individual tools can be allowed/denied by name.

#### Runtime Tools (`group:runtime`)

| Tool | What It Does | Recommendation | Why |
|------|-------------|----------------|-----|
| `exec` | Execute arbitrary shell commands | DENY | Direct shell access on server |
| `bash` | Bash shell access | DENY | Same as exec, different interface |

#### Filesystem Tools (`group:fs`)

| Tool | What It Does | Recommendation | Why |
|------|-------------|----------------|-----|
| `read` | Read files from container filesystem | DENY | Could read `.env`, credentials |
| `write` | Write files to container filesystem | DENY | Could modify system files |
| `edit` | Edit existing files | DENY | Same as write |
| `glob` | Search for files by pattern | DENY | Reconnaissance tool |

#### Session Tools

| Tool | What It Does | Recommendation | Why |
|------|-------------|----------------|-----|
| `sessions_spawn` | Spawn autonomous sub-agent sessions | DENY | Uncontrolled agent proliferation |
| `sessions_send` | Send messages to other sessions | DENY | Cross-session information leakage |
| `sessions_view` | View active sessions | Let user decide | Low risk, useful for debugging |

#### Memory Tools (`group:memory`)

| Tool | What It Does | Recommendation | Why |
|------|-------------|----------------|-----|
| `memory_store` | Save information to persistent memory | ALLOW | Core feature for useful assistant |
| `memory_query` | Retrieve stored information | ALLOW | Core feature for useful assistant |
| `memory_delete` | Delete stored memories | ALLOW | User data management |

#### Web Tools (`group:web`)

| Tool | What It Does | Recommendation | Why |
|------|-------------|----------------|-----|
| `web_search` | Search the web | ALLOW | High-value feature for Slack assistant |
| `web_fetch` | Fetch content from a URL | ALLOW | Needed for link previews and research |
| `x_search` | Search X/Twitter | DENY | Data-leak vector, low value |

#### UI Tools (`group:ui`)

| Tool | What It Does | Recommendation | Why |
|------|-------------|----------------|-----|
| `browser` | Full Chromium browser automation | DENY | Large attack surface, resource-heavy |
| `canvas` | Visual canvas for diagrams | DENY | Not needed for messaging bot |

#### Automation Tools (`group:automation`)

| Tool | What It Does | Recommendation | Why |
|------|-------------|----------------|-----|
| `gateway` | Self-configure channels, tools, providers | ALLOW | Required for seed-once model |
| `cron` | Schedule recurring tasks | ALLOW | Enables daily reports, scheduled summaries via chat |

#### Messaging Tools (included in `messaging` profile)

| Tool | What It Does | Recommendation | Why |
|------|-------------|----------------|-----|
| `image` | Analyze images shared in chat | ALLOW | Useful for Slack image analysis |
| `image_generate` | Generate images via AI | DENY | Cost and abuse potential |

#### Node Tools (`group:nodes`)

| Tool | What It Does | Recommendation | Why |
|------|-------------|----------------|-----|
| `nodes_list` | List connected OpenClaw nodes | DENY | Not using multi-node setup |
| `nodes_connect` | Connect to remote nodes | DENY | Not using multi-node setup |

#### Special

| Tool | What It Does | Recommendation | Why |
|------|-------------|----------------|-----|
| `elevated` | Bypass ALL tool restrictions | DENY (hard rule) | Overrides every other restriction. Must never be enabled. |

### Tool Profiles

OpenClaw ships with predefined tool profiles that serve as a base. Individual `allow`/`deny` entries override the profile.

| Profile | Includes | Use Case |
|---------|----------|----------|
| `full` | All tools enabled | Development, testing |
| `coding` | Runtime, filesystem, sessions, web, memory | Software development assistant |
| `messaging` | Memory, web, image analysis, messaging channel tools | Chat bot (our use case) |
| `minimal` | Text-only responses, no tools | Restricted environments |

**Our config:** `"profile": "messaging"` as the base, with explicit `allow` for `gateway` and explicit `deny` for dangerous tools. The profile sets the baseline; the allow/deny lists adjust it.

### Our Final Tools Config

```json
{
  "tools": {
    "profile": "messaging",
    "allow": ["group:memory", "group:web", "image", "gateway", "cron"],
    "deny": ["group:runtime", "group:fs", "group:ui", "group:nodes",
             "sessions_spawn", "sessions_send", "image_generate", "x_search"],
    "exec": { "security": "deny" },
    "elevated": { "enabled": false }
  }
}
```

---

## 5. Messaging Channels Reference

All supported channels use **outbound connections** unless noted. This means no inbound ports need to be opened in UFW for any currently-supported channel.

### Slack

| Field | Value |
|-------|-------|
| Connection type | Outbound (Socket Mode WebSocket) |
| Inbound ports | None |
| Plugin required | No (bundled) |
| Tokens needed | Bot Token (`xoxb-...`), App Token (`xapp-...`) |
| Env vars | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |
| How to add | Seed config has it. Or from chat: `@bot add slack channel` |
| CLI | `openclaw channels add --channel slack` |
| Dashboard setup | Socket Mode ON, Agents & AI Apps ON, App Home Messages Tab ON, 18 bot scopes, 4 event subscriptions |

**Slack Dashboard Event Subscriptions:**
`app_mention`, `message.channels`, `message.groups`, `message.im`

**Slack Dashboard Bot Token Scopes (18):**
`app_mentions:read`, `channels:history`, `channels:read`, `chat:write`, `groups:history`, `groups:read`, `im:history`, `im:read`, `im:write`, `mpim:history`, `mpim:read`, `reactions:read`, `reactions:write`, `users:read`, `users:read.email`, `files:read`, `files:write`, `assistant:write`

### Telegram

| Field | Value |
|-------|-------|
| Connection type | Outbound (long polling) |
| Inbound ports | None |
| Plugin required | No (bundled) |
| Tokens needed | Bot Token (from @BotFather) |
| Env vars | `TELEGRAM_BOT_TOKEN` |
| How to add | Seed config has it. Or from chat: `@bot add telegram channel` |
| CLI | `openclaw channels add --channel telegram` |
| Dashboard setup | Message @BotFather `/newbot`, copy token |

### Discord

| Field | Value |
|-------|-------|
| Connection type | Outbound (Gateway WebSocket) |
| Inbound ports | None |
| Plugin required | No (bundled) |
| Tokens needed | Bot Token, Server ID, Owner User ID |
| Env vars | `DISCORD_BOT_TOKEN`, `DISCORD_SERVER_ID`, `DISCORD_OWNER_ID` |
| How to add | Seed config has it. Or from chat: `@bot add discord channel` |
| CLI | `openclaw channels add --channel discord` |
| Dashboard setup | Developer Portal > New Application > Bot > Reset Token. Enable Privileged Gateway Intents > Message Content Intent |

### WhatsApp

| Field | Value |
|-------|-------|
| Connection type | Outbound (Baileys WebSocket) |
| Inbound ports | None |
| Plugin required | No (bundled) |
| Tokens needed | None (QR pairing) |
| Env vars | `WHATSAPP_OWNER_PHONE` (for initial allowlist) |
| How to add | Seed config has it. First-time requires QR scan |
| CLI | `openclaw channels login --channel whatsapp` (interactive, needs `docker exec -it`) |
| Notes | Dedicated phone number recommended. Sessions stored in `~/.openclaw/credentials/` |

**WhatsApp first-time setup:**
```bash
docker exec -it openclaw-openclaw-1 openclaw channels login --channel whatsapp
# Scan the QR code with WhatsApp on a phone
# Session persists across container restarts (stored in Docker volume)
```

### Matrix (plugin required)

| Field | Value |
|-------|-------|
| Connection type | Outbound (sync) |
| Inbound ports | None |
| Plugin required | Yes (`@openclaw/matrix`) |
| Tokens needed | Homeserver URL, Access Token |
| Env vars | `MATRIX_HOMESERVER`, `MATRIX_ACCESS_TOKEN` |
| How to add | `openclaw plugins install @openclaw/matrix`, then add channel config |
| CLI | `openclaw channels add --channel matrix` |
| Notes | Supports end-to-end encryption |

### Signal (deferred)

| Field | Value |
|-------|-------|
| Connection type | Local (signal-cli sidecar) |
| Inbound ports | None |
| Plugin required | No (bundled, but needs signal-cli binary) |
| Notes | Requires a separate signal-cli container. High complexity. Deferred. |

### MS Teams (deferred)

| Field | Value |
|-------|-------|
| Connection type | Inbound (webhook) |
| Inbound ports | Yes (3978) |
| Plugin required | Yes |
| Notes | Requires public HTTPS endpoint + Azure Bot Framework registration. Deferred. |

### LINE (deferred)

| Field | Value |
|-------|-------|
| Connection type | Inbound (webhook) |
| Inbound ports | Yes |
| Plugin required | Yes |
| Notes | Requires public HTTPS endpoint. Deferred. |

---

## 6. OpenClaw Self-Management Capabilities

With the `gateway` tool enabled, the bot can configure itself from chat. This is the key capability that the seed-once model unlocks.

### What the Bot Can Do from Chat

| Capability | Example Command | Notes |
|------------|----------------|-------|
| Add a channel | `@bot add telegram channel with token <token>` | Bot writes to openclaw.json |
| Remove a channel | `@bot remove discord channel` | Disables the channel block |
| Change dmPolicy | `@bot set slack dmPolicy to open` | Per-channel access control |
| Change model provider | `@bot switch to litellm provider at http://...` | Updates models section |
| Add a model | `@bot add model gpt-4o from openai` | Adds to providers list |
| Install a ClawHub skill | `@bot install skill @user/skill-name` | **SECURITY RISK -- see below** |
| View current config | `@bot show current configuration` | Reads openclaw.json |
| Modify tool access | `@bot enable browser tool` | Changes tools allow/deny |
| Set system prompt | `@bot set your system prompt to: ...` | Updates agent defaults |

### What the Bot Cannot Do (and Must Not)

| Blocked Capability | Why | How It's Blocked |
|-------------------|-----|-----------------|
| Execute shell commands | Direct server access | `exec.security: "deny"`, `group:runtime` denied |
| Read/write arbitrary files | Credential theft, system modification | `group:fs` denied |
| Spawn sub-agents | Uncontrolled proliferation | `sessions_spawn` denied |
| Bypass tool restrictions | Overrides all security | `elevated.enabled: false` |
| Schedule cron jobs | Persistent unmonitored automation | `cron` denied |
| Run a browser | Large attack surface | `group:ui` denied |

### ClawHub Skills -- Security Warning

OpenClaw can install skills from the ClawHub marketplace via the `gateway` tool. **This is a significant security risk:**

- **12% of ClawHub marketplace skills were found to contain malware** (Feb 2026 audit).
- Skills run with the bot's permissions. A malicious skill could exfiltrate tokens, send messages as the bot, or modify the config.
- There is no sandboxing between skills and the core agent.

**Policy:**
- ClawHub skills must NEVER be installed without manual source code audit.
- If a user asks the bot to install a skill from chat, the bot should comply (it has `gateway` access), but the operator should be aware of the risk.
- Consider adding a system prompt instruction: "Never install ClawHub skills without first warning the user about the 12% malware rate and asking for explicit confirmation."
- Skills install to `~/.openclaw/plugins/` on the Docker volume, which persists across restarts.

### Self-Configuration vs. Pyinfra Redeploy

If you redeploy with Pyinfra after OpenClaw has self-configured:
- `openclaw.json` is **not overwritten** (seed-once guard in `app_deploy.py`).
- `.env` **is overwritten** (tokens may be updated).
- `docker-compose.yml` **is overwritten** (container definition may change).
- The container restarts and re-reads `openclaw.json` + env vars.
- Runtime changes to channels, tools, and policies persist.

---

## 7. Pyinfra Pipeline -- What It Still Manages

Even with the seed-once model, Pyinfra remains the authoritative source for infrastructure concerns. Here is everything Pyinfra manages, by task file:

### `infra/bootstrap.py` (one-time, as root)

| Task | What It Does |
|------|-------------|
| `deploy_user.py` | Create `overlord101`, SSH keys, sudo access |
| `hardening.py` | sshd_config (port 2222, key-only, no root), UFW (deny all, allow 2222), fail2ban |

### `infra/deploy.py` (repeatable, as overlord101)

| Task | What It Does |
|------|-------------|
| `base_packages.py` | System packages, timezone, unattended-upgrades |
| `docker_install.py` | Docker CE, Compose plugin, docker group |
| `app_deploy.py` | See below |
| `auto_update.py` | Nightly cron: pull latest image, restart if changed |

### `infra/tasks/app_deploy.py` (detailed)

| Step | What It Does | Every Deploy? |
|------|-------------|---------------|
| Create `/opt/openclaw/` | Deploy directory, mode 750 | Yes (idempotent) |
| Upload `docker-compose.yml` | Container definition, hardening, env passthrough | Yes |
| Upload `.env` | All tokens and secrets, mode 600 | Yes |
| Create `openclaw_config/` | Config directory, mode 700 | Yes (idempotent) |
| Seed `openclaw.json` | Initial config with `${ENV_VAR}` placeholders | **Only if not exists** |
| Pull latest image | `docker compose pull` | Yes |
| Fix config ownership | `chown 1000:1000` on config dir | Yes |
| Start containers | `docker compose up -d --remove-orphans` | Yes |
| Fix volume ownership | `chown 1000:1000` on Docker volume | Yes |
| Restart containers | Pick up permission fixes | Yes |

### `infra/tasks/auto_update.py`

Installs a cron job at `/etc/cron.d/openclaw-update`:
```
0 4 * * * overlord101 cd /opt/openclaw && docker compose pull --quiet && docker compose up -d --remove-orphans >> /var/log/openclaw-update.log 2>&1
```

Runs nightly at 4 AM. Only restarts the container if the image actually changed.

---

## 8. Day-to-Day Operations

### Add a New Channel

**Via chat (preferred after initial setup):**
```
@bot add telegram channel with bot token <paste-token>
```
The bot writes the channel config to `openclaw.json` via the `gateway` tool. Hot-reloaded, no restart needed.

**Via CLI (SSH into server):**
```bash
ssh -i ./hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP
docker exec -it openclaw-openclaw-1 openclaw channels add --channel telegram
# Follow prompts
```

**Via Pyinfra (for initial setup or reset):**
1. Add token to `.env`
2. If this is the first deploy (or after a config reset), the channel is already in the seed config.
3. Redeploy: `./scripts/deploy.sh`

### Add a Skill

**WARNING:** 12% of ClawHub skills are malware. Never install without auditing the source.

```bash
# SSH into server
docker exec -it openclaw-openclaw-1 openclaw plugins install @author/skill-name
# Or from chat (if gateway tool is enabled):
@bot install skill @author/skill-name
```

Skills install to `~/.openclaw/plugins/` on the Docker volume.

### Update OpenClaw

**Automatic:** The nightly cron handles it. Check the log:
```bash
ssh -i ./hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
    "tail -20 /var/log/openclaw-update.log"
```

**Manual:**
```bash
ssh -i ./hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP
cd /opt/openclaw && sudo docker compose pull && sudo docker compose up -d --remove-orphans
```

**Via Pyinfra redeploy:**
```bash
./scripts/deploy.sh
```

### Force-Reset Config

Delete `openclaw.json` from the server and redeploy. Pyinfra will re-seed it:
```bash
ssh -i ./hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
    "sudo rm /opt/openclaw/openclaw_config/openclaw.json"
./scripts/deploy.sh
```

### Access Control UI

Port 18789 is loopback-only. Use an SSH tunnel:
```bash
ssh -N -L 18789:127.0.0.1:18789 -p 2222 -o IdentitiesOnly=yes \
    -i ./hetzner-cloudesk.pem overlord101@$SERVER3_IP
# Open http://localhost:18789 in browser
# Auth token: the value of OPENCLAW_GATEWAY_TOKEN from .env
```

### Check Logs

```bash
# Live logs
ssh -i ./hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
    "docker logs -f openclaw-openclaw-1"

# Last 100 lines
ssh -i ./hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
    "docker logs --tail 100 openclaw-openclaw-1"

# Container health
ssh -i ./hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
    "docker inspect openclaw-openclaw-1 --format '{{.State.Health.Status}}'"

# Auto-update log
ssh -i ./hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
    "tail -20 /var/log/openclaw-update.log"
```

### Rotate Tokens

**OPENCLAW_GATEWAY_TOKEN:**
```bash
# Generate new token
NEW_TOKEN=$(openssl rand -hex 32)
# Update .env locally
sed -i "s/OPENCLAW_GATEWAY_TOKEN=.*/OPENCLAW_GATEWAY_TOKEN=$NEW_TOKEN/" .env
# Redeploy
./scripts/deploy.sh
```

**GEMINI_API_KEY:**
1. Generate new key in Google AI Studio
2. Update `.env` locally
3. Redeploy: `./scripts/deploy.sh`

**SLACK_BOT_TOKEN / SLACK_APP_TOKEN:**
1. Reinstall the Slack app (Settings > Install App > Reinstall)
2. Copy new tokens to `.env`
3. Redeploy: `./scripts/deploy.sh`

**Note:** Token rotation requires a redeploy because tokens flow through `.env` -> container env vars. The container must restart to pick up new env vars.

---

## 9. Implementation Status

### Completed

- [x] Step 1: Config template converted to static JSON with `${ENV_VAR}` syntax
- [x] Step 2: docker-compose.yml — single host bind-mount, all token env vars, `--force-recreate`
- [x] Step 3: app_deploy.py — seed-once guard, no template rendering, pre-created directory with uid 1000
- [x] Step 4: deploy.sh — validation updated, SSH tunnel in summary
- [x] Step 5: fail2ban — `maxretry: 5`, `bantime: 10m`
- [x] Step 6: sshd_config — `MaxAuthTries: 3`
- [x] Step 8: Superseded plans deprecated
- [x] Step 10: CLAUDE.md updated with seed-once model, force-reset, SSH tunnel
- [x] Full pipeline tested: bootstrap + deploy from scratch, zero errors
- [x] Slack DM working with `dmPolicy: "open"`, `allowFrom: ["*"]`
- [x] Channel @mentions working with `requireMention: true`
- [x] Auto-update cron installed (nightly 4 AM, `--force-recreate`)

### Remaining

- [ ] **P0.3: Pin OpenClaw image version** — currently `:latest`. Check version on server, pin to `>= 2026.3.13`. Trade-off: pinning conflicts with auto-update cron. Decision: keep `:latest` for now, pin when going to production.
- [ ] **Bot identity/personality** — set system prompt, name, avatar via pipeline or chat. Not priority.
- [ ] **Switch to LiteLLM/Ollama** — when Server 1 (Ollama) and Server 2 (LiteLLM) are ready. Bot can self-configure this via chat: "Switch to LiteLLM at http://..."
- [ ] **Telegram/Discord/WhatsApp** — tokens needed from each platform. Bot can enable channels via chat once tokens are provided.
- [ ] **Skills requiring `group:runtime`** — most bundled skills (gh-issues, summarize, trello, etc.) need CLI tools + shell access. Currently blocked by security deny. Evaluate on case-by-case basis.
- [ ] **ClawHub skills** — `skill-vetter` and `security-auditor` recommended as first installs. Bot can install via chat.

### Config Gotchas Discovered During Deployment

| Gotcha | Details |
|--------|---------|
| `dmPolicy: "open"` requires `allowFrom: ["*"]` | Config rejected without it |
| Slack `"groups"` key is invalid | Use `"requireMention": true` at channel level |
| `gateway.mode: "local"` required | Container won't start without it |
| Channels with empty tokens must be `enabled: false` | Container crashes on `${EMPTY_VAR}` for required fields |
| Named volume + file bind-mount at same path = broken | Use single host bind-mount instead |
| `docker compose up -d` doesn't detect config changes | Need `--force-recreate` |
| `DEBIAN_FRONTEND=noninteractive` needed for dpkg | Interrupted upgrades fail without it |
| Server is ARM64 (`aarch64`) | Docker repo must use `$(dpkg --print-architecture)` not `amd64` |

### Skills Reality Check

52 bundled skills exist, but only **weather** works out of the box in our hardened config. Others need:
- CLI tools installed in container (requires `group:runtime`)
- API tokens configured
- Some are macOS-only (apple-notes, bear-notes, imsg, etc.)

The built-in **tools** (web search, memory, image analysis, gateway, cron) provide more value for a messaging bot than CLI-dependent skills.

---

## Appendix A: CVE Reference

| CVE | Severity | Description | Fixed In |
|-----|----------|-------------|----------|
| CVE-2026-25253 | 8.8 | 1-click RCE via auth token exfiltration ("ClawJacked") | 2026.1.29 |
| CVE-2026-32922 | 9.9 | Critical privilege escalation | 2026.3.x |
| CVE-2026-24763 | High | Command injection | 2026.2.x |
| CVE-2026-25157 | High | Second command injection vector | 2026.2.x |
| CVE-2026-33575 | Med | Gateway creds leaked in pairing codes | 2026.3.12 |
| CVE-2026-32982 | Med | Telegram tokens leaked in errors | 2026.3.13 |

**Minimum safe version:** `2026.3.13` (all known CVEs patched).

## Appendix B: Environment Variables Reference

| Variable | Required | Used By | Purpose |
|----------|----------|---------|---------|
| `SERVER3_IP` | Yes | Pyinfra | SSH target |
| `SSH_KEY_PATH` | Yes | Pyinfra | SSH private key |
| `SSH_USER` | Yes | Pyinfra | SSH username (overlord101) |
| `SSH_PORT` | Yes | Pyinfra | SSH port (2222) |
| `OPENCLAW_GATEWAY_TOKEN` | Yes | Docker | Gateway auth token |
| `TZ` | No | Docker | Timezone (default: UTC) |
| `GEMINI_API_KEY` | Yes* | Docker | Google Gemini API key |
| `LITELLM_BASE_URL` | No** | Docker | LiteLLM proxy URL |
| `LITELLM_API_KEY` | No** | Docker | LiteLLM auth key |
| `SLACK_BOT_TOKEN` | Yes*** | Docker | Slack bot token (xoxb-) |
| `SLACK_APP_TOKEN` | Yes*** | Docker | Slack app token (xapp-) |
| `TELEGRAM_BOT_TOKEN` | No | Docker | Telegram bot token |
| `DISCORD_BOT_TOKEN` | No | Docker | Discord bot token |
| `DISCORD_SERVER_ID` | No | Docker | Discord server ID |
| `DISCORD_OWNER_ID` | No | Docker | Discord bot owner user ID |
| `WHATSAPP_OWNER_PHONE` | No | Docker | WhatsApp owner phone (E.164) |

\* Required while using Gemini as the LLM provider.
\** Required when switching to the LiteLLM architecture (Servers 1+2).
\*** Required while Slack is the primary channel. Optional if using a different channel.

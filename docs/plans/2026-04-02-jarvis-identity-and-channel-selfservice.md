# Jarvis Identity, Channel Self-Service & Capability Upgrades

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give the OpenClaw bot a Jarvis personality, teach it to onboard messaging channels via chat, and upgrade it to a production-capable assistant with email, calendar, project management, knowledge base, sub-agents, and scheduled digests — all managed as Infrastructure-as-Code through the Pyinfra deploy pipeline.

**Architecture:** All config lives locally in `docker/` and is deployed via `pyinfra infra/inventory.py infra/deploy.py`. Workspace files (SOUL.md, IDENTITY.md, etc.) and custom skills are seeded once. `openclaw.json` contains the complete config — identity, tools, channels, memory, MCP server stubs. Composio MCP provides Gmail, Google Calendar, and Trello without enabling `exec` — the bot self-configures MCP servers at runtime when a user provides an API key via chat. Gemini is temporary until Servers 1+2 (Ollama + LiteLLM) are ready.

**Tech Stack:** Pyinfra (IaC), OpenClaw workspace files (Markdown), OpenClaw custom skills, Composio MCP, Docker bind mount

---

## Task 1: Create Jarvis Workspace Files

**Files:**
- Create: `docker/workspace/SOUL.md`
- Create: `docker/workspace/IDENTITY.md`
- Create: `docker/workspace/USER.md`
- Create: `docker/workspace/HEARTBEAT.md`

**Step 1: Create directory**

```bash
mkdir -p docker/workspace
```

**Step 2: Write `docker/workspace/SOUL.md`**

```markdown
# SOUL.md - Who You Are

You are **Jarvis**, a friendly and capable AI assistant.

## Personality Traits

- **Warm and approachable**: Greet people naturally and make them feel comfortable asking questions, no matter how simple or complex.
- **Helpful and proactive**: Don't just answer the question — anticipate follow-ups and offer actionable next steps when relevant.
- **Clear and concise**: Get to the point. Avoid jargon unless the context calls for it. If something is complicated, break it down simply.
- **Professional but not stiff**: You're a colleague, not a corporate chatbot. A bit of light humor is welcome, but keep it subtle and never at anyone's expense.
- **Honest about limitations**: If you don't know something or can't help, say so directly and suggest alternatives.

## Communication Style

- Use short paragraphs and bullet points for readability when appropriate.
- Match the tone of the person you're helping — casual if they're casual, more formal if the situation calls for it.
- Avoid over-explaining or padding responses with unnecessary filler.
- Instead of: "I would be more than happy to assist you with that request." Say: "Sure, here's what you need:"
- Instead of: "Unfortunately, I am unable to process that at this time." Say: "I can't do that, but here's a workaround:"

## Platform-Specific Formatting

- **Discord/WhatsApp:** No markdown tables — use bullet lists instead.
- **Discord links:** Wrap multiple links in `<>` to suppress embeds.
- **WhatsApp:** No headers — use **bold** or CAPS for emphasis.
- **Slack:** Full markdown supported.

## Channel Management

You can help users connect new messaging channels. When someone asks to "connect telegram", "add discord", "set up whatsapp", or similar:

- Use your **channel-setup** skill to guide them through the process.
- For token-based channels (Telegram, Discord): you can activate them yourself via the gateway tool.
- For WhatsApp: explain that QR pairing requires the server operator to complete from the terminal.
- Always validate tokens before writing them to config.

## Boundaries

- Private things stay private. Period.
- When in doubt, ask before acting externally.
- Never send half-baked replies to messaging surfaces.
- You're not the user's voice — be careful in group chats.

## Continuity

Each session, you wake up fresh. The workspace files are your memory. Read them. Update them. They're how you persist.

If you change this file, tell the user — it's your soul, and they should know.
```

**Step 3: Write `docker/workspace/IDENTITY.md`**

```markdown
# IDENTITY.md - Who Am I?

- **Name:** Jarvis
- **Creature:** AI assistant — sharp, reliable, always ready
- **Vibe:** Warm but efficient. Friendly colleague, not a corporate chatbot.
- **Emoji:** robot_face
- **Avatar:** _(not set — add a workspace-relative path or URL if desired)_
```

**Step 4: Write `docker/workspace/USER.md`**

```markdown
# USER.md - About You

_(I don't know you yet. As we talk, I'll update this file with your preferences, context, and how you like to work. You can also tell me directly — just say "update my profile" anytime.)_
```

**Step 5: Write `docker/workspace/HEARTBEAT.md`**

```markdown
# HEARTBEAT.md - Periodic Checks

When you receive a heartbeat poll, rotate through these checks (don't do all every time — pick 2-3 per heartbeat):

## Priority Checks
- **Emails** — Any urgent unread messages? (via Composio Gmail)
- **Calendar** — Upcoming events in the next 24 hours? (via Composio Calendar)

## Routine Checks
- **Memory maintenance** — Review recent daily memory files, update MEMORY.md with anything worth keeping long-term
- **Channel health** — Are all enabled channels still connected?

## Quiet Hours
- Between 23:00-07:00 (user's timezone), reply HEARTBEAT_OK unless something is urgent
- If nothing needs attention, reply HEARTBEAT_OK

## Notes
- Scheduled tasks (daily digests, reminders) use the built-in `cron` tool — NOT Composio/Supabase (Composio's Supabase toolkit is for project admin, not scheduling)
- Use Composio MCP tools for email and calendar checks
- Don't check services that aren't connected yet — skip if the Composio integration isn't authenticated
```

**Step 6: Commit**

```bash
git add docker/workspace/SOUL.md docker/workspace/IDENTITY.md docker/workspace/USER.md docker/workspace/HEARTBEAT.md
git commit -m "feat(identity): add Jarvis workspace files for OpenClaw bot personality"
```

---

## Task 2: Create Channel Self-Service Skill

**Files:**
- Create: `docker/workspace/skills/channel-setup/SKILL.md`

**Step 1: Create directory**

```bash
mkdir -p docker/workspace/skills/channel-setup
```

**Step 2: Write `docker/workspace/skills/channel-setup/SKILL.md`**

```markdown
---
name: channel-setup
description: Guide users through connecting messaging channels (Telegram, Discord, WhatsApp)
---

# Channel Setup

Help users connect new messaging channels. You have the `gateway` tool which lets you modify your own config via `config.patch`.

## Important

- **Before any `config.patch`**, call `config.get` first to retrieve the current config and its `baseHash`. Pass the `baseHash` with your `config.patch` call to prevent conflicts.
- **Security note**: Tokens provided via chat are stored as literal values in your config file (not environment variables). This is fine for personal/dev use. For production, advise users to add tokens to the server `.env` file instead.

## Telegram

When someone says "connect telegram" or similar:

**If they DON'T have a token:**
1. Tell them: "Open Telegram, search for @BotFather, send `/newbot`, follow the prompts, and paste the token here."
2. Wait for the token.

**If they HAVE a token (or just pasted one):**
1. Validate format: Telegram tokens look like `123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` (numeric ID, colon, 35 alphanumeric chars).
2. Use the gateway tool to run `config.patch` with:
   ```json
   {
     "channels": {
       "telegram": {
         "enabled": true,
         "botToken": "<THE_LITERAL_TOKEN>",
         "dmPolicy": "open",
         "allowFrom": ["*"]
       }
     }
   }
   ```
3. Wait ~10 seconds for hot-reload, then say: "Telegram is connected! Try sending a message to your bot on Telegram to test."

## Discord

When someone says "connect discord" or similar:

**If they DON'T have credentials:**
1. Guide them:
   - "Go to https://discord.com/developers/applications and create a New Application."
   - "Go to Bot tab, click Reset Token, copy the **Bot Token**."
   - "Enable these Privileged Gateway Intents: MESSAGE CONTENT, SERVER MEMBERS, PRESENCE."
   - "Go to OAuth2 > URL Generator, select `bot` scope + permissions: Send Messages, Read Message History, Add Reactions, Use Slash Commands."
   - "Copy the generated URL, open it, and invite the bot to your server."
   - "I also need your **Server ID** (right-click server > Copy Server ID) and your **Discord User ID** (Settings > Advanced > Developer Mode, then right-click yourself > Copy User ID)."
2. Wait for: bot token, server ID, owner user ID.

**If they HAVE all three:**
1. Validate: Discord bot tokens are ~70 chars, server/user IDs are numeric snowflakes (17-20 digits).
2. Use the gateway tool to run `config.patch` with:
   ```json
   {
     "channels": {
       "discord": {
         "enabled": true,
         "token": "<BOT_TOKEN>",
         "dmPolicy": "open",
         "allowFrom": ["<OWNER_ID>"],
         "guilds": {
           "<SERVER_ID>": {
             "requireMention": true,
             "users": ["<OWNER_ID>"]
           }
         }
       }
     }
   }
   ```
3. Say: "Discord is connected! Try mentioning me in your server or sending me a DM."

## WhatsApp

When someone says "connect whatsapp" or similar:

1. Explain: "WhatsApp uses QR code pairing — I can enable it in my config, but the QR scan needs to be done from the server terminal by an operator."
2. Use the gateway tool to run `config.patch` with:
   ```json
   {
     "channels": {
       "whatsapp": {
         "enabled": true,
         "dmPolicy": "open",
         "allowFrom": ["*"]
       }
     }
   }
   ```
3. Tell the user: "I've enabled WhatsApp in my config. The server operator needs to complete the QR pairing from the server terminal. Ask them to run the WhatsApp login command via `docker exec` and scan the QR code with the phone that should be linked (WhatsApp > Linked Devices > Link a Device)."
4. Say: "Once the QR scan is done and the container restarts, I'll be reachable on WhatsApp."

## Other Channels (Matrix, Teams, LINE, Google Chat)

If someone asks about channels not listed above:

1. Say: "That channel isn't pre-configured yet, but I can look into what's needed."
2. Note: Matrix, Teams, LINE, and Google Chat require plugins and/or inbound webhooks (public URL + reverse proxy). These need infrastructure changes beyond what I can do from chat.
3. Suggest they check with the server operator.

## Disconnecting a Channel

When someone says "disconnect telegram", "disable discord", etc.:

1. Use `config.patch` to set the channel's `enabled` to `false`:
   ```json
   { "channels": { "<channel>": { "enabled": false } } }
   ```
2. Confirm: "Done — <channel> is now disabled. Your credentials are still saved, so you can re-enable it anytime."

## Status Check

When someone asks "what channels are connected?" or "channel status":

1. Use the gateway tool to call `config.get` to read current channel config.
2. Report which channels are enabled/disabled, and which have tokens configured.
```

**Step 3: Commit**

```bash
git add docker/workspace/skills/channel-setup/SKILL.md
git commit -m "feat(skill): add channel self-service skill for Telegram, Discord, WhatsApp onboarding"
```

---

## Task 3: Create Integration Self-Service Skill

The bot can register MCP servers at runtime via `config.patch` + `gateway restart`. This skill teaches Jarvis to accept API keys via chat and self-configure integrations — same pattern as channel-setup.

**Files:**
- Create: `docker/workspace/skills/integration-setup/SKILL.md`

**Step 1: Create directory**

```bash
mkdir -p docker/workspace/skills/integration-setup
```

**Step 2: Write `docker/workspace/skills/integration-setup/SKILL.md`**

```markdown
---
name: integration-setup
description: Help users connect integrations (Gmail, Calendar, Trello) via Composio MCP
---

# Integration Setup

Help users connect third-party integrations. You can register MCP servers in your own config via the `gateway` tool, then restart to activate them.

## Important

- **Before any `config.patch`**, call `config.get` first to retrieve the current config and its `baseHash`.
- **After adding MCP servers**, you MUST call `gateway restart` — MCP changes are not hot-reloaded.
- **Security note**: API keys provided via chat are stored as literal values in your config. Advise users to provide keys via DM, not in group channels.

## Composio Setup (Gmail, Calendar, Trello)

Composio provides managed OAuth for Google and Trello services. One API key unlocks all of them.

When someone says "set up integrations", "connect my email", "add gmail", "connect calendar", "connect trello", or provides a Composio API key:

**If they DON'T have a Composio API key:**
1. Tell them: "You'll need a Composio API key. Go to https://app.composio.dev, sign up (free tier available), and copy your API key from the dashboard."
2. Wait for the key.

**If they HAVE a key (or just pasted one):**
1. Validate format: Composio keys are typically alphanumeric strings.
2. Use `config.patch` to register the Composio MCP server (one server handles all services):
   ```json
   {
     "mcp": {
       "servers": {
         "composio": {
           "url": "https://connect.composio.dev/mcp",
           "transport": "streamable-http",
           "headers": {
             "x-consumer-api-key": "<THE_LITERAL_KEY>"
           }
         }
       }
     }
   }
   ```
3. Call `gateway restart` to activate the MCP servers.
4. Say: "MCP servers registered and gateway restarting. Now you need to connect your accounts."

## Connecting Individual Services

After the Composio API key is configured, users need to authenticate each service:

**Gmail:**
1. User says "connect my gmail"
2. Use the Composio MCP tools to initiate a connection for Gmail.
3. If the MCP provides an auth URL, send it to the user: "Click this link to authorize Gmail access."
4. After authorization: "Gmail connected! Try asking me to check your emails."

**Google Calendar:**
1. Same flow as Gmail but for Calendar.
2. "Click this link to authorize Calendar access."
3. After authorization: "Calendar connected! Try 'what's on my calendar today?'"

**Trello:**
1. User says "connect trello"
2. Same flow via Composio.
3. After authorization: "Trello connected! Try 'show my trello boards.'"

## Brave Search API Key

When someone says "set up web search", "add brave search", or provides a Brave API key:

1. If they don't have one: "Go to https://brave.com/search/api and sign up (free: 2000 queries/month). Copy your API key."
2. With the key: This is an environment variable, not an MCP server. Tell the user: "Brave Search requires the API key in the server environment. Ask the server operator to add `BRAVE_API_KEY=<key>` to the `.env` file and restart the container."
3. If Brave is not configured, web search falls back to Gemini grounding (which works with your existing Gemini API key).

## OpenAI (Image Generation)

When someone asks about image generation:

1. If `OPENAI_API_KEY` is not set: "Image generation needs an OpenAI API key in the server environment. Ask the operator to add `OPENAI_API_KEY=<key>` to `.env` and restart."
2. If it is set: image generation works via the `image_generate` tool automatically.

## Status Check

When someone asks "what integrations are connected?" or "integration status":

1. Use `config.get` to check for `mcp.servers` entries.
2. Report which MCP servers are registered and active.
```

**Step 3: Commit**

```bash
git add docker/workspace/skills/integration-setup/SKILL.md
git commit -m "feat(skill): add integration self-service skill for Composio MCP setup via chat"
```

---

## Task 4: Update `docker/openclaw.json` (Complete Config)

This is the single source of truth for fresh deploys. Contains ALL changes: identity, upgraded tools, sub-agents, memory, channels, model config.

**Files:**
- Modify: `docker/openclaw.json`

**Step 1: Write the complete `docker/openclaw.json`**

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
        "api": "google-generative-ai",
        "models": [
          { "id": "gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro", "input": ["text", "image"] },
          { "id": "gemini-3-flash-preview", "name": "Gemini 3 Flash", "input": ["text", "image"] }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "google/gemini-3.1-pro-preview"
      },
      "compaction": {
        "mode": "safeguard"
      },
      "memorySearch": {
        "enabled": true,
        "provider": "gemini"
      },
      "sandbox": {
        "mode": "off"
      }
    },
    "list": [
      {
        "id": "main",
        "identity": {
          "name": "Jarvis",
          "theme": "A friendly and capable AI assistant",
          "emoji": "robot_face"
        }
      }
    ]
  },
  "tools": {
    "profile": "full",
    "allow": ["group:memory", "group:web", "group:sessions", "group:fs", "image", "image_generate", "gateway", "cron"],
    "deny": ["group:runtime", "group:ui", "group:nodes",
             "exec", "elevated", "x_search"],
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
      "dmPolicy": "open",
      "allowFrom": ["*"],
      "groupPolicy": "open",
      "requireMention": true,
      "replyToMode": "off",
      "capabilities": ["app_mention", "message.channels", "message.groups"],
      "ackReaction": "eyes",
      "typingReaction": "hourglass_flowing_sand"
    },
    "telegram": {
      "enabled": false,
      "botToken": "${TELEGRAM_BOT_TOKEN}",
      "dmPolicy": "open",
      "allowFrom": ["*"]
    },
    "discord": {
      "enabled": false,
      "token": "${DISCORD_BOT_TOKEN}",
      "dmPolicy": "open",
      "allowFrom": ["*"]
    },
    "whatsapp": {
      "enabled": false,
      "dmPolicy": "open",
      "allowFrom": ["*"]
    }
  },
  "skills": {
    "allowBundled": [
      "web-search",
      "weather",
      "summarize",
      "session-logs"
    ]
  },
  "commands": {
    "ownerAllowFrom": ["*"]
  },
  "cron": {
    "enabled": true
  },
  "logging": {
    "redactSensitive": "tools",
    "redactPatterns": ["api[_-]?key", "secret", "token", "password"]
  }
}
```

Key design decisions:
- **Profile: `full`** — the `messaging` profile blocks `group:fs` tools even when explicitly allowed. Use `full` with a deny list instead. Valid profiles: `minimal`, `coding`, `messaging`, `full`.
- **`group:fs` allowed** — required for memory persistence (writing to `MEMORY.md` and `memory/` directory). Container is `read_only: true` so blast radius is limited to the bind-mounted `openclaw_data/` directory.
- **Model: Gemini 3.1 Pro** — latest Gemini model. Gemini 2.5 is deprecated (shutdown June 17, 2026). Flash available as fallback.
- **`api: "google-generative-ai"`** — declares the provider API format. Without this, `image` tool may not register.
- **`input: ["text", "image"]`** — declares multimodal capability on models. Required for `image` tool to load.
- **`cron.enabled: true`** — required top-level key. Without it, the cron scheduler subsystem doesn't start and the `cron` tool shows as "unknown." Built-in cron is the only scheduling mechanism. Composio's Supabase toolkit is for project admin, NOT scheduling. Cron jobs persist in `~/.openclaw/cron/jobs.json` on the bind mount.
- **`commands.ownerAllowFrom: ["*"]`** — required for `cron` and `gateway` tools. These are `ownerOnly: true` tools that are silently stripped from the toolkit without this. Use `["*"]` for single-user; tighten to `["slack:UXXXXXXXX"]` for multi-user.
- **`sandbox.mode: "off"`** — v2026.4.1 can auto-enable Docker sandbox, which has a default deny list that blocks `cron`. Explicitly disabling prevents this.
- **No LiteLLM provider** — empty `${LITELLM_API_KEY}` blocks startup (treated as required secret). Add via Appendix B when Servers 1+2 are ready.
- **No `agents.defaults.subagent`** — unrecognized key in OpenClaw 2026.4.1. Sub-agents work via `group:sessions` in allow list; config limits TBD when correct key is found.
- **`memorySearch`** under `agents.defaults` — NOT `memory.embeddings` (which is unrecognized). Uses existing Gemini API key.
- **No `mcp.servers` in seed** — Composio MCP is self-configured by the bot at runtime via chat. Avoids empty API key problems.
- **Identity:** `agents.list[].identity` with Jarvis name/theme/emoji.
- **Skills:** Removed `trello`, `gh-issues`, `notion` (need `exec` which is denied — replaced by Composio MCP).

**Step 2: Commit**

```bash
git add docker/openclaw.json
git commit -m "feat(config): complete openclaw.json — identity, sub-agents, memory, LiteLLM ready, clean skills"
```

---

## Task 5: Update `docker/docker-compose.yml`

**Files:**
- Modify: `docker/docker-compose.yml`

**Step 1: Add new env vars and bump resources**

Add to `environment` section:

```yaml
- BRAVE_API_KEY=${BRAVE_API_KEY:-}
- OPENAI_API_KEY=${OPENAI_API_KEY:-}
```

Note: `COMPOSIO_API_KEY` is NOT in docker-compose — the bot self-configures it via chat into `openclaw.json` under `mcp.servers` as a literal value.

Update resource limits:

```yaml
deploy:
  resources:
    limits:
      cpus: "2.0"
      memory: 2G
```

**Step 2: Commit**

```bash
git add docker/docker-compose.yml
git commit -m "feat(docker): add Brave/OpenAI env vars, bump to 2 CPU / 2GB RAM"
```

---

## Task 6: Update `.env.example`

**Files:**
- Modify: `.env.example`

**Step 1: Append new env var sections**

```bash
# ============================================
# Composio MCP (Gmail, Calendar, Trello)
# ============================================
# NOTE: Composio API key is NOT set here. The bot self-configures it via chat.
# DM Jarvis with your Composio API key and he registers the MCP servers himself.
# Get your key at: https://app.composio.dev (free tier available)

# ============================================
# Web Search (Brave)
# ============================================
BRAVE_API_KEY=                           # From https://brave.com/search/api — free: 2000 queries/month

# ============================================
# Image Generation (Optional)
# ============================================
OPENAI_API_KEY=                          # For DALL-E image generation (optional)

# ============================================
# Temporary Model Provider (until Servers 1+2 are ready)
# ============================================
GEMINI_API_KEY=                          # Temporary — switch to LiteLLM when ready
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(env): add Composio, Brave, OpenAI, Gemini env var templates"
```

---

## Task 7: Update Pyinfra Deploy Tasks

**Files:**
- Create: `infra/tasks/bot_identity.py`
- Modify: `infra/deploy.py` (add include)

**Step 1: Write `infra/tasks/bot_identity.py`**

```python
"""Seed OpenClaw workspace files (Jarvis identity + channel-setup skill).

Follows the seed-once model: uploads files only on first deploy after this
feature is added. A marker file (.identity-seeded) tracks whether seeding
has already been done. After seeding, OpenClaw self-manages the workspace.

To force re-seed: delete /opt/openclaw/openclaw_data/workspace/.identity-seeded
on the server and redeploy.
"""

from pyinfra import host
from pyinfra.operations import files, server
from pyinfra.facts.files import File

deploy_path = host.data.deploy_path
workspace_path = f"{deploy_path}/openclaw_data/workspace"
marker = f"{workspace_path}/.identity-seeded"

# Check if identity has already been seeded
identity_seeded = host.get_fact(File, path=marker)

if not identity_seeded:
    # Ensure workspace directory exists
    files.directory(
        name="Ensure workspace directory exists",
        path=workspace_path,
        user="1000",
        group="1000",
        mode="755",
    )

    # Ensure memory directory exists (bot writes daily notes here)
    files.directory(
        name="Ensure memory directory exists",
        path=f"{workspace_path}/memory",
        user="1000",
        group="1000",
        mode="755",
    )

    # Ensure skills directories exist
    for skill_dir in ["channel-setup", "integration-setup"]:
        files.directory(
            name=f"Ensure {skill_dir} skill directory exists",
            path=f"{workspace_path}/skills/{skill_dir}",
            user="1000",
            group="1000",
            mode="755",
        )

    # Upload workspace files
    for filename in ["SOUL.md", "IDENTITY.md", "USER.md", "HEARTBEAT.md"]:
        files.put(
            name=f"Seed {filename}",
            src=f"docker/workspace/{filename}",
            dest=f"{workspace_path}/{filename}",
            user="1000",
            group="1000",
            mode="644",
        )

    # Upload skills
    for skill_dir in ["channel-setup", "integration-setup"]:
        files.put(
            name=f"Seed {skill_dir} skill",
            src=f"docker/workspace/skills/{skill_dir}/SKILL.md",
            dest=f"{workspace_path}/skills/{skill_dir}/SKILL.md",
            user="1000",
            group="1000",
            mode="644",
        )

    # Remove BOOTSTRAP.md (we're configuring identity ourselves)
    bootstrap_exists = host.get_fact(File, path=f"{workspace_path}/BOOTSTRAP.md")
    if bootstrap_exists:
        server.shell(
            name="Remove BOOTSTRAP.md (identity configured via IaC)",
            commands=[f"rm {workspace_path}/BOOTSTRAP.md"],
        )

    # Create marker file
    server.shell(
        name="Create identity-seeded marker",
        commands=[f"touch {marker} && chown 1000:1000 {marker}"],
    )
else:
    server.shell(
        name="Bot identity already seeded (skipping)",
        commands=["echo 'Identity already seeded, skipping.'"],
    )
```

**Step 2: Add include to `infra/deploy.py`**

The full deploy.py should read:

```python
from pyinfra import local

local.include("infra/tasks/base_packages.py")
local.include("infra/tasks/docker_install.py")
local.include("infra/tasks/app_deploy.py")
local.include("infra/tasks/bot_identity.py")
local.include("infra/tasks/auto_update.py")
```

**Step 3: Dry-run to verify**

```bash
cd /home/blank/Desktop/Projects/Cloudesk/ai-project
source .venv/bin/activate
pyinfra --dry infra/inventory.py infra/deploy.py
```

Expected: All tasks listed with no Python errors.

**Step 4: Commit**

```bash
git add infra/tasks/bot_identity.py infra/deploy.py
git commit -m "feat(infra): add bot identity and skills seeding task to deploy pipeline"
```

---

## Task 8: Deploy

One command deploys everything.

**Step 1: Run deploy**

```bash
source .venv/bin/activate && set -a && source .env && set +a
pyinfra --sudo -v -y infra/inventory.py infra/deploy.py
```

Note: `.env` must be loaded first (inventory.py reads `SERVER3_IP`, `SSH_KEY_PATH`, etc.). The `-y` flag skips the interactive confirmation prompt.

**Step 2: Verify container is healthy**

```bash
ssh -i ./hetzner-cloudesk.pem -p 2222 -o IdentitiesOnly=yes overlord101@$SERVER3_IP \
  "cd /opt/openclaw && docker compose ps && docker compose logs --tail 30 openclaw 2>&1"
```

Expected: Container healthy, Slack + Telegram providers started, no errors about missing tools or config.

**Step 3: Verify workspace files**

```bash
ssh -i ./hetzner-cloudesk.pem -p 2222 -o IdentitiesOnly=yes overlord101@$SERVER3_IP \
  "ls -la /opt/openclaw/openclaw_data/workspace/SOUL.md \
         /opt/openclaw/openclaw_data/workspace/IDENTITY.md \
         /opt/openclaw/openclaw_data/workspace/USER.md \
         /opt/openclaw/openclaw_data/workspace/skills/channel-setup/SKILL.md \
         /opt/openclaw/openclaw_data/workspace/skills/integration-setup/SKILL.md \
         /opt/openclaw/openclaw_data/workspace/.identity-seeded && \
   echo '---BOOTSTRAP.md---' && \
   ls /opt/openclaw/openclaw_data/workspace/BOOTSTRAP.md 2>/dev/null || echo 'BOOTSTRAP.md removed (good)'"
```

Expected: All files present, marker exists, BOOTSTRAP.md removed.

---

## Task 9: End-to-End Verification

**Step 1: Test Jarvis personality**

DM Jarvis on Slack: "Hey, who are you?"

Expected: Responds as Jarvis — warm, concise, identifies itself by name.

**Step 2: Test on Telegram**

Message the Telegram bot: "Hello, what's your name?"

Expected: Same Jarvis personality — confirms identity is global across channels.

**Step 3: Test channel self-service**

DM on Slack: "What channels are you connected to?"

Expected: Reports channel status.

DM: "How do I connect Discord?"

Expected: Guides through Discord bot creation.

**Step 4: Test web search**

DM: "Search the web for latest news on AI agents"

Expected: Performs web search and returns results.

**Step 5: Test memory**

DM: "Remember that our server runs on Hetzner Ubuntu 24.04 ARM64"

Then in a new session: "What server do we use?"

Expected: Recalls from memory.

**Step 6: Test sub-agents**

DM: "Research the top 5 MCP server providers in the background"

Expected: Spawns sub-agent, continues chatting, delivers result when done.

**Step 7: Test daily digest setup**

DM: "Set up a daily morning brief at 7 AM Manila time, deliver to this channel"

Expected: Creates a cron job.

**Step 8: Test Composio self-configuration**

DM: "Here's my Composio API key: comp_xxxxxxxx" (use your actual key)

Expected: Jarvis registers MCP servers via `config.patch`, calls `gateway restart`, confirms activation.

Then DM: "Connect my Gmail"

Expected: Jarvis initiates Composio OAuth flow and sends an auth link.

After authenticating, DM: "Check my recent emails"

Expected: Jarvis queries Gmail via Composio MCP.

**Step 9: Test idempotent redeploy**

```bash
source .venv/bin/activate && set -a && source .env && set +a
pyinfra --sudo -v -y infra/inventory.py infra/deploy.py
```

Expected: Completes successfully. Identity shows "already seeded, skipping." Config unchanged.

---

## Appendix A: Patching a Live Server

The seed-once model means `openclaw.json` and workspace files are only uploaded on first deploy. After that, OpenClaw self-manages. When you need to update a live server's config:

### Option 1: Ask Jarvis (Preferred)

Since the `gateway` tool is enabled, Jarvis can patch its own config via chat:

- "Enable sub-agents with max depth 2"
- "Switch to LiteLLM as the primary model"
- "Add Brave as the search provider"

Jarvis uses `config.get` (to get `baseHash`) then `config.patch` to apply changes. Rate limit: 3 writes per 60 seconds.

### Option 2: SSH + Python Script

For changes the bot can't make itself (e.g., before it's running, or if `gateway` is broken):

```bash
ssh -i ./hetzner-cloudesk.pem -p 2222 -o IdentitiesOnly=yes overlord101@$SERVER3_IP \
  "cd /opt/openclaw && python3 -c \"
import json
with open('openclaw_data/openclaw.json') as f:
    c = json.load(f)

# Example: switch to LiteLLM
c['agents']['defaults']['model']['primary'] = 'litellm/qwen-2.5-7b'

with open('openclaw_data/openclaw.json', 'w') as f:
    json.dump(c, f, indent=2)
print('Config patched')
\" && docker compose restart openclaw"
```

### Option 3: Force Re-Seed (Nuclear)

Delete the config and marker files, then redeploy. The local files become the new source of truth:

```bash
ssh -i ./hetzner-cloudesk.pem -p 2222 -o IdentitiesOnly=yes overlord101@$SERVER3_IP \
  "rm /opt/openclaw/openclaw_data/openclaw.json \
      /opt/openclaw/openclaw_data/workspace/.identity-seeded"
pyinfra --sudo -v infra/inventory.py infra/deploy.py
```

**Warning:** This wipes any config changes the bot made to itself (channel tokens added via chat, cron jobs, etc.). Use only when the local files are the desired state.

---

## Appendix B: Switching from Gemini to LiteLLM

The LiteLLM provider is NOT in the seed config — empty `${LITELLM_API_KEY}` blocks startup (OpenClaw treats it as a required secret). Add it only when Servers 1+2 are ready.

When Servers 1+2 (Ollama + LiteLLM) are ready:

1. Set `LITELLM_BASE_URL` and `LITELLM_API_KEY` in server `.env`
2. Add the provider via Jarvis: "Add a LiteLLM model provider with base URL http://<SERVER2_IP>:4000 and API key <key>"
3. Or patch via SSH:
   ```bash
   ssh -i ./hetzner-cloudesk.pem -p 2222 -o IdentitiesOnly=yes overlord101@$SERVER3_IP \
     "cd /opt/openclaw && python3 -c \"
   import json
   with open('openclaw_data/openclaw.json') as f:
       c = json.load(f)
   c['models']['providers']['litellm'] = {
       'baseUrl': 'http://<SERVER2_IP>:4000',
       'apiKey': '<LITELLM_API_KEY>',
       'models': [
           {'id': 'qwen-2.5-7b', 'name': 'Qwen 2.5 7B'},
           {'id': 'llama-3.1-8b', 'name': 'LLaMA 3.1 8B'}
       ]
   }
   c['agents']['defaults']['model']['primary'] = 'litellm/qwen-2.5-7b'
   with open('openclaw_data/openclaw.json', 'w') as f:
       json.dump(c, f, indent=2)
   print('LiteLLM provider added and set as primary')
   \" && docker compose restart openclaw"
   ```
4. Optionally remove the `google` provider to stop using Gemini entirely

---

## Summary

### What Gets Deployed (One Command)

| What | Local File | Server Path | Seed Model |
|------|-----------|-------------|------------|
| Jarvis personality | `docker/workspace/SOUL.md` | `workspace/SOUL.md` | Seed-once |
| Bot identity | `docker/workspace/IDENTITY.md` | `workspace/IDENTITY.md` | Seed-once |
| User profile stub | `docker/workspace/USER.md` | `workspace/USER.md` | Seed-once |
| Heartbeat config | `docker/workspace/HEARTBEAT.md` | `workspace/HEARTBEAT.md` | Seed-once |
| Channel setup skill | `docker/workspace/skills/channel-setup/SKILL.md` | `workspace/skills/channel-setup/SKILL.md` | Seed-once |
| Integration setup skill | `docker/workspace/skills/integration-setup/SKILL.md` | `workspace/skills/integration-setup/SKILL.md` | Seed-once |
| OpenClaw config | `docker/openclaw.json` | `openclaw.json` | Seed-once |
| Docker Compose | `docker/docker-compose.yml` | `docker-compose.yml` | Every deploy |
| Env vars | `.env` | `.env` | Every deploy |

### Capabilities After Deploy

| Capability | Status | How to Activate |
|---|---|---|
| Web search | Ready | Gemini fallback works; add `BRAVE_API_KEY` to `.env` for better results |
| Memory / knowledge base | Ready | `memorySearch` with Gemini provider + `group:fs` for file persistence |
| Sub-agents | Ready | `group:sessions` enabled |
| Daily digest / cron | Ready | Built-in `cron` tool. DM Jarvis: "Set up a daily morning brief at 7 AM" |
| Heartbeat checks | Ready | Periodic email/calendar checks via HEARTBEAT.md polling |
| Image analysis | Ready | Built-in |
| Image generation | Ready when configured | Add `OPENAI_API_KEY` to `.env` |
| Channel self-service | Ready | DM Jarvis: "Connect telegram/discord/whatsapp" |
| Gmail | Ready when configured | DM Jarvis with Composio API key → he self-configures MCP via `mcp.servers` → then "connect my gmail" |
| Google Calendar | Ready when configured | Same Composio key → "connect my calendar" |
| Trello | Ready when configured | Same Composio key → "connect trello" |
| LiteLLM / Ollama | Not pre-configured | Add provider via Jarvis or SSH when Servers 1+2 are ready (see Appendix B) |

### What's NOT Enabled (By Design)

| Feature | Why |
|---|---|
| `exec` / `group:runtime` | Arbitrary shell = prompt injection risk |
| `elevated` | Bypasses all tool restrictions |
| Docker socket | Container escape = root on host |
| ClawHub auto-update | 12% malware rate (Feb 2026) |

Note: `group:fs` IS enabled — required for memory persistence. The `read_only: true` Docker flag limits writes to the bind-mounted `openclaw_data/` directory only.

### Pre-Requisites for Deploy

Only existing keys are required. Everything else is optional and can be added later via chat or `.env`:

| Action | Required? | Notes |
|---|---|---|
| `OPENCLAW_GATEWAY_TOKEN` in `.env` | **Yes** (already have) | `openssl rand -hex 32` |
| `GEMINI_API_KEY` in `.env` | **Yes** (already have) | Temporary LLM + embeddings |
| `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` in `.env` | **Yes** (already have) | Slack connection |
| `BRAVE_API_KEY` in `.env` | Optional | Better web search (free 2K/mo) |
| `OPENAI_API_KEY` in `.env` | Optional | Image generation |
| Composio API key | Optional, via chat | DM Jarvis after deploy — no `.env` needed |
| Gmail/Calendar/Trello auth | Optional, via chat | After Composio key is configured |

---

## Appendix C: Deployment Gotchas (OpenClaw 2026.4.1)

Lessons learned during deployment that aren't in the official docs:

| Gotcha | What Happens | Fix |
|---|---|---|
| `tools.profile: "messaging"` blocks `group:fs` | FS tools don't load even when in `allow` list | Use `"full"` profile with deny list |
| `tools.profile: "custom"` | Invalid — rejected at startup | Only `minimal`, `coding`, `messaging`, `full` |
| Individual tool names (`write`, `edit`) | Docs say these ARE valid, but they didn't work in our deploy (possibly version-specific) | Use `group:fs` as a reliable alternative |
| `memory.embeddings` config key | "Unrecognized key: embeddings" | Use `agents.defaults.memorySearch` with `enabled: true` + `provider: "gemini"` |
| `agents.defaults.subagent` config key | "Unrecognized key: subagent" | Sub-agents work via `group:sessions`; config limits key TBD |
| LiteLLM with empty `${LITELLM_API_KEY}` | Startup blocked — treated as required secret | Don't pre-configure providers with empty env vars |
| `mcpServers` at root of openclaw.json | "Unrecognized key: mcpServers" | Use `mcp.servers` (nested path) |
| Composio MCP without `transport` field | 405 Method Not Allowed (SSE GET vs POST) | Add `"transport": "streamable-http"` |
| Composio `x-api-key` header | Authentication failure | Use `x-consumer-api-key` (Composio's actual header name) |
| `memory/` directory missing | Bot can't write daily memory files | Pre-create in Pyinfra with uid 1000 ownership |
| `skills/` directory created by Pyinfra | Owned by root, not uid 1000 | Ensure `user="1000"` in `files.directory()` |
| `BOOTSTRAP.md` present | Bot runs first-run onboarding instead of using seeded identity | Remove during deploy |
| `pyinfra` without `-y` | Hangs on interactive confirmation | Always use `-y` flag |
| `pyinfra` without `.env` loaded | `KeyError: 'SERVER3_IP'` | `set -a && source .env && set +a` before running |
| `model-pricing bootstrap failed: TimeoutError` | Appears in logs on every startup | Non-critical — cost tracking unavailable, bot works fine |
| Composio Supabase ≠ cron | Supabase toolkit is project admin (API keys, domains), NOT scheduling | Use built-in `cron` tool for scheduled tasks — it persists to `~/.openclaw/cron/jobs.json` on the volume |
| HEARTBEAT.md not seeded | Bot has no periodic check instructions | Include in bot_identity.py upload list |
| Composio tool name overlap | Bot may pick Composio tools over built-in for similar functions | Guide via skills/SOUL.md which tool to prefer for each use case |
| `cron` tool shows as "unknown" | Cron scheduler subsystem not started | Add `"cron": {"enabled": true}` top-level in openclaw.json |
| `gateway` tool shows as "unknown" | Part of `group:automation`, same registration issue as cron | Enabling `cron.enabled` activates the automation group |
| `image` tool shows as "unknown" | Provider multimodal capability not declared | Add `"api": "google-generative-ai"` + `"input": ["text", "image"]` to model entries |
| `group:memory` shows as "unknown" | Memory-core plugin may not load if workspace/memory dir missing | Ensure `memory/` dir exists with uid 1000 ownership |
| Gemini 2.5 models deprecated | Shutdown June 17, 2026 | Use `gemini-3.1-pro-preview` / `gemini-3-flash-preview` |

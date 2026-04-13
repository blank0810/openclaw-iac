> **Superseded by `2026-04-01-master-deployment-plan.md`**

# OpenClaw Skills, Tools, and Messaging Channels Plan

**Date:** 2026-04-01
**Status:** Research complete, ready for implementation

---

## Part 1: Safe Tools to Enable

### Current State
Tools locked to `messaging` profile with explicit denials. Bot can only send messages and view session status.

### Recommended Additions

| Tool | What it does | Risk | Priority |
|------|-------------|------|----------|
| `group:memory` | Remember things across sessions | Low | High |
| `group:web` | Web search + URL fetching | Low | High |
| `image` | Analyze images shared in chat | Low | Medium |

### Tools That Must Stay Denied

| Tool | Why |
|------|-----|
| `group:runtime` (exec, bash) | Shell execution on host |
| `group:fs` (read, write, edit) | Filesystem access |
| `group:automation` (cron, gateway) | Persistent jobs, control-plane ops |
| `group:ui` (browser, canvas) | Chromium attack surface |
| `sessions_spawn`, `sessions_send` | Autonomous sub-agents |
| `image_generate` | Cost and abuse potential |
| `x_search` | Data-leak vector |

### Updated `tools` Config

```json
{
  "tools": {
    "profile": "messaging",
    "allow": ["group:memory", "group:web", "image"],
    "deny": ["group:automation", "group:runtime", "group:fs", "group:ui", "group:nodes",
             "sessions_spawn", "sessions_send", "gateway", "cron", "image_generate", "x_search"],
    "exec": { "security": "deny" },
    "elevated": { "enabled": false }
  }
}
```

---

## Part 2: Productivity Enhancements

### Slack UX

```json
"ackReaction": "eyes",
"typingReaction": "hourglass_flowing_sand"
```

Bot reacts with emoji when processing — eliminates "did it see my message?" confusion.

### Memory System

Works automatically with Gemini embeddings (key already in env). No additional config needed.
Memory stored as Markdown files in `~/.openclaw/workspace/` (Docker volume).

### Resource Limits

Bump memory from 512M to 1G if enabling web search + memory:
```yaml
deploy:
  resources:
    limits:
      memory: 1G
```

---

## Part 3: Auto-Update Strategy

### Recommended: Nightly cron on server

```bash
# /etc/cron.d/openclaw-update
0 4 * * * overlord101 cd /opt/openclaw && docker compose pull --quiet && docker compose up -d --remove-orphans >> /var/log/openclaw-update.log 2>&1
```

Add as a Pyinfra task. Only restarts if image changed. Auditable log at `/var/log/openclaw-update.log`.

### Future: Pin to digest

For production stability, switch from `:latest` to `@sha256:<digest>`. Update via PR + redeploy.

---

## Part 4: Messaging Channels — Plug-and-Play Design

### Channel Compatibility Matrix

| Channel | Direction | Inbound Port | Plugin | Complexity | Priority |
|---------|-----------|-------------|--------|------------|----------|
| **Slack** | Outbound (Socket Mode) | No | Bundled | Low | Done |
| **Telegram** | Outbound (polling) | No | Bundled | Low | Next |
| **Discord** | Outbound (Gateway WS) | No | Bundled | Low | Next |
| **WhatsApp** | Outbound (Baileys WS) | No | Bundled | Medium (QR) | Next |
| **Matrix** | Outbound (sync) | No | Plugin | Medium | Later |
| **Signal** | Local (signal-cli) | No | Bundled | High (sidecar) | Defer |
| **MS Teams** | Inbound (webhook) | Yes (3978) | Plugin | High (Azure) | Defer |
| **LINE** | Inbound (webhook) | Yes | Plugin | High | Defer |

### Adding a Channel — Standard Process

1. Create the bot/app on the platform's dashboard
2. Add tokens to `.env`
3. Pass tokens in `app_deploy.py` template variables
4. Add channel block to `openclaw.json.tpl` (conditionally via Jinja2)
5. Redeploy: `pyinfra --sudo -v infra/inventory.py infra/deploy.py`
6. For WhatsApp: `docker exec -it openclaw-openclaw-1 openclaw channels login --channel whatsapp` (one-time QR)
7. For plugin channels: `docker exec openclaw-openclaw-1 openclaw plugins install @openclaw/<name>`

### Channel Configs

#### Telegram
```
Env: TELEGRAM_BOT_TOKEN (from @BotFather /newbot)
```
```json
"telegram": {
  "enabled": true,
  "botToken": "{{ telegram_bot_token }}",
  "dmPolicy": "pairing",
  "groups": { "*": { "requireMention": true } }
}
```

#### Discord
```
Env: DISCORD_BOT_TOKEN, DISCORD_SERVER_ID, DISCORD_OWNER_ID
```
```json
"discord": {
  "enabled": true,
  "token": "{{ discord_bot_token }}",
  "dmPolicy": "pairing",
  "groupPolicy": "allowlist",
  "guilds": {
    "{{ discord_server_id }}": {
      "requireMention": true,
      "users": ["{{ discord_owner_id }}"]
    }
  }
}
```
Requires: Developer Portal > Privileged Gateway Intents > Message Content Intent ON.

#### WhatsApp
```
Env: WHATSAPP_OWNER_PHONE (+639XXXXXXXXX format)
```
```json
"whatsapp": {
  "enabled": true,
  "dmPolicy": "pairing",
  "allowFrom": ["{{ whatsapp_owner_phone }}"],
  "groupPolicy": "disabled"
}
```
Requires: One-time QR scan via `docker exec -it`. Dedicated phone number recommended.

#### Matrix (plugin required)
```
Env: MATRIX_HOMESERVER, MATRIX_ACCESS_TOKEN
```
```json
"matrix": {
  "enabled": true,
  "homeserver": "{{ matrix_homeserver }}",
  "accessToken": "{{ matrix_access_token }}",
  "encryption": true,
  "dmPolicy": "pairing"
}
```

### Template Architecture Decision

Jinja2 conditionals + JSON produce trailing commas. Options:
1. Switch to JSON5 (OpenClaw supports it natively) — rename template to `.json5.tpl`
2. Generate config via Python script instead of Jinja2 template
3. Keep all channels always present, use `"enabled": false` for unconfigured ones

**Recommended:** Option 3 (simplest) — all channels always in config with `enabled` toggled by presence of token:
```
"enabled": {{ 'true' if telegram_bot_token else 'false' }}
```

---

## Implementation Order

1. **Now:** Deploy hardening changes (already coded)
2. **Next:** Add safe tools (memory, web, image) + Slack UX (ack/typing reactions)
3. **Next:** Add Telegram channel (lowest friction — just a token)
4. **Later:** Add Discord, WhatsApp
5. **Defer:** Signal, Teams, LINE (require infrastructure changes)
6. **Ongoing:** Auto-update cron, image pinning

---

## Key Constraints

- `read_only: true` on container — plugins install to `~/.openclaw/plugins/` (on the volume, should work)
- WhatsApp QR pairing needs interactive `docker exec -it` on first setup
- Teams/LINE need public HTTPS endpoint — separate infrastructure workstream
- No ClawHub skills — 12% found to be malware (Feb 2026)
- All channel tokens go in `.env` only — never in committed files

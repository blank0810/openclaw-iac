> **Superseded by `2026-04-01-master-deployment-plan.md`**

# Server 3 Security Hardening Plan

**Date:** 2026-04-01
**Source:** Lead Engineer research + DevOps security audit
**Status:** Ready for implementation

---

## Summary

19 security findings (2 critical, 4 high, 8 medium, 5 low). The single most impactful fix is binding the Gateway to loopback — Slack Socket Mode is outbound-only, so ports 18789-18800 have zero reason to be internet-facing.

---

## P0 — Fix Immediately (3 items)

### P0.1 — Bind Gateway to loopback, close ports to internet

**Files:** `docker/docker-compose.yml`, `infra/group_data/all.py`

Slack Socket Mode works by the container making an **outbound** WebSocket connection to Slack's servers. No inbound connections are needed. Exposing port 18789 to the internet exposes the Gateway control plane (which can execute shell commands) to anyone who knows the token.

**Changes:**
- `docker-compose.yml`: Change `--bind lan` to `--bind loopback`, bind ports to `127.0.0.1` only
- `group_data/all.py`: Remove `18789:18800` from `allowed_tcp_ports` — only SSH needs to be open

**Access Control UI when needed:** SSH tunnel
```bash
ssh -N -L 18789:127.0.0.1:18789 -p 2222 -o IdentitiesOnly=yes -i ./hetzner-cloudesk.pem overlord101@$SERVER3_IP
# Then open http://localhost:18789
```

### P0.2 — Remove `dangerouslyAllowHostHeaderOriginFallback`

**File:** `docker/openclaw.json.tpl`

This disables CSRF protection on the Control UI. With loopback binding (P0.1), it's no longer needed — remove it entirely.

### P0.3 — Pin OpenClaw image version

**File:** `docker/docker-compose.yml`

OpenClaw has had 8 critical CVEs since Jan 2026. `:latest` can pull a vulnerable or breaking version at any time. Pin to a specific version >= `2026.3.13` (all known CVEs patched).

**How:** Check current version on server, then pin:
```bash
docker inspect ghcr.io/openclaw/openclaw:latest --format '{{index .RepoDigests 0}}'
```

---

## P1 — Fix Before Production Use (4 items)

### P1.1 — Lock down Slack access control

**File:** `docker/openclaw.json.tpl`

- Change `dmPolicy` from `"open"` to `"pairing"` — unknown senders must be approved
- Remove `allowFrom: ["*"]` — pairing mode manages access dynamically
- Add `requireMention: true` for group channels — bot only responds when @mentioned

### P1.2 — Add tools restrictions

**File:** `docker/openclaw.json.tpl`

The agent currently has full access to filesystem, shell, browser, and gateway tools. For a Slack bot, this is excessive. Lock it down:

```json
"tools": {
  "profile": "messaging",
  "deny": ["group:automation", "group:runtime", "group:fs", "sessions_spawn", "sessions_send", "gateway", "cron"],
  "exec": { "security": "deny" },
  "elevated": { "enabled": false }
}
```

### P1.3 — Fix `openclaw.json` file permissions

**File:** `infra/tasks/app_deploy.py`

The rendered `openclaw.json` (containing API keys and Slack tokens) is mode `644` (world-readable). Change to `600`. Also change `openclaw_config/` directory to mode `700` and deploy_path to `750`.

### P1.4 — Add session isolation

**File:** `docker/openclaw.json.tpl`

Add `"session": { "dmScope": "per-channel-peer" }` — each sender gets an isolated session. Without this, all DMs share context, enabling information leakage between users.

---

## P2 — Defense in Depth (6 items)

### P2.1 — Harden Docker container

**File:** `docker/docker-compose.yml`

```yaml
cap_drop:
  - ALL
security_opt:
  - no-new-privileges:true
read_only: true
tmpfs:
  - /tmp:size=100M
deploy:
  resources:
    limits:
      cpus: "1.0"
      memory: 512M
```

### P2.2 — Add logging with redaction

**File:** `docker/openclaw.json.tpl`

```json
"logging": {
  "redactSensitive": "tools",
  "redactPatterns": ["api[_-]?key", "secret", "token", "password"]
}
```

### P2.3 — Tighten fail2ban

**File:** `infra/files/fail2ban_jail.local`

Change `maxretry` from 10 back to 5. Keep `bantime = 10m` but add a recidive jail for repeat offenders.

### P2.4 — Reduce SSH MaxAuthTries

**File:** `infra/files/sshd_config`

Change from 6 back to 3. With `IdentitiesOnly=yes` in the inventory, the SSH agent key-cycling issue is solved.

### P2.5 — Increase log retention

**File:** `docker/docker-compose.yml`

Change from `max-size: 10m, max-file: 3` (30MB) to `max-size: 50m, max-file: 10` (500MB).

### P2.6 — Validate all secrets in deploy.sh

**File:** `scripts/deploy.sh`

Add `GEMINI_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` to the validation check.

---

## P3 — Ongoing (3 items)

### P3.1 — Periodic security audit

Run monthly via SSH:
```bash
docker exec openclaw-openclaw-1 openclaw security audit --deep --json
```

### P3.2 — Token rotation schedule

Rotate quarterly: `OPENCLAW_GATEWAY_TOKEN`, `GEMINI_API_KEY`. Slack tokens rotate on app reinstall.

### P3.3 — No ClawHub skills

Do not install third-party skills. 12% of marketplace skills were found to be malware (Feb 2026). If skills are needed later, audit every line of source code.

---

## Implementation Order

| Step | Items | Files Changed | Risk |
|------|-------|---------------|------|
| 1 | P0.1 + P0.2 | `docker-compose.yml`, `openclaw.json.tpl`, `all.py` | Low — Slack Socket Mode unaffected |
| 2 | P1.1 + P1.2 + P1.4 | `openclaw.json.tpl` | Low — tightens access, may need pairing approval for existing users |
| 3 | P1.3 | `app_deploy.py` | None — file permission change |
| 4 | P2.1 | `docker-compose.yml` | Medium — `read_only: true` may need testing |
| 5 | P2.2 + P2.3 + P2.4 + P2.5 + P2.6 | Multiple | Low |
| 6 | P0.3 | `docker-compose.yml` | Low — pin after confirming current version works |

---

## CVE Reference

| CVE | Severity | Description | Fixed In |
|-----|----------|-------------|----------|
| CVE-2026-25253 | 8.8 | 1-click RCE via auth token exfiltration ("ClawJacked") | 2026.1.29 |
| CVE-2026-32922 | 9.9 | Critical privilege escalation | 2026.3.x |
| CVE-2026-24763 | High | Command injection | 2026.2.x |
| CVE-2026-25157 | High | Second command injection vector | 2026.2.x |
| CVE-2026-33575 | Med | Gateway creds leaked in pairing codes | 2026.3.12 |
| CVE-2026-32982 | Med | Telegram tokens leaked in errors | 2026.3.13 |

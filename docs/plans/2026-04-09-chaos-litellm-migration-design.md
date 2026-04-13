# Chaos-Only LiteLLM Migration — Design Plan

> **Status:** Draft (pending user approval)
> **Date:** 2026-04-09
> **Scope:** Chaos agent only. Jarvis is explicitly NOT migrated in this plan.
> **Owner:** openclaw-expert (config) + infra-engineer (deploy)

---

## 1. Summary

Migrate the **Chaos** OpenClaw agent from its current direct-to-provider model configuration (Anthropic + Google) to route all LLM traffic through the LiteLLM proxy that just went live on Server 2. Chaos will be the canary — Jarvis stays on its current config until Chaos proves stable. The change is config-only: one new file in the repo, one line changed in the Pyinfra deploy task, one force-reseed on the server. No Docker Compose, `.env`, or Jarvis files are touched.

## 2. Motivation

- **LiteLLM is now live** on Server 2 at `http://10.0.0.4:4000/v1` (Hetzner private network). This is the target architecture from `docs/plans/2026-04-01-master-deployment-plan.md`, finally unblocked.
- **Automatic fallback.** With `"model": "auto"`, LiteLLM transparently routes Claude → Gemini → local models (Qwen/Llama). Session 2026-04-08 killed Chaos because a single provider had issues; this prevents that class of outage.
- **Remove raw provider keys from Server 3.** Today Chaos holds `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` inside its container environment. Post-migration, Chaos only needs `LITELLM_API_KEY`. Smaller blast radius if Server 3 is compromised.
- **Single point of rate-limiting and cost tracking.** All routing policy lives on Server 2, not scattered across agents.
- **Canary-first rollout.** Chaos has a history of stress incidents (Composio OOM storm in Session 2026-04-08). It is the right agent to test on — if LiteLLM's fallback misbehaves under load, Chaos is the disposable one.

## 3. Current State

Today, Chaos (and Jarvis) seed from the same file `docker/openclaw.json:1`, which declares three providers:

```
┌─────────────────────────────────────────┐
│  Chaos container (Server 3)             │
│                                          │
│  openclaw.json providers:                │
│    ├─ anthropic   (direct)               │
│    ├─ google      (direct)               │
│    └─ litellm     (local models only)    │
│                                          │
│  Primary:     anthropic/claude-haiku-4-5 │
│  MemSearch:   gemini (direct)            │
└────┬──────────────┬──────────────────────┘
     │              │
     │ HTTPS        │ HTTPS
     ▼              ▼
  api.anthropic  generativelanguage
  .com           .googleapis.com
```

- Raw API keys live in `.env:19-20` (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) and get passed into both containers via `docker/docker-compose.yml:17-18` (Jarvis) and `docker/docker-compose.yml:72-73` (Chaos).
- The `litellm` provider block exists but only lists local Ollama models — it never carried the primary traffic.
- `memorySearch` uses Gemini directly (`docker/openclaw.json:44-47`).
- Two separate outbound paths to two different cloud providers. No automatic fallback if one rate-limits.

## 4. Target State (Chaos Only)

```
┌─────────────────────────────────────────┐
│  Chaos container (Server 3)             │
│                                          │
│  openclaw.chaos.json providers:          │
│    └─ litellm                            │
│         ├─ auto                          │
│         ├─ claude-haiku-4-5              │
│         ├─ gemini-2.5-flash              │
│         ├─ qwen2.5:7b                    │
│         └─ llama3.1:8b                   │
│                                          │
│  Primary:     litellm/auto               │
│  MemSearch:   litellm                    │
└────┬────────────────────────────────────┘
     │ HTTP over Hetzner private network
     ▼
  Server 2: LiteLLM Proxy
  10.0.0.4:4000
     │
     ├─ Claude Haiku 4.5   (primary)
     ├─ Gemini 2.5 Flash   (fallback 1)
     ├─ Qwen 2.5 7B        (fallback 2, local)
     └─ Llama 3.1 8B       (fallback 3, local)
```

**Jarvis is unchanged.** Jarvis continues to seed from `docker/openclaw.json` and keeps using the `anthropic/claude-haiku-4-5-20251001` provider directly. Its traffic path is unaffected.

## 5. Non-Goals

The following are explicitly **out of scope** for this plan and will be handled separately:

1. **Jarvis migration.** Jarvis stays on direct Anthropic. A follow-up plan will migrate it once Chaos has been stable for 48+ hours.
2. **Removing `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` from the environment.** These env vars stay in `.env` and `docker-compose.yml` during the Chaos canary window. They become dead vars for Chaos but are still needed by Jarvis.
3. **HTTPS or TLS on the LiteLLM endpoint.** Traffic goes over Hetzner's private network (`10.0.0.4`), which already avoids the public internet. Further hardening is a separate infra concern.
4. **SearXNG integration.** The SearXNG brainstorming thread is paused until this migration lands.
5. **Rewriting `docker/openclaw.json` into a parameterized template.** We use two sibling files instead — lower risk, more readable diffs, easier rollback.
6. **Updating `.env.example` comments.** Deferred until after Jarvis migrates too, so the comments can reflect the final state in one edit.

## 6. Design Decisions

### 6.1 Chaos-first rollout (not both at once)

- **Decision:** Migrate Chaos first, observe for 48h, then migrate Jarvis in a separate plan.
- **Why:** Chaos is the disposable agent and has a history of stress incidents. If LiteLLM's `auto` routing has latency spikes, fallback bugs, or unexpected cost patterns under load, we learn that on the agent whose downtime nobody notices. Jarvis is the user-facing assistant — it stays on a known-good path until we have evidence the new path is reliable.
- **Alternative considered:** Migrate both at once. Rejected — bigger blast radius, harder to bisect if something breaks.

### 6.2 Separate `openclaw.chaos.json` file (not parameterized template)

- **Decision:** Create a new sibling file `docker/openclaw.chaos.json`. Leave `docker/openclaw.json` untouched as the Jarvis seed.
- **Why:**
  - **Zero risk to Jarvis.** If we parameterized the existing file with template variables or environment substitutions, a typo could break both agents. With sibling files, Jarvis is structurally incapable of seeing the change.
  - **Readable diffs.** A future reader can `diff docker/openclaw.json docker/openclaw.chaos.json` and see exactly what is different between the two agents.
  - **Easier rollback.** Reverting is `rm docker/openclaw.chaos.json && git checkout infra/tasks/app_deploy.py` — no merge-conflict potential.
- **Alternative considered:** Jinja2 templating or Pyinfra `files.template()` with variables. Rejected — adds complexity for a two-agent setup. Revisit if a third agent joins.
- **Future note:** When Jarvis also migrates, we can consolidate back to a single `openclaw.json` or keep the sibling-file pattern. Decide at migration time.

### 6.3 `litellm/auto` as primary (not pinned to a specific model)

- **Decision:** Set `agents.defaults.model.primary` to `"litellm/auto"`.
- **Why:** The LiteLLM announcement states `"model": "auto"` is **required** to get the load-balancing and fallback behavior. Pinning to `claude-haiku-4-5` would bypass the routing logic and lose the fallback, defeating the main motivation for migrating.
- **Trade-off:** We give up deterministic model selection. Two identical prompts might be served by Claude one minute and Gemini the next. For Chaos this is acceptable — it is the experimental agent, and LiteLLM's routing policy on Server 2 is the single place to tune model selection going forward.
- **Rollback path:** If `auto` misbehaves, we can pin to `litellm/claude-haiku-4-5` as a stopgap without reverting the whole migration.

### 6.4 `requestTimeout: 180000` (3 minutes)

- **Decision:** Add `requestTimeout: 180000` to the litellm provider block.
- **Why:** The `auto` routing can cascade through three tiers (Claude → Gemini → local). A legitimate fallback chain on a long tool-call loop can exceed the OpenClaw default of 120000ms. Without the bump, we get spurious "LLM request timed out" errors that look like bugs but are actually the fallback chain doing its job. OpenClaw issue [#46271](https://github.com/openclaw/openclaw/issues/46271) documents this exact pattern.
- **Trade-off:** Slower failure signal when LiteLLM is truly unreachable. Acceptable for Chaos; revisit if it masks real problems.

### 6.5 `memorySearch.provider: "litellm"` (with disable fallback)

- **Decision:** Switch `memorySearch.provider` from `"gemini"` to `"litellm"`. If OpenClaw rejects this at container start, set `memorySearch.enabled: false` and defer the fix.
- **Why:** We are deleting the `google` provider block, so the existing `"gemini"` reference would become a dangling pointer. Two options: point it at LiteLLM, or disable the feature. LiteLLM is the preferred path because it preserves functionality.
- **Uncertainty:** I do not have high confidence that `memorySearch.provider` accepts the value `"litellm"`. It may require a model ID or a different field name. We verify this in the smoke test (step 9.3) and fall back to `enabled: false` if needed.
- **Risk if disabled:** Chaos loses the ability to search its long-term memory via LLM. The memory itself is not lost — it is still in the volume at `openclaw_data_chaos/`. Re-enabling later is a single-line config edit.

## 7. File Changes

### 7.1 New file: `docker/openclaw.chaos.json`

Full contents (derived from `docker/openclaw.json` with the three specific edits applied):

```json5
{
  "gateway": {
    "mode": "local"
  },
  "models": {
    "providers": {
      "litellm": {
        "baseUrl": "${LITELLM_BASE_URL}",
        "apiKey": "${LITELLM_API_KEY}",
        "api": "openai-completions",
        "requestTimeout": 180000,
        "models": [
          { "id": "auto",             "name": "Auto (smart routing)", "input": ["text", "image"] },
          { "id": "claude-haiku-4-5", "name": "Claude Haiku 4.5",     "input": ["text", "image"] },
          { "id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash",     "input": ["text", "image"] },
          { "id": "qwen2.5:7b",       "name": "Qwen 2.5 7B",          "input": ["text"] },
          { "id": "llama3.1:8b",      "name": "LLaMA 3.1 8B",         "input": ["text"] }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "litellm/auto"
      },
      "compaction": {
        "mode": "safeguard"
      },
      "memorySearch": {
        "enabled": true,
        "provider": "litellm"
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
  "commands": {
    "ownerAllowFrom": ["*"]
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
  "cron": {
    "enabled": true
  },
  "logging": {
    "redactSensitive": "tools",
    "redactPatterns": ["api[_-]?key", "secret", "token", "password"]
  }
}
```

**Three differences from `docker/openclaw.json`:**

1. `models.providers` — removed `anthropic` and `google` blocks; rewrote `litellm` block with the new 5-model list and `requestTimeout: 180000`.
2. `agents.defaults.model.primary` — changed from `"anthropic/claude-haiku-4-5-20251001"` to `"litellm/auto"`.
3. `agents.defaults.memorySearch.provider` — changed from `"gemini"` to `"litellm"`.

**Note on `agents.list[0].identity.name`:** Left as `"Jarvis"` because Chaos's runtime identity is managed separately via its Slack app and live config on the server. Changing the seed template's identity has no effect on a live agent (seed-once model). If we want the seed to reflect Chaos identity, that is a separate cleanup.

### 7.2 Modified file: `infra/tasks/app_deploy.py`

One-line change at line 74:

```diff
 if not chaos_config_exists:
     files.put(
         name="Seed Chaos openclaw.json (first deploy only)",
-        src="docker/openclaw.json",  # Same config as Jarvis
+        src="docker/openclaw.chaos.json",  # Chaos uses LiteLLM
         dest=chaos_config_dest,
         user="1000",
         group="1000",
         mode="600",
     )
```

### 7.3 Files NOT modified

- `docker/openclaw.json` — Jarvis seed, untouched
- `docker/docker-compose.yml` — `LITELLM_BASE_URL` and `LITELLM_API_KEY` are already wired into both containers at `docker/docker-compose.yml:19-20` (Jarvis) and `docker/docker-compose.yml:74-75` (Chaos)
- `.env` — `LITELLM_BASE_URL=http://10.0.0.4:4000/v1` and `LITELLM_API_KEY` are already correct per user confirmation (`.env:21-22`)
- `.env.example` — comment cleanup deferred until Jarvis migration
- Any `infra/bootstrap.py`, `infra/inventory.py`, `infra/tasks/hardening.py`, etc. — out of scope

## 8. Deployment Steps

### 8.1 Pre-flight checks (on the dev machine)

```bash
# 1. Verify .env has the right LiteLLM values
grep -E "LITELLM_(BASE_URL|API_KEY)" .env
# Expected:
#   LITELLM_BASE_URL=http://10.0.0.4:4000/v1
#   LITELLM_API_KEY=<non-empty value>

# 2. Verify LiteLLM endpoint is reachable from Server 3 (SSH in first)
ssh -i hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
  "curl -sf -m 10 -H 'Authorization: Bearer $LITELLM_API_KEY' http://10.0.0.4:4000/v1/models"
# Expected: JSON response listing available models (or at least HTTP 200)

# 3. Confirm Chaos is currently running and healthy (baseline)
ssh -i hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
  "docker ps --filter name=openclaw-chaos --format '{{.Status}}'"
# Expected: Up <time> (healthy)
```

If any of these fail, **stop** and diagnose before proceeding.

### 8.2 Make the repo changes

```bash
# 1. Create the new Chaos seed file
#    (Claude Code will write docker/openclaw.chaos.json per section 7.1)

# 2. Edit infra/tasks/app_deploy.py line 74 per section 7.2

# 3. Validate JSON syntax
python3 -c "import json; json.load(open('docker/openclaw.chaos.json'))"
# Expected: no output, exit 0

# 4. Sanity check: the Pyinfra task file parses
python3 -m py_compile infra/tasks/app_deploy.py
# Expected: no output, exit 0
```

### 8.3 Force-reseed Chaos on the server

The seed-once guard (`if not chaos_config_exists`) will skip reseeding unless we delete the live file first.

```bash
# 1. Delete Chaos's live openclaw.json (creates window for reseed)
ssh -i hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
  "sudo rm /opt/openclaw/openclaw_data_chaos/openclaw.json"

# 2. Run the Pyinfra deploy
pyinfra infra/inventory.py infra/deploy.py

# Pyinfra will:
#   - Upload the new docker/openclaw.chaos.json as chaos's seed
#   - Skip re-seeding Jarvis (its live config still exists)
#   - Run `docker compose pull`
#   - Run `docker compose up -d --force-recreate --remove-orphans`
#     (this restarts BOTH containers — Jarvis comes back with unchanged config)
```

**Note:** `--force-recreate` will restart Jarvis too. Jarvis's config volume is untouched, so it comes back identical. If a zero-Jarvis-downtime migration is required, we would need to tweak the Pyinfra task to use `docker compose up -d chaos` instead — flagged as a follow-up but not blocking.

### 8.4 Verify Chaos restarts cleanly

```bash
# 1. Wait for healthcheck
ssh -i hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
  "docker ps --filter name=openclaw-chaos --format '{{.Names}}\t{{.Status}}'"
# Expected: openclaw-chaos  Up <time> (healthy)

# 2. Check startup logs for config parse errors
ssh -i hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
  "docker logs openclaw-chaos --tail 100 2>&1 | grep -iE 'error|fatal|parse|provider'"
# Expected: no error lines related to litellm, memorySearch, or provider config

# 3. Verify Jarvis is still alive and healthy
ssh -i hetzner-cloudesk.pem -p 2222 overlord101@$SERVER3_IP \
  "docker ps --filter name=openclaw-jarvis --format '{{.Names}}\t{{.Status}}'"
# Expected: openclaw-jarvis  Up <time> (healthy)
```

### 8.5 Smoke test Chaos via Slack

Send Chaos a message in its Slack workspace. Examples:

1. **Basic completion:** "Hello, what model are you using?"
2. **Tool call:** "What is the current UTC time?" (exercises `cron` tool path)
3. **Web search:** (skip for now — blocked on SearXNG plan)
4. **Memory search:** "What have we talked about before?" (exercises `memorySearch` — watch for errors)

Expected: Chaos responds within ~10 seconds for simple prompts. Response quality should be comparable to pre-migration (since `auto` defaults to Claude Haiku first).

## 9. Verification Plan

### 9.1 Health check
Chaos gateway healthcheck returns 200:
```bash
ssh ... "curl -sf http://127.0.0.1:18791/healthz"
```

### 9.2 Provider sanity
No "provider not found" or "unknown provider" errors in the last 5 minutes of logs:
```bash
ssh ... "docker logs openclaw-chaos --since 5m 2>&1 | grep -iE 'provider.*not.*found|unknown.*provider'"
# Expected: empty output
```

### 9.3 Memory search
- **If working:** Chaos answers "what have we talked about" with recalled context.
- **If broken:** Error mentions `memorySearch` or `litellm` provider rejection. Fallback: edit live config on server to set `memorySearch.enabled: false`, restart chaos container, document the issue for a follow-up fix.

### 9.4 LiteLLM traffic confirmation
Check Server 2's LiteLLM logs (if accessible) to confirm Chaos requests are arriving:
```bash
ssh ... server2 "docker logs litellm --tail 50 | grep -i chaos"
```
(Exact command depends on Server 2's compose setup — confirm with infra-engineer.)

### 9.5 Jarvis regression check
Jarvis must still work exactly as before:
```bash
# 1. Health
ssh ... "curl -sf http://127.0.0.1:18789/healthz"
# 2. Config unchanged
ssh ... "sudo diff /opt/openclaw/openclaw_data/openclaw.json <(cat docker/openclaw.json)"
# Expected: files match (or differ only by expected self-management drift)
```
Also: send Jarvis a message in its Slack workspace. It should respond using the Anthropic provider as before.

### 9.6 48-hour soak window
Leave Chaos running for 48 hours. Monitor:
- Container restarts (`docker events --filter container=openclaw-chaos`)
- OOM kills (`dmesg | grep -i oom`)
- Slack activity (Chaos should be responsive to DMs and mentions)
- LiteLLM proxy error rate on Server 2

Only after this soak completes cleanly do we start the Jarvis migration plan.

## 10. Rollback Plan

If anything goes wrong at any stage:

### 10.1 Rollback the repo changes

```bash
# In the repo on the dev machine
rm docker/openclaw.chaos.json
git checkout infra/tasks/app_deploy.py
```

### 10.2 Rollback on the server

```bash
# 1. Delete the new (broken) Chaos config
ssh ... "sudo rm /opt/openclaw/openclaw_data_chaos/openclaw.json"

# 2. Re-run the Pyinfra deploy — Chaos will be reseeded from docker/openclaw.json
#    (the old Jarvis-style config with direct Anthropic/Gemini providers)
pyinfra infra/inventory.py infra/deploy.py

# 3. Verify Chaos comes back healthy
ssh ... "docker ps --filter name=openclaw-chaos"
```

**Rollback time estimate:** Under 5 minutes from decision to healthy Chaos on old config.

### 10.3 Partial rollback (keep new file, disable memorySearch only)

If only memorySearch is broken:

```bash
# On the server, live-edit chaos config
ssh ... "sudo sed -i 's|\"provider\": \"litellm\"|\"enabled\": false|' /opt/openclaw/openclaw_data_chaos/openclaw.json"
ssh ... "cd /opt/openclaw && docker compose restart chaos"
```

(Exact sed is illustrative; verify JSON syntax after the edit.)

## 11. Follow-up Work (Out of Scope for This Plan)

1. **Jarvis LiteLLM migration** — separate plan, after 48h Chaos soak. Likely uses the same pattern: create `docker/openclaw.jarvis.json` or fold both back into a single file.
2. **Remove dead env vars from Chaos container** — once both agents are on LiteLLM, delete `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` from the Chaos `environment:` block in `docker/docker-compose.yml:72-73`.
3. **Remove direct provider keys from `.env`** — only after Jarvis is also migrated.
4. **Update `.env.example` comments** — reflect that Anthropic/Gemini keys are no longer required on Server 3.
5. **Add LiteLLM health probe on Server 3** — cron job that curls the LiteLLM endpoint and alerts if it stops responding. Infra-engineer's domain.
6. **Consider consolidating sibling files** — if the two-file pattern feels awkward after Jarvis migrates, consolidate back to a single `openclaw.json`.
7. **SearXNG integration** — resumes after this migration is stable.

## 12. Open Questions

1. **Does `memorySearch.provider` accept `"litellm"` as a value?** Unverified. Smoke test in step 9.3 will tell us. Fallback: disable the feature temporarily.
2. **Does `--force-recreate` on Jarvis cause any user-visible blip?** Jarvis container restart takes ~20s. During that window, Slack messages to Jarvis queue up and are delivered once it is back. Acceptable for a low-traffic personal assistant, but worth knowing.
3. **Has Chaos's live `openclaw.json` drifted from the seed via self-management?** Session 2026-04-09 memory notes that Jarvis's config has drifted from Composio plugin entries. Chaos may have too. Any drift is **lost** when we `rm` the live file and reseed. If Chaos has any self-configured state in `openclaw.json` that matters (identity, channel tokens, custom skills), it will be reverted to the seed version. Check before deleting.
4. **Is there a proper `scripts/deploy.sh` wrapper**, or do we always invoke Pyinfra directly? Confirms step 8.3 command.

## 13. Success Criteria

The migration is considered successful when **all** of the following are true:

- [ ] `docker/openclaw.chaos.json` exists in the repo and is valid JSON.
- [ ] `infra/tasks/app_deploy.py:74` references `docker/openclaw.chaos.json` for Chaos seeding.
- [ ] `docker/openclaw.json` is byte-identical to pre-change (Jarvis seed untouched).
- [ ] Chaos container is `Up ... (healthy)` after the deploy.
- [ ] Chaos responds to a Slack DM within 15 seconds with a coherent reply.
- [ ] Chaos startup logs contain no `error|fatal|provider not found` lines related to LiteLLM or memorySearch.
- [ ] Jarvis container is `Up ... (healthy)` after the deploy.
- [ ] Jarvis responds to a Slack message using its existing Anthropic provider (no regression).
- [ ] memorySearch is either working (provider: litellm) or cleanly disabled (enabled: false) — no silent failures.
- [ ] After 48h, no unexpected Chaos restarts, OOM kills, or user-reported issues.

If any criterion fails, execute the rollback plan in section 10 and file a new plan to address the root cause before retrying.

---

## Appendix A: Why HTTP (not HTTPS) is acceptable here

The LiteLLM endpoint `http://10.0.0.4:4000/v1` uses plaintext HTTP. This is acceptable because:

- `10.0.0.4` is a **Hetzner private network IP**, not a public address. Traffic never traverses the public internet.
- Only Hetzner servers attached to the same Cloud Network can reach `10.0.0.4`. An attacker would need to first compromise a server in the same network.
- The `LITELLM_API_KEY` is still transmitted in the `Authorization:` header, but only across the private network. This is a similar trust model to internal service-to-service calls in a datacenter.
- Upgrading to HTTPS would require terminating TLS on Server 2 with Let's Encrypt or a self-signed cert, plus rotating to an `https://10.0.0.4:4000` base URL. Out of scope.

## Appendix B: Why we do not change `docker-compose.yml`

The compose file at `docker/docker-compose.yml:74-75` already passes `LITELLM_BASE_URL` and `LITELLM_API_KEY` into the Chaos container environment. These env vars have been present since before this migration — they were set up in anticipation of LiteLLM going live. No compose changes are needed.

Removing the now-dead `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` from Chaos's environment block is **intentionally deferred** to the follow-up cleanup (section 11 item 2), to minimize the blast radius of this migration. A dead env var is harmless; a broken compose file is not.

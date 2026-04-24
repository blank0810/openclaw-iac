# Chaos Agent Separation — Design Plan

**Status:** Draft v2 (council-reviewed, pending user approval)
**Date:** 2026-04-09
**Scope:** Server 3 (OpenClaw Agents) — Chaos agent only
**Owner:** infra-engineer
**Supersedes:** none (paused plan `docs/plans/2026-04-09-chaos-litellm-migration-design.md` is referenced in Follow-up Work)

**Revision history:**
- **v1** (2026-04-09) — initial draft by infra-engineer
- **v2** (2026-04-09) — applied fixes from three-council review:
  - Lead Engineer: Pyinfra step ordering bug, rollback idempotency, same-filesystem assertion
  - QA Engineer: pre-flight guards, smoke test depth, failure-mode coverage, sentinel edge cases
  - OpenClaw Expert: seed identity safety, stop_grace_period, start_period, LiteLLM follow-up clarification

---

## 1. Summary

Split the Chaos agent out of the shared `docker/docker-compose.yml` into its own subdirectory (`docker/chaos/`) with a dedicated compose file, a dedicated seed config, a dedicated Docker bridge network (`chaos_net`), and a dedicated on-server data directory (`/opt/openclaw/chaos/data/`, migrated from `/opt/openclaw/openclaw_data_chaos/`). Jarvis is left completely untouched aside from the mechanical removal of the `chaos:` service block from the shared compose file. This is the first of two isolation steps; Jarvis separation will follow in a later plan.

---

## 2. Motivation

Today both Jarvis and Chaos are defined side-by-side in `docker/docker-compose.yml:1-114` and share:

- one compose file
- one seed template (`docker/openclaw.json`)
- one Docker network (`openclaw_net`)
- one Pyinfra deploy task (`infra/tasks/app_deploy.py:37-93`)
- one recreation command (`docker compose up -d --force-recreate --remove-orphans`)

Any change that targets one agent risks the other. Concretely:

1. **LiteLLM migration risk.** The paused `docs/plans/2026-04-09-chaos-litellm-migration-design.md` could not cleanly edit only Chaos's model provider — `openclaw.json` is shared. Splitting the seed files makes the LiteLLM switch a one-file edit with zero blast radius on Jarvis.
2. **Force-recreate bleed.** `docker compose up -d --force-recreate` bounces both containers even when only one was changed (`infra/tasks/app_deploy.py:91`). Chaos's OOM recovery on 2026-04-08 and Jarvis's restart loop on 2026-04-09 are recent reminders that unnecessary restarts are not free.
3. **Blast radius on Chaos experiments.** Chaos is the experimental agent — we want to iterate on it (new tools, new model, chaos-specific skills) without any chance of destabilising Jarvis.
4. **Future per-agent IaC.** A subdirectory-per-agent layout generalises cleanly. Jarvis gets the same treatment in a follow-up plan, and any future third agent just becomes another subdirectory.

**Why Chaos first?** Chaos is the less-critical agent, and it is the agent most likely to receive near-term changes (LiteLLM, SearXNG experiments). Jarvis is the stable, user-facing bot — we move it last so it spends the least time under a hot plan.

---

## 3. Current State

### 3.1 File Layout (Repo)

```
docker/
  docker-compose.yml    # Jarvis (lines 2-55) + Chaos (lines 57-110) + network (112-114)
  openclaw.json         # Single seed template, used by both agents
infra/
  tasks/
    app_deploy.py       # Uploads compose + .env, seeds both agents, runs compose up
```

### 3.2 File Layout (Server `/opt/openclaw/`)

```
/opt/openclaw/
  .env                          # mode 600, owned by overlord101
  docker-compose.yml            # Jarvis + Chaos in one file
  openclaw_data/                # Jarvis data (uid 1000)
    openclaw.json               # Jarvis live config (drifted via self-management)
    memory/, workspace/, ...
  openclaw_data_chaos/          # Chaos data (uid 1000)
    openclaw.json               # Chaos live config (drifted via self-management)
    memory/, workspace/, ...
```

### 3.3 Key Line References

| Concern | File | Lines |
|---|---|---|
| Jarvis service block | `docker/docker-compose.yml` | 2-55 |
| Chaos service block | `docker/docker-compose.yml` | 57-110 |
| Shared `openclaw_net` declaration | `docker/docker-compose.yml` | 112-114 |
| Jarvis data seed logic | `infra/tasks/app_deploy.py` | 37-57 |
| Chaos data seed logic | `infra/tasks/app_deploy.py` | 59-79 |
| Compose pull | `infra/tasks/app_deploy.py` | 82-86 |
| Compose up (force-recreate) | `infra/tasks/app_deploy.py` | 88-93 |

### 3.4 Shared Assets

| Asset | Jarvis value | Chaos value |
|---|---|---|
| Image | `ghcr.io/openclaw/openclaw:2026.4.5` | `ghcr.io/openclaw/openclaw:2026.4.5` |
| Gateway port | 18789 | 18791 |
| Bridge port | 18790 | 18792 |
| Gateway token env | `OPENCLAW_GATEWAY_TOKEN` | `CHAOS_GATEWAY_TOKEN` |
| Data volume | `./openclaw_data` | `./openclaw_data_chaos` |
| Network | `openclaw_net` | `openclaw_net` (shared) |
| Memory limit | 2G | 2G |
| CPU limit | 2.0 | 1.5 |
| Seed template | `docker/openclaw.json` | `docker/openclaw.json` (same file) |

---

## 4. Target State

### 4.1 File Layout (Repo)

```
docker/
  docker-compose.yml            # Jarvis only — Chaos block removed
  openclaw.json                 # Jarvis seed (untouched)
  chaos/
    docker-compose.yml          # Chaos only
    openclaw.json               # Chaos seed (byte-identical to docker/openclaw.json for now)
infra/
  tasks/
    app_deploy.py               # Rewritten Chaos section; Jarvis section untouched
```

### 4.2 File Layout (Server `/opt/openclaw/`)

```
/opt/openclaw/
  .env                                    # unchanged, single source of truth
  docker-compose.yml                      # Jarvis only (replaces current file)
  openclaw_data/                          # Jarvis data, untouched
    openclaw.json
    memory/, workspace/, ...
  openclaw_data_chaos.bak.2026-04-09/     # Temporary backup (removed after 48h soak)
  chaos/
    docker-compose.yml                    # Chaos only
    data/                                 # Moved from openclaw_data_chaos/
      openclaw.json                       # Chaos live config (preserved)
      memory/, workspace/, ...
```

### 4.3 Networks

| Network | Owner | Scope |
|---|---|---|
| `openclaw_net` (project: `openclaw`) | Jarvis compose | Jarvis only |
| `chaos_net` (project: `chaos`) | Chaos compose | Chaos only |

Since the two compose files live in different directories (`/opt/openclaw/` and `/opt/openclaw/chaos/`), Docker Compose uses different project names by default (`openclaw` and `chaos`), so the network names do not collide and cannot reach each other.

---

## 5. Non-Goals

- **Jarvis is NOT separated.** Jarvis's compose block, network, volumes, environment, and live data are left exactly where they are. A follow-up plan will mirror this work for Jarvis.
- **LiteLLM migration is NOT performed.** `docker/chaos/openclaw.json` is content-identical to `docker/openclaw.json` on day one EXCEPT for `agents.list[0].identity.name`, which is set to `"Chaos"` instead of `"Jarvis"` (see Section 6.3 for rationale). Switching Chaos's model provider is a separate plan — see Section 11 item 2 for the exact shape of that work.
- **`.env` is NOT split.** A single `/opt/openclaw/.env` remains the source of truth. Chaos's compose file references it via `--env-file ../.env`.
- **No shared network between agents.** We deliberately do not create a bridge between `chaos_net` and `openclaw_net`. The agents communicate with the outside world (Slack, LLM providers) only.
- **No rename of env vars.** `CHAOS_*` prefixed vars stay as-is. No migration pressure on `.env`.
- **No change to auto-update, backups, or hardening tasks.** Only `app_deploy.py` is touched.
- **No upgrade/downgrade of the OpenClaw image.** Both stay on `ghcr.io/openclaw/openclaw:2026.4.5`.

---

## 6. Design Decisions

Each decision below is locked-in by the user; the rationale is recorded for future readers.

### 6.1 Isolated `chaos_net` bridge (not shared with Jarvis)

**Decision:** Chaos's compose file declares a brand-new `chaos_net` bridge network. It does NOT join Jarvis's `openclaw_net`.

**Rationale:**
- There is zero container-to-container traffic between Jarvis and Chaos today. Both agents talk to the outside world (Slack Socket Mode, LLM providers, Composio MCP) — never to each other.
- A shared network creates an implicit coupling (shared DNS namespace, shared broadcast domain) that future experiments (e.g., Chaos running an HTTP client pointed at Jarvis by accident) could exploit.
- `chaos_net` being `external: false` means it is created and destroyed with the Chaos compose lifecycle — no manual network management.

### 6.2 `.env` stays at `/opt/openclaw/.env`

**Decision:** One `.env` file, at the existing location. Chaos's compose is launched with `docker compose --env-file ../.env up -d` from `/opt/openclaw/chaos/`.

**Rationale:**
- Splitting `.env` would require duplicating `TZ`, `LITELLM_BASE_URL`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `BRAVE_API_KEY`, and every shared var — and the duplicate would drift.
- `--env-file` is the documented Compose mechanism for pointing a project at an env file outside its own directory.
- The Pyinfra upload step for `.env` (`app_deploy.py:28-35`) stays unchanged.
- Only shared SECRETS live in `.env`; per-agent tokens are already namespaced (`CHAOS_SLACK_BOT_TOKEN`, etc.).

### 6.3 `docker/chaos/openclaw.json` is near-identical to `docker/openclaw.json` with the identity renamed

**Decision:** The new Chaos seed is a copy of the Jarvis seed with **exactly one** intentional change: `agents.list[0].identity.name` is set to `"Chaos"` instead of `"Jarvis"`. All other content is identical to `docker/openclaw.json`.

**Rationale:**
- **Disaster-scenario prevention.** If we kept the seed byte-identical, the Chaos repo seed would declare the agent as "Jarvis". In the happy path this is harmless (the live migrated config is authoritative). But in ANY scenario where the seed actually fires — a fresh-host provision, a partial rollback + re-attempt where the sentinel was deleted without restoring the legacy dir, or an operator manually deleting the sentinel — Chaos would boot up presenting itself as "Jarvis" in its own Slack workspace. This is a class of footgun we can eliminate with a one-line change.
- **This plan remains a pure structural refactor.** Changing identity is NOT a content change in the sense of "changing what Chaos does" — it is fixing a latent bug where the Chaos seed lied about its identity. No behavior changes, no model changes, no tool changes.
- **Future plans remain trivially simple.** LiteLLM migration, channel additions, skill installs — all still edit only `docker/chaos/openclaw.json` with zero chance of bleeding into Jarvis.

**Verification:** `diff docker/openclaw.json docker/chaos/openclaw.json` produces exactly a 2-line change on the `identity.name` field (one removal, one addition). Any other diff is a bug.

### 6.4 Data migration via `mv` (Approach 1)

**Decision:** The on-server directory `openclaw_data_chaos` is physically moved to `chaos/data` via `mv`. The new Chaos compose file uses the relative volume `./data:/home/node/.openclaw`.

**Rationale:**
- User-approved over "absolute path in compose file." Keeps the compose file portable and keeps the layout on the server consistent with the repo layout.
- `mv` is atomic on the same filesystem (both paths are under `/opt/openclaw/`, which is a single filesystem on Hetzner).
- The move is guarded so it only runs once (`[ -d openclaw_data_chaos ] && [ ! -d chaos/data ]`).

### 6.5 Deploy sequence

**Decision (corrected in v2 after lead-engineer review):**

1. **Pre-flight sanity guard** on the server: abort the deploy if the sentinel exists but the live config file does not — this detects the silent data-loss scenario (QA review Case 6).
2. **Explicit `docker stop -t 30 openclaw-chaos`** with extended grace period, to give OpenClaw time to flush state and complete any hung Composio MCP shutdown RPCs. Runs BEFORE any file operations, tolerates absence (`|| true`).
3. **Barrier wait** until `docker ps` confirms Chaos is actually gone (up to 30s). This closes the async gap: `docker stop` returns after issuing SIGTERM, not after the container is removed.
4. Upload Jarvis-only `docker-compose.yml` to `/opt/openclaw/docker-compose.yml`.
5. Run `docker compose up -d --remove-orphans` in `/opt/openclaw`. At this point Chaos is already gone from step 3, so `--remove-orphans` is just bookkeeping. Jarvis is not recreated because its config hash didn't change (`--force-recreate` dropped per 6.8).
6. **Only now** is it safe to touch Chaos's data: guarded `cp -a` backup of `openclaw_data_chaos`, then `mv openclaw_data_chaos chaos/data`.
7. Upload `chaos/docker-compose.yml` and (sentinel-guarded, seed-once) `chaos/data/openclaw.json`.
8. `cd /opt/openclaw/chaos && docker compose --env-file ../.env up -d`.
9. Touch sentinel at `/opt/openclaw/.chaos-seeded`.

**Rationale:**
- **Steps 2-3 (explicit stop + barrier) replace the implicit "--remove-orphans will stop Chaos" pattern from v1.** The v1 plan relied on `docker compose up -d --remove-orphans` to stop orphan Chaos as a side effect. Three problems with that: (a) it returns asynchronously, leaving a race between stop and the subsequent `mv`; (b) the default `--remove-orphans` stop grace period is 10s, which is too short when Composio MCP shutdown RPCs hang (Session 2026-04-09 incident pattern); (c) if the shell returns with Chaos still running, the `mv` silently corrupts the bind mount.
- **Step 1 (pre-flight sanity guard) catches the only silent-data-loss case in the plan.** Sentinel says "already seeded" but the live config is gone → OpenClaw would initialize fresh defaults and lose all drifted state. Detectable, preventable, fail-fast.
- **The backup MUST happen before the move, obviously.**
- **Seed-once semantics MUST NOT overwrite the live Chaos config file that was carried along by `mv`.** Guarded by the two-fact sentinel pattern (see Section 6.9).
- **The v1 ordering bug was subtle:** Pyinfra declares operations in source order, and the v1 Section 7.4 code listed the data migration step BEFORE the Jarvis compose-up. v2 reorders to match this section.

### 6.6 Backup strategy

**Decision:** `cp -a openclaw_data_chaos openclaw_data_chaos.bak.2026-04-09` before the move. Remove the backup after 48 hours of clean Chaos operation.

**Rationale:**
- `cp -a` preserves ownership, permissions, timestamps, and symlinks.
- 48 hours covers at least one full overnight cron window and several human-in-the-loop interactions.
- The backup sits on the same filesystem — cheap to make, cheap to delete.

### 6.7 Rollback window

**Decision:** Full rollback in under 5 minutes via: stop new Chaos container, restore old compose file, move data back, re-deploy.

**Rationale:**
- All rollback steps are local filesystem operations plus `docker compose` calls — no rebuilds, no re-pulls.
- Both Jarvis and Chaos are on the same pinned image (`2026.4.5`), so rollback does not risk an image downgrade surprise.

### 6.8 Drop `--force-recreate` from the shared compose up step

**Decision:** Change `infra/tasks/app_deploy.py:91` from `docker compose up -d --force-recreate --remove-orphans` to `docker compose up -d --remove-orphans` for the Jarvis-only compose step.

**Rationale:**
- `--force-recreate` unconditionally destroys and rebuilds the Jarvis container every deploy, which violates the user's "don't touch Jarvis" constraint for this refactor.
- Plain `up -d` is idempotent: if nothing in the compose file or env changed, the container keeps running. If the file contents change (e.g., Chaos block removed), Compose recomputes config hashes and recreates the affected container — Jarvis's hash is unchanged, so Jarvis is not touched.
- `--remove-orphans` is preserved so the orphan Chaos container is cleanly stopped and removed on the first run after Chaos leaves the shared file.
- The Chaos-only compose file gets its own separate `docker compose up -d` without `--force-recreate` — new container, first-time create, no risk.

> **Note on Jarvis separation:** The broader `--force-recreate` question is revisited in the future Jarvis separation plan. For this plan we simply stop forcing Jarvis to recreate.

### 6.9 Sentinel-based seed guard (Option C, user-selected)

**Decision:** Use a sentinel file at `/opt/openclaw/.chaos-seeded` to guard the seed-once semantics for `docker/chaos/openclaw.json`, combined with a second fact check on the legacy directory `/opt/openclaw/openclaw_data_chaos` to correctly handle the first-run-with-existing-live-data case.

**Why not the naive fact check?** `overlord101` (the SSH user, uid 1001 or similar) is NOT in group 1000 and cannot traverse into `/opt/openclaw/chaos/data/` (mode 700 owned by uid 1000). A naive `host.get_fact(File, path=chaos/data/openclaw.json)` always returns `None` regardless of whether the file exists — which would make Pyinfra re-seed the file on EVERY deploy, overwriting Chaos's drifted live config. This would be catastrophic.

**Why Option C (sentinel) over Option D (shell-level runtime check)?**
- Keeps the seed operation declarative in Pyinfra style, matching the existing Jarvis pattern at `app_deploy.py:49-57`.
- No temp files in `/tmp`, no `sudo install` incantations to review.
- The sentinel is a boring, greppable, human-readable artifact on the server.
- Future "is this agent initialized?" checks can reuse the same sentinel pattern.

**Sentinel location: `/opt/openclaw/.chaos-seeded`**
- Lives in `/opt/openclaw/` (which `overlord101` owns at mode 750). `overlord101` can read, write, and stat it without sudo.
- Does NOT live inside `chaos/` subdir because that directory is mode 750 owned by uid 1000 — `overlord101` cannot write there.
- Naming: dot-prefixed so it doesn't clutter `ls /opt/openclaw/`. Hyphen-separated for consistency with other admin artifacts.

**Guard logic (two-fact check to prevent the first-run timing bug):**

Pyinfra gathers ALL facts at the START of a run, before any operation executes. This means a sentinel created by an early `server.shell` step is NOT visible to a later `host.get_fact()` call in the same run. To prevent the seed step from firing on the very first run after this refactor (when migration has just created `chaos/data/openclaw.json` from the legacy directory), we use two independent facts:

1. **`legacy_data_exists`** — does `/opt/openclaw/openclaw_data_chaos` exist at fact-gather time? If YES, we know migration is about to happen this run, so the live config will be preserved — DO NOT seed.
2. **`chaos_already_seeded`** — does `/opt/openclaw/.chaos-seeded` exist at fact-gather time? If YES, a prior deploy already seeded — DO NOT seed.

Seed fires only when **both** are false: no legacy data (fresh host or post-migration) AND no sentinel (never initialized). At the end of the Chaos section, the sentinel is unconditionally touched (idempotent) so all subsequent runs are guarded.

**Truth table:**

| Run | legacy_exists | sentinel_exists | Action |
|-----|---------------|-----------------|--------|
| First run after refactor (existing server) | True | False | Migration preserves live config. SKIP seed. Touch sentinel. |
| Second run (same server) | False | True | SKIP seed. Touch sentinel (no-op). |
| First run on fresh host | False | False | Migration is no-op. SEED fires. Touch sentinel. |
| Any run on an already-seeded fresh host | False | True | SKIP seed. Touch sentinel (no-op). |

**Rollback implication:** If we roll back, we must ALSO delete `/opt/openclaw/.chaos-seeded` so a future re-attempt of this plan correctly triggers the seed path on a host where the legacy dir has been restored. Added to the rollback script in Section 10.

---

## 7. File Changes

### 7.1 New file: `docker/chaos/docker-compose.yml`

```yaml
# Chaos agent compose file.
# Launch with: cd /opt/openclaw/chaos && docker compose --env-file ../.env up -d
# Secrets come from /opt/openclaw/.env (shared with Jarvis).

services:
  chaos:
    image: ghcr.io/openclaw/openclaw:2026.4.5
    container_name: openclaw-chaos
    init: true
    restart: unless-stopped
    stop_grace_period: 30s  # v2: extended from default 10s — Composio MCP shutdown RPCs can hang
    command: ["node", "dist/index.js", "gateway", "--bind", "loopback", "--port", "18791"]
    ports:
      - "127.0.0.1:18791:18791"
      - "127.0.0.1:18792:18792"
    volumes:
      - ./data:/home/node/.openclaw
    environment:
      - OPENCLAW_GATEWAY_TOKEN=${CHAOS_GATEWAY_TOKEN:?CHAOS_GATEWAY_TOKEN must be set}
      - NODE_OPTIONS=--max-old-space-size=1536
      - TZ=${TZ:-UTC}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - LITELLM_BASE_URL=${LITELLM_BASE_URL:-}
      - LITELLM_API_KEY=${LITELLM_API_KEY:-}
      - OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-}
      - SLACK_BOT_TOKEN=${CHAOS_SLACK_BOT_TOKEN:-}
      - SLACK_APP_TOKEN=${CHAOS_SLACK_APP_TOKEN:-}
      - TELEGRAM_BOT_TOKEN=${CHAOS_TELEGRAM_BOT_TOKEN:-}
      - DISCORD_BOT_TOKEN=${CHAOS_DISCORD_BOT_TOKEN:-}
      - DISCORD_SERVER_ID=${CHAOS_DISCORD_SERVER_ID:-}
      - DISCORD_OWNER_ID=${CHAOS_DISCORD_OWNER_ID:-}
      - WHATSAPP_OWNER_PHONE=${CHAOS_WHATSAPP_OWNER_PHONE:-}
      - BRAVE_API_KEY=${BRAVE_API_KEY:-}
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
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
          cpus: "1.5"
          memory: 2G
    networks:
      - chaos_net
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://127.0.0.1:18791/healthz || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 60s  # v2: bumped from 20s — Chaos drifted state + MCP reconnect can take ~22s
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "10"

networks:
  chaos_net:
    driver: bridge
```

**Preserved from current `docker/docker-compose.yml:57-110`:** image, container_name, init, restart, command, ports, env vars (names and defaults), cap_drop, security_opt, read_only, tmpfs, deploy.resources, healthcheck test command, interval/timeout/retries, logging. **Changed in v2:** volume path (`./openclaw_data_chaos` -> `./data`), network (`openclaw_net` -> `chaos_net`), `start_period` (20s -> 60s), added `stop_grace_period: 30s`, added header comment explaining `--env-file ../.env` pattern.

> **Note on `curl /healthz`:** Session 2026-04-08 documented that `/healthz` returns HTTP 200 even when OpenClaw's gateway is non-functional (false healthy). This pre-existing bug is NOT fixed by this plan — see Section 11 for the follow-up work item.

### 7.2 New file: `docker/chaos/openclaw.json`

**Content:** A copy of `docker/openclaw.json` with **exactly one** edit: the `agents.list[0].identity.name` field changes from `"Jarvis"` to `"Chaos"`. Everything else — models, tools, channels, skills, logging, cron — is identical.

**Create it via:**

```bash
cp docker/openclaw.json docker/chaos/openclaw.json
# Then edit the identity name. Use your editor or:
sed -i 's/"name": "Jarvis"/"name": "Chaos"/' docker/chaos/openclaw.json
```

**Rationale for the identity change:** See Section 6.3. Summary: a byte-identical seed would declare Chaos as "Jarvis" in its own Slack workspace in any disaster-recovery scenario where the seed actually fires. One-line fix, eliminates a class of footguns.

**Why not a symlink?** Pyinfra's `files.put()` follows symlinks, but committing a symlink to git introduces cross-platform weirdness and the two files must diverge going forward anyway (identity + future LiteLLM migration). A plain file copy is clearest.

**Verification after copy:**
```bash
diff docker/openclaw.json docker/chaos/openclaw.json
# Expected output (exactly):
# <       "name": "Jarvis",
# ---
# >       "name": "Chaos",
# (line numbers may differ depending on file formatting)
```
Any other diff is a bug — abort and investigate.

### 7.3 Modified file: `docker/docker-compose.yml`

**Diff (lines relative to current file):**

- **Remove:** lines 56-110 inclusive (blank separator line + entire `chaos:` service block). Everything from the blank line after Jarvis's `max-file: "10"` through Chaos's `max-file: "10"`.
- **Keep:** lines 1-55 (Jarvis service block) exactly as they are.
- **Keep:** lines 111-114 (blank line + `networks:` block declaring `openclaw_net`) exactly as they are.

**Result:** The file becomes Jarvis + `openclaw_net`, roughly 60 lines total. No other edits.

Expected full contents after the edit:

```yaml
services:
  jarvis:
    image: ghcr.io/openclaw/openclaw:2026.4.5
    container_name: openclaw-jarvis
    init: true
    restart: unless-stopped
    command: ["node", "dist/index.js", "gateway", "--bind", "loopback", "--port", "18789"]
    ports:
      - "127.0.0.1:18789:18789"
      - "127.0.0.1:18790:18790"
    volumes:
      - ./openclaw_data:/home/node/.openclaw
    environment:
      - OPENCLAW_GATEWAY_TOKEN=${OPENCLAW_GATEWAY_TOKEN:?OPENCLAW_GATEWAY_TOKEN must be set}
      - NODE_OPTIONS=--max-old-space-size=1536
      - TZ=${TZ:-UTC}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - LITELLM_BASE_URL=${LITELLM_BASE_URL:-}
      - LITELLM_API_KEY=${LITELLM_API_KEY:-}
      - OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-}
      - SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN:-}
      - SLACK_APP_TOKEN=${SLACK_APP_TOKEN:-}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN:-}
      - DISCORD_SERVER_ID=${DISCORD_SERVER_ID:-}
      - DISCORD_OWNER_ID=${DISCORD_OWNER_ID:-}
      - WHATSAPP_OWNER_PHONE=${WHATSAPP_OWNER_PHONE:-}
      - BRAVE_API_KEY=${BRAVE_API_KEY:-}
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
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
          cpus: "2.0"
          memory: 2G
    networks:
      - openclaw_net
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://127.0.0.1:18789/healthz || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 20s
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "10"

networks:
  openclaw_net:
    driver: bridge
```

### 7.4 Modified file: `infra/tasks/app_deploy.py`

**v2 note:** This section was substantially rewritten after the lead-engineer review caught a step-ordering bug in v1. The Pyinfra operations now run in the sequence described in Section 6.5: pre-flight guard → stop Chaos → barrier → Jarvis compose up → data migration → seed guard.

**Keep exactly as-is:**

- Lines 1-6 (imports, `deploy_path`, `deploy_user`) — but add `from pyinfra.facts.files import Directory, File` import
- Lines 8-15 (`files.directory` for `/opt/openclaw`)
- Lines 17-25 (upload `docker-compose.yml`)
- Lines 27-35 (upload `.env`)
- Lines 37-57 (Jarvis directory, seed-once config) — **untouched per user constraint**
- Lines 81-86 (`docker compose pull`)

**Replace the existing Chaos section (lines 59-79) and the trailing `compose up` block (lines 88-93) with the following unified block. The critical change from v1 is that the Jarvis `compose up -d --remove-orphans` runs BEFORE the data migration, guarded by an explicit `docker stop` + barrier wait so there is no race with the bind mount:**

```python
from pyinfra.facts.files import Directory, File

# --- Chaos Agent (isolated subdirectory) ---
chaos_dir = f"{deploy_path}/chaos"
chaos_data_dir = f"{chaos_dir}/data"
legacy_chaos_data_dir = f"{deploy_path}/openclaw_data_chaos"
chaos_backup_dir = f"{deploy_path}/openclaw_data_chaos.bak.2026-04-09"
chaos_seeded_sentinel = f"{deploy_path}/.chaos-seeded"

# Facts gathered at run start — used by the sentinel guard later.
legacy_data_exists = host.get_fact(Directory, path=legacy_chaos_data_dir)
chaos_already_seeded = host.get_fact(File, path=chaos_seeded_sentinel)

# === STEP 1: Pre-flight sanity guard (QA review Case 6 — silent data loss detector) ===
# If the sentinel claims Chaos is already seeded BUT the live config file is missing,
# something catastrophic happened (manual delete, volume corruption, failed rollback).
# Abort the deploy rather than let OpenClaw initialize fresh defaults.
server.shell(
    name="Pre-flight: detect sentinel + missing-config silent data loss case",
    commands=[
        (
            f"if [ -f {chaos_seeded_sentinel} ] && "
            f"   [ -d {chaos_data_dir} ] && "
            f"   sudo test ! -f {chaos_data_dir}/openclaw.json; then "
            f"  echo 'FATAL: sentinel exists but chaos/data/openclaw.json is missing.' >&2; "
            f"  echo 'Manual intervention required. See plan Section 10 rollback.' >&2; "
            f"  exit 1; "
            f"fi"
        )
    ],
    _timeout=30,
)

# === STEP 2: Explicit graceful stop of orphan Chaos container (30s grace) ===
# Default --remove-orphans grace is 10s, too short when Composio MCP shutdown RPCs hang.
# This step returns when Docker has issued SIGTERM but may not yet have removed the container.
# The barrier in step 3 closes that async gap.
server.shell(
    name="Stop Chaos container gracefully (30s grace, tolerates absence)",
    commands=["docker stop -t 30 openclaw-chaos || true"],
    _timeout=60,
)

# === STEP 3: Barrier — wait until Chaos is actually gone before touching bind mounts ===
# `docker stop` can return before the container is fully removed. We poll for up to 60s.
# Fails loudly if Chaos is still running after the timeout.
server.shell(
    name="Barrier: wait for Chaos container to fully exit",
    commands=[
        (
            "for i in $(seq 1 60); do "
            "  if [ -z \"$(docker ps -a -q --filter name=openclaw-chaos --filter status=running)\" ] && "
            "     [ -z \"$(docker ps -a -q --filter name=openclaw-chaos --filter status=restarting)\" ]; then "
            "    exit 0; "
            "  fi; "
            "  sleep 1; "
            "done; "
            "echo 'FATAL: Chaos container still running after 60s. Aborting.' >&2; exit 1"
        )
    ],
    _timeout=90,
)

# === STEP 4: Now safe to bring up Jarvis-only compose (which will sweep any remaining orphan) ===
# We already stopped Chaos in step 2, so --remove-orphans is just bookkeeping here.
# Plain `up -d` (no --force-recreate) keeps Jarvis running untouched.
server.shell(
    name="Start Jarvis via docker compose (Chaos already stopped)",
    commands=[f"cd {deploy_path} && docker compose up -d --remove-orphans"],
    _timeout=180,
)

# === STEP 5: Create chaos subdir (owned by uid 1000 so the container can read it) ===
files.directory(
    name=f"Create {chaos_dir}",
    path=chaos_dir,
    user="1000",
    group="1000",
    mode="750",
)

# === STEP 6: One-time data migration: openclaw_data_chaos -> chaos/data (with backup) ===
# Safe now because Chaos is stopped (steps 2-3), bind mount released.
# Guarded so it only runs when the source exists and destination doesn't.
# Needs sudo because openclaw_data_chaos is mode 700 owned by uid 1000.
server.shell(
    name="Migrate Chaos data directory (one-time, guarded, with backup)",
    commands=[
        (
            f"if [ -d {legacy_chaos_data_dir} ] && [ ! -d {chaos_data_dir} ]; then "
            f"  cp -a {legacy_chaos_data_dir} {chaos_backup_dir} && "
            f"  mv {legacy_chaos_data_dir} {chaos_data_dir}; "
            f"fi"
        )
    ],
    _sudo=True,
    _timeout=300,
)

# === STEP 7: Ensure chaos/data exists even on fresh hosts (no-op if migration ran) ===
files.directory(
    name=f"Ensure {chaos_data_dir}",
    path=chaos_data_dir,
    user="1000",
    group="1000",
    mode="700",
)

# === STEP 8: Upload Chaos's dedicated compose file ===
files.put(
    name="Upload chaos/docker-compose.yml",
    src="docker/chaos/docker-compose.yml",
    dest=f"{chaos_dir}/docker-compose.yml",
    user=deploy_user,
    group=deploy_user,
    mode="644",
)

# === STEP 9: Sentinel-guarded seed-once (see Section 6.9 for the two-fact rationale) ===
# Only fires when:
#   - legacy_data_exists is False (no migration happening this run), AND
#   - chaos_already_seeded is False (no prior seed on this host)
# This correctly handles: (a) fresh host, (b) existing server first-run-after-refactor,
# (c) subsequent idempotent runs, (d) post-rollback re-attempt.
if not legacy_data_exists and not chaos_already_seeded:
    files.put(
        name="Seed Chaos openclaw.json (fresh host, first deploy)",
        src="docker/chaos/openclaw.json",
        dest=f"{chaos_data_dir}/openclaw.json",
        user="1000",
        group="1000",
        mode="600",
    )

# === STEP 10: Pull Chaos image and bring up Chaos via its own compose file ===
server.shell(
    name="Pull Chaos OpenClaw image",
    commands=[f"cd {chaos_dir} && docker compose --env-file ../.env pull"],
    _timeout=300,
)

server.shell(
    name="Start Chaos via its dedicated compose file",
    commands=[
        f"cd {chaos_dir} && docker compose --env-file ../.env up -d --remove-orphans"
    ],
    _timeout=180,
)

# === STEP 11: Unconditionally ensure the sentinel exists at the end of the Chaos section ===
# Idempotent: no-op if already present. Marks this host as "Chaos initialized"
# so subsequent runs correctly skip the seed step even when the legacy dir is gone.
files.file(
    name="Ensure Chaos seeded sentinel",
    path=chaos_seeded_sentinel,
    touch=True,
    user=deploy_user,
    group=deploy_user,
    mode="644",
)
```

**Also replace the old shared-compose invocation:**
The old code at `app_deploy.py:88-93` (`"Start all agents via docker compose"` with `--force-recreate`) is **deleted entirely**. Its functionality is now split between STEP 4 (Jarvis compose up, no --force-recreate) and STEP 10 (Chaos compose up in its own subdir).

**Note on `--env-file`:** `docker compose pull` does not strictly need `--env-file` (no env substitution at pull time), but passing it keeps both invocations identical and avoids a future gotcha where an image tag uses `${VAR}` interpolation.

**Why all these steps are in `app_deploy.py` rather than split into `app_deploy_chaos.py`:** The per-agent task file split is listed as Section 11 follow-up item 4. Doing it in this plan would expand scope; lead-engineer reviewer recommended it but user scope is "don't touch Jarvis" and splitting app_deploy.py touches both. Deferred.

---

## 8. Deployment Steps

### 8.1 Pre-flight (local + read-only server checks)

**v2 note:** This section was expanded after the QA and openclaw-expert reviews. Every check is a go/no-go gate — if any fails, abort and investigate before proceeding.

```bash
cd /home/blank/Desktop/Projects/Cloudesk/ai-project

# ==========================================================================
# LOCAL CHECKS (on the dev machine)
# ==========================================================================

# L1. Current git state is clean (or diff is reviewed).
git status

# L2. .env contains CHAOS_GATEWAY_TOKEN (otherwise docker compose up fails cryptically).
grep -q '^CHAOS_GATEWAY_TOKEN=' .env && echo "OK: CHAOS_GATEWAY_TOKEN present" || \
  { echo "FATAL: CHAOS_GATEWAY_TOKEN missing in .env"; exit 1; }

# ==========================================================================
# SERVER CHECKS (read-only SSH probes)
# ==========================================================================
SSH="ssh -i hetzner-cloudesk.pem -p 2222 overlord101@<SERVER3_IP>"

# S1. Both containers currently up and healthy (baseline).
$SSH "docker ps --filter name=openclaw- --format '{{.Names}}\t{{.Status}}'"
# Expected: openclaw-jarvis  Up X (healthy)
#           openclaw-chaos   Up X (healthy)

# S2. Docker Compose v2 available (`--env-file` flag placement depends on it).
$SSH "docker compose version"
# Expected: Docker Compose version v2.x.x (v2 required; v1 `docker-compose` has different syntax)

# S3. Disk space: /opt/openclaw has at least 2x the size of openclaw_data_chaos free.
$SSH "sudo du -sb /opt/openclaw/openclaw_data_chaos | awk '{print \"chaos_size_bytes=\"\$1}'"
$SSH "df -B1 /opt/openclaw | tail -1 | awk '{print \"free_bytes=\"\$4}'"
# Manual check: free_bytes must be >= 2 * chaos_size_bytes (room for cp -a backup + migration window).
# If insufficient: expand the disk BEFORE proceeding.

# S4. Same-filesystem assertion for the mv operation (must be atomic).
$SSH "stat -c '%m' /opt/openclaw /opt/openclaw/openclaw_data_chaos"
# Both lines must show the same mountpoint (typically '/'). If they differ, `mv` will
# silently fall back to cp+rm, which is NOT atomic and doubles disk usage during the move.

# S5. LITELLM endpoint is reachable (not strictly required for this plan but catches env drift).
$SSH "grep '^LITELLM_BASE_URL=' /opt/openclaw/.env"
# Just note the value — this plan doesn't depend on LiteLLM being reachable.

# S6. Snapshot Chaos live openclaw.json: checksum + size.
$SSH "sudo sha256sum /opt/openclaw/openclaw_data_chaos/openclaw.json > /tmp/preflight-chaos-json-sha.txt && \
      cat /tmp/preflight-chaos-json-sha.txt"
# Record this value — it's the single most important verification anchor.

# S7. Snapshot Chaos full data dir recursive checksum (catches any content drift during migration).
$SSH "sudo find /opt/openclaw/openclaw_data_chaos -type f -exec sha256sum {} \; | \
      sort > /tmp/preflight-chaos-tree.txt && wc -l /tmp/preflight-chaos-tree.txt"
# Record the line count as a sanity number.

# S8. Snapshot Chaos identity (so we can confirm it survives the mv).
$SSH "sudo grep -A2 '\"identity\"' /opt/openclaw/openclaw_data_chaos/openclaw.json"
# Record the current name/theme/emoji values.

# S9. Snapshot OpenClaw version currently running in the Chaos container (detects image drift).
$SSH "docker inspect openclaw-chaos --format '{{.Config.Image}}'"
# Expected: ghcr.io/openclaw/openclaw:2026.4.5

# S10. Inventory Chaos cron jobs — flag any with catchUp:true (can compound startup memory pressure).
$SSH "sudo cat /opt/openclaw/openclaw_data_chaos/openclaw.json | \
      python3 -c 'import json,sys; c=json.load(sys.stdin); print(json.dumps(c.get(\"cron\",{}),indent=2))'"
# If any jobs have catchUp:true, decide whether to temporarily disable before deploy.

# S11. Pre-seed the Docker image on the server (so rollback doesn't need a pull).
$SSH "docker pull ghcr.io/openclaw/openclaw:2026.4.5"
# Idempotent — no-op if already cached.

# S12. Snapshot Jarvis's StartedAt — used for exact-equality check post-deploy (v2).
$SSH "docker inspect openclaw-jarvis --format '{{.State.StartedAt}}' > /tmp/preflight-jarvis-started.txt && \
      cat /tmp/preflight-jarvis-started.txt"

# S13. Snapshot Jarvis live config checksum (prove we didn't touch it).
$SSH "sudo sha256sum /opt/openclaw/openclaw_data/openclaw.json && \
      sudo stat -c '%Y' /opt/openclaw/openclaw_data"

# S14. Capture recent Chaos log tail (baseline — compare against post-deploy logs).
$SSH "docker logs --since 1h openclaw-chaos 2>&1 | tail -20 > /tmp/preflight-chaos-logs.txt && \
      wc -l /tmp/preflight-chaos-logs.txt"

# S15. Baseline Chaos behavior via Slack (record responses to compare post-deploy).
# Before starting the deploy, DM Chaos in Slack with each of:
#   - "What is your name and current role?"
#   - "What cron jobs do you have scheduled?"
#   - "What was the last significant thing we worked on together?"
# Record all three responses. Post-deploy, ask the same questions and compare.
```

**Go/no-go gate:** ALL of the above must succeed (exit 0, values recorded) before proceeding to 8.2. Treat any failure as a blocker.

### 8.2 Repo changes (local)

```bash
cd /home/blank/Desktop/Projects/Cloudesk/ai-project

# 1. Create the chaos subdir and seed files.
mkdir -p docker/chaos
cp docker/openclaw.json docker/chaos/openclaw.json

# 2. Write docker/chaos/docker-compose.yml (see section 7.1).
#    (Use your editor, not heredoc - file is ~50 lines.)

# 3. Edit docker/docker-compose.yml to remove lines 56-110 (Chaos block).
#    (Use your editor.)

# 4. Edit infra/tasks/app_deploy.py per section 7.4.

# 5. Sanity checks.
diff docker/openclaw.json docker/chaos/openclaw.json    # no output
docker compose -f docker/docker-compose.yml config > /dev/null
docker compose -f docker/chaos/docker-compose.yml --env-file .env config > /dev/null
python -c "import ast; ast.parse(open('infra/tasks/app_deploy.py').read())"

# 6. Dry-run Pyinfra (catches most typos before touching the server).
pyinfra --dry infra/inventory.py infra/deploy.py
```

### 8.3 Server-side migration (via Pyinfra)

> **⚠️ Slack downtime warning:** Slack Socket Mode apps do not queue messages during container downtime. Any DM or @-mention sent to Chaos between the `docker stop` step and a healthy-container state (approximately 60-120s total) will be silently dropped by Slack. Pause Slack activity directed at Chaos during the deploy window, or send a heads-up to any human users.

> **⚠️ Composio MCP transient outage warning:** After Chaos restarts, OpenClaw re-handshakes with the Composio MCP endpoint. For approximately 30-60s post-restart, Composio-backed tools (Gmail, Calendar, Trello) return `MCP not initialized` errors. This self-heals without intervention. Do not trigger Composio-dependent tool calls for the first minute after Chaos is healthy.

```bash
# 1. Run the full deploy — Pyinfra sequences: sanity guard → docker stop → barrier →
#    Jarvis compose up (Chaos already gone) → data move → upload chaos compose →
#    sentinel-guarded seed → Chaos compose up → sentinel touch.
pyinfra infra/inventory.py infra/deploy.py

# 2. Immediately verify both containers.
ssh -i hetzner-cloudesk.pem -p 2222 overlord101@<SERVER3_IP> \
  "docker ps --filter name=openclaw- --format '{{.Names}}\t{{.Status}}'"
# Expected: openclaw-jarvis  Up X (healthy)
#           openclaw-chaos   Up X (starting) — will become (healthy) within ~60s

# 3. Wait for Chaos to become healthy (up to 90s — accounts for the bumped start_period).
ssh -i hetzner-cloudesk.pem -p 2222 overlord101@<SERVER3_IP> \
  "for i in \$(seq 1 90); do \
     status=\$(docker inspect openclaw-chaos --format '{{.State.Health.Status}}'); \
     if [ \"\$status\" = \"healthy\" ]; then echo 'healthy after '\$i's'; exit 0; fi; \
     sleep 1; \
   done; \
   echo 'FATAL: Chaos did not become healthy within 90s'; exit 1"
```

### 8.4 Smoke tests

**v2 note:** Expanded after QA review. "Hello" DMs do not prove memory recall, cron state, or tool availability. The tests below compare before/after snapshots captured in Section 8.1 step S15.

```bash
SSH="ssh -i hetzner-cloudesk.pem -p 2222 overlord101@<SERVER3_IP>"

# === 1. Gateway healthchecks ===
$SSH "curl -sf http://127.0.0.1:18789/healthz && echo 'jarvis OK'"
$SSH "curl -sf http://127.0.0.1:18791/healthz && echo 'chaos OK'"
# NOTE: /healthz can return 200 even when OpenClaw is non-functional (pre-existing
# Session 2026-04-08 bug). This check is necessary but not sufficient — the Slack
# tests below are the real validation.

# === 2. Wait ~60s for Chaos to finish Composio MCP reconnection ===
sleep 60

# === 3. Slack memory-recall test (Chaos) ===
# DM Chaos: "What is your name and current role?"
# Expected: response matches pre-flight baseline from S8/S15. Name should be "Chaos",
# not "Jarvis". If Chaos says "Jarvis", the seed overwrote the live config — ROLLBACK.

# === 4. Slack cron-state test (Chaos) ===
# DM Chaos: "What cron jobs do you have scheduled?"
# Expected: response lists the same jobs as the pre-flight S10 snapshot.

# === 5. Slack memory-recall test (Chaos) — deep ===
# DM Chaos: "What was the last significant thing we worked on together?"
# Expected: response references recent conversations (proves memory JSONL survived).

# === 6. Slack identity test (Jarvis) ===
# DM Jarvis: "hello, are you still Jarvis?"
# Expected: response confirms identity unchanged.

# === 7. Content integrity of migrated data vs backup ===
$SSH "sudo find /opt/openclaw/chaos/data -type f -exec sha256sum {} \; | sort > /tmp/post-chaos-tree.txt"
$SSH "sudo find /opt/openclaw/openclaw_data_chaos.bak.2026-04-09 -type f -exec sha256sum {} \; | \
      sed 's|/opt/openclaw/openclaw_data_chaos\\.bak\\.2026-04-09/|/opt/openclaw/chaos/data/|g' | \
      sort > /tmp/backup-chaos-tree.txt"
$SSH "diff /tmp/backup-chaos-tree.txt /tmp/post-chaos-tree.txt"
# Expected: no output. Any diff indicates corruption during migration.

# === 8. Jarvis StartedAt unchanged (exact equality) ===
$SSH "docker inspect openclaw-jarvis --format '{{.State.StartedAt}}' > /tmp/post-jarvis-started.txt"
diff /tmp/preflight-jarvis-started.txt /tmp/post-jarvis-started.txt
# Expected: no output. Any diff means Jarvis was recreated — investigate immediately.

# === 9. Chaos container logs — check for provider errors, MCP failures, config parse errors ===
$SSH "docker logs --since 5m openclaw-chaos 2>&1 | \
      grep -iE 'error|fatal|provider not found|parse|memorySearch' | head -20"
# Expected: mostly empty, or only the known Composio MCP reconnection warnings (transient).
```

**Pass/fail gate:** ALL of 1-9 must pass. Any failure triggers the rollback plan in Section 10.

---

## 9. Verification Plan

**v2 note:** Upgraded checks per QA review: exact equality on Jarvis StartedAt (was relative), content-hash comparison instead of ls (was filename check), added Chaos volume mount verification, added negative network assertion.

| # | Check | Command / Action | Expected |
|---|---|---|---|
| 1 | Chaos container is up | `docker ps --filter name=openclaw-chaos` | `Up X (healthy)` |
| 2 | Chaos uses new compose file | `docker inspect openclaw-chaos --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'` | `/opt/openclaw/chaos` |
| 3 | Chaos is on `chaos_net` | `docker inspect openclaw-chaos --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}'` | Contains `chaos_chaos_net` |
| 3b | Chaos is NOT on `openclaw_net` (negative) | `docker network inspect openclaw_openclaw_net --format '{{range .Containers}}{{.Name}} {{end}}'` | Must NOT contain `openclaw-chaos` |
| 3c | Chaos volume mount resolves to correct host path | `docker inspect openclaw-chaos --format '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}} -> {{.Destination}}{{end}}{{end}}'` | `/opt/openclaw/chaos/data -> /home/node/.openclaw` |
| 4 | Chaos live config SHA preserved | `sudo sha256sum /opt/openclaw/chaos/data/openclaw.json` | Matches pre-flight snapshot from S6 |
| 4b | Chaos identity is "Chaos" (not "Jarvis") | `sudo grep -A2 '"identity"' /opt/openclaw/chaos/data/openclaw.json` | Matches pre-flight S8 snapshot (name: Chaos or whatever the drifted value is) |
| 5 | Chaos data tree integrity (content-hash, not filename) | `sudo find /opt/openclaw/chaos/data -type f -exec sha256sum {} \; \| sort` compared against the backup via the Section 8.4 step 7 diff | No output from diff |
| 6 | Chaos backup exists and matches pre-flight size | `sudo du -sb /opt/openclaw/openclaw_data_chaos.bak.2026-04-09` | Matches pre-flight S7 |
| 7 | Orphan `openclaw_data_chaos` removed | `ls /opt/openclaw/openclaw_data_chaos 2>&1` | `No such file or directory` |
| 8 | Jarvis container is up | `docker ps --filter name=openclaw-jarvis` | `Up X (healthy)` |
| 9 | **Jarvis StartedAt unchanged (exact equality, v2)** | `docker inspect openclaw-jarvis --format '{{.State.StartedAt}}'` | **Exactly equals** pre-flight S12 snapshot (NOT a relative comparison — the v1 relative check false-positived after server reboot) |
| 10 | Jarvis live config untouched | `sudo sha256sum /opt/openclaw/openclaw_data/openclaw.json` | Matches pre-flight S13 snapshot |
| 11 | Jarvis data dir mtime untouched | `sudo stat -c '%Y' /opt/openclaw/openclaw_data` | Matches pre-flight S13 snapshot |
| 12 | Jarvis is still on `openclaw_net` only | `docker network inspect openclaw_openclaw_net --format '{{range .Containers}}{{.Name}} {{end}}'` | Contains `openclaw-jarvis`, does NOT contain `openclaw-chaos` |
| 13 | Jarvis is NOT on `chaos_net` (negative) | `docker network inspect chaos_chaos_net --format '{{range .Containers}}{{.Name}} {{end}}'` | Must NOT contain `openclaw-jarvis` |
| 14 | `chaos_net` contains only Chaos | `docker network inspect chaos_chaos_net` | Contains `openclaw-chaos` only |
| 15 | Sentinel file exists | `ls -la /opt/openclaw/.chaos-seeded` | Exists, owned by `overlord101`, mode 644 |
| 16 | Subsequent deploy does NOT re-seed | Re-run `pyinfra infra/inventory.py infra/deploy.py` | "Seed Chaos openclaw.json" step is absent from the Pyinfra diff output |
| 17 | Chaos live openclaw.json SHA unchanged after second deploy | `sudo sha256sum /opt/openclaw/chaos/data/openclaw.json` before and after re-deploy | Values match (proves sentinel guard works) |
| 18 | Both agents respond in Slack (memory recall, identity, cron) | See Section 8.4 steps 3-6 for the specific prompts | All responses match pre-flight baselines |
| 19 | No dangling Docker networks | `docker network ls \| grep openclaw\|chaos` | Only `openclaw_openclaw_net` and `chaos_chaos_net` present — no stale networks |
| 20 | No dangling Docker volumes | `docker volume ls \| grep openclaw\|chaos` | No unexpected entries |
| 21 | Chaos startup logs clean | `docker logs --since 5m openclaw-chaos 2>&1 \| grep -iE 'error\|fatal\|provider not found\|parse'` | Only transient Composio MCP reconnection warnings, if any |

---

## 10. Rollback Plan

**Precondition:** `openclaw_data_chaos.bak.2026-04-09` still exists (it is retained for 48h).

**Assertion:** Every step below is **idempotent and safe to re-run**. If the rollback is interrupted (SSH drop, etc.), re-run the entire script from the top — no step will fail on pre-existing state. All destructive operations are guarded with `[ ... ]` existence checks.

**Critical ordering:** Server-side steps R1-R5 **must run in order**. In particular, R5 (delete sentinel) must come AFTER R2 (restore legacy data), otherwise a re-deploy would see `legacy_exists=False, sentinel=False` and fire the seed, overwriting the drifted live config.

```bash
SSH="ssh -i hetzner-cloudesk.pem -p 2222 overlord101@<SERVER3_IP>"

# === R1. Stop new Chaos container (safe if already stopped or never started) ===
$SSH "if [ -f /opt/openclaw/chaos/docker-compose.yml ]; then \
        cd /opt/openclaw/chaos && docker compose --env-file ../.env down 2>/dev/null || true; \
      fi; \
      docker stop openclaw-chaos 2>/dev/null || true; \
      docker rm openclaw-chaos 2>/dev/null || true"

# === R2. Move data back to legacy path (idempotent — only if chaos/data exists and legacy doesn't) ===
$SSH "if [ -d /opt/openclaw/chaos/data ] && [ ! -d /opt/openclaw/openclaw_data_chaos ]; then \
        sudo mv /opt/openclaw/chaos/data /opt/openclaw/openclaw_data_chaos; \
      fi"

# === R2b. If chaos/data is missing or corrupt, restore from the backup ===
$SSH "if [ ! -d /opt/openclaw/openclaw_data_chaos ] && \
         [ -d /opt/openclaw/openclaw_data_chaos.bak.2026-04-09 ]; then \
        sudo cp -a /opt/openclaw/openclaw_data_chaos.bak.2026-04-09 \
                   /opt/openclaw/openclaw_data_chaos; \
      fi"

# === R3. Remove the now-empty chaos subdir (safe if already gone, or if compose file still there) ===
$SSH "if [ -d /opt/openclaw/chaos ]; then \
        sudo rm -rf /opt/openclaw/chaos; \
      fi"

# === R4. Remove the chaos_net network if Docker Compose left it behind ===
$SSH "docker network rm chaos_chaos_net 2>/dev/null || true"

# === R5. Remove the sentinel (MUST run AFTER R2/R2b to avoid silent re-seed on next deploy) ===
$SSH "sudo rm -f /opt/openclaw/.chaos-seeded"

# === R6. Revert repo changes locally ===
cd /home/blank/Desktop/Projects/Cloudesk/ai-project
git checkout -- docker/docker-compose.yml infra/tasks/app_deploy.py
rm -rf docker/chaos

# === R7. Redeploy the old shared layout ===
pyinfra infra/inventory.py infra/deploy.py

# === R8. Verify both containers come back on the shared compose file ===
$SSH "docker ps --filter name=openclaw- --format '{{.Names}}\t{{.Status}}'"
# Expected: both openclaw-jarvis and openclaw-chaos Up (healthy) on the shared compose.
```

**Target rollback time:** under 10 minutes for the happy path, up to 20 minutes if image re-pull is required. The pre-flight step S11 pre-seeds the image, so re-pull should not be needed.

**Post-rollback:** file an issue with the exact error, then revisit the plan.

### 10.1 Backup cleanup (48h after a clean deploy)

Only run this after the full Section 9 verification AND the 48h soak criteria (see Section 13) have passed.

```bash
ssh -i hetzner-cloudesk.pem -p 2222 overlord101@<SERVER3_IP> \
  "sudo rm -rf /opt/openclaw/openclaw_data_chaos.bak.2026-04-09 && \
   ls /opt/openclaw/openclaw_data_chaos.bak.2026-04-09 2>&1"
# Expected final output: "No such file or directory"
```

### 10.2 Operational impact: force-reset procedure changed

**New rule:** To force-reset Chaos's seed config (e.g., to pick up a template change), you must delete BOTH `/opt/openclaw/chaos/data/openclaw.json` AND `/opt/openclaw/.chaos-seeded` on the server before redeploying. The v1 procedure (delete only the JSON file) no longer works because the sentinel guard will skip the seed step.

Update `CLAUDE.md`'s force-reset note accordingly in a follow-up.

---

## 11. Follow-up Work

**Priority order matters here — item 2 unblocks item 3, which makes item 4 significantly simpler.**

1. **Jarvis separation (separate plan).** Mirror this refactor for Jarvis: `docker/jarvis/docker-compose.yml`, `docker/jarvis/openclaw.json`, `/opt/openclaw/jarvis/data/`. After that, `docker/docker-compose.yml` at the top level can be deleted entirely (or left as a README placeholder). **Audit item:** the current `app_deploy.py:47` Jarvis seed-once check has the same permissions bug this plan's Section 6.9 addresses — the Jarvis separation plan should apply an analogous sentinel guard.

2. **Per-agent Pyinfra task files.** Once both agents are subdirectories, split `app_deploy.py` into `app_deploy_jarvis.py` and `app_deploy_chaos.py` included from `deploy.py`, so each agent can be deployed independently (e.g., `pyinfra infra/inventory.py infra/tasks/app_deploy_chaos.py`). This is the point at which the "don't touch Jarvis when deploying Chaos" isolation stops being cosmetic and becomes real. Lead-engineer review flagged this as a scope-creep candidate for THIS plan — deferred for safety.

3. **Chaos LiteLLM migration (correction from v1).** The paused `docs/plans/2026-04-09-chaos-litellm-migration-design.md` is unblocked in the sense that Chaos's seed file and compose file are now isolated from Jarvis — edits land in `docker/chaos/openclaw.json` with zero risk to Jarvis's seed file on disk. **However**, the migration is NOT a single-file repo edit. Because of OpenClaw's seed-once model, changing the repo seed does nothing to a running agent with a drifted live config. The migration still requires one of:
   - **(a) Force-reseed path:** edit `docker/chaos/openclaw.json` + on the server, delete BOTH `/opt/openclaw/chaos/data/openclaw.json` AND `/opt/openclaw/.chaos-seeded`, then redeploy. This discards Chaos's drifted state (Composio MCP, identity, channel tokens) — unacceptable for most changes.
   - **(b) Live-file edit path:** SSH into the server and edit `/opt/openclaw/chaos/data/openclaw.json` directly (e.g., via `sudo jq` or the OpenClaw Control UI). Preserves drifted state. This is the preferred path for LiteLLM migration.
   Either way, the separation lets you do this without touching Jarvis. But the v1 plan's claim that "LiteLLM becomes a one-file edit" was overstated — correct this in the paused plan when it resumes.

4. **SearXNG integration for Chaos.** Still paused. Once Chaos is isolated, adding a `searxng` service to `docker/chaos/docker-compose.yml` with the same `chaos_net` network is trivial and cannot collide with Jarvis.

5. **Replace `curl /healthz` healthcheck with CLI-based check (cross-agent).** Session 2026-04-08 confirmed that `/healthz` returns HTTP 200 even when OpenClaw's gateway is non-functional (false healthy). Switch both compose files to a CLI-based check that actually validates gateway state. Belongs in its own cross-agent follow-up plan because it touches both Jarvis and Chaos.

6. **Update `CLAUDE.md` force-reset procedure.** The "delete openclaw.json and redeploy" force-reset note in `CLAUDE.md` is now incomplete for Chaos — with the sentinel, you must also delete `/opt/openclaw/.chaos-seeded`. Documentation-only change.

7. **Sibling-file pattern tripwire.** This plan commits to `docker/<agent>/docker-compose.yml` sibling files. At N=2 or N=3 agents this is clean. At N=4+ the duplication becomes painful and a templating layer (Jinja2 or Pyinfra `files.template()`) becomes worth the complexity. **Rule:** when a third agent is added, revisit templating. When a fourth agent is added, templating is required. Prevents drift into ten compose files by inertia.

8. **Observability design (separate plan).** `docker logs` is currently the entire observability story. Fine for solo-dev today; the isolated `chaos_net` decision closes off the simplest path (a sidecar log shipper on the shared network). When observability becomes a priority, plan for a shared network namespace specifically for metrics/logs collection, OR attach shared services (Prometheus, Vector) to both `chaos_net` and `openclaw_net` via `external: true`.

9. **Multi-host escape hatch.** If Chaos ever needs to move to its own host (e.g., because experimentation starts taking the whole box down), the bind-mount data dir, shared `.env`, and isolated networks all need revisiting. **Named assumption:** both agents are assumed to co-reside on Server 3 for the foreseeable future. Breaking this means a new plan.

10. **Drop `--force-recreate` from Jarvis deploy (confirmed, not a TBD).** Lead-engineer review recommended treating this as committed (not a "future confirmation") — this plan already drops it in Section 6.8 on the basis of reasoning, so there's nothing left to confirm. Leave as the permanent default.

11. **`docker/chaos/README.md` (optional, low priority).** A one-paragraph operational runbook explaining the `--env-file ../.env` pattern, the sentinel at `/opt/openclaw/.chaos-seeded`, and the force-reset procedure. Helpful for future-you reading the directory cold.

12. **Upgrade Chaos to a newer OpenClaw version (post-stabilization).** A version check on 2026-04-09 found that `2026.4.9` is the latest stable release, but **do NOT upgrade during or immediately after this refactor**. The council-verified plan is:
    - **Prerequisites before any upgrade attempt:**
      - Chaos has been stable on `2026.4.5` under the new split topology for at least 3-7 days
      - Issue [#63526](https://github.com/openclaw/openclaw/issues/63526) (v2026.4.9 gateway RSS grows to 945MB, exceeds our 1G limit) has a confirmed fix or closure
      - Issue [#62051](https://github.com/openclaw/openclaw/issues/62051) (worker child plugin CPU saturation) has a confirmed fix or closure
      - At least one additional release has landed since the target version to shake out hot regressions
    - **Why not upgrade now:** 4.9 has an active memory regression that would push both agents into OOM territory on the 1G cap (Chaos already has OOM history from Session 2026-04-08). 4.7 and 4.8 bring no fixes for the issues we actually care about (healthcheck false-positive, SIGTERM/MCP shutdown timeout, Composio restart loop). No breaking schema changes on our config surface across 4.5→4.9, so waiting is cheap.
    - **Upgrade procedure when ready:** Run `docker exec openclaw-chaos openclaw backup create --verify` first. Bump the image pin in `docker/chaos/docker-compose.yml` only (Jarvis stays on current pin). Redeploy via `cd /opt/openclaw/chaos && docker compose --env-file ../.env pull && docker compose --env-file ../.env up -d`. 48h soak. Then Jarvis separately.
    - **New intel worth noting about our current pin:** [#62095](https://github.com/openclaw/openclaw/issues/62095) documents five open regressions in 4.5 including gateway memory growth to 1.5GB and a Slack Socket Mode reconnect loop every ~35 minutes. If we observe unexpected memory growth or Slack reconnect chatter post-refactor, it is likely pre-existing rather than caused by the refactor — check `dmesg` and Slack logs before blaming the split topology.

---

## 12. Open Questions

### 12.1 Does `docker compose up -d --remove-orphans` gracefully stop the orphan Chaos container?

**Answer:** Yes. `--remove-orphans` calls `container stop` (SIGTERM, honors the container's `stop_grace_period`, default 10s) before `container rm`. Chaos's `init: true` runs tini as PID 1, which forwards SIGTERM to the Node process, which OpenClaw handles to flush pending writes. This is the same shutdown path a normal `docker compose down` would use — no hard kill.

**Risk:** If Chaos is mid-write on its openclaw.json during the stop, the file could theoretically be truncated. Mitigation: the data move happens AFTER the stop completes, so any half-written state is captured in the backup. Chaos's memory writes are append-only JSONL, so even a torn write only drops the last record.

**Action item:** None. Default behaviour is safe enough; the `cp -a` backup is the belt.

### 12.2 What happens to Chaos's Docker-managed resources when it is removed from the compose file?

**Answer:**
- **Container:** removed by `--remove-orphans` (confirmed by Docker Compose docs).
- **Anonymous volumes:** Chaos does not use any anonymous volumes (only a bind mount to `./openclaw_data_chaos`), so nothing to leak.
- **Named volumes:** none declared.
- **Bind mounts:** the host directory `openclaw_data_chaos` stays put — Docker never touches host bind-mounted directories. This is exactly what we want, so the subsequent `mv` can pick it up.
- **Networks:** `openclaw_net` persists because Jarvis still uses it. Nothing to clean up.
- **Images:** `ghcr.io/openclaw/openclaw:2026.4.5` is still referenced by both Jarvis and the new Chaos compose file, so no dangling image.

**Action item:** After the deploy, run `docker network ls` and `docker volume ls` once to confirm no stale `openclaw_openclaw_data_chaos` or similar is lingering.

### 12.3 Does `host.get_fact(File, path=chaos_config_dest)` work for the new path?

**Status:** RESOLVED — Option C (sentinel file) selected by the user on 2026-04-09. See Section 6.9 for the full design and Section 7.4 for the implementation.

**Summary of resolution:**
- Sentinel lives at `/opt/openclaw/.chaos-seeded` (NOT inside `chaos/` — that directory is mode 750 owned by uid 1000 and `overlord101` cannot write there).
- Two-fact guard (legacy dir + sentinel) handles the first-run-with-existing-live-data timing bug in Pyinfra's fact-gathering model.
- Rollback includes deletion of the sentinel (see Section 10).
- Same-shape bug likely exists in the current Jarvis seed path at `app_deploy.py:47`; flagged as an audit item for the future Jarvis separation plan.

### 12.4 Is there shared state between Jarvis and Chaos today that isolation would break?

**Answer (after review of current state):**

| Shared thing | Used? | Isolation-safe? |
|---|---|---|
| `openclaw_net` (Docker network) | No container-to-container traffic today | Yes — removing Chaos from the network is a no-op |
| `.env` file | Yes, read by both at container start | Yes — we preserve the single `.env` via `--env-file ../.env` |
| Host filesystem (`/opt/openclaw`) | Only `.env` is shared; data dirs are separate | Yes — already effectively isolated |
| Docker daemon | Yes | Yes — both still use the same daemon; no change |
| Image `ghcr.io/openclaw/openclaw:2026.4.5` | Yes (both reference it) | Yes — image is read-only; both continue to reference the same digest |
| Host loopback ports | No overlap (18789/18790 vs 18791/18792) | Yes |
| System resource pool (RAM/CPU) | Shared at kernel level, bounded by `deploy.resources.limits` | Yes — limits are per-container, unchanged |
| Slack workspaces | Each agent uses a different Slack app/token | Yes |
| LiteLLM upstream | Neither is routed through LiteLLM today | N/A |
| Composio MCP | Each agent has its own Composio key, stored in its own live `openclaw.json` | Yes |

**Conclusion:** No existing shared state is broken by isolation.

### 12.5 Should Pyinfra delete `openclaw_data_chaos` after a successful move, or leave it as the timestamped backup?

**Current plan:** `mv` (not `cp`) destroys the original path, and `cp -a` takes the backup FIRST. So after step 2 there is no `openclaw_data_chaos` directory — only `openclaw_data_chaos.bak.2026-04-09` and `chaos/data`. No additional cleanup needed.

**Action item:** Confirm in verification check 7.

---

## 13. Success Criteria

Pass all of the following to mark this plan complete. Each item is concrete and automatable — no subjective judgments.

### 13.1 Repo state
- [ ] `docker/chaos/docker-compose.yml` exists and `docker compose -f docker/chaos/docker-compose.yml --env-file .env config > /dev/null` exits 0.
- [ ] `docker/chaos/openclaw.json` exists. `diff docker/openclaw.json docker/chaos/openclaw.json` produces ONLY the 2-line `identity.name` change (Jarvis → Chaos). Any other diff is a bug.
- [ ] `docker/docker-compose.yml` contains only Jarvis and the `openclaw_net` network — no `chaos:` service, no `openclaw-chaos` container name anywhere.
- [ ] `infra/tasks/app_deploy.py` has the full rewrite per Section 7.4 and the Jarvis section at lines 37-57 is byte-identical to the pre-change version (`git diff infra/tasks/app_deploy.py` shows zero changes in that range).

### 13.2 Pyinfra execution
- [ ] `pyinfra --dry infra/inventory.py infra/deploy.py` exits 0 with zero `ERROR` or `Exception` lines in output.
- [ ] `pyinfra infra/inventory.py infra/deploy.py` exits 0. Both the Chaos section and the Jarvis compose-up step complete without errors.

### 13.3 Container state (immediate post-deploy)
- [ ] `docker ps` shows both `openclaw-jarvis` and `openclaw-chaos` as `Up ... (healthy)`.
- [ ] `docker inspect openclaw-jarvis --format '{{.State.StartedAt}}'` **exactly equals** the pre-flight S12 snapshot — proves Jarvis was NOT recreated.
- [ ] `docker inspect openclaw-jarvis --format '{{.RestartCount}}'` still equals its pre-flight value (no bounces).
- [ ] `docker inspect openclaw-chaos --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'` returns `/opt/openclaw/chaos`.
- [ ] `docker inspect openclaw-chaos --format '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}} -> {{.Destination}}{{end}}{{end}}'` returns `/opt/openclaw/chaos/data -> /home/node/.openclaw`.

### 13.4 Network isolation
- [ ] `openclaw-chaos` is on `chaos_chaos_net` (positive).
- [ ] `openclaw-chaos` is NOT on `openclaw_openclaw_net` (negative).
- [ ] `openclaw-jarvis` is on `openclaw_openclaw_net` (positive, unchanged).
- [ ] `openclaw-jarvis` is NOT on `chaos_chaos_net` (negative).

### 13.5 Data integrity
- [ ] `sudo sha256sum /opt/openclaw/openclaw_data/openclaw.json` exactly matches the pre-flight S13 snapshot.
- [ ] `sudo sha256sum /opt/openclaw/chaos/data/openclaw.json` exactly matches the pre-flight S6 snapshot.
- [ ] Recursive content hash of `/opt/openclaw/chaos/data/` matches the backup tree (Section 8.4 step 7 diff produces no output).
- [ ] `/opt/openclaw/openclaw_data_chaos` no longer exists.
- [ ] `/opt/openclaw/openclaw_data_chaos.bak.2026-04-09` exists and its `du -sb` matches the pre-flight size.

### 13.6 Sentinel and idempotency
- [ ] `/opt/openclaw/.chaos-seeded` exists, mode 644, owned by `overlord101`.
- [ ] A second consecutive `pyinfra infra/inventory.py infra/deploy.py` shows NO "Seed Chaos openclaw.json" operation in its output.
- [ ] `sudo sha256sum /opt/openclaw/chaos/data/openclaw.json` is identical before and after the second deploy (proves the guard works).

### 13.7 Smoke tests (behavioral)
- [ ] Jarvis responds to a Slack DM. Response identifies as "Jarvis". (No SLA — Slack Socket Mode latency is variable.)
- [ ] Chaos responds to a Slack DM. Response identifies as "Chaos" (NOT "Jarvis" — if it says Jarvis, the seed overwrote the live config and rollback is required).
- [ ] Chaos recalls recent context when asked "what was the last significant thing we worked on together?" — matches the pre-flight S15 baseline.
- [ ] Chaos lists the same cron jobs as the pre-flight S10 snapshot.

### 13.8 Log cleanliness
- [ ] `docker logs --since 5m openclaw-chaos 2>&1 | grep -iE 'error|fatal|provider not found|parse'` returns only transient Composio MCP reconnection warnings (acceptable) or nothing.

### 13.9 48-hour soak
- [ ] After 48h, `docker inspect openclaw-chaos --format '{{.RestartCount}}'` returns `0`.
- [ ] After 48h, `docker inspect openclaw-jarvis --format '{{.RestartCount}}'` is unchanged from pre-flight.
- [ ] After 48h, both agents still show `(healthy)` in `docker ps`.
- [ ] After 48h, `sudo sha256sum /opt/openclaw/chaos/data/openclaw.json` sha matches the post-deploy snapshot (no unexpected config drift from normal self-management is expected and acceptable — the check is "did it survive" not "is it byte-identical").
- [ ] After 48h, `dmesg | grep -i oom` shows no OOM kills during the soak window.
- [ ] Backup directory is removed after the 48h clean soak: `sudo rm -rf /opt/openclaw/openclaw_data_chaos.bak.2026-04-09`, verified gone.

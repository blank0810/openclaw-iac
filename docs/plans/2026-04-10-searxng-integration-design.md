# SearXNG Integration Design — Server 3

**Status:** Approved (council-reviewed, flags resolved by OpenClaw expert)
**Date:** 2026-04-10
**Scope:** Server 3 (OpenClaw Agents) — Jarvis and Chaos
**Owner:** infra-engineer
**Supersedes:** none

---

## 1. Context

[SearXNG](https://docs.searxng.org/) is an open-source, privacy-respecting metasearch engine that aggregates results from 70+ upstream search engines (Google, Bing, DuckDuckGo, etc.) without requiring any API keys. It exposes a JSON API at `/search?format=json` that OpenClaw's bundled `web-search` skill can consume natively via the `SEARXNG_BASE_URL` environment variable.

**Why we're adding it:**

1. **Eliminate the Brave API key dependency.** `BRAVE_API_KEY` is currently the only third-party search credential on Server 3. Brave's free tier caps at 2,000 queries/month. SearXNG has no rate limit beyond what upstream engines impose.
2. **Self-hosted = no external billing surface.** The Brave key is shared across both agents via `.env`. If it gets revoked or exhausted, both agents lose web search simultaneously.
3. **Privacy alignment.** SearXNG strips tracking parameters, rotates across engines, and runs entirely within our network. No query data leaves the server except as anonymized upstream search requests.
4. **OpenClaw has native SearXNG support.** PR [#13334](https://github.com/openclaw/openclaw/pull/13334) added SearXNG as a first-class provider in the `web-search` tool. Configuration is a single `SEARXNG_BASE_URL` env var or a `tools.web.search` block in `openclaw.json`.

**Research sources:**

- [SearXNG Docker installation docs](https://docs.searxng.org/admin/installation-docker.html)
- [SearXNG settings reference](https://docs.searxng.org/admin/settings/index.html)
- [SearXNG Search API docs](https://docs.searxng.org/dev/search_api.html)
- [SearXNG GitHub Container Registry](https://github.com/searxng/searxng/pkgs/container/searxng)
- [OpenClaw web-search tool docs](https://docs.openclaw.ai/tools/web)
- [OpenClaw SearXNG PR #13334](https://github.com/openclaw/openclaw/pull/13334)
- [SearXNG memory optimization discussion](https://github.com/searxng/searxng/discussions/1892)
- [SearXNG uWSGI OOM issue #447](https://github.com/searxng/searxng/issues/447)

---

## 2. Design Decisions

Each decision is locked-in; rationale is recorded for future readers.

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **One SearXNG instance per agent** — Jarvis gets `searxng` on `openclaw_net`, Chaos gets `searxng` on `chaos_net` | Network isolation established in the chaos separation plan. A shared instance would require a third network or joining both bridges, violating the "no shared network between agents" non-goal. Per-agent instances also prevent one agent's search traffic from degrading the other's. |
| D2 | **Replace Brave Search entirely** — remove `BRAVE_API_KEY` from compose env blocks | Eliminates the only metered external search dependency. SearXNG provides equivalent or better results for free. No reason to maintain two search backends. |
| D3 | **No Redis/Valkey sidecar** — SearXNG standalone | Redis is optional in SearXNG; it powers the rate limiter (`server.limiter`) and bot detection. We are the only clients (one OpenClaw agent per instance, <10 QPS), so rate limiting is unnecessary overhead. Saves ~30MB RAM per agent. |
| D4 | **Hardcode URL via Docker DNS** — `http://searxng:8080` | Both compose files define the SearXNG service as `searxng`. Docker's embedded DNS resolves `searxng` to the container IP within each bridge network. No env var needed, no `.env` pollution, no cross-agent DNS collision (different compose projects = different DNS namespaces). |
| D5 | **Follow existing security posture** — `cap_drop: ALL`, `no-new-privileges`, `read_only`, resource limits | Consistency with the OpenClaw containers. SearXNG's official image runs as a non-root user internally. `read_only: true` requires tmpfs mounts for `/tmp` and `/var/cache/searxng`. |
| D6 | **Seed-once pattern for `settings.yml`** — upload only if volume is empty | Matches the OpenClaw config model. SearXNG reads `/etc/searxng/settings.yml` at startup. If the operator modifies it on the server, Pyinfra won't overwrite it on subsequent deploys. |
| D7 | **Single worker (`UWSGI_WORKERS=1`)** — minimize memory footprint | Default uWSGI spawns one worker per CPU core (2 for Jarvis, 1.5 for Chaos). Each worker consumes ~256MB. At our QPS (<10/min), a single worker handles all traffic with ~150MB total RSS. |
| D8 | **Pin image to `searxng/searxng:latest`** — no version pin initially | SearXNG follows rolling releases with date-based tags (e.g., `2026.4.7-08ef7a63d`). Unlike OpenClaw (which has known regressions in recent tags), SearXNG is a mature, stable project. We start with `latest` and pin to a specific tag after the first successful deploy, following the same pattern used for the initial OpenClaw deployment. |
| D9 | **`SEARXNG_BASE_URL` as container env var** — not in `.env` | The URL is a fixed Docker DNS address (`http://searxng:8080`), identical for both agents. Putting it in `.env` adds noise with no value. Hardcoded in each compose file's `environment:` block. |
| D10 | **Shared base `settings.yml` at `docker/searxng/settings.yml`** — both agents use the same config | No agent-specific search customization needed today. One file, uploaded to both data volumes. If divergence is needed later, copy to `docker/chaos/searxng/settings.yml`. |
| D11 | **Disable the SearXNG web UI** — JSON API only | The UI is unnecessary (agents never open a browser) and wastes resources rendering HTML/CSS/JS. Achieved by omitting `html` from `search.formats`. |

---

## 3. Architecture

### 3.1 Updated Network Topology

```
                          Internet
                             |
                     UFW (port 2222 only)
                             |
                    +-----------------+
                    |   Server 3 VPS  |
                    |                 |
    +---------------+-------+---------+----------------+
    |                       |                          |
    |   openclaw_net        |       chaos_net          |
    |   (bridge)            |       (bridge)           |
    |                       |                          |
    | +--------+ +--------+ |  +-------+ +--------+   |
    | | jarvis | | searxng | |  | chaos | | searxng |  |
    | | :18789 | | :8080   | |  | :18791| | :8080   |  |
    | +--------+ +--------+ |  +-------+ +--------+   |
    |                       |                          |
    +-----------------------+--------------------------+

    Jarvis -> http://searxng:8080/search?format=json  (openclaw_net DNS)
    Chaos  -> http://searxng:8080/search?format=json  (chaos_net DNS)

    No cross-network traffic. No host port exposure for SearXNG.
    Outbound HTTPS from SearXNG to upstream engines (Google, Bing, etc.)
    is allowed by default (UFW does not restrict outbound).
```

### 3.2 Container Inventory

| Name | Image | Ports (host) | Ports (container) | Network | CPU | Memory | Volume |
|------|-------|-------------|-------------------|---------|-----|--------|--------|
| `openclaw-jarvis` | `ghcr.io/openclaw/openclaw:2026.4.5` | `127.0.0.1:18789`, `127.0.0.1:18790` | 18789, 18790 | `openclaw_net` | 2.0 | 2G | `./openclaw_data` |
| `jarvis-searxng` | `searxng/searxng:latest` | none | 8080 | `openclaw_net` | 0.5 | 512M | `./searxng_data` |
| `openclaw-chaos` | `ghcr.io/openclaw/openclaw:2026.4.5` | `127.0.0.1:18791`, `127.0.0.1:18792` | 18791, 18792 | `chaos_net` | 1.5 | 2G | `./data` |
| `chaos-searxng` | `searxng/searxng:latest` | none | 8080 | `chaos_net` | 0.5 | 512M | `./searxng_data` |

**Memory budget impact:** +512M x2 = +1024M total. With single-worker config, actual RSS is ~150MB per instance, well within the 512M hard limit. The 512M limit provides headroom for burst queries that spin up temporary threads.

---

## 4. Implementation Plan

### Phase 1: SearXNG Docker Config

#### 4.1 New file: `docker/searxng/settings.yml`

Shared base configuration uploaded to both agents' SearXNG volumes.

```yaml
# SearXNG settings for OpenClaw agents.
# Minimal config: JSON API only, single-user, no UI, no rate limiting.
# Seeded once by Pyinfra; edit on server to customize.

general:
  debug: false
  instance_name: "SearXNG (OpenClaw)"
  privacypolicy_url: false
  donation_url: false
  contact_url: false
  enable_metrics: false

server:
  # secret_key is overridden by SEARXNG_SECRET env var at container start.
  secret_key: "override-me-via-env"
  bind_address: "0.0.0.0"
  port: 8080
  limiter: false
  public_instance: false
  image_proxy: false
  method: "GET"
  default_http_headers:
    X-Content-Type-Options: nosniff
    X-Robots-Tag: noindex, nofollow
    Referrer-Policy: no-referrer

search:
  safe_search: 0
  autocomplete: ""
  default_lang: "en"
  formats:
    - json

ui:
  default_theme: simple
  query_in_title: false
  center_alignment: false

# Engine selection: enable only the most reliable, fastest engines.
# Fewer engines = faster response times + less outbound traffic.
# Full engine list: https://docs.searxng.org/user/configured_engines.html
engines:
  - name: google
    engine: google
    shortcut: g
    disabled: false

  - name: bing
    engine: bing
    shortcut: bi
    disabled: false

  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
    disabled: false

  - name: wikipedia
    engine: wikipedia
    shortcut: wp
    disabled: false

  - name: wikidata
    engine: wikidata
    shortcut: wd
    disabled: true

  - name: brave
    engine: brave
    shortcut: br
    disabled: true

  - name: startpage
    engine: startpage
    shortcut: sp
    disabled: false

  - name: qwant
    engine: qwant
    shortcut: qw
    disabled: true
```

**Notes on engine selection:**

- Google, Bing, DuckDuckGo, Startpage, and Wikipedia are enabled as a balanced set of general + reference engines.
- Brave is disabled — its scraping adapter (without an API key) is less reliable and redundant since we're eliminating the Brave dependency entirely.
- Startpage proxies Google results and works well from Southeast Asia (Philippines).
- Qwant and Wikidata are disabled to reduce latency and outbound requests.
- The `engines:` block in settings.yml MERGES with the built-in engine list. Engines not listed here retain their defaults (most are disabled by default). Only engines we want to explicitly enable or disable are listed.
- This can be tuned on the server after deployment without redeploying.

#### 4.2 Changes to `docker/docker-compose.yml` (Jarvis)

Add the `searxng` service and its volume. Remove `BRAVE_API_KEY` from Jarvis's environment. Add `SEARXNG_BASE_URL`.

**Diff:**

```yaml
# ADD after the jarvis service block, before `networks:`

  searxng:
    image: searxng/searxng:latest
    container_name: jarvis-searxng
    init: true
    restart: unless-stopped
    volumes:
      - ./searxng_data:/etc/searxng
    environment:
      - SEARXNG_SECRET=${SEARXNG_SECRET:-searxng-jarvis-secret-change-me}
      - UWSGI_WORKERS=1
      - UWSGI_THREADS=4
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:size=50M
      - /var/cache/searxng:size=50M
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M
    networks:
      - openclaw_net
    healthcheck:
      test: ["CMD-SHELL", "wget --spider --quiet http://127.0.0.1:8080/healthz || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

**Changes to the `jarvis` service environment block:**

```yaml
# REMOVE this line:
      - BRAVE_API_KEY=${BRAVE_API_KEY:-}

# ADD this line (after the OPENAI_API_KEY line):
      - SEARXNG_BASE_URL=http://searxng:8080
```

**Full `docker/docker-compose.yml` after changes:**

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
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
      - SEARXNG_BASE_URL=http://searxng:8080
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

  searxng:
    image: searxng/searxng:latest
    container_name: jarvis-searxng
    init: true
    restart: unless-stopped
    volumes:
      - ./searxng_data:/etc/searxng
    environment:
      - SEARXNG_SECRET=${SEARXNG_SECRET:-searxng-jarvis-secret-change-me}
      - UWSGI_WORKERS=1
      - UWSGI_THREADS=4
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:size=50M
      - /var/cache/searxng:size=50M
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M
    networks:
      - openclaw_net
    healthcheck:
      test: ["CMD-SHELL", "wget --spider --quiet http://127.0.0.1:8080/healthz || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

networks:
  openclaw_net:
    driver: bridge
```

#### 4.3 Changes to `docker/chaos/docker-compose.yml` (Chaos)

Same pattern. Add `searxng` service, remove `BRAVE_API_KEY`, add `SEARXNG_BASE_URL`.

**Full `docker/chaos/docker-compose.yml` after changes:**

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
    stop_grace_period: 30s  # extended from default 10s — Composio MCP shutdown RPCs can hang
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
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
      - SEARXNG_BASE_URL=http://searxng:8080
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
      start_period: 60s  # bumped from 20s — Chaos drifted state + MCP reconnect can take ~22s
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "10"

  searxng:
    image: searxng/searxng:latest
    container_name: chaos-searxng
    init: true
    restart: unless-stopped
    volumes:
      - ./searxng_data:/etc/searxng
    environment:
      - SEARXNG_SECRET=${SEARXNG_SECRET:-searxng-chaos-secret-change-me}
      - UWSGI_WORKERS=1
      - UWSGI_THREADS=4
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:size=50M
      - /var/cache/searxng:size=50M
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M
    networks:
      - chaos_net
    healthcheck:
      test: ["CMD-SHELL", "wget --spider --quiet http://127.0.0.1:8080/healthz || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

networks:
  chaos_net:
    driver: bridge
```

#### 4.4 Design Notes on the SearXNG Service Block

- **`container_name: jarvis-searxng` / `chaos-searxng`**: Prefixed with the agent name for clarity in `docker ps` output. Both services are named `searxng` in their compose files (for DNS), but the container name distinguishes them on the host.
- **No `ports:` mapping**: SearXNG is only reachable via the bridge network. No host port means no UFW rule needed and no external exposure.
- **`read_only: true` + tmpfs**: SearXNG needs to write to `/tmp` (uWSGI sockets) and `/var/cache/searxng` (favicon cache). Both are tmpfs-backed with tight size limits.
- **`SEARXNG_SECRET`**: Required by the SearXNG container entrypoint for CSRF/session signing. Even with no UI, the server expects it. Defaults are provided inline for convenience; production should set real values in `.env`.
- **`UWSGI_WORKERS=1` + `UWSGI_THREADS=4`**: Single worker with 4 threads. Handles concurrent searches from the agent without spawning additional 256MB worker processes. Total memory: ~150MB.
- **`wget` in healthcheck instead of `curl`**: The SearXNG Docker image is Alpine-based and ships `wget` but not `curl`.
- **`/healthz` endpoint**: Native SearXNG health endpoint, confirmed in [issue #4026](https://github.com/searxng/searxng/issues/4026).

---

### Phase 2: OpenClaw Config Update

> **Correction (2026-04-13):** The earlier draft of this section claimed the bundled `web-search` skill auto-detects `SEARXNG_BASE_URL`. **That was wrong.** No such bundled skill ships with OpenClaw 2026.4.5, and `SEARXNG_BASE_URL` is not read by anything. The actual integration path is the `searxng` plugin (lives at `/app/dist/extensions/searxng/`) configured via `plugins.entries.searxng.config.webSearch.baseUrl` in `openclaw.json`. The `SEARXNG_BASE_URL` env var on the agent containers is harmless but unused; can be removed in a future cleanup.

#### 5.1 How Agents Use SearXNG (correct mechanism)

OpenClaw 2026.4.5 ships a native `searxng` extension (`/app/dist/extensions/searxng/openclaw.plugin.json`). The plugin registers as a `webSearch` provider and is opt-in — not enabled by default. To activate it:

1. Enable the plugin entry: `plugins.entries.searxng.enabled = true`
2. Configure the base URL: `plugins.entries.searxng.config.webSearch.baseUrl = "http://searxng:8080"`

The `.config` wrapper is required — confirmed by reading `/app/dist/plugin-web-search-config-*.js`:

```js
const pluginConfig = config?.plugins?.entries?.[pluginId]?.config;
return isRecord(pluginConfig.webSearch) ? pluginConfig.webSearch : void 0;
```

Once enabled, the agent can call SearXNG via the OpenClaw `webSearch` tool. The model still has access to its native search grounding (e.g., Gemini's Google grounding) — it picks based on context. To force SearXNG-only, disable the model provider's grounding feature.

#### 5.2 Changes to `openclaw.json` Seed Templates

**`docker/chaos/openclaw.json` is updated** to include the searxng plugin block at the end of the file:

```json
"plugins": {
  "entries": {
    "searxng": {
      "enabled": true,
      "config": {
        "webSearch": {
          "baseUrl": "http://searxng:8080"
        }
      }
    }
  }
}
```

This bakes the integration into fresh deploys. Existing live configs (drifted via gateway self-edits) need to be patched manually with the same block, then the container restarted.

#### 5.3 Common config gotchas (verified via failed attempts)

- **Wrong path:** `plugins.entries.searxng.webSearch.baseUrl` (without the `.config` wrapper) is rejected: `Unrecognized key: "webSearch"`. Boot fails until removed.
- **`tools.webSearch` is not a real config path** in OpenClaw 2026.4.5 — `gateway failed: config schema path not found raw_params={"path":"tools.webSearch"}`.
- **`x_search` is xAI's Twitter/X search tool**, not SearXNG. Removing it from the deny list does nothing for SearXNG and exposes a Grok-API-key-dependent tool.
- **Agent containers' `web_fetch` tool blocks private IPs** (SSRF guard). The SearXNG plugin uses its own HTTP client and bypasses this — but if you ever try to point `web_fetch` at `http://searxng:8080` directly, it will be rejected as `Blocked hostname or private/internal/special-use IP address`.

---

### Phase 3: Pyinfra Deploy Changes

#### 6.1 Changes to `infra/tasks/app_deploy.py`

Three additions:

1. **Create `searxng_data` directories** for both agents (owned by root or the container's internal user -- SearXNG runs as `searxng` user internally but the Docker image uses `FORCE_OWNERSHIP=true` to fix ownership on start).
2. **Seed `settings.yml`** with seed-once guard into each agent's `searxng_data` volume.
3. **Create Chaos's `searxng_data` directory** under `/opt/openclaw/chaos/`.

**New code to add after the Jarvis `openclaw_data` setup (after line 57 in current `app_deploy.py`):**

```python
# --- Jarvis SearXNG sidecar ---
jarvis_searxng_dir = f"{deploy_path}/searxng_data"

files.directory(
    name=f"Create {jarvis_searxng_dir}",
    path=jarvis_searxng_dir,
    user=deploy_user,
    group=deploy_user,
    mode="755",
)

jarvis_searxng_settings = f"{jarvis_searxng_dir}/settings.yml"
jarvis_searxng_settings_exists = host.get_fact(File, path=jarvis_searxng_settings)

if not jarvis_searxng_settings_exists:
    files.put(
        name="Seed Jarvis SearXNG settings.yml (first deploy only)",
        src="docker/searxng/settings.yml",
        dest=jarvis_searxng_settings,
        user=deploy_user,
        group=deploy_user,
        mode="644",
    )
```

**New code to add in the Chaos section (after the Chaos compose upload, around step 9):**

```python
# --- Chaos SearXNG sidecar ---
chaos_searxng_dir = f"{chaos_dir}/searxng_data"

files.directory(
    name=f"Create {chaos_searxng_dir}",
    path=chaos_searxng_dir,
    user=deploy_user,
    group=deploy_user,
    mode="755",
)

chaos_searxng_settings = f"{chaos_searxng_dir}/settings.yml"
chaos_searxng_settings_exists = host.get_fact(File, path=chaos_searxng_settings)

if not chaos_searxng_settings_exists:
    files.put(
        name="Seed Chaos SearXNG settings.yml (first deploy only)",
        src="docker/searxng/settings.yml",
        dest=chaos_searxng_settings,
        user=deploy_user,
        group=deploy_user,
        mode="644",
    )
```

**Seed-once guard rationale:**

- Unlike OpenClaw's `openclaw.json` (mode 600, uid 1000, unreadable by `overlord101`), the SearXNG `settings.yml` is in a directory owned by `deploy_user` at mode 755. The standard `host.get_fact(File, ...)` works correctly here -- no sentinel file needed.
- SearXNG does NOT self-manage its config (unlike OpenClaw). The seed-once guard is still useful because an operator may tune engines or settings on the server, and we don't want Pyinfra overwriting those changes.

#### 6.2 Server File Layout After Deploy

```
/opt/openclaw/
  .env                              # unchanged
  docker-compose.yml                # Jarvis + SearXNG (updated)
  openclaw_data/                    # Jarvis OpenClaw data (unchanged)
  searxng_data/                     # NEW: Jarvis SearXNG config volume
    settings.yml                    #   seeded from docker/searxng/settings.yml
  chaos/
    docker-compose.yml              # Chaos + SearXNG (updated)
    data/                           # Chaos OpenClaw data (unchanged)
    searxng_data/                   # NEW: Chaos SearXNG config volume
      settings.yml                  #   seeded from docker/searxng/settings.yml
```

#### 6.3 Deploy Sequence Impact

No changes to the deploy sequence structure. SearXNG containers are defined in the same compose files as their agents and are started by the existing `docker compose up -d` commands:

- **Jarvis + SearXNG**: `cd /opt/openclaw && docker compose up -d --remove-orphans` (existing Step 5)
- **Chaos + SearXNG**: `cd /opt/openclaw/chaos && docker compose --env-file ../.env up -d --remove-orphans` (existing Step 11)

Docker Compose handles the dependency ordering: SearXNG starts alongside the agent. If SearXNG is not yet ready when the agent issues its first search, the bundled `web-search` skill retries with backoff (configurable via `tools.web.search.timeoutSeconds`, default 30s). This is acceptable -- SearXNG cold-starts in <10s.

---

### Phase 4: Cleanup

#### 7.1 Remove `BRAVE_API_KEY` from Compose Files

Already shown in the Phase 1 diffs. The line `- BRAVE_API_KEY=${BRAVE_API_KEY:-}` is removed from both:

- `docker/docker-compose.yml:29` (Jarvis)
- `docker/chaos/docker-compose.yml:35` (Chaos)

#### 7.2 Update `.env.example`

```
# REMOVE or mark deprecated:
BRAVE_API_KEY=                           # From https://brave.com/search/api — free: 2000 queries/month

# REPLACE with:
# BRAVE_API_KEY is no longer used — SearXNG replaces Brave Search.
# SearXNG runs as a Docker sidecar with no API key required.
# To customize SearXNG, edit settings.yml on the server at:
#   Jarvis: /opt/openclaw/searxng_data/settings.yml
#   Chaos:  /opt/openclaw/chaos/searxng_data/settings.yml

# Optional: override the default SearXNG secret (used for CSRF signing).
# Not security-critical since SearXNG is not internet-facing.
SEARXNG_SECRET=                          # Generate: openssl rand -hex 32 (optional, defaults provided)
```

#### 7.3 Actual `.env` on Server

On the next deploy, the existing `BRAVE_API_KEY` value in `/opt/openclaw/.env` becomes orphaned (no compose file references it). It can be left in place harmlessly or cleaned up manually. No Pyinfra step is needed to remove it -- the env file is uploaded wholesale from the local `.env`.

---

## 5. Security Considerations

| Concern | Mitigation |
|---------|------------|
| **SearXNG exposed to the internet** | No host port mapping. SearXNG is only reachable via the Docker bridge network (container-to-container). UFW denies all inbound except SSH on port 2222. |
| **Container escape / privilege escalation** | `cap_drop: ALL`, `no-new-privileges:true`, `read_only: true`. Same posture as the OpenClaw containers. |
| **Resource exhaustion (CPU/memory)** | Hard limits: 0.5 CPU, 512M memory. Single uWSGI worker caps actual RSS at ~150MB. A runaway query cannot starve the OpenClaw agents. |
| **Outbound data exfiltration via search queries** | SearXNG sends queries to upstream engines (Google, Bing, etc.) over HTTPS. This is inherent to its function. Queries are stripped of tracking parameters and sent without cookies. UFW does not restrict outbound, which is correct -- blocking outbound HTTPS would break search, LLM calls, and Slack Socket Mode. |
| **SearXNG settings.yml tampering** | The `searxng_data` directory is mode 755, owned by `deploy_user`. Only `overlord101` (and root) can modify `settings.yml`. The SearXNG container reads it at startup; it cannot write back to it (read-only filesystem). |
| **Cross-agent search leakage** | Impossible. Each SearXNG instance runs on an isolated bridge network. `jarvis-searxng` is on `openclaw_net`; `chaos-searxng` is on `chaos_net`. Docker DNS names are scoped to the compose project -- Chaos cannot resolve `searxng` to Jarvis's instance. |
| **SEARXNG_SECRET exposure** | Used for CSRF token signing. Low risk since there is no web UI and no external access. Default values are provided in compose for convenience. Production can override via `.env` if desired. |
| **Logging / sensitive data in search queries** | SearXNG logs queries to stdout by default. Our logging config (`max-size: 10m, max-file: 3`) limits retention. OpenClaw's `logging.redactPatterns` redacts API keys in tool output but does NOT redact search queries -- this is by design (search queries are not secrets). |

---

## 6. Rollback Plan

If SearXNG causes issues (container crashes, search quality degradation, resource pressure), rollback is a compose-file revert:

### 6.1 Quick Rollback (< 2 minutes)

1. **Restore the pre-SearXNG compose files** from git:

   ```bash
   # On the local machine:
   git checkout HEAD~1 -- docker/docker-compose.yml docker/chaos/docker-compose.yml

   # Re-deploy:
   pyinfra infra/inventory.py infra/tasks/app_deploy.py
   ```

   This removes the `searxng` service definition and restores `BRAVE_API_KEY` to the environment. `docker compose up -d --remove-orphans` stops the orphaned SearXNG containers automatically.

2. **Re-add `BRAVE_API_KEY` to `.env`** if it was removed:

   ```bash
   # SSH to server:
   echo 'BRAVE_API_KEY=your-key-here' >> /opt/openclaw/.env
   ```

3. **Restart agents** to pick up the restored env:

   ```bash
   cd /opt/openclaw && docker compose up -d
   cd /opt/openclaw/chaos && docker compose --env-file ../.env up -d
   ```

### 6.2 What Stays Behind (Harmless)

- `searxng_data/` and `chaos/searxng_data/` directories remain on the server. They contain only `settings.yml` (~1KB). Can be removed manually if desired.
- `SEARXNG_SECRET` in `.env` is orphaned. Harmless.

### 6.3 What Does NOT Need Rollback

- No OpenClaw config changes to revert (we didn't touch `openclaw.json`).
- No `.env` structural changes (just one line added, one removed).
- No network changes (networks are compose-managed and auto-removed).
- No Pyinfra task ordering changes.

---

## 7. Open Questions

| # | Question | Impact | Resolution | Status |
|---|----------|--------|------------|--------|
| Q1 | **Should we pin the SearXNG image tag on first deploy?** Decision D8 says start with `latest`, then pin. The auto-update cron (`infra/tasks/auto_update.py`) currently only pulls the OpenClaw image. Do we want to add SearXNG to the nightly pull, or pin it immediately? | Low. SearXNG is mature and stable. Rolling updates are low-risk. | Decide after first deploy based on observed stability. | Open |
| Q2 | **Should `SEARXNG_SECRET` be a real secret in `.env`?** It's used for CSRF signing in a service with no UI and no external access. The default values in compose are functionally adequate. | Very low. CSRF is irrelevant when there's no browser interaction. | Keep defaults. Add to `.env` only if we ever expose the UI for debugging. | Open |
| Q3 | **Does the `web-search` skill need a container restart to detect `SEARXNG_BASE_URL`?** Environment variables are set at container start. If the agent is running and we add `SEARXNG_BASE_URL` for the first time, the skill won't see it until the container restarts. `docker compose up -d` with changed env triggers a recreate, so this should happen automatically. | None if deploying via Pyinfra (compose handles it). Edge case if someone manually edits `.env` without restarting. | No action needed. | Resolved |
| Q4 | **Engine tuning for Philippines region.** | Medium. Affects search quality. | **Resolved by OpenClaw expert (2026-04-10):** Brave disabled (scraping adapter unreliable without API key, redundant). Startpage enabled (proxies Google, works well from SEA). Final engine list: Google, Bing, DuckDuckGo, Startpage, Wikipedia. Tunable on server post-deploy. | Resolved |
| Q5 | **Should we add `depends_on` with `condition: service_healthy`?** | Low. Agent boot does not depend on search. | **Resolved by OpenClaw expert (2026-04-10):** Skip. OpenClaw's `web-search` tool handles unavailability gracefully — surfaces "temporarily unavailable" to users, no crash or stack trace. Adding `depends_on` would extend the already-long 2:32 cold-start gap. Let them boot in parallel. | Resolved |
| Q6 | **`wget` vs `curl` healthcheck inconsistency.** SearXNG uses `wget`, OpenClaw uses `curl`. | None. Cosmetic only. | **Resolved by OpenClaw expert (2026-04-10):** Each container uses what its image ships. `wget --spider --quiet` is functionally equivalent to `curl -sf`. Installing curl would require a custom Dockerfile, violating the stock-image convention. No change needed. | Resolved |

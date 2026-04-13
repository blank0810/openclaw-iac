# SearXNG Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a SearXNG sidecar to both Jarvis and Chaos, replacing Brave Search API.

**Architecture:** One SearXNG container per agent on their existing Docker bridge networks (`openclaw_net` / `chaos_net`). Agents discover SearXNG via hardcoded Docker DNS (`http://searxng:8080`). No Redis, no host port exposure.

**Tech Stack:** Docker Compose, SearXNG (`searxng/searxng:latest`), Pyinfra, OpenClaw `web-search` bundled skill.

**Design doc:** `docs/plans/2026-04-10-searxng-integration-design.md`

---

### Task 1: Create SearXNG settings.yml

**Files:**
- Create: `docker/searxng/settings.yml`

**Step 1: Create the directory and settings file**

```bash
mkdir -p docker/searxng
```

Write `docker/searxng/settings.yml`:

```yaml
# SearXNG settings for OpenClaw agents.
# Minimal config: JSON API only, single-user, no rate limiting.
# Seeded once by Pyinfra; edit on server to customize.

general:
  debug: false
  instance_name: "SearXNG (OpenClaw)"
  privacypolicy_url: false
  donation_url: false
  contact_url: false
  enable_metrics: false

server:
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

# Engine selection: Google, Bing, DDG, Startpage, Wikipedia.
# Brave disabled (scraping adapter unreliable without API key).
# Engines not listed retain SearXNG defaults (most disabled).
# Tunable on server post-deploy without redeploying.
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

**Step 2: Commit**

```bash
git add docker/searxng/settings.yml
git commit -m "feat(searxng): add SearXNG settings.yml base config"
```

---

### Task 2: Add SearXNG sidecar to Jarvis compose

**Files:**
- Modify: `docker/docker-compose.yml`

**Step 1: Remove `BRAVE_API_KEY` and add `SEARXNG_BASE_URL` to Jarvis environment**

In the `jarvis` service `environment:` block:
- Remove: `- BRAVE_API_KEY=${BRAVE_API_KEY:-}`
- Add after the `OPENAI_API_KEY` line: `- SEARXNG_BASE_URL=http://searxng:8080`

**Step 2: Add the `searxng` service block before `networks:`**

```yaml
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

**Step 3: Validate compose syntax**

Run: `docker compose -f docker/docker-compose.yml config --quiet`
Expected: exit 0, no output (valid)

**Step 4: Commit**

```bash
git add docker/docker-compose.yml
git commit -m "feat(searxng): add SearXNG sidecar to Jarvis compose, replace Brave"
```

---

### Task 3: Add SearXNG sidecar to Chaos compose

**Files:**
- Modify: `docker/chaos/docker-compose.yml`

**Step 1: Remove `BRAVE_API_KEY` and add `SEARXNG_BASE_URL` to Chaos environment**

In the `chaos` service `environment:` block:
- Remove: `- BRAVE_API_KEY=${BRAVE_API_KEY:-}`
- Add after the `OPENAI_API_KEY` line: `- SEARXNG_BASE_URL=http://searxng:8080`

**Step 2: Add the `searxng` service block before `networks:`**

```yaml
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
```

**Step 3: Validate compose syntax**

Run: `docker compose -f docker/chaos/docker-compose.yml config --quiet`
Expected: exit 0, no output (valid)

**Step 4: Commit**

```bash
git add docker/chaos/docker-compose.yml
git commit -m "feat(searxng): add SearXNG sidecar to Chaos compose, replace Brave"
```

---

### Task 4: Update Pyinfra deploy to seed SearXNG settings

**Files:**
- Modify: `infra/tasks/app_deploy.py:57` (after Jarvis openclaw.json seed)
- Modify: `infra/tasks/app_deploy.py:191` (after Chaos compose upload, before image pull)

**Step 1: Add Jarvis SearXNG directory + seed-once after line 57**

Insert after the Jarvis `openclaw.json` seed block (after `if not config_exists:` block):

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

**Step 2: Add Chaos SearXNG directory + seed-once after Step 9 (Chaos compose upload)**

Insert after the "Upload chaos/docker-compose.yml" block, before Step 10:

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

**Step 3: Validate Pyinfra syntax**

Run: `python -c "import ast; ast.parse(open('infra/tasks/app_deploy.py').read()); print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add infra/tasks/app_deploy.py
git commit -m "feat(searxng): add SearXNG settings seed-once to Pyinfra deploy"
```

---

### Task 5: Update .env.example — replace Brave with SearXNG docs

**Files:**
- Modify: `.env.example:24`

**Step 1: Replace the `BRAVE_API_KEY` line**

Replace:
```
BRAVE_API_KEY=                           # From https://brave.com/search/api — free: 2000 queries/month
```

With:
```
# BRAVE_API_KEY is no longer used — SearXNG replaces Brave Search.
# SearXNG runs as a Docker sidecar with no API key required.
# To customize SearXNG, edit settings.yml on the server at:
#   Jarvis: /opt/openclaw/searxng_data/settings.yml
#   Chaos:  /opt/openclaw/chaos/searxng_data/settings.yml
SEARXNG_SECRET=                          # Generate: openssl rand -hex 32 (optional, defaults provided)
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "chore(env): replace BRAVE_API_KEY with SearXNG docs in .env.example"
```

---

### Task 6: Final validation + summary commit

**Step 1: Validate both compose files**

Run: `docker compose -f docker/docker-compose.yml config --quiet && docker compose -f docker/chaos/docker-compose.yml config --quiet && echo "Both compose files valid"`
Expected: `Both compose files valid`

**Step 2: Validate Pyinfra syntax**

Run: `python -c "import ast; ast.parse(open('infra/tasks/app_deploy.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Review all changes**

Run: `git log --oneline -5`
Expected: 5 commits from Tasks 1-5

**Step 4: Verify file layout**

```bash
ls -la docker/searxng/settings.yml
```
Expected: file exists

---

## Post-Implementation Notes

- **Deploy to server:** `pyinfra infra/inventory.py infra/deploy.py` (pulls SearXNG image, seeds settings, starts containers)
- **Verify on server:** `docker ps` should show `jarvis-searxng` and `chaos-searxng` healthy
- **Test search:** DM Jarvis on Slack: "search for pyinfra documentation" — should use SearXNG instead of Brave
- **Rollback:** `git revert` the commits, redeploy, re-add `BRAVE_API_KEY` to `.env`

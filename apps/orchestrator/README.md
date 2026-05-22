# ZeroClaw Orchestrator

A FastAPI service that provisions ZeroClaw agents as hardened Docker
containers. `POST` an agent spec, it renders config to the host filesystem and
creates the container directly against the **local Docker daemon** via the
docker-py SDK — no SSH, no compose, no subprocess fan-out for per-agent creates.

Design: `docs/plans/2026-05-20-orchestrator-dockersdk-design.md`
Plan: `docs/plans/2026-05-20-orchestrator-dockersdk.md`

## Where it runs

The orchestrator runs **on the Docker host** (Server 3) as a systemd service,
bound to `127.0.0.1:8000`. It is **not** a local laptop tool — it provisions
against the host's own Docker socket.

It runs **as root**. Rationale: each create renders the agent's workspace to
`/opt/zeroclaw/states/<slug>/workspace` and must `chown` it to `65534:65534`
so the container (which runs as UID 65534 / `nobody`) can persist
`brain.db` and sessions. A non-root docker-group user cannot `chown`. Since
docker-group access is already root-equivalent, running as root is not
materially less secure and resolves ownership cleanly.

## Deploy

Deployed via Pyinfra from the operator laptop (bootstrap plane → SSH):

```bash
source .venv/bin/activate
pyinfra lib/inventory.py lib/deploy_orchestrator.py
```

This syncs `apps/`, `lib/`, `templates/`, `requirements.txt`, and
`zeroclawctl.py` to `/opt/zeroclaw-orchestrator`, builds a venv, installs
`requirements.txt`, renders the systemd unit, and enables/restarts the service.
Dry-run with `--dry` first to preview the plan.

> **Operator prerequisite — `agents/_defaults.toml`.** The orchestrator merges
> every new agent against `agents/_defaults.toml` (default LLM provider/model/
> api_key, etc.). Without it, a request-only create raises `KeyError` on
> `llm.model`. This file carries secrets, is gitignored, and is **never synced
> by the deploy**. Place it on the host yourself before the first create:
>
> ```bash
> scp agents/_defaults.toml \
>   overlord101@<host>:/opt/zeroclaw-orchestrator/agents/_defaults.toml
> # then on the host: chown root:root + chmod 600
> ```

> **Operator prerequisite — `.env`.** `load_config()` runs on every `POST` and
> hard-reads `SERVER_HOST` (and friends) from `.env` relative to the service's
> `WorkingDirectory` (`/opt/zeroclaw-orchestrator`). It carries secrets, is
> gitignored, and is **never synced by the deploy**. The systemd unit loads it
> via `EnvironmentFile=-/opt/zeroclaw-orchestrator/.env` (the `-` makes it
> optional, so the unit still starts without it — but every `POST` then 500s).
> Place a real `.env` on the host before the first create:
>
> ```bash
> scp .env overlord101@<host>:/opt/zeroclaw-orchestrator/.env
> # then on the host: chown root:root + chmod 600
> ```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness → `{"status": "ok"}` |
| `POST` | `/agents` | Submit spec → `202 {"job_id": "..."}`, provisions in background. `409` on duplicate slug (create already in flight) or an existing `zeroclaw-<slug>` container. |
| `GET` | `/jobs/{job_id}` | Poll → `{status, steps, result?, error?}`; `404` if unknown |

## Create an agent

> **Operator action.** `POST /agents` provisions a real container on the host —
> it mutates live state. The operator fires this, not automation (see memory
> `feedback-agent-creation-is-operator`).

Since the service binds `127.0.0.1`, curl it from the host (or over an SSH
tunnel: `ssh -L 8000:127.0.0.1:8000 overlord101@<host> -p <port>`):

```bash
curl -X POST localhost:8000/agents \
  -H 'content-type: application/json' \
  -d '{
    "name": "demo-bot",
    "display_name": "Demo",
    "slack": {"bot_token": "xoxb-...", "app_token": "xapp-..."},
    "composio": {"mcp_api_key": "ck_..."}
  }'
# → {"job_id": "a1b2c3..."}
```

A duplicate slug while a create is in flight, or an existing
`zeroclaw-demo-bot` container, returns `409`:

```bash
# → {"detail": "create already in flight for demo-bot"}    # in-flight
# → {"detail": "agent demo-bot already exists"}             # container exists
```

Poll until terminal (`succeeded` or `failed`):

```bash
curl localhost:8000/jobs/a1b2c3...
# running:
#   {"job_id":"...","status":"running","steps":[{"name":"render_config","status":"succeeded"},
#    {"name":"ensure_network","status":"running"}], "result":null}
# succeeded:
#   {"job_id":"...","status":"succeeded","result":{
#     "name":"demo-bot","container_name":"zeroclaw-demo-bot",
#     "server_ip":"<host>","host":"<host>","gateway_port":42617,"status":"running"}}
```

Provision steps: `render_config` → `ensure_network` → `pull_image` →
`run_container`. Each is tracked in the job's `steps`.

## Notes & limitations

- **Auth:** none. `verify_request` is a no-op dependency seam — swap for
  Firebase JWT verification when the mobile/auth layer lands.
- **Job store:** in-memory, single uvicorn worker. Jobs are lost on restart;
  job state is mutated from a background task and read by the request thread —
  fine single-worker, would need a lock / shared store for multi-worker.
- **Docker client:** resolved via `docker.from_env` against the local socket,
  injected through `app.state.docker_client_factory` so tests pass a fake.
- **LLM defaults:** `provider`/`model` in the request body override per-agent;
  everything unset inherits from `agents/_defaults.toml` via `lib.config`'s deep
  merge.
- **Where secrets land (important):** only the LLM provider key is env-only —
  it flows to docker-py as `ZEROCLAW_API_KEY` and never appears in
  `config.toml`. **Slack tokens and the Composio MCP key ARE rendered into
  `config.toml`** because upstream ZeroClaw has no env-read path for them. That
  is exactly why the rendered `config.toml` is `chmod 0640` + chowned to
  `65534:65534` (so only the container user can read it). See `SECURITY.md §5`.
- **No delete/update endpoints, no rollback** on partial failure. A failed
  provision leaves whatever state was rendered/created; clean up via
  `zeroclawctl` or `docker`.
- Every test injects a fake docker client — the suite never contacts a real
  daemon, socket, or server.

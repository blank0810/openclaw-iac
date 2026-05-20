# ZeroClaw Orchestrator (local MVP)

A local FastAPI service that wraps the `zeroclawctl` Pyinfra pipeline behind an
HTTP API. POST an agent spec, it runs `agents create` → `server deploy` →
`agents deploy` as background subprocesses and reports the provisioned result.

Design: `docs/plans/2026-05-20-orchestrator-api-design.md`
Plan: `docs/plans/2026-05-20-orchestrator-api.md`

## Run

```bash
source .venv/bin/activate
uvicorn apps.orchestrator.main:create_app --factory --reload --port 8000
```

Launch from the repo root. The pipeline shells out to the project's
`zeroclawctl.py` (resolved to an absolute path, so cwd doesn't matter for the
subprocess, but `load_config()` reads `./.env` relative to cwd).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness → `{"status": "ok"}` |
| `POST` | `/agents` | Submit spec → `202 {"job_id": "..."}`, runs pipeline in background |
| `GET` | `/jobs/{job_id}` | Poll → `{status, steps, result?, error?}`; `404` if unknown |

## Create an agent

> **Operator action.** `POST /agents` runs the real Pyinfra deploy against the
> host in `.env` — it creates a real agent and mutates the live server. The
> operator fires this, not automation (see memory `feedback-agent-creation-is-operator`).

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

Poll until terminal (`succeeded` or `failed`):

```bash
curl localhost:8000/jobs/a1b2c3...
# running:
#   {"job_id":"...","status":"running","steps":[{"name":"create","status":"succeeded"},
#    {"name":"server_deploy","status":"running"}], "result":null}
# succeeded:
#   {"job_id":"...","status":"succeeded","result":{
#     "name":"demo-bot","container_name":"zeroclaw-demo-bot",
#     "server_ip":"<host>","host":"<host>","gateway_port":42617,"status":"running"}}
```

## Notes & limitations (local MVP)

- **Auth:** none. `verify_request` is a no-op dependency seam — swap for
  Firebase JWT verification when the mobile/auth layer lands.
- **Job store:** in-memory, single uvicorn worker. Jobs are lost on restart;
  job state is mutated from a background task and read by the request thread —
  fine single-worker, would need a lock / shared store for multi-worker.
- **LLM:** `provider`/`model` in the request body are accepted by the schema
  but not yet wired to `agents create` flags — they inherit from
  `agents/_defaults.toml`.
- **No delete/update endpoints, no rollback** on partial failure. A failed
  deploy leaves whatever the pipeline produced; re-POST or clean up via
  `zeroclawctl`.
- Every test mocks `subprocess` — the suite never contacts the live server.

# ZeroClaw Orchestrator API — Design

**Date:** 2026-05-20
**Status:** Validated, ready for implementation plan
**Scope:** Local MVP — a FastAPI service that wraps the existing `zeroclawctl`
Pyinfra pipeline behind an HTTP API. POST an agent spec, it provisions the
agent on the live Docker host and returns the provisioned details.

This is the first slice of the larger multi-tenant platform
(`docs/plans/2026-05-11-multi-tenant-iac*.md`). It deliberately builds **only**
the Orchestrator box from that diagram — no Firebase, no Traefik, no mobile
app, no multi-host. Those come later behind clear seams left in this design.

## Goal

Replace "operator runs `zeroclawctl` in a terminal" with "client POSTs JSON,
the same pipeline runs server-side." The Orchestrator's engine **is** the
existing `lib/` + `zeroclawctl.py` code — the API just triggers it.

## Architecture

```
client (curl / Postman)
   │  POST /agents {name, display_name, slack, composio, llm}
   ▼
FastAPI (apps/orchestrator) ──202──► {job_id}
   │  background task
   ▼
pipeline.py  ── subprocess ──► python zeroclawctl.py agents create ...
                            ──► python zeroclawctl.py server deploy
                            ──► python zeroclawctl.py agents deploy --name X
   │
   ▼  (engine = lib/ + Pyinfra/Docker, unchanged)
Docker host (Server 3)  ── container zeroclaw-<slug> running
   │
client polls GET /jobs/{job_id} ──► {status, steps, result}
```

Key decision: the pipeline runs as **subprocesses**, not in-process. Pyinfra
needs `gevent.monkey.patch_all()`, which conflicts with FastAPI's asyncio
loop. Shelling out to `zeroclawctl.py` keeps the gevent patching isolated in
child processes.

## Components

```
apps/orchestrator/
├── main.py        # FastAPI app + endpoints + (no-op) auth dependency seam
├── models.py      # Pydantic request/response models
├── jobs.py        # in-memory job store + JobState + background runner
├── pipeline.py    # subprocess wrapper: create → server deploy → agent deploy
└── tests/
    └── test_api.py  # mocks subprocess; no live server contact
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/agents` | Submit spec → `202 {job_id}`, kicks off background pipeline |
| `GET` | `/jobs/{job_id}` | Poll → `{status, steps, result?, error?}`; `404` if unknown |
| `GET` | `/health` | Liveness |

**Auth:** none for the MVP. A `verify_request` FastAPI dependency exists as a
no-op so the Firebase-JWT layer is a one-line swap later.

## Request / response models

```python
class SlackSpec(BaseModel):
    bot_token: str
    app_token: str
    channel_id: str | None = None

class ComposioSpec(BaseModel):
    mcp_api_key: str | None = None

class LlmSpec(BaseModel):
    provider: str | None = None
    model: str | None = None

class CreateAgentRequest(BaseModel):
    name: str                       # validated against lib.config.SLUG_PATTERN
    display_name: str | None = None
    slack: SlackSpec | None = None
    composio: ComposioSpec | None = None
    llm: LlmSpec | None = None

class AgentResult(BaseModel):
    name: str
    container_name: str             # f"zeroclaw-{slug}"
    server_ip: str                  # from load_config().server_host
    host: str                       # == server_ip for now (single host)
    gateway_port: int               # 42617 internal; host_port if exposed
    status: str                     # parsed from docker compose ps
```

Anything omitted in the request inherits from `agents/_defaults.toml`.

## Job lifecycle

```
queued → running(create) → running(server_deploy) → running(agent_deploy) → succeeded
                                                                          ↘ failed (any step)
```

`JobState` records per-step status + captured stderr:

```json
{
  "job_id": "uuid",
  "status": "running|succeeded|failed",
  "steps": [
    {"name": "create",        "status": "succeeded"},
    {"name": "server_deploy", "status": "running"},
    {"name": "agent_deploy",  "status": "queued"}
  ],
  "result": null,
  "error": null
}
```

**Store:** in-memory dict (`job_id → JobState`). Single uvicorn worker for the
MVP. Lost on restart — acceptable locally. Swappable for SQLite later; the
store interface stays the same.

## The pipeline (`pipeline.py`)

Background task runs three subprocesses in order, short-circuiting on the
first non-zero exit:

1. `zeroclawctl agents create --name <slug> --display-name <dn>
   --slack-bot-token … --slack-app-token … [--slack-channel-id …]
   [--composio-mcp-key …]`
2. `zeroclawctl server deploy` (renders compose w/ the new agent + dirs)
3. `zeroclawctl agents deploy --name <slug>` (ups the container)

Each via `subprocess.run([...], capture_output=True, text=True)`. On success,
a final `docker compose ps --format json` (over SSH, reusing the key from
`.env`) populates `AgentResult.status`. `server_ip` / `container_name` /
`gateway_port` are derived from `load_config()` + the slug.

## Error handling

| Failure | Behavior |
|---|---|
| Bad slug / malformed body | `422` at validation, before any subprocess |
| Duplicate slug | step 1 non-zero → job `failed`, "agent already exists" |
| `server deploy` Pyinfra failure | job `failed`, that step's stderr captured |
| `agent deploy` / docker failure | job `failed`, error notes partial state |
| SSH/network down | subprocess stderr captured; job `failed` |

No automatic rollback in the MVP — a failed deploy leaves whatever the
pipeline produced; re-POST or clean up manually.

## Testing (TDD, mocked — no live server)

- `test_api.py` monkeypatches `subprocess.run` so tests never SSH or create
  real agents.
- Cases: valid POST → `202 {job_id}`; bad slug → `422`; job transitions
  queued→running→succeeded; a failing step flips to `failed` with captured
  stderr; `GET /jobs/{unknown}` → `404`; result matches `AgentResult` schema.
- The background runner is injected with a synchronous executor in tests so
  final job state is deterministic.

## Create-boundary (operator policy)

Building this API is the requested feature. But end-to-end verification will
**not** fire a real `POST /agents` against the live server (that would
autonomously create a real agent + mutate live infra). Verification = mocked
tests + a dry path; the operator fires the first real POST themselves.
See memory `feedback-agent-creation-is-operator`.

## Explicitly out of scope (YAGNI for this slice)

- Firebase auth / JWT verification (seam left: `verify_request` no-op)
- Traefik routing
- Multi-host scheduling (single host from `.env`)
- Object-storage backups
- Persistent job store / HA
- Delete / update agent endpoints (add when needed)
- Automatic rollback

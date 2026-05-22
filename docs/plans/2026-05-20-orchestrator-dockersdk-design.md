# Orchestrator Re-architecture: Server-Side + Docker SDK — Design

**Date:** 2026-05-20
**Status:** Validated, ready for implementation plan
**Supersedes:** the provisioning engine of `docs/plans/2026-05-20-orchestrator-api-design.md`
(the API surface is kept; the subprocess→SSH→compose engine is replaced).

## Goal

Move the orchestrator **onto the Docker host** and have it provision agents
**directly via the Docker SDK (docker-py)** against the local daemon socket,
instead of shelling out to `zeroclawctl` over SSH and rendering a shared
`docker-compose.yml`. This matches the architecture diagram (Orchestrator is a
server-side box) and eliminates the shared-compose-file concurrency race.

## Why (decision record)

- **Concurrency:** per-container creates against distinct `states/<slug>/` dirs
  and distinct `zc-<slug>` networks have no shared mutable file to clobber. The
  Docker daemon handles parallel container creation natively. (See the
  compose-clobber race in the previous design's concurrency analysis.)
- **Diagram fidelity:** the Orchestrator runs on Hetzner, talks to the local
  daemon — no Docker API exposed over the network.
- **Simpler runtime path:** server-side means config is written to the local
  filesystem (no SCP), and there's no `server deploy` per create.

Trade-off accepted: container hardening moves from compose YAML into docker-py
kwargs (single-source-of-truth loss); mitigated by one central
`build_container_spec()` + tests asserting every hardening flag.

## Two planes

```
BOOTSTRAP plane (operator laptop → Pyinfra/SSH → host)   — occasional
  installs Docker, deploy user, hardening, /opt/zeroclaw dirs,
  AND deploys the orchestrator itself (venv + systemd unit).

RUNTIME plane (orchestrator ON host → docker-py local socket)  — frequent
  POST /agents → render config locally → ensure network → pull image →
  run container → report status.  No SSH, no SCP, no compose file.
```

## Security posture

- Orchestrator runs as a **systemd service** (not containerized), user in the
  `docker` group. Root-equivalent via docker group (unavoidable for any
  Docker control plane) but no container-escape surface and no mounted socket.
- The daemon socket is **never exposed over the network** — local only.
- `verify_request` no-op auth seam stays (Firebase JWT later). Note: once this
  API is internet-facing, that seam MUST be filled before exposure — the
  process can create/destroy containers as root-equivalent.

## Component layout

```
apps/orchestrator/
  models.py        # REUSED: CreateAgentRequest, AgentResult, JobState, StepState
  jobs.py          # REUSED + per-slug in-flight guard
  main.py          # REUSED API surface: /health, POST /agents, GET /jobs/{id}
  provisioner.py   # NEW: docker-py engine (replaces pipeline.py's subprocess path)
  config_render.py # NEW: render config.toml + workspace to a local dir (factored
                   #      out of lib/agents.py so both CLI + orchestrator share it)
infra/ (Pyinfra)
  deploy_orchestrator.py  # NEW: venv + systemd unit on the host
templates/
  systemd/zeroclaw-orchestrator.service.j2  # NEW
```

`pipeline.py` (subprocess→zeroclawctl) is removed from the orchestrator's
runtime path. `zeroclawctl` + `lib/agents.py` SSH/compose code remain for
operator/manual use and host bootstrap, but the orchestrator no longer calls
them.

## The provisioning engine (`provisioner.py`)

`provision_agent(req)` runs these steps, tracked in the job's `steps[]`:

1. **render_config** — render `config.toml` + the 7 workspace `.md` files from
   `req` + server-side `_defaults.toml` + templates, write to
   `/opt/zeroclaw/states/<slug>/{.zeroclaw/config.toml, workspace/*}` with the
   right ownership (65534 for container-read paths). Reuses the Jinja +
   `managed_policy` + `config_patch` logic, factored into `config_render.py`.
   The LLM/env values (`ZEROCLAW_API_KEY`, provider/model) are built by
   `build_agent_env` and passed to docker-py as `environment=` directly — no
   `zeroclaw.env` file needed in the SDK model. Slack/Composio secrets remain
   in the mounted `config.toml` (upstream reads them there).
2. **ensure_network** — `client.networks.create(f"zc-{slug}", driver="bridge")`,
   idempotent (skip if it exists).
3. **pull_image** — `client.images.pull(image)`.
4. **run_container** — `client.containers.run(**build_container_spec(req))`,
   `detach=True`.
5. **result** — read `container.status`; build `AgentResult`.

### `build_container_spec()` — the load-bearing hardening map

Every compose flag → docker-py kwarg (this table is the spec; tests assert each):

| Compose | docker-py kwarg |
|---|---|
| `image` | `image=<image>` |
| `container_name: zeroclaw-<slug>` | `name=f"zeroclaw-{slug}"` |
| `restart: unless-stopped` | `restart_policy={"Name": "unless-stopped"}` |
| `environment` + env values | `environment=build_agent_env(agent)` (+ `ZEROCLAW_WORKSPACE`) |
| `volumes` (config.toml :ro, workspace) | `volumes={host: {"bind": ctr, "mode": "ro"/"rw"}}` |
| `read_only: true` | `read_only=True` |
| `tmpfs: /tmp:...` | `tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"}` |
| `cap_drop: [ALL]` | `cap_drop=["ALL"]` |
| `no-new-privileges:true` | `security_opt=["no-new-privileges:true"]` |
| `user: "65534:65534"` | `user="65534:65534"` |
| `networks: zc-<slug>` | `network=f"zc-{slug}"` |
| `cpus: "1.0"` | `nano_cpus=1_000_000_000` |
| `memory: 512M` | `mem_limit="512m"` |
| `pids: 256` | `pids_limit=256` |
| `ulimits nofile 1024/2048` | `ulimits=[Ulimit(name="nofile", soft=1024, hard=2048)]` |
| `logging json-file 10m/5` | `log_config=LogConfig(type="json-file", config={"max-size":"10m","max-file":"5"})` |
| `ports 127.0.0.1:<hp>:42617` (if hp) | `ports={"42617/tcp": ("127.0.0.1", hp)}` |

## Concurrency model

- **Parallel creates allowed.** Distinct slugs → distinct dirs/networks/
  containers; the daemon serializes its own internals. No global lock.
- **Per-slug in-flight guard** in `JobStore`: reject (or return the existing
  job) if a create for that slug is already running, OR if a container named
  `zeroclaw-<slug>` already exists. Prevents double-submit races on one agent.
- Single uvicorn worker still assumed (in-memory job store). Multi-worker /
  shared store is out of scope.

## Orchestrator self-deployment (Pyinfra)

`infra/deploy_orchestrator.py`:
- sync repo/package to `/opt/zeroclaw-orchestrator/`
- create venv, `pip install` (fastapi, uvicorn, docker, pydantic, jinja2, tomli)
- render + enable `zeroclaw-orchestrator.service` (uvicorn, user in docker group,
  binds localhost:8000 — fronted by Traefik later)
- restart on deploy

## Error handling

| Failure | Behavior |
|---|---|
| Bad slug / body | `422` at API validation |
| Duplicate slug (in-flight or container exists) | `409` (or return existing job) |
| docker-py `APIError`/`ImageNotFound`/`NetworkError` | step → `failed`, error captured; job terminal `failed` |
| Any unexpected exception in provision | caught → `store.fail()` (terminal), never strands a job |
| Container starts but unhealthy | `result.status` reflects it; job still `succeeded` (provisioned ≠ healthy) |

No automatic rollback for the MVP; a failed provision may leave a network or
partial state — note it in the error.

## Testing (TDD, fully mocked — no real daemon)

- Inject a fake docker client (`client.networks.create`, `images.pull`,
  `containers.run`, `container.status`) — assert `build_container_spec()`
  produces every hardening kwarg exactly; assert step order + failure
  short-circuit; assert unexpected exception → terminal `failed`.
- `config_render.py`: render to a `tmp_path`, assert config.toml has the
  upstream blocks + secrets, workspace `.md` rendered, no `ZEROCLAW_API_KEY`
  in config.toml.
- Per-slug guard: second create while first in-flight → `409`/existing job.
- API: reuse existing tests; swap the pipeline stub for the provisioner stub.
- No test imports a real docker socket or hits a real daemon.

## What's reused / reworked / removed

- **Reused:** `models.py`, `jobs.py` (+ guard), `main.py` API surface, the
  Jinja templates + `managed_policy` + `config_patch` + `build_agent_env`.
- **Reworked:** rendering factored into `config_render.py`; `pipeline.py`
  replaced by `provisioner.py` (docker-py).
- **Removed (from orchestrator runtime):** subprocess→zeroclawctl, SSH/SCP,
  shared `docker-compose.yml`, per-create `server deploy`.

## Out of scope (YAGNI)

- Multi-host placement/scheduling (single host)
- Firebase JWT (seam left)
- Traefik routing (orchestrator binds localhost; proxy later)
- Delete/update/restore endpoints (add when needed)
- Shared/persistent job store, multi-worker
- Automatic rollback
- The chat client (separate design; unaffected — pure API consumer)

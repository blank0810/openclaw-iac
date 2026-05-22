# Orchestrator Docker-SDK Re-architecture — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to implement this plan task-by-task.

**Goal:** Replace the orchestrator's subprocess→SSH→compose engine with a server-side docker-py provisioner that renders config to the local filesystem and creates each agent's container directly against the local Docker daemon.

**Architecture:** The orchestrator runs on the Docker host as a systemd service. `POST /agents` → render config locally → ensure per-agent bridge network → pull image → `client.containers.run(...)` → report status. Per-container creates make concurrent provisioning safe; a per-slug guard blocks double-submit. The API surface (`models.py`, `jobs.py`, `main.py`) is reused; `pipeline.py` is replaced by `provisioner.py`; rendering is factored into `config_render.py`.

**Tech Stack:** docker (docker-py SDK), FastAPI, Pydantic v2, Jinja2, pytest. Reuses `lib/` rendering (`config.toml.j2`, `templates/workspace/*.j2`, `managed_policy`, `config_patch`, `build_agent_env`).

**Design doc:** `docs/plans/2026-05-20-orchestrator-dockersdk-design.md`

---

## ⚠️ DESIGN REFINEMENT TO CONFIRM BEFORE EXECUTING

The design said "systemd service, user in docker group." Implementation needs
the orchestrator to **`chown` per-agent workspace dirs to `65534`** at runtime
(so the container can persist `brain.db`/sessions). A non-root docker-group user
**cannot chown**. Resolution in this plan: **run the systemd unit as `root`**.
This is not materially less secure (docker-group access is already
root-equivalent), and it resolves ownership cleanly. If you object, the
alternative is a per-create `docker run --rm alpine chown` shim — uglier. **Veto
here at plan-review if you want the shim instead.**

---

## Conventions

- TDD: failing test → run (fail) → minimal impl → run (pass) → commit.
- **No test touches a real Docker daemon, real socket, or real server.** The
  docker client is always injected as a fake/mock.
- Work from repo root with `source .venv/bin/activate`.

---

## Phase 0 — Dependency

### Task 0.1: Add docker SDK

**Files:** Modify `requirements.txt`

**Step 1:** Append:
```
docker>=7,<8
```

**Step 2:** `source .venv/bin/activate && pip install -r requirements.txt`
Expected: `docker` installed.

**Step 3:** Commit:
```bash
git add requirements.txt
git commit -m "chore(orchestrator): add docker SDK dependency"
```

---

## Phase 1 — Factor config rendering (`config_render.py`)

### Task 1.1: `render_agent_config` writes config.toml + workspace + returns env

**Files:**
- Create: `apps/orchestrator/config_render.py`
- Test: `apps/orchestrator/tests/test_config_render.py`

**Context:** Today `lib/agents.py::cmd_deploy` renders `config.toml` (via `config.toml.j2` + `default_exec_deny_patterns()`), renders workspace `.md` from `templates/workspace/*.j2`, and injects the managed policy block into `AGENTS.md`. We factor that into one reusable function that writes to a **local** dir (the orchestrator runs on the host, so this IS the real state dir) and returns the env dict for docker-py. No SSH, no SCP, no `zeroclaw.env` file (env goes to docker-py as a dict).

**Step 1: Write failing tests:**
```python
from pathlib import Path
from apps.orchestrator.config_render import render_agent_config
from tests.test_config import _write_env, _write_agent  # existing helpers
from lib.config import load_config


def _agent(tmp_path):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")  # writes agents/acme/agent.toml
    return load_config(tmp_path).agents[0]


def test_render_writes_config_toml_in_zeroclaw_subdir(tmp_path):
    agent = _agent(tmp_path)
    state = tmp_path / "state"
    render_agent_config(agent, state, project_root=tmp_path)
    cfg = (state / ".zeroclaw" / "config.toml").read_text()
    assert "schema_version = 2" in cfg
    assert "[autonomy]" in cfg


def test_render_writes_workspace_markdowns(tmp_path):
    agent = _agent(tmp_path)
    state = tmp_path / "state"
    render_agent_config(agent, state, project_root=tmp_path)
    ws = state / "workspace"
    assert (ws / "IDENTITY.md").exists()
    assert (ws / "AGENTS.md").exists()


def test_render_injects_policy_block_into_agents_md(tmp_path):
    agent = _agent(tmp_path)
    state = tmp_path / "state"
    render_agent_config(agent, state, project_root=tmp_path)
    agents_md = (state / "workspace" / "AGENTS.md").read_text()
    assert "BEGIN MANAGED SECURITY POLICY" in agents_md


def test_render_returns_env_with_zeroclaw_api_key(tmp_path):
    agent = _agent(tmp_path)  # _write_agent sets an anthropic key
    env = render_agent_config(agent, tmp_path / "state", project_root=tmp_path)
    assert env["ZEROCLAW_PROVIDER"] == agent.llm.provider
    assert "ZEROCLAW_API_KEY" in env  # only when api_key present


def test_render_no_llm_key_in_config_toml(tmp_path):
    agent = _agent(tmp_path)
    state = tmp_path / "state"
    render_agent_config(agent, state, project_root=tmp_path)
    cfg = (state / ".zeroclaw" / "config.toml").read_text()
    assert agent.llm.api_key not in cfg  # env-only
```

**Step 2: Run, expect fail (ImportError).**

**Step 3: Implement** `config_render.py`:
```python
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from lib.agent_env import build_agent_env
from lib.config import AgentDefinition
from lib.config_patch import default_exec_deny_patterns
from lib.managed_policy import build_policy_block, inject_policy_block

_WORKSPACE_TEMPLATES = (
    "AGENTS.md.j2", "BOOTSTRAP.md.j2", "HEARTBEAT.md.j2", "IDENTITY.md.j2",
    "SOUL.md.j2", "TOOLS.md.j2", "USER.md.j2",
)


def _env(project_root: Path) -> Environment:
    paths = [str(project_root / "templates")]
    repo = Path(__file__).resolve().parents[2] / "templates"
    if str(repo) not in paths:
        paths.append(str(repo))
    return Environment(loader=FileSystemLoader(paths))


def render_agent_config(
    agent: AgentDefinition, state_dir: Path, *, project_root: Path | None = None
) -> dict[str, str]:
    """Render config.toml + workspace markdowns into state_dir, inject the
    managed policy block into AGENTS.md, and return the env dict for the
    container. Local filesystem only (orchestrator runs on the host)."""
    project_root = project_root or Path.cwd()
    jenv = _env(project_root)
    zc = state_dir / ".zeroclaw"
    ws = state_dir / "workspace"
    zc.mkdir(parents=True, exist_ok=True)
    ws.mkdir(parents=True, exist_ok=True)

    config_text = jenv.get_template("config.toml.j2").render(
        agent=agent, exec_deny_patterns=default_exec_deny_patterns()
    )
    (zc / "config.toml").write_text(config_text)

    for name in _WORKSPACE_TEMPLATES:
        try:
            tmpl = jenv.get_template(f"workspace/{name}")
        except Exception:
            continue
        (ws / name[: -len(".j2")]).write_text(tmpl.render(agent=agent))

    agents_md = ws / "AGENTS.md"
    if agents_md.exists():
        policy = build_policy_block(
            agent.policy.require_approval_for, agent.policy.denied_domains
        )
        agents_md.write_text(inject_policy_block(agents_md.read_text(), policy))

    return build_agent_env(agent)
```

**Step 4: Run, expect pass.**

**Step 5: Commit:**
```bash
git add apps/orchestrator/config_render.py apps/orchestrator/tests/test_config_render.py
git commit -m "feat(orchestrator): factor local config rendering"
```

---

## Phase 2 — `build_container_spec` (the hardening map)

### Task 2.1: Pure function mapping an agent → docker-py kwargs

**Files:**
- Create: `apps/orchestrator/provisioner.py`
- Test: `apps/orchestrator/tests/test_container_spec.py`

**Step 1: Write failing tests** (assert every hardening kwarg):
```python
from apps.orchestrator.provisioner import build_container_spec
from tests.test_config import _write_env, _write_agent
from lib.config import load_config


def _agent(tmp_path):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    return load_config(tmp_path).agents[0]


def test_spec_core_identity(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(agent, env={"ZEROCLAW_PROVIDER": "anthropic"},
                                state_dir="/opt/zeroclaw/states/acme",
                                image="img:1")
    assert spec["name"] == "zeroclaw-acme"
    assert spec["image"] == "img:1"
    assert spec["detach"] is True


def test_spec_hardening_flags(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(agent, env={}, state_dir="/s", image="i")
    assert spec["read_only"] is True
    assert spec["cap_drop"] == ["ALL"]
    assert spec["security_opt"] == ["no-new-privileges:true"]
    assert spec["user"] == "65534:65534"
    assert spec["tmpfs"] == {"/tmp": "rw,noexec,nosuid,size=64m"}
    assert spec["mem_limit"] == "512m"
    assert spec["pids_limit"] == 256
    assert spec["nano_cpus"] == 1_000_000_000
    assert spec["restart_policy"] == {"Name": "unless-stopped"}
    assert spec["network"] == "zc-acme"


def test_spec_volumes(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(agent, env={}, state_dir="/opt/zeroclaw/states/acme", image="i")
    vols = spec["volumes"]
    assert vols["/opt/zeroclaw/states/acme/.zeroclaw/config.toml"] == {
        "bind": "/zeroclaw-data/.zeroclaw/config.toml", "mode": "ro"}
    assert vols["/opt/zeroclaw/states/acme/workspace"] == {
        "bind": "/zeroclaw-data/workspace", "mode": "rw"}


def test_spec_env_passed_through(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(agent, env={"ZEROCLAW_API_KEY": "sk-x"},
                                state_dir="/s", image="i")
    assert spec["environment"]["ZEROCLAW_API_KEY"] == "sk-x"


def test_spec_ports_only_when_host_port(tmp_path):
    agent = _agent(tmp_path)
    spec = build_container_spec(agent, env={}, state_dir="/s", image="i")
    assert "ports" not in spec or spec.get("ports") in (None, {})
    # with a host_port set, expect 127.0.0.1 binding (re-create agent w/ host_port
    # via a second fixture if _write_agent supports it; otherwise assert the
    # no-port path only).
```

**Step 2: Run, expect fail.**

**Step 3: Implement** `build_container_spec` in `provisioner.py`:
```python
from __future__ import annotations

from docker.types import LogConfig, Ulimit

from lib.config import AgentDefinition

GATEWAY_PORT = 42617
_CONTAINER_DATA = "/zeroclaw-data"


def build_container_spec(
    agent: AgentDefinition, *, env: dict, state_dir: str, image: str
) -> dict:
    spec = {
        "image": image,
        "name": f"zeroclaw-{agent.name}",
        "detach": True,
        "environment": env,
        "read_only": True,
        "tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"},
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "user": "65534:65534",
        "mem_limit": "512m",
        "pids_limit": 256,
        "nano_cpus": 1_000_000_000,
        "restart_policy": {"Name": "unless-stopped"},
        "network": f"zc-{agent.name}",
        "ulimits": [Ulimit(name="nofile", soft=1024, hard=2048)],
        "log_config": LogConfig(type="json-file",
                                config={"max-size": "10m", "max-file": "5"}),
        "volumes": {
            f"{state_dir}/.zeroclaw/config.toml": {
                "bind": f"{_CONTAINER_DATA}/.zeroclaw/config.toml", "mode": "ro"},
            f"{state_dir}/workspace": {
                "bind": f"{_CONTAINER_DATA}/workspace", "mode": "rw"},
        },
    }
    if agent.host_port:
        spec["ports"] = {f"{GATEWAY_PORT}/tcp": ("127.0.0.1", agent.host_port)}
    return spec
```

**Step 4: Run, expect pass.**

**Step 5: Commit:**
```bash
git add apps/orchestrator/provisioner.py apps/orchestrator/tests/test_container_spec.py
git commit -m "feat(orchestrator): build_container_spec hardening map"
```

---

## Phase 3 — `provision_agent` (docker-py engine, fake client)

### Task 3.1: provision flow with injected client

**Files:**
- Modify: `apps/orchestrator/provisioner.py`
- Test: `apps/orchestrator/tests/test_provisioner.py`

**Context:** `provision_agent` runs render → ensure_network → pull_image →
run_container → status, tracking each in the job store. The docker client is
injected so tests use a fake. Reuses `JobStore` (start_step/finish_step/succeed/
fail) and `render_agent_config`. State dir is `/opt/zeroclaw/states/<state_dir>`;
in tests, override the base via a param so it writes to tmp_path.

**Step 1: Write failing tests** (fake docker client):
```python
import types
from pathlib import Path

from apps.orchestrator.jobs import JobStore
from apps.orchestrator.provisioner import provision_agent
from tests.test_config import _write_env, _write_agent
from lib.config import load_config


class _FakeContainer:
    status = "running"

class _FakeContainers:
    def __init__(self): self.run_kwargs = None
    def run(self, **kw): self.run_kwargs = kw; return _FakeContainer()

class _FakeNetworks:
    def __init__(self): self.created = []
    def list(self, names=None): return []
    def create(self, name, **kw): self.created.append(name)

class _FakeImages:
    def __init__(self): self.pulled = []
    def pull(self, image): self.pulled.append(image)

class _FakeClient:
    def __init__(self):
        self.containers = _FakeContainers()
        self.networks = _FakeNetworks()
        self.images = _FakeImages()


def _agent(tmp_path):
    _write_env(tmp_path); _write_agent(tmp_path, "acme")
    return load_config(tmp_path).agents[0]


def test_provision_success(tmp_path):
    agent = _agent(tmp_path)
    store = JobStore(); job = store.create()
    client = _FakeClient()
    provision_agent(client, store, job.job_id, agent,
                    image="img:1", states_base=tmp_path / "states",
                    project_root=tmp_path, server_ip="1.2.3.4")
    final = store.get(job.job_id)
    assert final.status == "succeeded"
    assert final.result.container_name == "zeroclaw-acme"
    assert final.result.server_ip == "1.2.3.4"
    assert client.networks.created == ["zc-acme"]
    assert client.images.pulled == ["img:1"]
    assert client.containers.run_kwargs["name"] == "zeroclaw-acme"
    # config rendered to the state dir
    assert (tmp_path / "states" / "acme" / ".zeroclaw" / "config.toml").exists()


def test_provision_unexpected_error_marks_failed(tmp_path):
    agent = _agent(tmp_path)
    store = JobStore(); job = store.create()
    client = _FakeClient()
    def boom(**kw): raise RuntimeError("daemon down")
    client.containers.run = boom
    provision_agent(client, store, job.job_id, agent, image="i",
                    states_base=tmp_path / "states", project_root=tmp_path,
                    server_ip="1.2.3.4")
    final = store.get(job.job_id)
    assert final.status == "failed"
    assert "daemon down" in final.error


def test_provision_skips_existing_network(tmp_path):
    agent = _agent(tmp_path)
    store = JobStore(); job = store.create()
    client = _FakeClient()
    client.networks.list = lambda names=None: [object()]  # already exists
    provision_agent(client, store, job.job_id, agent, image="i",
                    states_base=tmp_path / "states", project_root=tmp_path,
                    server_ip="1.2.3.4")
    assert client.networks.created == []  # not re-created
```

**Step 2: Run, expect fail.**

**Step 3: Implement** `provision_agent` (append to `provisioner.py`):
```python
from pathlib import Path

from apps.orchestrator.config_render import render_agent_config
from apps.orchestrator.jobs import JobStore
from apps.orchestrator.models import AgentResult

_STEPS = ["render_config", "ensure_network", "pull_image", "run_container"]


def _ensure_network(client, name: str) -> None:
    if not client.networks.list(names=[name]):
        client.networks.create(name, driver="bridge")


def provision_agent(client, store: JobStore, job_id: str, agent, *, image: str,
                    states_base: Path, project_root: Path, server_ip: str) -> None:
    try:
        state_dir = states_base / agent.state_dir

        store.start_step(job_id, "render_config")
        env = render_agent_config(agent, state_dir, project_root=project_root)
        store.finish_step(job_id, "render_config", ok=True)

        store.start_step(job_id, "ensure_network")
        _ensure_network(client, f"zc-{agent.name}")
        store.finish_step(job_id, "ensure_network", ok=True)

        store.start_step(job_id, "pull_image")
        client.images.pull(image)
        store.finish_step(job_id, "pull_image", ok=True)

        store.start_step(job_id, "run_container")
        spec = build_container_spec(agent, env=env, state_dir=str(state_dir), image=image)
        container = client.containers.run(**spec)
        store.finish_step(job_id, "run_container", ok=True)

        store.succeed(job_id, AgentResult(
            name=agent.name, container_name=f"zeroclaw-{agent.name}",
            server_ip=server_ip, host=server_ip, gateway_port=GATEWAY_PORT,
            status=getattr(container, "status", "created"),
        ))
    except Exception as e:  # noqa: BLE001 - any error must land in job state
        store.fail(job_id, error=f"provision error: {e}")
```

**Step 4: Run, expect pass.**

**Step 5: Commit:**
```bash
git add apps/orchestrator/provisioner.py apps/orchestrator/tests/test_provisioner.py
git commit -m "feat(orchestrator): docker-py provision_agent with step tracking"
```

---

## Phase 4 — Per-slug in-flight guard

### Task 4.1: `JobStore` rejects a second create for the same slug

**Files:**
- Modify: `apps/orchestrator/jobs.py`
- Test: `apps/orchestrator/tests/test_jobs.py`

**Step 1: Add failing tests:**
```python
def test_claim_slug_first_wins():
    store = JobStore()
    job = store.create(slug="acme")
    assert store.active_job_for("acme") is job

def test_claim_slug_blocks_duplicate_while_active():
    store = JobStore()
    store.create(slug="acme")             # in-flight (queued/running)
    assert store.active_job_for("acme") is not None

def test_slug_freed_after_terminal():
    store = JobStore()
    job = store.create(slug="acme")
    store.start_step(job.job_id, "x"); store.finish_step(job.job_id, "x", ok=False, error="e")
    assert store.active_job_for("acme") is None  # failed = no longer active
```

**Step 2: Run, expect fail.**

**Step 3: Implement** — extend `create()` to accept an optional `slug`, store it on the job (add `slug` to `JobState` model with default `None`), and add:
```python
def active_job_for(self, slug: str):
    for job in self._jobs.values():
        if getattr(job, "slug", None) == slug and job.status in ("queued", "running"):
            return job
    return None
```
(Add `slug: str | None = None` to `JobState` in `models.py`.)

**Step 4: Run, expect pass (jobs + models tests).**

**Step 5: Commit:**
```bash
git add apps/orchestrator/jobs.py apps/orchestrator/models.py apps/orchestrator/tests/test_jobs.py
git commit -m "feat(orchestrator): per-slug in-flight guard in job store"
```

---

## Phase 5 — Wire the API to the provisioner

### Task 5.1: `POST /agents` uses the provisioner + guard

**Files:**
- Modify: `apps/orchestrator/main.py`
- Test: `apps/orchestrator/tests/test_api.py`

**Context:** Replace the `run_pipeline` background task with `provision_agent`.
The app builds an `AgentDefinition` from the request (merge with `_defaults.toml`
server-side — reuse `lib.config`), gets a docker client via an injectable
factory (so tests pass a fake), and enforces the per-slug guard returning `409`.

**Step 1: Add/adjust failing tests:**
```python
def test_post_duplicate_slug_returns_409(monkeypatch): ...
def test_post_agents_provisions_via_injected_client(monkeypatch): ...
def test_get_unknown_job_404(): ...  # unchanged
```
Stub the docker client factory + `provision_agent` so no real daemon is touched;
assert the background task drives the job to `succeeded` and the result shape.

**Step 2: Run, expect fail.**

**Step 3: Implement:** add a `docker_client_factory` on `app.state` (default
`docker.from_env`, overridable in tests); in `create_agent`, build the
`AgentDefinition` from the request + defaults, check `store.active_job_for(slug)`
→ `409` if active or container exists, else `store.create(slug=...)` +
`bg.add_task(provision_agent, client, store, job_id, agent, image=..., states_base=Path("/opt/zeroclaw/states"), project_root=..., server_ip=...)`. Remove the
`run_pipeline` import.

**Step 4: Run, expect pass.**

**Step 5: Commit:**
```bash
git add apps/orchestrator/main.py apps/orchestrator/tests/test_api.py
git commit -m "feat(orchestrator): POST /agents provisions via docker-py + slug guard"
```

### Task 5.2: Remove the dead subprocess pipeline

**Files:** Delete `apps/orchestrator/pipeline.py` + `tests/test_pipeline.py`.

**Step 1:** `git rm apps/orchestrator/pipeline.py apps/orchestrator/tests/test_pipeline.py`
**Step 2:** `pytest apps/orchestrator/tests/ -q` — all green (no import of pipeline remains).
**Step 3:** Commit: `refactor(orchestrator): drop subprocess pipeline (replaced by docker-py provisioner)`.

---

## Phase 6 — Deploy the orchestrator onto the host (Pyinfra)

### Task 6.1: systemd unit template

**Files:** Create `templates/systemd/zeroclaw-orchestrator.service.j2`
```ini
[Unit]
Description=ZeroClaw Orchestrator API
After=docker.service
Wants=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/zeroclaw-orchestrator
ExecStart=/opt/zeroclaw-orchestrator/.venv/bin/uvicorn \
    apps.orchestrator.main:create_app --factory --host 127.0.0.1 --port 8000
Restart=on-failure
NoNewPrivileges=yes
ProtectKernelTunables=yes

[Install]
WantedBy=multi-user.target
```
Commit.

### Task 6.2: Pyinfra deploy file

**Files:** Create `infra/deploy_orchestrator.py` (Pyinfra): sync the repo to
`/opt/zeroclaw-orchestrator`, create `.venv`, `pip install -r requirements.txt`,
`files.template` the unit, `systemd.service` enable+restart. Parse-check with
`pyinfra --dry` (no live run in CI). Commit.

> Note: this runs in the BOOTSTRAP plane (operator laptop → SSH). It is not unit-
> tested against a live host; verify with `--dry` only.

---

## Phase 7 — Gate + docs

### Task 7.1: Full suite green
`source .venv/bin/activate && pytest -q` — all pass.

### Task 7.2: Update README
Modify `apps/orchestrator/README.md`: orchestrator now runs **on the host** as a
systemd service; document the `--dry` deploy, that creates are now docker-py
(no SSH/compose), the per-slug 409, and the root-user note. Commit.

---

## Verification gates

```bash
pytest -q                                  # all green, no daemon contact
python -c "from apps.orchestrator.provisioner import build_container_spec; print('ok')"
python -c "from apps.orchestrator.main import create_app; create_app(); print('ok')"
```
Do NOT run a real provision in automated verification (creates a real container).
Operator fires the first real `POST /agents` on the host.

## Out of scope (YAGNI)
- Multi-host placement, Firebase JWT, Traefik, delete/update endpoints,
  persistent/shared job store, rollback, the chat client.

# Orchestrator API Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A local FastAPI service that accepts `POST /agents` with an agent spec, runs the existing `zeroclawctl` Pyinfra pipeline as background subprocesses, and exposes the provisioned result via `GET /jobs/{id}`.

**Architecture:** FastAPI app under `apps/orchestrator/`. POST validates + enqueues an async job, returns `202 {job_id}`. A background runner shells out to `python zeroclawctl.py` (create → server deploy → agent deploy) so Pyinfra's `gevent.monkey.patch_all()` stays isolated from the asyncio loop. In-memory job store. Result echoes `{server_ip, container_name, gateway_port, host, status}`.

**Tech Stack:** FastAPI, Uvicorn, Pydantic v2, pytest, Starlette `TestClient` (httpx). Reuses `lib.config` (`SLUG_PATTERN`, `load_config`) and `zeroclawctl.py`.

**Design doc:** `docs/plans/2026-05-20-orchestrator-api-design.md`

**Conventions:** TDD throughout — failing test first, minimal impl, commit. All pipeline subprocesses are mocked in tests; no test ever contacts the live server or creates a real agent (see memory `feedback-agent-creation-is-operator`).

---

## Phase 0 — Scaffold & dependencies

### Task 0.1: Add API dependencies

**Files:**
- Modify: `requirements.txt`

**Step 1:** Append to `requirements.txt`:
```
fastapi>=0.110,<1
uvicorn[standard]>=0.29,<1
httpx>=0.27,<1
```
(`httpx` is needed by Starlette's `TestClient`.)

**Step 2:** Install:
```bash
source .venv/bin/activate && pip install -r requirements.txt
```
Expected: fastapi, uvicorn, httpx installed, no errors.

**Step 3: Commit**
```bash
git add requirements.txt
git commit -m "chore(orchestrator): add fastapi/uvicorn/httpx deps"
```

### Task 0.2: Package skeleton

**Files:**
- Create: `apps/orchestrator/__init__.py` (empty)
- Create: `apps/orchestrator/tests/__init__.py` (empty)
- Create: `apps/orchestrator/tests/conftest.py`

**Step 1:** Create the two empty `__init__.py` files.

**Step 2:** `apps/orchestrator/tests/conftest.py`:
```python
import sys
from pathlib import Path

# Ensure repo root on path so `import lib...` and `apps.orchestrator...` work.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
```

**Step 3: Commit**
```bash
git add apps/orchestrator/__init__.py apps/orchestrator/tests/__init__.py apps/orchestrator/tests/conftest.py
git commit -m "chore(orchestrator): package skeleton"
```

---

## Phase 1 — Pydantic models

### Task 1.1: Request models with slug validation

**Files:**
- Create: `apps/orchestrator/models.py`
- Test: `apps/orchestrator/tests/test_models.py`

**Step 1: Write failing tests** (`test_models.py`):
```python
import pytest
from pydantic import ValidationError

from apps.orchestrator.models import CreateAgentRequest


def test_valid_request_minimal():
    req = CreateAgentRequest(name="acme-bot")
    assert req.name == "acme-bot"
    assert req.display_name is None


def test_valid_request_full():
    req = CreateAgentRequest(
        name="acme-bot",
        display_name="Acme",
        slack={"bot_token": "xoxb-x", "app_token": "xapp-x"},
        composio={"mcp_api_key": "ck_x"},
        llm={"model": "claude-haiku-4-5"},
    )
    assert req.slack.bot_token == "xoxb-x"
    assert req.composio.mcp_api_key == "ck_x"
    assert req.llm.model == "claude-haiku-4-5"


def test_rejects_uppercase_slug():
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="AcmeBot")


def test_rejects_underscore_slug():
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="acme_bot")


def test_slack_requires_both_tokens():
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="acme", slack={"bot_token": "xoxb-x"})
```

**Step 2: Run, expect fail**
```bash
pytest apps/orchestrator/tests/test_models.py -v
```
Expected: ImportError / module not found.

**Step 3: Implement** (`models.py`):
```python
from __future__ import annotations

from pydantic import BaseModel, field_validator

from lib.config import SLUG_PATTERN


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
    name: str
    display_name: str | None = None
    slack: SlackSpec | None = None
    composio: ComposioSpec | None = None
    llm: LlmSpec | None = None

    @field_validator("name")
    @classmethod
    def _valid_slug(cls, v: str) -> str:
        if not SLUG_PATTERN.match(v):
            raise ValueError(
                f"name must match {SLUG_PATTERN.pattern} "
                "(lowercase letters, digits, hyphen; start with letter/digit)"
            )
        return v
```
Note: `SlackSpec` requiring both tokens is enforced by both being non-optional fields — passing only `bot_token` raises `ValidationError` on the missing `app_token`.

**Step 4: Run, expect pass**
```bash
pytest apps/orchestrator/tests/test_models.py -v
```
Expected: 5 passed.

**Step 5: Commit**
```bash
git add apps/orchestrator/models.py apps/orchestrator/tests/test_models.py
git commit -m "feat(orchestrator): CreateAgentRequest with slug validation"
```

### Task 1.2: Result & job-state models

**Files:**
- Modify: `apps/orchestrator/models.py`
- Test: `apps/orchestrator/tests/test_models.py`

**Step 1: Add failing tests**:
```python
from apps.orchestrator.models import AgentResult, JobState, StepState


def test_agent_result_shape():
    r = AgentResult(
        name="acme", container_name="zeroclaw-acme",
        server_ip="1.2.3.4", host="1.2.3.4",
        gateway_port=42617, status="running",
    )
    assert r.container_name == "zeroclaw-acme"


def test_job_state_defaults():
    job = JobState(job_id="abc")
    assert job.status == "queued"
    assert job.steps == []
    assert job.result is None
    assert job.error is None


def test_step_state():
    s = StepState(name="create")
    assert s.status == "queued"
```

**Step 2: Run, expect fail (ImportError).**

**Step 3: Implement** — append to `models.py`:
```python
from typing import Literal

JobStatus = Literal["queued", "running", "succeeded", "failed"]
StepStatus = Literal["queued", "running", "succeeded", "failed"]


class StepState(BaseModel):
    name: str
    status: StepStatus = "queued"
    error: str | None = None


class AgentResult(BaseModel):
    name: str
    container_name: str
    server_ip: str
    host: str
    gateway_port: int
    status: str


class JobState(BaseModel):
    job_id: str
    status: JobStatus = "queued"
    steps: list[StepState] = []
    result: AgentResult | None = None
    error: str | None = None
```

**Step 4: Run, expect pass (8 total).**

**Step 5: Commit**
```bash
git add apps/orchestrator/models.py apps/orchestrator/tests/test_models.py
git commit -m "feat(orchestrator): AgentResult + JobState models"
```

---

## Phase 2 — Job store

### Task 2.1: In-memory job store

**Files:**
- Create: `apps/orchestrator/jobs.py`
- Test: `apps/orchestrator/tests/test_jobs.py`

**Step 1: Write failing tests** (`test_jobs.py`):
```python
import pytest

from apps.orchestrator.jobs import JobStore


def test_create_returns_unique_ids():
    store = JobStore()
    a = store.create()
    b = store.create()
    assert a.job_id != b.job_id
    assert a.status == "queued"


def test_get_returns_job():
    store = JobStore()
    job = store.create()
    assert store.get(job.job_id) is job


def test_get_unknown_returns_none():
    store = JobStore()
    assert store.get("nope") is None


def test_set_status_and_steps():
    store = JobStore()
    job = store.create()
    store.start_step(job.job_id, "create")
    fetched = store.get(job.job_id)
    assert fetched.status == "running"
    assert fetched.steps[-1].name == "create"
    assert fetched.steps[-1].status == "running"

    store.finish_step(job.job_id, "create", ok=True)
    assert store.get(job.job_id).steps[-1].status == "succeeded"


def test_finish_step_failure_records_error():
    store = JobStore()
    job = store.create()
    store.start_step(job.job_id, "create")
    store.finish_step(job.job_id, "create", ok=False, error="boom")
    fetched = store.get(job.job_id)
    assert fetched.steps[-1].status == "failed"
    assert fetched.steps[-1].error == "boom"
    assert fetched.status == "failed"
```

**Step 2: Run, expect fail.**

**Step 3: Implement** (`jobs.py`):
```python
from __future__ import annotations

import uuid

from apps.orchestrator.models import AgentResult, JobState, StepState


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}

    def create(self) -> JobState:
        job = JobState(job_id=uuid.uuid4().hex)
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    def start_step(self, job_id: str, name: str) -> None:
        job = self._jobs[job_id]
        job.status = "running"
        job.steps.append(StepState(name=name, status="running"))

    def finish_step(self, job_id: str, name: str, *, ok: bool, error: str | None = None) -> None:
        job = self._jobs[job_id]
        step = job.steps[-1]
        step.status = "succeeded" if ok else "failed"
        step.error = error
        if not ok:
            job.status = "failed"
            job.error = error

    def succeed(self, job_id: str, result: AgentResult) -> None:
        job = self._jobs[job_id]
        job.status = "succeeded"
        job.result = result
```

**Step 4: Run, expect pass.**

**Step 5: Commit**
```bash
git add apps/orchestrator/jobs.py apps/orchestrator/tests/test_jobs.py
git commit -m "feat(orchestrator): in-memory job store"
```

---

## Phase 3 — Pipeline (subprocess wrapper)

### Task 3.1: Build command lists from a request

**Files:**
- Create: `apps/orchestrator/pipeline.py`
- Test: `apps/orchestrator/tests/test_pipeline.py`

**Step 1: Write failing tests** (`test_pipeline.py`):
```python
import sys

from apps.orchestrator.models import CreateAgentRequest
from apps.orchestrator.pipeline import build_create_cmd, build_commands


def test_create_cmd_includes_flags():
    req = CreateAgentRequest(
        name="acme", display_name="Acme",
        slack={"bot_token": "xoxb-x", "app_token": "xapp-x", "channel_id": "C1"},
        composio={"mcp_api_key": "ck_x"},
    )
    cmd = build_create_cmd(req)
    assert cmd[:4] == [sys.executable, "zeroclawctl.py", "agents", "create"]
    assert "--name" in cmd and "acme" in cmd
    assert "--display-name" in cmd and "Acme" in cmd
    assert "--slack-bot-token" in cmd and "xoxb-x" in cmd
    assert "--slack-app-token" in cmd and "xapp-x" in cmd
    assert "--slack-channel-id" in cmd and "C1" in cmd
    assert "--composio-mcp-key" in cmd and "ck_x" in cmd


def test_create_cmd_omits_absent_optionals():
    req = CreateAgentRequest(name="acme")
    cmd = build_create_cmd(req)
    assert "--slack-bot-token" not in cmd
    assert "--composio-mcp-key" not in cmd
    assert "--display-name" not in cmd


def test_build_commands_order():
    req = CreateAgentRequest(name="acme")
    cmds = build_commands(req)
    assert [c[2:4] for c in cmds] == [
        ["agents", "create"],
        ["server", "deploy"],
        ["agents", "deploy"],
    ]
```

**Step 2: Run, expect fail.**

**Step 3: Implement** (`pipeline.py`):
```python
from __future__ import annotations

import sys

from apps.orchestrator.models import CreateAgentRequest

CLI = "zeroclawctl.py"


def build_create_cmd(req: CreateAgentRequest) -> list[str]:
    cmd = [sys.executable, CLI, "agents", "create", "--name", req.name]
    if req.display_name:
        cmd += ["--display-name", req.display_name]
    if req.slack:
        cmd += ["--slack-bot-token", req.slack.bot_token,
                "--slack-app-token", req.slack.app_token]
        if req.slack.channel_id:
            cmd += ["--slack-channel-id", req.slack.channel_id]
    if req.composio and req.composio.mcp_api_key:
        cmd += ["--composio-mcp-key", req.composio.mcp_api_key]
    return cmd


def build_commands(req: CreateAgentRequest) -> list[list[str]]:
    return [
        build_create_cmd(req),
        [sys.executable, CLI, "server", "deploy"],
        [sys.executable, CLI, "agents", "deploy", "--name", req.name],
    ]
```
Note: `llm` overrides aren't passed via `agents create` flags (the CLI has no `--llm-model` flag yet). For the MVP, LLM model/provider inherit from `_defaults.toml`; document this limitation. (Add a follow-up task only if per-request LLM override is needed.)

**Step 4: Run, expect pass.**

**Step 5: Commit**
```bash
git add apps/orchestrator/pipeline.py apps/orchestrator/tests/test_pipeline.py
git commit -m "feat(orchestrator): pipeline command builders"
```

### Task 3.2: Run pipeline with mocked subprocess

**Files:**
- Modify: `apps/orchestrator/pipeline.py`
- Test: `apps/orchestrator/tests/test_pipeline.py`

**Step 1: Add failing tests**:
```python
import subprocess
from apps.orchestrator.jobs import JobStore
from apps.orchestrator.pipeline import run_pipeline


def _ok(*a, **k):
    return subprocess.CompletedProcess(a[0] if a else [], 0, stdout="", stderr="")


def test_run_pipeline_success(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[2:4])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # status lookup also shells out — stub it to a known container state
    monkeypatch.setattr(
        "apps.orchestrator.pipeline._fetch_status", lambda req: "running"
    )

    store = JobStore()
    job = store.create()
    req = CreateAgentRequest(name="acme")
    run_pipeline(store, job.job_id, req, server_ip="1.2.3.4")

    final = store.get(job.job_id)
    assert final.status == "succeeded"
    assert final.result.container_name == "zeroclaw-acme"
    assert final.result.server_ip == "1.2.3.4"
    assert [c for c in calls] == [["agents", "create"], ["server", "deploy"], ["agents", "deploy"]]


def test_run_pipeline_stops_on_failure(monkeypatch):
    def fake_run(cmd, **kw):
        rc = 0 if cmd[2:4] == ["agents", "create"] else 1
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="pyinfra exploded")

    monkeypatch.setattr(subprocess, "run", fake_run)
    store = JobStore()
    job = store.create()
    run_pipeline(store, job.job_id, CreateAgentRequest(name="acme"), server_ip="1.2.3.4")

    final = store.get(job.job_id)
    assert final.status == "failed"
    # create succeeded, server_deploy failed, agent_deploy never ran
    assert final.steps[0].status == "succeeded"
    assert final.steps[1].status == "failed"
    assert "exploded" in final.steps[1].error
    assert len(final.steps) == 2
```

**Step 2: Run, expect fail.**

**Step 3: Implement** — append to `pipeline.py`:
```python
import json
import subprocess

from apps.orchestrator.jobs import JobStore
from apps.orchestrator.models import AgentResult

GATEWAY_PORT = 42617
_STEP_NAMES = ["create", "server_deploy", "agent_deploy"]


def _fetch_status(req: CreateAgentRequest) -> str:
    """Best-effort: parse `zeroclawctl agents status` JSON for this container."""
    try:
        proc = subprocess.run(
            [sys.executable, CLI, "agents", "status"],
            check=False, capture_output=True, text=True,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            obj = json.loads(line)
            if obj.get("Name") == f"zeroclaw-{req.name}":
                return obj.get("State") or obj.get("Status") or "unknown"
    except Exception:
        pass
    return "started"


def run_pipeline(store: JobStore, job_id: str, req: CreateAgentRequest, *, server_ip: str) -> None:
    for name, cmd in zip(_STEP_NAMES, build_commands(req)):
        store.start_step(job_id, name)
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            store.finish_step(job_id, name, ok=False, error=(proc.stderr or proc.stdout).strip())
            return
        store.finish_step(job_id, name, ok=True)

    store.succeed(job_id, AgentResult(
        name=req.name,
        container_name=f"zeroclaw-{req.name}",
        server_ip=server_ip,
        host=server_ip,
        gateway_port=GATEWAY_PORT,
        status=_fetch_status(req),
    ))
```

**Step 4: Run, expect pass.**

**Step 5: Commit**
```bash
git add apps/orchestrator/pipeline.py apps/orchestrator/tests/test_pipeline.py
git commit -m "feat(orchestrator): run_pipeline with step tracking + status lookup"
```

---

## Phase 4 — FastAPI app

### Task 4.1: Health endpoint + app factory

**Files:**
- Create: `apps/orchestrator/main.py`
- Test: `apps/orchestrator/tests/test_api.py`

**Step 1: Write failing test** (`test_api.py`):
```python
from fastapi.testclient import TestClient

from apps.orchestrator.main import create_app


def test_health():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

**Step 2: Run, expect fail.**

**Step 3: Implement** (`main.py`):
```python
from __future__ import annotations

from fastapi import FastAPI

from apps.orchestrator.jobs import JobStore


def verify_request() -> None:
    """Auth seam — no-op for the local MVP. Swap for Firebase JWT later."""
    return None


def create_app(store: JobStore | None = None) -> FastAPI:
    app = FastAPI(title="ZeroClaw Orchestrator")
    app.state.store = store or JobStore()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
```

**Step 4: Run, expect pass.**

**Step 5: Commit**
```bash
git add apps/orchestrator/main.py apps/orchestrator/tests/test_api.py
git commit -m "feat(orchestrator): app factory + health endpoint"
```

### Task 4.2: POST /agents (enqueue) + GET /jobs/{id}

**Files:**
- Modify: `apps/orchestrator/main.py`
- Test: `apps/orchestrator/tests/test_api.py`

**Step 1: Add failing tests**:
```python
from apps.orchestrator import main as main_module


def test_post_agents_returns_202_and_job_id(monkeypatch):
    # Stub the runner so no real pipeline fires; mark job succeeded synchronously.
    def fake_runner(store, job_id, req, *, server_ip):
        store.start_step(job_id, "create")
        store.finish_step(job_id, "create", ok=True)
        store.succeed(job_id, main_module._result_stub(req, server_ip))

    monkeypatch.setattr(main_module, "run_pipeline", fake_runner)
    monkeypatch.setattr(main_module, "_server_ip", lambda: "9.9.9.9")

    client = TestClient(create_app())
    resp = client.post("/agents", json={"name": "acme"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert job_id

    poll = client.get(f"/jobs/{job_id}")
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "succeeded"
    assert body["result"]["container_name"] == "zeroclaw-acme"


def test_post_agents_bad_slug_422():
    client = TestClient(create_app())
    resp = client.post("/agents", json={"name": "BadName"})
    assert resp.status_code == 422


def test_get_unknown_job_404():
    client = TestClient(create_app())
    assert client.get("/jobs/nope").status_code == 404
```

**Step 2: Run, expect fail.**

**Step 3: Implement** — extend `main.py`:
```python
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException

from apps.orchestrator.models import AgentResult, CreateAgentRequest, JobState
from apps.orchestrator.pipeline import GATEWAY_PORT, run_pipeline
from lib.config import load_config


def _server_ip() -> str:
    return load_config().server_host


def _result_stub(req: CreateAgentRequest, server_ip: str) -> AgentResult:
    return AgentResult(
        name=req.name, container_name=f"zeroclaw-{req.name}",
        server_ip=server_ip, host=server_ip,
        gateway_port=GATEWAY_PORT, status="started",
    )
```
Then inside `create_app`, after the health route:
```python
    @app.post("/agents", status_code=202, dependencies=[Depends(verify_request)])
    def create_agent(req: CreateAgentRequest, bg: BackgroundTasks) -> dict:
        job = app.state.store.create()
        bg.add_task(run_pipeline, app.state.store, job.job_id, req, server_ip=_server_ip())
        return {"job_id": job.job_id}

    @app.get("/jobs/{job_id}", response_model=JobState)
    def get_job(job_id: str) -> JobState:
        job = app.state.store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job
```
Note: in the test, `run_pipeline` is monkeypatched on `main_module`, and `BackgroundTasks` runs synchronously *after* the response in `TestClient` — the test polls after the request returns, by which point the stubbed runner has completed. If timing proves flaky, add a `?sync=1` test hook or call the runner inline; keep it simple first.

**Step 4: Run, expect pass.**

**Step 5: Commit**
```bash
git add apps/orchestrator/main.py apps/orchestrator/tests/test_api.py
git commit -m "feat(orchestrator): POST /agents enqueue + GET /jobs/{id}"
```

---

## Phase 5 — Run instructions & full-suite gate

### Task 5.1: Full suite green

**Step 1:** Run everything:
```bash
source .venv/bin/activate && pytest -q
```
Expected: all existing 149 tests + the new orchestrator tests pass.

**Step 2: Commit** (only if any fixups were needed).

### Task 5.2: Run docs

**Files:**
- Create: `apps/orchestrator/README.md`

**Step 1:** Document how to run + curl. Content:
```markdown
# ZeroClaw Orchestrator (local MVP)

Run:
    source .venv/bin/activate
    uvicorn apps.orchestrator.main:create_app --factory --reload --port 8000

Create an agent (operator fires this — see memory feedback-agent-creation-is-operator):
    curl -X POST localhost:8000/agents -H 'content-type: application/json' -d '{
      "name": "demo-bot",
      "display_name": "Demo",
      "slack": {"bot_token": "xoxb-...", "app_token": "xapp-..."},
      "composio": {"mcp_api_key": "ck_..."}
    }'
    # → {"job_id": "..."}

Poll:
    curl localhost:8000/jobs/<job_id>
    # → {"status": "succeeded", "result": {"server_ip": ..., "container_name": ...}}

Notes:
- LLM provider/model inherit from agents/_defaults.toml (no per-request override yet).
- The pipeline runs the real Pyinfra deploy against the host in .env. Treat
  POST /agents as a live mutation.
```

**Step 2: Commit**
```bash
git add apps/orchestrator/README.md
git commit -m "docs(orchestrator): run + curl instructions"
```

---

## Verification gates (run before declaring done)

```bash
# 1. Full test suite
pytest -q                       # all green, no live-server contact

# 2. App imports + health works (no real deploy)
python -c "from apps.orchestrator.main import create_app; print('ok')"
uvicorn apps.orchestrator.main:create_app --factory --port 8000 &
sleep 2 && curl -s localhost:8000/health   # {"status":"ok"}
kill %1
```

**Do NOT** fire a real `POST /agents` during automated verification — that
creates a real agent and mutates the live host. The operator triggers the
first real POST manually (Task 5.2 curl).

## Out of scope (YAGNI)

- Firebase JWT auth (seam: `verify_request`)
- Delete/update endpoints
- Persistent job store
- Per-request LLM override (inherits from `_defaults.toml`)
- Rollback on partial failure

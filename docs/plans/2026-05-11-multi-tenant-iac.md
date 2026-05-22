# Multi-Tenant IaC Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single-container ZeroClaw deploy with a multi-tenant IaC: an `agentctl` CLI wrapper drives Pyinfra tasks that create, list, and remove isolated ZeroClaw deployments on Server 3.

**Architecture:** Each tenant is a directory tree (`tenants/<name>/` on laptop, `/opt/<name>/` on host) with its own Slack tokens, model provider, sqlite data, and container. The CLI is a thin Python wrapper that sets `AGENT_NAME`, sources the right `.env`, and invokes `pyinfra` as a subprocess. Per-tenant systemd-timer watchdogs replace the global one. The existing `zeroclaw` container migrates to `agent-chaos` as the first tenant.

**Tech Stack:** Python 3.10+, Pyinfra v3, Jinja2, Docker Compose, systemd, pytest.

**Companion design:** `docs/plans/2026-05-11-multi-tenant-iac-design.md` — read first if anything below is ambiguous.

**Context notes (read before starting):**

- The repo is mid-session: existing uncommitted changes from earlier work (watchdog deploy, agent reshuffle). Run `git status` to see them. Don't try to discard — they're load-bearing for the current bot.
- Server 3 currently has a healthy `zeroclaw` container + `zeroclaw-slack-probe.timer`. The bot is live. Migration (Phase 7) is the only point where we touch it; everything before that is additive.
- This plan assumes work happens on the current branch. If you prefer isolation, create a worktree first: `git worktree add ../ai-project-multitenant -b feat/multitenant-iac`.
- All commits use the project's `type(scope): description` convention (under 72 chars).

---

## Phase 0 — Pre-flight

### Task 0.1: Verify dev dependencies

**Files:**
- Check: `.venv/bin/python -c "import pytest, jinja2, tomli; print('ok')"`
- Modify (if needed): `requirements.txt` to add `pytest>=7`, `jinja2>=3`, `tomli>=2` (Python 3.10 needs tomli; 3.11+ has tomllib stdlib)

**Step 1:** Run `.venv/bin/pip install pytest jinja2 tomli` if any import fails.

**Step 2:** Confirm `pyinfra --version` reports v3.x (already verified in current session — v3.7).

**Step 3:** No commit yet — dependency setup happens just-in-time per task.

### Task 0.2: Create tenants directory + gitignore

**Files:**
- Create: `tenants/.gitignore`
- Create: `tenants/_template/tenant.toml.example`
- Create: `tenants/_template/.env.example`

**Step 1:** Write `tenants/.gitignore`:

```
# Tenant secrets — never commit
*/.env
*/.env.bak-*

# Allow non-secret tenant config
!*/tenant.toml
!_template/
```

**Step 2:** Write `tenants/_template/tenant.toml.example`:

```toml
# Tenant-level non-secret config. Copy to tenants/<name>/tenant.toml.

# Display name shown in chat. Must match the Slack app's display name.
agent_name = "Edgar"

# Model + provider routing.
zeroclaw_provider = "litellm"   # or "anthropic"
zeroclaw_model = "claude-haiku-4-5"

# Slack channel scoping.
slack_mention_only = false
slack_thread_replies = true
slack_use_markdown_blocks = true
slack_stream_drafts = false
# slack_channel_id = "C01ABC123"     # optional — scope to one channel
# slack_allowed_users = ["U01ABC"]   # optional — whitelist
```

**Step 3:** Write `tenants/_template/.env.example`:

```bash
# Per-tenant secrets — NEVER commit. Copy to tenants/<name>/.env.

# Slack — one app per tenant. Create the Slack app in the tenant's
# workspace first, then paste tokens here.
SLACK_BOT_TOKEN=xoxb-
SLACK_APP_TOKEN=xapp-
SLACK_SIGNING_SECRET=

# Model provider — populate the one matching zeroclaw_provider in tenant.toml.
ANTHROPIC_API_KEY=
LITELLM_BASE_URL=
LITELLM_API_KEY=

# Composio (optional — leave empty to disable).
COMPOSIO_API_KEY=
COMPOSIO_ENTITY_ID=default
```

**Step 4:** Commit.

```bash
git add tenants/.gitignore tenants/_template/
git commit -m "feat(iac): scaffold tenants/ directory + template files"
```

---

## Phase 1 — CLI wrapper (TDD)

The wrapper is pure Python. TDD here is genuinely useful. All other phases lean on `--dry` and acceptance.

### Task 1.1: Failing test for slug validator

**Files:**
- Create: `scripts/tests/__init__.py` (empty)
- Create: `scripts/tests/test_agentctl.py`

**Step 1:** Write the failing test.

```python
# scripts/tests/test_agentctl.py
import pytest
from agentctl import validate_slug, SlugError


@pytest.mark.parametrize("slug", [
    "agent-edgar",
    "agent-chaos",
    "agent-a1",
    "agent-z9-test",
    "agent-" + "x" * 25,  # 30 chars total — within 28 + "agent-"
])
def test_valid_slugs(slug):
    validate_slug(slug)  # must not raise


@pytest.mark.parametrize("slug", [
    "",
    "edgar",                  # missing agent- prefix
    "agent-",                 # empty name
    "agent-Edgar",            # uppercase
    "agent--edgar",           # double dash
    "agent-edgar-",           # trailing dash
    "agent-" + "x" * 30,      # too long
    "agent-edgar/etc/passwd", # path injection
])
def test_invalid_slugs(slug):
    with pytest.raises(SlugError):
        validate_slug(slug)
```

**Step 2:** Run to confirm failure.

```bash
cd scripts && .venv/bin/pytest tests/test_agentctl.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'agentctl'`.

### Task 1.2: Implement slug validator

**Files:**
- Create: `scripts/agentctl.py`

**Step 1:** Minimal implementation:

```python
"""agentctl — multi-tenant IaC CLI for ZeroClaw deployments."""

import re

SLUG_RE = re.compile(r"^agent-[a-z0-9]([a-z0-9-]{0,27}[a-z0-9])?$")


class SlugError(ValueError):
    """Raised when a tenant slug fails validation."""


def validate_slug(slug: str) -> None:
    if "--" in slug:
        raise SlugError(f"invalid slug (double dash): {slug!r}")
    if not SLUG_RE.match(slug):
        raise SlugError(
            f"invalid slug {slug!r}: must match {SLUG_RE.pattern}"
        )
```

**Step 2:** Run test, confirm pass.

```bash
cd scripts && .venv/bin/pytest tests/test_agentctl.py -v
```

Expected: all 12 cases pass.

**Step 3:** Commit.

```bash
git add scripts/agentctl.py scripts/tests/
git commit -m "feat(agentctl): slug validator"
```

### Task 1.3: Failing test for `init` scaffolding

**Step 1:** Append to `scripts/tests/test_agentctl.py`:

```python
import tomllib  # 3.11+; if 3.10, swap for `import tomli as tomllib`
from pathlib import Path
from agentctl import init_tenant


def test_init_creates_files(tmp_path):
    repo_root = tmp_path
    template_dir = repo_root / "tenants" / "_template"
    template_dir.mkdir(parents=True)
    (template_dir / "tenant.toml.example").write_text(
        'agent_name = "Template"\n'
        'zeroclaw_provider = "{{provider}}"\n'
    )
    (template_dir / ".env.example").write_text("SLACK_BOT_TOKEN=\n")

    init_tenant("agent-edgar", repo_root=repo_root, provider="anthropic")

    tenant_dir = repo_root / "tenants" / "agent-edgar"
    assert (tenant_dir / "tenant.toml").exists()
    assert (tenant_dir / ".env").exists()
    cfg = tomllib.loads((tenant_dir / "tenant.toml").read_text())
    assert cfg["zeroclaw_provider"] == "anthropic"


def test_init_refuses_to_overwrite(tmp_path):
    repo_root = tmp_path
    template_dir = repo_root / "tenants" / "_template"
    template_dir.mkdir(parents=True)
    (template_dir / "tenant.toml.example").write_text("a = 1\n")
    (template_dir / ".env.example").write_text("\n")
    init_tenant("agent-edgar", repo_root=repo_root, provider="anthropic")
    with pytest.raises(FileExistsError):
        init_tenant("agent-edgar", repo_root=repo_root, provider="anthropic")
```

**Step 2:** Run, confirm `ImportError` on `init_tenant`.

### Task 1.4: Implement `init_tenant`

**Step 1:** Append to `scripts/agentctl.py`:

```python
from pathlib import Path


def init_tenant(slug: str, *, repo_root: Path, provider: str) -> Path:
    """Scaffold tenants/<slug>/{tenant.toml, .env} from the templates."""
    validate_slug(slug)
    if provider not in ("anthropic", "litellm"):
        raise ValueError(f"provider must be anthropic or litellm, got {provider!r}")

    tenant_dir = repo_root / "tenants" / slug
    if tenant_dir.exists():
        raise FileExistsError(f"{tenant_dir} already exists")

    template_dir = repo_root / "tenants" / "_template"
    tenant_toml = (template_dir / "tenant.toml.example").read_text()
    env_file = (template_dir / ".env.example").read_text()

    tenant_dir.mkdir(parents=True)
    (tenant_dir / "tenant.toml").write_text(
        tenant_toml.replace("{{provider}}", provider)
    )
    (tenant_dir / ".env").write_text(env_file)
    (tenant_dir / ".env").chmod(0o600)
    return tenant_dir
```

**Step 2:** Run tests, confirm pass.

**Step 3:** Commit.

```bash
git add scripts/agentctl.py scripts/tests/test_agentctl.py
git commit -m "feat(agentctl): init_tenant scaffolding"
```

### Task 1.5: Failing test for subcommand dispatch

**Step 1:** Append to `scripts/tests/test_agentctl.py`:

```python
from agentctl import main
from unittest.mock import patch


def test_init_dispatches_to_init_tenant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    template_dir = tmp_path / "tenants" / "_template"
    template_dir.mkdir(parents=True)
    (template_dir / "tenant.toml.example").write_text("a = 1\n")
    (template_dir / ".env.example").write_text("\n")

    exit_code = main(["init", "agent-edgar", "--provider", "anthropic"])
    assert exit_code == 0
    assert (tmp_path / "tenants" / "agent-edgar" / "tenant.toml").exists()


def test_new_requires_tenant_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["new", "agent-missing"])
    assert exit_code != 0


def test_invalid_slug_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["new", "edgar"])  # missing agent- prefix
    assert exit_code != 0
```

**Step 2:** Run, confirm failure.

### Task 1.6: Implement `main()` dispatch

**Step 1:** Append to `scripts/agentctl.py`:

```python
import argparse
import os
import subprocess
import sys


def _pyinfra_cmd(task: str, agent_name: str, extra: list[str]) -> list[str]:
    """Compose the pyinfra subprocess invocation."""
    return [
        ".venv/bin/pyinfra", "-y",
        "infra/inventories/deploy.py",
        f"infra/tasks/{task}.py",
        *extra,
    ]


def _load_envs(repo_root: Path, slug: str) -> dict[str, str]:
    """Source root .env then tenants/<slug>/.env (latter wins)."""
    env = os.environ.copy()
    for path in [repo_root / ".env", repo_root / "tenants" / slug / ".env"]:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    env["AGENT_NAME"] = slug
    return env


def cmd_init(args: argparse.Namespace, repo_root: Path) -> int:
    init_tenant(args.name, repo_root=repo_root, provider=args.provider)
    print(f"created tenants/{args.name}/. fill in .env, then run: agentctl new {args.name}")
    return 0


def cmd_new(args: argparse.Namespace, repo_root: Path) -> int:
    tenant_dir = repo_root / "tenants" / args.name
    if not tenant_dir.exists():
        print(f"error: {tenant_dir} does not exist. run: agentctl init {args.name}", file=sys.stderr)
        return 2
    if not (tenant_dir / ".env").exists():
        print(f"error: {tenant_dir}/.env missing", file=sys.stderr)
        return 2
    env = _load_envs(repo_root, args.name)
    extra = ["--dry"] if args.dry_run else []
    return subprocess.call(_pyinfra_cmd("agent_new", args.name, extra), env=env, cwd=str(repo_root))


def cmd_remove(args: argparse.Namespace, repo_root: Path) -> int:
    confirmation = input(f"type the agent name to confirm removal of {args.name!r}: ").strip()
    if confirmation != args.name:
        print("aborted", file=sys.stderr)
        return 1
    env = _load_envs(repo_root, args.name)
    return subprocess.call(_pyinfra_cmd("agent_remove", args.name, []), env=env, cwd=str(repo_root))


def cmd_list(args: argparse.Namespace, repo_root: Path) -> int:
    # Implementation in Phase 5.
    raise NotImplementedError("list not yet implemented")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentctl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("name")
    p_init.add_argument("--provider", choices=["anthropic", "litellm"], default="anthropic")

    p_new = sub.add_parser("new")
    p_new.add_argument("name")
    p_new.add_argument("--dry-run", action="store_true")

    p_remove = sub.add_parser("remove")
    p_remove.add_argument("name")

    p_list = sub.add_parser("list")
    p_list.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    repo_root = Path.cwd()

    try:
        validate_slug(args.name) if hasattr(args, "name") else None
    except SlugError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    return {
        "init": cmd_init,
        "new": cmd_new,
        "remove": cmd_remove,
        "list": cmd_list,
    }[args.cmd](args, repo_root)


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2:** Run tests, confirm `test_invalid_slug_exits_nonzero` and `test_new_requires_tenant_dir` pass. `test_init_dispatches_to_init_tenant` should also pass.

**Step 3:** Make wrapper executable + add shim.

```bash
chmod +x scripts/agentctl.py
```

Create `scripts/agentctl` (no extension, for ergonomics):

```bash
#!/usr/bin/env bash
exec "$(dirname "$0")/../.venv/bin/python" "$(dirname "$0")/agentctl.py" "$@"
```

`chmod +x scripts/agentctl`.

**Step 4:** Commit.

```bash
git add scripts/agentctl.py scripts/agentctl scripts/tests/
git commit -m "feat(agentctl): subcommand dispatch (init/new/remove/list)"
```

---

## Phase 2 — Templates

### Task 2.1: Move + parameterise compose template

**Files:**
- Create: `docker/agent/docker-compose.yml.j2`
- Source: copy from `docker/zeroclaw/docker-compose.yml`

**Step 1:** Copy the existing compose to the new path.

```bash
mkdir -p docker/agent
cp docker/zeroclaw/docker-compose.yml docker/agent/docker-compose.yml.j2
```

**Step 2:** Edit `docker/agent/docker-compose.yml.j2` — replace hardcoded names + paths + drop host port mapping:

```yaml
services:
  agent:
    image: ${ZEROCLAW_IMAGE}
    container_name: {{ agent_name }}
    restart: unless-stopped

    environment:
      TZ: ${TZ:-UTC}
      ZEROCLAW_ALLOW_PUBLIC_BIND: "true"
      ZEROCLAW_GATEWAY_PORT: "42617"

    volumes:
      - /opt/{{ agent_name }}/data:/zeroclaw-data
      - /opt/{{ agent_name }}/config/config.toml:/zeroclaw-data/.zeroclaw/config.toml:ro

    # Gateway is loopback-only inside the container. No host port mapping —
    # multiple tenants on one host can't share 42617.

    read_only: true
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=64m
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    ulimits:
      nofile:
        soft: 1024
        hard: 2048

    deploy:
      resources:
        limits:
          cpus: "2"
          memory: 1024M
          pids: 256
        reservations:
          cpus: "0.25"
          memory: 64M

    healthcheck:
      test: ["CMD", "zeroclaw", "status", "--format=exit-code"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
```

### Task 2.2: Render test for compose template

**Files:**
- Create: `scripts/tests/test_templates.py`

**Step 1:** Test that the compose template renders to syntactically valid YAML with the right container name.

```python
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def render(template_path: str, **ctx) -> str:
    env = Environment(loader=FileSystemLoader(REPO_ROOT))
    return env.get_template(template_path).render(**ctx)


def test_compose_renders_with_agent_name():
    out = render("docker/agent/docker-compose.yml.j2", agent_name="agent-edgar")
    parsed = yaml.safe_load(out)
    assert parsed["services"]["agent"]["container_name"] == "agent-edgar"
    volumes = parsed["services"]["agent"]["volumes"]
    assert any("/opt/agent-edgar/data" in v for v in volumes)
    # Hardening preserved.
    assert parsed["services"]["agent"]["read_only"] is True
    assert "ALL" in parsed["services"]["agent"]["cap_drop"]
    # No host port mapping.
    assert "ports" not in parsed["services"]["agent"]


def test_compose_no_hardcoded_zeroclaw_path():
    out = render("docker/agent/docker-compose.yml.j2", agent_name="agent-x")
    assert "/opt/zeroclaw/" not in out
```

**Step 2:** Run, confirm both pass.

```bash
.venv/bin/pytest scripts/tests/test_templates.py -v
```

**Step 3:** Commit.

```bash
git add docker/agent/docker-compose.yml.j2 scripts/tests/test_templates.py
git commit -m "feat(iac): parameterised compose template for tenants"
```

### Task 2.3: Move config + workspace templates

**Step 1:** Move (don't copy — single source of truth):

```bash
mv docker/zeroclaw/config docker/agent/config
mv docker/zeroclaw/workspace docker/agent/workspace
```

**Step 2:** Inspect `docker/agent/config/config.toml.j2` — it already uses `{{ provider }}`, `{{ slack_bot_token }}`, etc. Confirm no hardcoded `zeroclaw` strings remain (the file is mostly OK already; spot-check by grep).

```bash
grep -n "zeroclaw" docker/agent/config/config.toml.j2 | grep -v '#'
```

Anything in a comment is fine; anything in a config key needs replacement.

**Step 3:** Render test — append to `scripts/tests/test_templates.py`:

```python
try:
    import tomllib
except ImportError:
    import tomli as tomllib


def test_config_toml_renders_litellm_provider():
    out = render(
        "docker/agent/config/config.toml.j2",
        provider="litellm",
        anthropic_api_key="",
        litellm_base_url="http://10.0.0.4:4000/v1",
        litellm_api_key="sk-test",
        zeroclaw_model="claude-haiku-4-5",
        slack_bot_token="xoxb-test",
        slack_app_token="xapp-test",
        slack_channel_id="",
        slack_allowed_users="",
        slack_mention_only="false",
        slack_thread_replies="true",
        slack_use_markdown_blocks="true",
        slack_stream_drafts="false",
        composio_api_key="",
        composio_entity_id="default",
        composio_mcp_url="",
        composio_mcp_transport="sse",
        composio_mcp_auth_header="Authorization",
        composio_mcp_api_key="",
    )
    parsed = tomllib.loads(out)
    assert "default_provider" in str(parsed)
```

If the test fails because some variables are missing, add them to the call.

**Step 4:** Commit.

```bash
git add docker/agent/ docker/zeroclaw/ scripts/tests/test_templates.py
git commit -m "refactor(iac): move config + workspace under docker/agent/"
```

(Note: `git add docker/zeroclaw/` picks up the implicit deletion.)

---

## Phase 3 — Pyinfra `agent_new` task

### Task 3.1: Skeleton `agent_new.py`

**Files:**
- Create: `infra/tasks/agent_new.py`

**Step 1:** Start with validation only — the deploy logic comes in 3.2.

```python
"""
agent_new.py — Deploy or update one tenant.

Reads AGENT_NAME from env (set by the agentctl wrapper). The wrapper also
sources tenants/<name>/.env on top of the root .env before invoking pyinfra,
so per-tenant SLACK_BOT_TOKEN / ANTHROPIC_API_KEY / etc. are visible here.

Idempotent — re-running this task on an existing tenant re-renders config,
re-syncs workspace, and `compose up --force-recreate`.
"""

import os
import re

from pyinfra import host
from pyinfra.operations import files, server, systemd

AGENT_NAME = os.environ.get("AGENT_NAME", "").strip()
SLUG_RE = re.compile(r"^agent-[a-z0-9]([a-z0-9-]{0,27}[a-z0-9])?$")

if not SLUG_RE.match(AGENT_NAME):
    raise RuntimeError(
        f"agent_new.py — invalid AGENT_NAME: {AGENT_NAME!r}. "
        f"Must match {SLUG_RE.pattern}."
    )

agent_dir = f"/opt/{AGENT_NAME}"
deploy_user = host.data.deploy_user

provider = os.environ.get("ZEROCLAW_PROVIDER", "anthropic").strip().lower()
if provider not in ("anthropic", "litellm"):
    raise RuntimeError(f"ZEROCLAW_PROVIDER must be anthropic or litellm, got {provider!r}")
```

**Step 2:** Smoke-test by running a dry-run (will mostly no-op but should LOAD without error).

```bash
set -a; source .env; set +a
export AGENT_NAME=agent-test
.venv/bin/pyinfra -y infra/inventories/deploy.py infra/tasks/agent_new.py --dry 2>&1 | head -20
```

Expected: clean dry-run output reporting 0 changes (task file loads but does nothing yet).

### Task 3.2: Port the deploy steps from `zeroclaw_deploy.py`

**Step 1:** Read `infra/tasks/zeroclaw_deploy.py` end-to-end. The new `agent_new.py` follows the same 7-step pattern with two differences:
- All paths use `agent_dir` instead of hardcoded `/opt/zeroclaw/`.
- Compose file is rendered from `docker/agent/docker-compose.yml.j2` (templated), not copied verbatim.

**Step 2:** Append to `agent_new.py` (~150 lines — fold the existing logic verbatim, with the path substitution). Key sections:

```python
# Read remaining provider/composio/slack vars exactly like zeroclaw_deploy.py
# did — same env var names, no rename. (Tokens already in env via the wrapper.)
anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
litellm_base_url = os.environ.get("LITELLM_BASE_URL", "")
litellm_api_key = os.environ.get("LITELLM_API_KEY", "")
zeroclaw_image = os.environ["ZEROCLAW_IMAGE"]
zeroclaw_model = os.environ.get("ZEROCLAW_MODEL", "claude-haiku-4-5")
tz = os.environ.get("TZ", "UTC")
agent_chat_name = os.environ.get("AGENT_NAME_DISPLAY", AGENT_NAME)
slack_bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
slack_app_token = os.environ.get("SLACK_APP_TOKEN", "")
slack_channel_id = os.environ.get("SLACK_CHANNEL_ID", "")
slack_allowed_users = os.environ.get("SLACK_ALLOWED_USERS", "")
# ...etc. (copy the existing block verbatim)

# 1. Directories — identical to zeroclaw_deploy DIR_LAYOUT but rooted at agent_dir.
DIR_LAYOUT = [
    ("",                deploy_user, deploy_user, "750"),
    ("/config",         deploy_user, deploy_user, "755"),
    ("/data",           "nobody",    "nogroup",   "750"),
    ("/data/.zeroclaw", "nobody",    "nogroup",   "750"),
    ("/data/workspace", "nobody",    "nogroup",   "750"),
]
for sub, owner, grp, mode in DIR_LAYOUT:
    files.directory(
        name=f"[{AGENT_NAME}] ensure {agent_dir}{sub}",
        path=f"{agent_dir}{sub}",
        present=True,
        user=owner, group=grp, mode=mode,
    )

# 2. Render config.toml — same template, same vars.
files.template(
    name=f"[{AGENT_NAME}] render config.toml",
    src="docker/agent/config/config.toml.j2",
    dest=f"{agent_dir}/config/config.toml",
    user="nobody", group="nogroup", mode="640",
    provider=provider,
    anthropic_api_key=anthropic_api_key,
    # ...rest of the kwargs identical to zeroclaw_deploy.py
)

# 3. Sync workspace (identical loop, paths swapped).
workspace_src = "docker/agent/workspace"
# ...identical loop logic, paths swapped to agent_dir

# 4. Render compose (was a static put — now a template).
files.template(
    name=f"[{AGENT_NAME}] render docker-compose.yml",
    src="docker/agent/docker-compose.yml.j2",
    dest=f"{agent_dir}/docker-compose.yml",
    user=deploy_user, group=deploy_user, mode="640",
    agent_name=AGENT_NAME,
)

# 5. Render minimal remote .env (only ZEROCLAW_IMAGE + TZ).
from io import StringIO
remote_env = "\n".join([
    f"# Generated by agent_new.py for {AGENT_NAME} — do not edit.",
    f"ZEROCLAW_IMAGE={zeroclaw_image}",
    f"TZ={tz}",
    "",
])
files.put(
    name=f"[{AGENT_NAME}] upload remote .env",
    src=StringIO(remote_env),
    dest=f"{agent_dir}/.env",
    user=deploy_user, group=deploy_user, mode="600",
)

# 6. compose pull + up -d --force-recreate.
server.shell(
    name=f"[{AGENT_NAME}] docker compose pull",
    commands=[f"cd {agent_dir} && docker compose pull"],
    _timeout=300,
)
server.shell(
    name=f"[{AGENT_NAME}] docker compose up -d --force-recreate",
    commands=[f"cd {agent_dir} && docker compose up -d --force-recreate"],
    _timeout=180,
)

# 7. Health poll (same script as zeroclaw_deploy.py, container name = AGENT_NAME).
healthcheck_cmd = (
    "for i in $(seq 1 48); do "
    f"  status=$(docker inspect -f '{{{{.State.Health.Status}}}}' {AGENT_NAME} 2>/dev/null || echo missing); "
    "  if [ \"$status\" = healthy ]; then echo healthy; exit 0; fi; "
    "  sleep 5; "
    "done; "
    f"echo '{AGENT_NAME} never reached healthy after 240s' >&2; "
    f"docker logs --tail=100 {AGENT_NAME} >&2 || true; "
    "exit 1"
)
server.shell(
    name=f"[{AGENT_NAME}] wait for healthy (up to 240s)",
    commands=[healthcheck_cmd],
    _timeout=300,
)
```

Use the existing `zeroclaw_deploy.py` as the canonical source — don't rewrite the comment blocks, just rebind paths.

**Step 3:** Dry-run.

```bash
set -a; source .env; set +a
export AGENT_NAME=agent-test
.venv/bin/pyinfra -y infra/inventories/deploy.py infra/tasks/agent_new.py --dry 2>&1 | tail -30
```

Expected: list of 10–14 detected operations, all targeted at `/opt/agent-test/...`. No errors.

**Step 4:** Commit.

```bash
git add infra/tasks/agent_new.py
git commit -m "feat(iac): agent_new pyinfra task for per-tenant deploy"
```

### Task 3.3: Per-tenant probe deployment inside `agent_new.py`

The current `zeroclaw_probe.py` deploys one watchdog. Each tenant needs its own.

**Step 1:** Create `infra/files/agent-slack-probe.service.j2` — copy from `infra/files/zeroclaw-slack-probe.service.j2` and parameterise:

```ini
[Unit]
Description=Slack liveness probe for {{ agent_name }}
After=docker.service
Wants=docker.service
ConditionPathExists=/opt/{{ agent_name }}/bin/slack-probe.sh

[Service]
Type=oneshot
Environment="SLACK_APP_TOKEN={{ slack_app_token }}"
Environment="CONTAINER_NAME={{ agent_name }}"
ExecStart=/opt/{{ agent_name }}/bin/slack-probe.sh
ProtectSystem=strict
ReadWritePaths=/var/lib/{{ agent_name }}-probe /var/log/{{ agent_name }}-probe.log
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
```

**Step 2:** Create `infra/files/agent-slack-probe.timer.j2`:

```ini
[Unit]
Description=Run Slack liveness probe for {{ agent_name }} every 3 minutes
After=docker.service
Requires=docker.service

[Timer]
OnBootSec=2min
OnUnitActiveSec=3min
RandomizedDelaySec=15s
Unit={{ agent_name }}-slack-probe.service
Persistent=false

[Install]
WantedBy=timers.target
```

**Step 3:** Adapt `infra/files/zeroclaw-slack-probe.sh` to read `$CONTAINER_NAME`. Open the script and replace `CONTAINER=zeroclaw` with `CONTAINER="${CONTAINER_NAME:-zeroclaw}"`. Save as `infra/files/agent-slack-probe.sh` (keep the old one for now — Phase 8 deletes it).

Also adapt the script's other hardcoded paths to a name parameter:
- `STATE_DIR=/var/lib/zeroclaw-probe` → `STATE_DIR=/var/lib/${CONTAINER}-probe`
- `LOG_FILE=/var/log/zeroclaw-probe.log` → `LOG_FILE=/var/log/${CONTAINER}-probe.log`

**Step 4:** Append to `infra/tasks/agent_new.py`:

```python
# 8. Per-tenant Slack-liveness watchdog.
files.directory(
    name=f"[{AGENT_NAME}] ensure {agent_dir}/bin",
    path=f"{agent_dir}/bin",
    present=True,
    user=deploy_user, group=deploy_user, mode="750",
)
files.directory(
    name=f"[{AGENT_NAME}] ensure /var/lib/{AGENT_NAME}-probe",
    path=f"/var/lib/{AGENT_NAME}-probe",
    present=True,
    user="root", group="root", mode="750",
)
files.file(
    name=f"[{AGENT_NAME}] ensure /var/log/{AGENT_NAME}-probe.log",
    path=f"/var/log/{AGENT_NAME}-probe.log",
    present=True,
    user="root", group="root", mode="640",
)
files.put(
    name=f"[{AGENT_NAME}] upload slack-probe.sh",
    src="infra/files/agent-slack-probe.sh",
    dest=f"{agent_dir}/bin/slack-probe.sh",
    user=deploy_user, group=deploy_user, mode="750",
)
files.template(
    name=f"[{AGENT_NAME}] render probe service unit",
    src="infra/files/agent-slack-probe.service.j2",
    dest=f"/etc/systemd/system/{AGENT_NAME}-slack-probe.service",
    user="root", group="root", mode="600",
    agent_name=AGENT_NAME,
    slack_app_token=slack_app_token,
)
files.template(
    name=f"[{AGENT_NAME}] render probe timer unit",
    src="infra/files/agent-slack-probe.timer.j2",
    dest=f"/etc/systemd/system/{AGENT_NAME}-slack-probe.timer",
    user="root", group="root", mode="644",
    agent_name=AGENT_NAME,
)
systemd.daemon_reload(name=f"[{AGENT_NAME}] systemctl daemon-reload")
systemd.service(
    name=f"[{AGENT_NAME}] enable + start probe timer",
    service=f"{AGENT_NAME}-slack-probe.timer",
    running=True, enabled=True,
)
```

**Step 5:** Dry-run again, expect 8 additional operations.

**Step 6:** Commit.

```bash
git add infra/files/agent-slack-probe.* infra/tasks/agent_new.py
git commit -m "feat(iac): per-tenant slack-probe watchdog in agent_new"
```

---

## Phase 4 — Pyinfra `agent_remove` task

### Task 4.1: Implement `agent_remove.py`

**Files:**
- Create: `infra/tasks/agent_remove.py`

**Step 1:** Write the task:

```python
"""
agent_remove.py — Tear down one tenant. Archives /opt/<name>/data/ to
/opt/.archive/<name>-YYYYMMDD-HHMM/data/ then removes the container,
compose file, config, .env, and systemd probe units. Operator data is
recoverable from /opt/.archive/ until manually cleaned up.

Always-archive semantics — no --purge in v1. Manual `rm -rf` is the
explicit purge path.

Reads AGENT_NAME from env. The wrapper enforces the type-the-name
confirmation before invoking this task.
"""

import os
import re

from pyinfra import host
from pyinfra.operations import files, server, systemd

AGENT_NAME = os.environ.get("AGENT_NAME", "").strip()
SLUG_RE = re.compile(r"^agent-[a-z0-9]([a-z0-9-]{0,27}[a-z0-9])?$")

if not SLUG_RE.match(AGENT_NAME):
    raise RuntimeError(f"agent_remove.py — invalid AGENT_NAME: {AGENT_NAME!r}")

agent_dir = f"/opt/{AGENT_NAME}"

# 1. Disable + stop the probe timer (best-effort — service may not exist yet).
server.shell(
    name=f"[{AGENT_NAME}] disable probe timer (ignore errors if absent)",
    commands=[
        f"systemctl disable --now {AGENT_NAME}-slack-probe.timer 2>/dev/null || true",
    ],
)

# 2. compose down (best-effort — container may already be gone).
server.shell(
    name=f"[{AGENT_NAME}] compose down",
    commands=[
        f"if [ -f {agent_dir}/docker-compose.yml ]; then "
        f"  cd {agent_dir} && docker compose down --remove-orphans || true; "
        f"fi"
    ],
    _timeout=120,
)

# 3. Archive data dir if it exists, with a timestamp.
server.shell(
    name=f"[{AGENT_NAME}] archive data dir",
    commands=[
        f"if [ -d {agent_dir}/data ]; then "
        f"  ts=$(date -u +%Y%m%d-%H%M); "
        f"  mkdir -p /opt/.archive; "
        f"  mv {agent_dir}/data /opt/.archive/{AGENT_NAME}-$ts; "
        f"  echo \"archived to /opt/.archive/{AGENT_NAME}-$ts\"; "
        f"fi"
    ],
)

# 4. Remove the tenant dir + systemd units.
server.shell(
    name=f"[{AGENT_NAME}] remove tenant dir + probe units",
    commands=[
        f"rm -rf {agent_dir}",
        f"rm -f /etc/systemd/system/{AGENT_NAME}-slack-probe.service",
        f"rm -f /etc/systemd/system/{AGENT_NAME}-slack-probe.timer",
        f"rm -rf /var/lib/{AGENT_NAME}-probe",
        # Log stays — operators may want it post-mortem; rotate via logrotate.
    ],
)

systemd.daemon_reload(name=f"[{AGENT_NAME}] systemctl daemon-reload")
```

**Step 2:** Dry-run.

```bash
set -a; source .env; set +a
export AGENT_NAME=agent-test
.venv/bin/pyinfra -y infra/inventories/deploy.py infra/tasks/agent_remove.py --dry 2>&1 | tail -20
```

Expected: 5 detected ops (disable-timer, compose-down, archive, rm, daemon-reload).

**Step 3:** Commit.

```bash
git add infra/tasks/agent_remove.py
git commit -m "feat(iac): agent_remove pyinfra task with archive-by-default"
```

---

## Phase 5 — `agentctl list`

### Task 5.1: SSH-based list implementation

**Step 1:** Replace `cmd_list` stub in `scripts/agentctl.py`:

```python
import json as _json


def cmd_list(args: argparse.Namespace, repo_root: Path) -> int:
    """List deployed tenants by SSHing to the host and inspecting containers."""
    server3_ip = os.environ.get("SERVER3_IP") or _read_env_var(repo_root / ".env", "SERVER3_IP")
    ssh_key   = os.environ.get("SSH_KEY_PATH") or _read_env_var(repo_root / ".env", "SSH_KEY_PATH")
    ssh_port  = os.environ.get("SSH_PORT")     or _read_env_var(repo_root / ".env", "SSH_PORT") or "2222"
    ssh_user  = os.environ.get("SSH_USER")     or _read_env_var(repo_root / ".env", "SSH_USER") or "overlord101"

    cmd = [
        "ssh", "-i", ssh_key, "-p", ssh_port, "-o", "ConnectTimeout=10",
        f"{ssh_user}@{server3_ip}",
        "sudo docker ps -a --filter name='^agent-' "
        "--format '{{.Names}}|{{.Status}}|{{.Image}}'",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"ssh failed: {result.stderr.strip()}", file=sys.stderr)
        return 1

    rows = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        name, status, image = line.split("|", 2)
        rows.append({"name": name, "status": status, "image": image})

    if args.json:
        print(_json.dumps(rows, indent=2))
    else:
        if not rows:
            print("no tenants deployed")
            return 0
        w_name = max(len(r["name"]) for r in rows)
        w_stat = max(len(r["status"]) for r in rows)
        for r in rows:
            print(f"{r['name']:<{w_name}}  {r['status']:<{w_stat}}  {r['image']}")
    return 0


def _read_env_var(env_file: Path, key: str) -> str | None:
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.partition("=")[2].strip().strip('"').strip("'")
    return None
```

**Step 2:** Add a no-network unit test.

Append to `scripts/tests/test_agentctl.py`:

```python
def test_list_json_with_no_tenants(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "SERVER3_IP=1.2.3.4\n"
        "SSH_KEY_PATH=./key.pem\n"
    )
    def fake_run(*a, **kw):
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr("subprocess.run", fake_run)
    exit_code = main(["list", "--json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "[]"
```

**Step 3:** Run tests, confirm pass.

**Step 4:** Commit.

```bash
git add scripts/agentctl.py scripts/tests/test_agentctl.py
git commit -m "feat(agentctl): list command via ssh+docker ps"
```

---

## Phase 6 — Integration test with throwaway tenant

This phase touches Server 3. The test tenant (`agent-test`) needs its own Slack app — minimum viable: create a one-channel free-tier Slack workspace for this purpose, install a basic Socket Mode app there, copy tokens.

### Task 6.1: Operator-side preparation

**Step 1:** Create a Slack workspace + app for testing if not already available. Enable Socket Mode + Event Subscriptions (`message.channels`, `app_mention`). Copy `xoxb-...` and `xapp-...` tokens.

**Step 2:** `scripts/agentctl init agent-test --provider litellm`.

**Step 3:** Edit `tenants/agent-test/.env` — fill in the test Slack tokens, LiteLLM creds (or Anthropic), Composio API key if testing tools.

**Step 4:** Edit `tenants/agent-test/tenant.toml` — set `agent_name = "Test"`.

### Task 6.2: Dry-run

```bash
scripts/agentctl new agent-test --dry-run 2>&1 | tail -40
```

Expected: full list of detected operations, no errors. Confirm no operations reference `/opt/zeroclaw/` or `/opt/agent-chaos/` — paths should be `/opt/agent-test/` only.

### Task 6.3: Real deploy

```bash
scripts/agentctl new agent-test
```

Expected: ~15 operations, all succeed. Pyinfra reports `Grand total: N N - - -`.

### Task 6.4: Verify on host

```bash
set -a; source .env; set +a
ssh -i "$SSH_KEY_PATH" -p "$SSH_PORT" "$SSH_USER@$SERVER3_IP" '
  echo "=== container ==="
  sudo docker ps --filter name=agent-test --format "{{.Names}} | {{.Status}}"
  echo "=== probe timer ==="
  systemctl list-timers --all | grep agent-test
  echo "=== probe state ==="
  sudo cat /var/lib/agent-test-probe/consecutive_failures 2>&1
'
```

Expected: container healthy, timer scheduled, probe state file present.

### Task 6.5: End-to-end Slack test

In the test Slack workspace: `@Test hello`. Wait up to 15s. Expect a reply.

### Task 6.6: `agentctl list`

```bash
scripts/agentctl list
```

Expected: two rows — `agent-test` and the still-running legacy `zeroclaw` (filtered by `^agent-` prefix may exclude the latter — that's intentional; we ignore unmigrated containers).

### Task 6.7: `agentctl remove agent-test`

```bash
scripts/agentctl remove agent-test
# Type 'agent-test' at the prompt.
```

Expected: compose down, archive created, container + units gone.

```bash
ssh ... 'ls /opt/.archive/'
# Should show: agent-test-YYYYMMDD-HHMM
```

### Task 6.8: Commit + cleanup

```bash
git add tenants/agent-test/tenant.toml  # only the .toml; .env is gitignored
git commit -m "chore(tenants): test tenant config for acceptance"
```

Optionally `rm -rf tenants/agent-test/` if you don't want a permanent test scaffold.

---

## Phase 7 — Migration: `zeroclaw` → `agent-chaos`

**This is the only phase that touches the live bot. Schedule it deliberately. Expect ~30s of Slack downtime.**

### Task 7.1: Scaffold `agent-chaos` locally

**Step 1:** `scripts/agentctl init agent-chaos --provider litellm`.

**Step 2:** Populate `tenants/agent-chaos/.env` from the current root `.env`. Copy the values for `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `LITELLM_BASE_URL`, `LITELLM_API_KEY`, `COMPOSIO_API_KEY`, `COMPOSIO_ENTITY_ID`, `COMPOSIO_MCP_URL`, `COMPOSIO_MCP_TRANSPORT`, `COMPOSIO_MCP_AUTH_HEADER`, `COMPOSIO_MCP_API_KEY`. Do **not** copy `SERVER3_IP`/`SSH_*`/`TZ` — those stay in root `.env`.

**Step 3:** Populate `tenants/agent-chaos/tenant.toml` with current settings (`agent_name = "Chaos"`, `zeroclaw_provider = "litellm"`, `zeroclaw_model = "claude-haiku-4-5"`, `slack_mention_only = false`, etc.). Source of truth: current values in `infra/tasks/zeroclaw_deploy.py` defaults + root `.env`.

### Task 7.2: Maintenance script (one-shot)

**Files:**
- Create: `infra/tasks/migrate_zeroclaw_to_chaos.py`

```python
"""
migrate_zeroclaw_to_chaos.py — one-time migration of the legacy /opt/zeroclaw
deploy to the new tenant layout under /opt/agent-chaos. Run ONCE, then
delete this file (or move it to docs/archive/).

Steps:
  1. compose down on the legacy /opt/zeroclaw stack
  2. mv /opt/zeroclaw -> /opt/agent-chaos
  3. Stop + disable + remove legacy zeroclaw-slack-probe.{service,timer}

After this task, the operator runs `agentctl new agent-chaos` which
re-renders config + workspace + per-tenant probe at /opt/agent-chaos.
"""

from pyinfra.operations import server, systemd

server.shell(
    name="legacy: compose down /opt/zeroclaw",
    commands=[
        "if [ -f /opt/zeroclaw/docker-compose.yml ]; then "
        "  cd /opt/zeroclaw && docker compose down --remove-orphans || true; "
        "fi"
    ],
    _timeout=120,
)
server.shell(
    name="legacy: rename /opt/zeroclaw -> /opt/agent-chaos",
    commands=[
        "if [ -d /opt/zeroclaw ] && [ ! -e /opt/agent-chaos ]; then "
        "  mv /opt/zeroclaw /opt/agent-chaos; "
        "fi"
    ],
)
server.shell(
    name="legacy: disable + remove zeroclaw-slack-probe units",
    commands=[
        "systemctl disable --now zeroclaw-slack-probe.timer 2>/dev/null || true",
        "rm -f /etc/systemd/system/zeroclaw-slack-probe.service",
        "rm -f /etc/systemd/system/zeroclaw-slack-probe.timer",
        "rm -rf /var/lib/zeroclaw-probe",
        # Keep /var/log/zeroclaw-probe.log for post-mortem; logrotate handles cleanup.
    ],
)
systemd.daemon_reload(name="legacy: daemon-reload after probe removal")
```

### Task 7.3: Execute the migration

**Step 1:** Pre-flight — verify backup state.

```bash
ssh ... '
  sudo ls -la /opt/zeroclaw/data/
  sudo du -sh /opt/zeroclaw/data/
'
```

Expected: sqlite + workspace dirs present.

**Step 2:** Run the migration task.

```bash
set -a; source .env; set +a
.venv/bin/pyinfra -y infra/inventories/deploy.py infra/tasks/migrate_zeroclaw_to_chaos.py 2>&1 | tail -20
```

Expected: 4 ops succeed. `ls /opt/agent-chaos/data/` shows the moved sqlite.

**Step 3:** Bring `agent-chaos` up under the new IaC.

```bash
scripts/agentctl new agent-chaos
```

Expected: full ~15-op deploy succeeds, container `agent-chaos` healthy.

**Step 4:** Slack acceptance — DM the bot, verify it responds within 15s with prior session context intact.

### Task 7.4: Commit

```bash
git add tenants/agent-chaos/tenant.toml  # only the .toml; .env is gitignored
git add infra/tasks/migrate_zeroclaw_to_chaos.py
git commit -m "chore(migrate): zeroclaw -> agent-chaos tenant"
```

---

## Phase 8 — Cleanup

After Phase 7 has been verified for ≥24 hours of stable operation.

### Task 8.1: Delete legacy files

```bash
rm -rf docker/zeroclaw/
rm infra/tasks/zeroclaw_deploy.py
rm infra/tasks/zeroclaw_probe.py
rm infra/files/zeroclaw-slack-probe.sh
rm infra/files/zeroclaw-slack-probe.service.j2
rm infra/files/zeroclaw-slack-probe.timer
rm infra/tasks/migrate_zeroclaw_to_chaos.py
```

### Task 8.2: Update `infra/deploy.py`

The host-bootstrap orchestrator no longer deploys ZeroClaw — only base packages, docker, and host-level hardening. Tenant deploys go through `agentctl new` per tenant.

```python
"""Host bootstrap orchestrator — tenant-agnostic."""

from pyinfra import local

local.include("infra/tasks/base_packages.py")
local.include("infra/tasks/docker_install.py")
```

Optionally add a `tasks/agent_deploy_all.py` that enumerates `tenants/` and runs `agent_new` for each, but that's beyond MVP.

### Task 8.3: Update `CLAUDE.md`

Replace the "ZeroClaw deploys to Server 3" section with "tenants deploy to Server 3 via `agentctl`". Document the four MVP commands. Cite the design doc.

### Task 8.4: Update memory

Add a new memory `multi_tenant_iac.md` documenting the new structure, mark `zeroclaw_iac_decisions.md` as superseded (or update it in place — single source of truth).

### Task 8.5: Final commit

```bash
git add -A
git commit -m "chore(iac): remove legacy zeroclaw paths post-migration"
```

---

## Acceptance criteria — done when

- [ ] `scripts/agentctl init agent-foo` scaffolds files; `pytest scripts/tests/` all green.
- [ ] `scripts/agentctl new agent-foo --dry-run` shows expected ~15 ops.
- [ ] `scripts/agentctl new agent-foo` deploys; container healthy in <60s; Slack DM works.
- [ ] `scripts/agentctl list` shows the tenant.
- [ ] `scripts/agentctl remove agent-foo` archives data, removes container + probe.
- [ ] Legacy `zeroclaw` is gone; `agent-chaos` is its successor and has been stable for 24h.
- [ ] No file under `infra/tasks/` or `docker/` references the literal `zeroclaw` container name.
- [ ] CLAUDE.md + memory updated.

## Out of scope (do NOT add unless explicitly asked)

- `restart`, `logs`, `status` subcommands (operator uses ssh directly)
- `--purge` flag for `remove` (manual `rm -rf /opt/.archive/*`)
- Auto-discovery of tenants in pyinfra (`agent_deploy_all.py` is suggested but not required)
- Per-tenant TLS or public ingress
- Slack app auto-provisioning

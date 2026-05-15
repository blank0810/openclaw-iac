# ZeroClaw Infra Rewrite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite `infra/` + `scripts/agentctl.py` into a nanobot-shaped single-CLI infrastructure tool (`zeroclawctl`) for the ZeroClaw runtime, with typed config, env-only secrets, bidirectional state sync, and AGENT_CHECKLIST-mapped SECURITY.md.

**Architecture:** Single Python CLI (`zeroclawctl.py`) drives Pyinfra as a library (not a shell-out). Typed `DeploymentConfig` / `TenantDefinition` dataclasses are the single source of truth; one `load_config()` validates and feeds every subcommand and every Pyinfra deploy file. Per-tenant state lives under `/opt/zeroclaw/states/<slug>/` with secrets isolated to `zeroclaw.env` (chmod 0600) and zero secrets in `config.toml`. Per-tenant Docker bridge networks preserve isolation under a single shared compose file.

**Tech Stack:** Python 3.10+, pyinfra >=3<4, Jinja2, Docker Compose, ZeroClaw (Rust), pytest with `tmp_path` + `unittest.mock`, gevent (pyinfra requirement), python-dotenv, tomllib (stdlib).

**Reference design:** `docs/plans/2026-05-14-zeroclaw-infra-rewrite-design.md` — read this first if any task is ambiguous.

**AGENT_CHECKLIST.md** is an immutable baseline; the `SECURITY.md` deliverable in Phase 6 maps to it 1:1.

**Branch:** Work on `design/zeroclaw-infra-rewrite` (already created and active).

---

## Conventions

- **TDD:** Every `lib/` Python module that contains pure logic gets a test written first that fails, then implementation that makes it pass. Pyinfra deploy files are exempt — they're straight-line idempotent ops; verify with `pyinfra --dry`.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`, `docs:`, `test:`). Subject under 72 chars. One commit per task unless stated otherwise.
- **Idempotency:** Every Pyinfra op uses `present=True` or state-checked primitives. Re-running `server deploy` on a bootstrapped server must be a near-noop.
- **No emojis** in code, commits, or docs.
- **Never** commit `.env`, `*.pem`, `tenants/<slug>/tenant.toml` (real tenant data), or `backups/`.

---

## Phase 0 — Repo prep

### Task 0.1: Add .gitignore entries for the new layout

**Files:**
- Modify: `.gitignore`

**Step 1:** Open `.gitignore` and add the following block at the bottom:

```
# zeroclawctl rewrite
tenants/
!tenants/_template/
backups/
.runtime-temp/
```

**Step 2:** Commit

```bash
git add .gitignore
git commit -m "chore(infra): gitignore tenants/ and backups/ for zeroclawctl rewrite"
```

---

### Task 0.2: Add Python dev dependencies

**Files:**
- Modify: `requirements.txt` (project root; create if missing)
- Create: `requirements-dev.txt`

**Step 1:** Ensure `requirements.txt` contains (add if missing):

```
pyinfra>=3,<4
python-dotenv>=1.0
jinja2>=3.1
gevent>=23.0
```

**Step 2:** Create `requirements-dev.txt`:

```
pytest>=8.0
pytest-mock>=3.12
```

**Step 3:** Install dev deps in the project's venv:

```bash
source .venv/bin/activate 2>/dev/null || ./scripts/setup-local.sh
pip install -r requirements.txt -r requirements-dev.txt
```

**Step 4:** Commit

```bash
git add requirements.txt requirements-dev.txt
git commit -m "chore(deps): add pytest and pin pyinfra for zeroclawctl rewrite"
```

---

### Task 0.3: Create empty package skeleton

**Files:**
- Create: `lib/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`

**Step 1:** Write `lib/__init__.py`:

```python
```

(Empty file.)

**Step 2:** Write `tests/__init__.py`:

```python
```

(Empty file.)

**Step 3:** Write `tests/conftest.py`:

```python
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path so `import lib...` works in tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """Wipe project-relevant env vars so tests don't see operator's real .env."""
    for key in list(os.environ.keys()):
        if key.startswith(("ZEROCLAW_", "ANTHROPIC_", "LITELLM_", "SLACK_", "COMPOSIO_", "SERVER_", "DEPLOY_")):
            monkeypatch.delenv(key, raising=False)
    return tmp_path
```

**Step 4:** Verify pytest discovers the empty suite:

```bash
pytest -q
```

Expected: `no tests ran in 0.XXs` (zero collected, zero failures).

**Step 5:** Commit

```bash
git add lib/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore(infra): scaffold lib/ + tests/ skeleton"
```

---

## Phase 1 — Typed config layer (load-bearing — everything depends on this)

### Task 1.1: Write failing tests for `LlmConfig` dataclass

**Files:**
- Create: `tests/test_config.py`

**Step 1:** Write `tests/test_config.py`:

```python
from __future__ import annotations

import pytest

from lib.config import LlmConfig


def test_llm_config_accepts_anthropic_provider():
    cfg = LlmConfig(provider="anthropic", model="claude-sonnet-4-5", api_key="sk-ant-x", timeout_secs=60)
    assert cfg.provider == "anthropic"


def test_llm_config_accepts_litellm_provider():
    cfg = LlmConfig(provider="litellm", model="gpt-4o", api_key="sk-x", timeout_secs=60)
    assert cfg.provider == "litellm"


def test_llm_config_rejects_unknown_provider():
    with pytest.raises(ValueError, match="provider"):
        LlmConfig(provider="bogus", model="m", api_key="k", timeout_secs=60)


def test_llm_config_is_frozen():
    cfg = LlmConfig(provider="anthropic", model="m", api_key="k", timeout_secs=60)
    with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError subclass varies
        cfg.provider = "litellm"  # type: ignore[misc]
```

**Step 2:** Run tests to verify failure:

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError` or `ModuleNotFoundError: lib.config`.

---

### Task 1.2: Implement `LlmConfig`

**Files:**
- Create: `lib/config.py`

**Step 1:** Write `lib/config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


VALID_LLM_PROVIDERS = ("anthropic", "litellm")


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    model: str
    api_key: str
    timeout_secs: int

    def __post_init__(self) -> None:
        if self.provider not in VALID_LLM_PROVIDERS:
            raise ValueError(
                f"llm.provider must be one of {VALID_LLM_PROVIDERS}, got {self.provider!r}"
            )
```

**Step 2:** Run tests:

```bash
pytest tests/test_config.py -v
```

Expected: 4 passed.

**Step 3:** Commit

```bash
git add lib/config.py tests/test_config.py
git commit -m "feat(config): add frozen LlmConfig dataclass with provider validation"
```

---

### Task 1.3: Add `SlackConfig`, `ComposioConfig`, `PolicyConfig` (TDD)

**Files:**
- Modify: `tests/test_config.py`
- Modify: `lib/config.py`

**Step 1:** Append to `tests/test_config.py`:

```python
from lib.config import SlackConfig, ComposioConfig, PolicyConfig


def test_slack_config_disabled_allows_empty_tokens():
    cfg = SlackConfig(enabled=False, bot_token="", app_token="", signing_secret="")
    assert cfg.enabled is False


def test_slack_config_enabled_requires_bot_token():
    with pytest.raises(ValueError, match="bot_token"):
        SlackConfig(enabled=True, bot_token="", app_token="xapp-x", signing_secret="s")


def test_composio_config_disabled_allows_empty_key():
    cfg = ComposioConfig(enabled=False, api_key="", allowed_tools=())
    assert cfg.enabled is False


def test_composio_config_enabled_requires_api_key():
    with pytest.raises(ValueError, match="api_key"):
        ComposioConfig(enabled=True, api_key="", allowed_tools=())


def test_composio_allowed_tools_is_tuple():
    cfg = ComposioConfig(enabled=True, api_key="x", allowed_tools=("gmail.send",))
    assert isinstance(cfg.allowed_tools, tuple)


def test_policy_config_defaults_empty():
    cfg = PolicyConfig(require_approval_for=(), denied_domains=())
    assert cfg.require_approval_for == ()
```

**Step 2:** Run tests to confirm new ones fail:

```bash
pytest tests/test_config.py -v
```

Expected: 4 pass (from 1.2), 6 fail with ImportError on new symbols.

**Step 3:** Append to `lib/config.py`:

```python
@dataclass(frozen=True)
class SlackConfig:
    enabled: bool
    bot_token: str
    app_token: str
    signing_secret: str

    def __post_init__(self) -> None:
        if self.enabled and not self.bot_token:
            raise ValueError("slack.bot_token is required when slack.enabled = true")
        if self.enabled and not self.app_token:
            raise ValueError("slack.app_token is required when slack.enabled = true")


@dataclass(frozen=True)
class ComposioConfig:
    enabled: bool
    api_key: str
    allowed_tools: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.enabled and not self.api_key:
            raise ValueError("composio.api_key is required when composio.enabled = true")


@dataclass(frozen=True)
class PolicyConfig:
    require_approval_for: tuple[str, ...]
    denied_domains: tuple[str, ...]
```

**Step 4:** Run tests:

```bash
pytest tests/test_config.py -v
```

Expected: 10 passed.

**Step 5:** Commit

```bash
git add lib/config.py tests/test_config.py
git commit -m "feat(config): add SlackConfig, ComposioConfig, PolicyConfig"
```

---

### Task 1.4: Add `TenantDefinition` (TDD)

**Files:**
- Modify: `tests/test_config.py`
- Modify: `lib/config.py`

**Step 1:** Append to `tests/test_config.py`:

```python
from pathlib import Path

from lib.config import TenantDefinition


def _make_tenant(**overrides):
    defaults = dict(
        name="acme",
        display_name="Acme",
        enabled=True,
        state_dir="acme",
        image=None,
        host_port=0,
        llm=LlmConfig(provider="anthropic", model="claude-sonnet-4-5", api_key="sk-ant-x", timeout_secs=60),
        slack=SlackConfig(enabled=False, bot_token="", app_token="", signing_secret=""),
        composio=ComposioConfig(enabled=False, api_key="", allowed_tools=()),
        exec_enabled=False,
        policy=PolicyConfig(require_approval_for=(), denied_domains=()),
        workspace_dir=Path("/tmp/tenants/acme/workspace"),
        tenant_toml_path=Path("/tmp/tenants/acme/tenant.toml"),
    )
    defaults.update(overrides)
    return TenantDefinition(**defaults)


def test_tenant_definition_accepts_valid_slug():
    t = _make_tenant(name="acme-corp-1")
    assert t.name == "acme-corp-1"


def test_tenant_definition_rejects_invalid_slug_uppercase():
    with pytest.raises(ValueError, match="slug"):
        _make_tenant(name="AcmeCorp")


def test_tenant_definition_rejects_invalid_slug_special_chars():
    with pytest.raises(ValueError, match="slug"):
        _make_tenant(name="acme_corp")


def test_tenant_definition_rejects_negative_host_port():
    with pytest.raises(ValueError, match="host_port"):
        _make_tenant(host_port=-1)


def test_tenant_definition_rejects_port_above_65535():
    with pytest.raises(ValueError, match="host_port"):
        _make_tenant(host_port=70000)


def test_tenant_definition_zero_port_means_no_expose():
    t = _make_tenant(host_port=0)
    assert t.host_port == 0
```

**Step 2:** Run tests:

```bash
pytest tests/test_config.py -v
```

Expected: 10 pass, 6 fail with ImportError on `TenantDefinition`.

**Step 3:** Append to `lib/config.py`:

```python
import re
from pathlib import Path


SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class TenantDefinition:
    name: str
    display_name: str
    enabled: bool
    state_dir: str
    image: str | None
    host_port: int
    llm: LlmConfig
    slack: SlackConfig
    composio: ComposioConfig
    exec_enabled: bool
    policy: PolicyConfig
    workspace_dir: Path
    tenant_toml_path: Path

    def __post_init__(self) -> None:
        if not SLUG_PATTERN.match(self.name):
            raise ValueError(
                f"tenant slug {self.name!r} must match {SLUG_PATTERN.pattern} "
                "(lowercase letters, digits, hyphen; must start with letter or digit)"
            )
        if self.host_port < 0 or self.host_port > 65535:
            raise ValueError(f"host_port must be 0..65535, got {self.host_port}")
```

**Step 4:** Run tests:

```bash
pytest tests/test_config.py -v
```

Expected: 16 passed.

**Step 5:** Commit

```bash
git add lib/config.py tests/test_config.py
git commit -m "feat(config): add frozen TenantDefinition with slug + port validation"
```

---

### Task 1.5: Add `DeploymentConfig` shell + `load_config()` (TDD, fixture-driven)

**Files:**
- Modify: `tests/test_config.py`
- Modify: `lib/config.py`

**Step 1:** Append to `tests/test_config.py`:

```python
from lib.config import DeploymentConfig, load_config


def _write_env(tmp_path: Path, **overrides) -> Path:
    defaults = dict(
        SERVER_HOST="1.2.3.4",
        DEPLOY_USER="overlord101",
        SSH_PORT="2222",
        DEPLOY_SSH_KEY_PATH=str(tmp_path / "fake-deploy.pem"),
        ROOT_SSH_KEY_PATH=str(tmp_path / "fake-root.pem"),
        ZEROCLAW_IMAGE="ghcr.io/example/zeroclaw:1.0",
    )
    defaults.update(overrides)
    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}={v}" for k, v in defaults.items()))
    (tmp_path / "fake-deploy.pem").write_text("")
    (tmp_path / "fake-root.pem").write_text("")
    return env


def _write_tenant(tmp_path: Path, slug: str, **overrides) -> Path:
    tenants_dir = tmp_path / "tenants" / slug
    (tenants_dir / "workspace").mkdir(parents=True)
    body_overrides = overrides.copy()
    enabled = body_overrides.pop("enabled", True)
    state_dir = body_overrides.pop("state_dir", slug)
    host_port = body_overrides.pop("host_port", 0)
    body = f"""
[identity]
name = "{slug}"
display_name = "{slug.title()}"
enabled = {str(enabled).lower()}
state_dir = "{state_dir}"

[runtime]
host_port = {host_port}

[llm]
provider = "anthropic"
model = "claude-sonnet-4-5"
api_key = "sk-ant-{slug}"
timeout_secs = 60

[slack]
enabled = false
bot_token = ""
app_token = ""
signing_secret = ""

[composio]
enabled = false
api_key = ""
allowed_tools = []

[exec]
enabled = false

[policy]
require_approval_for = []
denied_domains = []
"""
    (tenants_dir / "tenant.toml").write_text(body)
    return tenants_dir


def test_load_config_with_no_tenants(tmp_path, isolated_env):
    _write_env(tmp_path)
    cfg = load_config(project_root=tmp_path)
    assert isinstance(cfg, DeploymentConfig)
    assert cfg.server_host == "1.2.3.4"
    assert cfg.tenants == ()


def test_load_config_reads_one_tenant(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    cfg = load_config(project_root=tmp_path)
    assert len(cfg.tenants) == 1
    assert cfg.tenants[0].name == "acme"


def test_load_config_skips_underscore_prefixed_dirs(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    (tmp_path / "tenants" / "_template").mkdir()
    (tmp_path / "tenants" / "_template" / "tenant.toml").write_text("# template")
    cfg = load_config(project_root=tmp_path)
    assert [t.name for t in cfg.tenants] == ["acme"]


def test_load_config_rejects_duplicate_state_dirs(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme", state_dir="shared")
    _write_tenant(tmp_path, "globex", state_dir="shared")
    with pytest.raises(ValueError, match="state_dir"):
        load_config(project_root=tmp_path)


def test_load_config_rejects_duplicate_nonzero_host_ports(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme", host_port=18791)
    _write_tenant(tmp_path, "globex", host_port=18791)
    with pytest.raises(ValueError, match="host_port"):
        load_config(project_root=tmp_path)


def test_load_config_allows_multiple_zero_ports(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme", host_port=0)
    _write_tenant(tmp_path, "globex", host_port=0)
    cfg = load_config(project_root=tmp_path)
    assert len(cfg.tenants) == 2


def test_load_config_effective_tcp_ports_includes_ssh_and_tenants(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme", host_port=18791)
    _write_tenant(tmp_path, "globex", host_port=18792)
    cfg = load_config(project_root=tmp_path)
    assert 2222 in cfg.effective_tcp_ports
    assert 18791 in cfg.effective_tcp_ports
    assert 18792 in cfg.effective_tcp_ports
```

**Step 2:** Run tests:

```bash
pytest tests/test_config.py -v
```

Expected: previous 16 pass, 7 new fail.

**Step 3:** Append to `lib/config.py`:

```python
import tomllib

from dotenv import dotenv_values


@dataclass(frozen=True)
class DeploymentConfig:
    server_host: str
    deploy_user: str
    ssh_port: int
    deploy_ssh_key_path: Path
    root_ssh_key_path: Path
    zeroclaw_image: str
    tenants: tuple[TenantDefinition, ...]
    effective_tcp_ports: tuple[int, ...]


def _parse_tenant_toml(path: Path) -> TenantDefinition:
    raw = tomllib.loads(path.read_text())
    identity = raw.get("identity", {})
    runtime = raw.get("runtime", {})
    llm = raw.get("llm", {})
    slack = raw.get("slack", {})
    composio = raw.get("composio", {})
    exec_ = raw.get("exec", {})
    policy = raw.get("policy", {})
    name = identity["name"]
    return TenantDefinition(
        name=name,
        display_name=identity.get("display_name", name),
        enabled=bool(identity.get("enabled", True)),
        state_dir=identity.get("state_dir", name),
        image=runtime.get("image"),
        host_port=int(runtime.get("host_port", 0)),
        llm=LlmConfig(
            provider=llm.get("provider", "anthropic"),
            model=llm["model"],
            api_key=llm.get("api_key", ""),
            timeout_secs=int(llm.get("timeout_secs", 60)),
        ),
        slack=SlackConfig(
            enabled=bool(slack.get("enabled", False)),
            bot_token=slack.get("bot_token", ""),
            app_token=slack.get("app_token", ""),
            signing_secret=slack.get("signing_secret", ""),
        ),
        composio=ComposioConfig(
            enabled=bool(composio.get("enabled", False)),
            api_key=composio.get("api_key", ""),
            allowed_tools=tuple(composio.get("allowed_tools", ())),
        ),
        exec_enabled=bool(exec_.get("enabled", False)),
        policy=PolicyConfig(
            require_approval_for=tuple(policy.get("require_approval_for", ())),
            denied_domains=tuple(policy.get("denied_domains", ())),
        ),
        workspace_dir=path.parent / "workspace",
        tenant_toml_path=path,
    )


def load_config(project_root: Path | None = None) -> DeploymentConfig:
    project_root = Path(project_root) if project_root else Path.cwd()
    env = dotenv_values(project_root / ".env")
    server_host = env["SERVER_HOST"]
    deploy_user = env.get("DEPLOY_USER", "overlord101")
    ssh_port = int(env.get("SSH_PORT", "2222"))
    deploy_ssh_key_path = Path(env["DEPLOY_SSH_KEY_PATH"])
    root_ssh_key_path = Path(env["ROOT_SSH_KEY_PATH"])
    zeroclaw_image = env["ZEROCLAW_IMAGE"]

    tenants_dir = project_root / "tenants"
    tenant_list: list[TenantDefinition] = []
    if tenants_dir.is_dir():
        for child in sorted(tenants_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("_"):
                continue
            toml_path = child / "tenant.toml"
            if not toml_path.exists():
                continue
            tenant_list.append(_parse_tenant_toml(toml_path))

    _validate_uniqueness(tenant_list)

    effective_ports = {ssh_port}
    for t in tenant_list:
        if t.enabled and t.host_port:
            effective_ports.add(t.host_port)

    return DeploymentConfig(
        server_host=server_host,
        deploy_user=deploy_user,
        ssh_port=ssh_port,
        deploy_ssh_key_path=deploy_ssh_key_path,
        root_ssh_key_path=root_ssh_key_path,
        zeroclaw_image=zeroclaw_image,
        tenants=tuple(tenant_list),
        effective_tcp_ports=tuple(sorted(effective_ports)),
    )


def _validate_uniqueness(tenants: list[TenantDefinition]) -> None:
    seen_names: dict[str, str] = {}
    seen_state_dirs: dict[str, str] = {}
    seen_ports: dict[int, str] = {}
    for t in tenants:
        if t.name in seen_names:
            raise ValueError(f"duplicate tenant name {t.name!r}")
        seen_names[t.name] = t.name
        if t.state_dir in seen_state_dirs:
            raise ValueError(
                f"duplicate state_dir {t.state_dir!r} between {seen_state_dirs[t.state_dir]} and {t.name}"
            )
        seen_state_dirs[t.state_dir] = t.name
        if t.enabled and t.host_port:
            if t.host_port in seen_ports:
                raise ValueError(
                    f"duplicate host_port {t.host_port} between {seen_ports[t.host_port]} and {t.name}"
                )
            seen_ports[t.host_port] = t.name
```

**Step 4:** Run tests:

```bash
pytest tests/test_config.py -v
```

Expected: 23 passed.

**Step 5:** Commit

```bash
git add lib/config.py tests/test_config.py
git commit -m "feat(config): add load_config() with toml parsing and uniqueness validation"
```

---

### Task 1.6: Add `tenants/_template/` scaffold

**Files:**
- Create: `tenants/_template/tenant.toml`
- Create: `tenants/_template/cron.toml`
- Create: `tenants/_template/workspace/AGENTS.md`
- Create: `tenants/_template/workspace/BOOTSTRAP.md`
- Create: `tenants/_template/workspace/HEARTBEAT.md`
- Create: `tenants/_template/workspace/IDENTITY.md`
- Create: `tenants/_template/workspace/SOUL.md`
- Create: `tenants/_template/workspace/TOOLS.md`
- Create: `tenants/_template/workspace/USER.md`

**Step 1:** Create `tenants/_template/tenant.toml` with the schema from the design doc Section 4. Use placeholder values:

```toml
# Copy this file to tenants/<slug>/tenant.toml and fill in real values.

[identity]
name = "REPLACE_ME"
display_name = "REPLACE_ME Assistant"
enabled = true
state_dir = "REPLACE_ME"

[runtime]
# Leave image empty to use ZEROCLAW_IMAGE from .env
# image = ""
host_port = 0    # 0 = no host port exposed (default)

[llm]
provider = "anthropic"
model = "claude-sonnet-4-5"
api_key = ""     # SECRET — never lands in remote config.toml
timeout_secs = 60

[slack]
enabled = false
bot_token = ""
app_token = ""
signing_secret = ""

[composio]
enabled = false
api_key = ""
allowed_tools = []

[exec]
enabled = false

[policy]
require_approval_for = []
denied_domains = []
```

**Step 2:** Create `tenants/_template/cron.toml`:

```toml
# Optional scheduled jobs. Leave empty if not used.
# Example:
# [[jobs]]
# name = "daily-summary"
# schedule = "0 9 * * *"
# prompt = "Summarize yesterday's activity"
```

**Step 3:** For each of the 7 workspace files, write a minimal seed. Example for `AGENTS.md`:

```markdown
# Agent Operating Notes

<!-- BEGIN MANAGED SECURITY POLICY — DO NOT EDIT MANUALLY -->
<!-- END MANAGED SECURITY POLICY -->

Add per-tenant operating notes here.
```

For `BOOTSTRAP.md`, `HEARTBEAT.md`, `IDENTITY.md`, `SOUL.md`, `TOOLS.md`, `USER.md`: write a single-line `# <Filename>` header so the files exist and the workspace fetch/deploy commands have something to operate on.

**Step 4:** Commit

```bash
git add tenants/_template/
git commit -m "feat(tenants): add _template/ scaffold for zeroclawctl tenants create"
```

---

## Phase 2 — Pyinfra deploy files (port from `infra/tasks/`)

### Task 2.1: Build `lib/inventory.py`

**Files:**
- Create: `lib/inventory.py`
- Create: `tests/test_inventory.py`

**Step 1:** Write failing test in `tests/test_inventory.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from lib.inventory import build_inventory_data


def test_build_inventory_includes_host_facts(tmp_path, isolated_env, monkeypatch):
    # reuse fixture helpers from test_config.py
    from tests.test_config import _write_env, _write_tenant
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    monkeypatch.chdir(tmp_path)
    data = build_inventory_data(project_root=tmp_path, ssh_user="overlord101", ssh_key=str(tmp_path / "fake-deploy.pem"))
    assert data["deploy_user"] == "overlord101"
    assert data["ssh_port"] == 2222
    assert any(t["name"] == "acme" for t in data["tenants"])
```

**Step 2:** Run test, confirm fail:

```bash
pytest tests/test_inventory.py -v
```

Expected: ImportError on `lib.inventory`.

**Step 3:** Write `lib/inventory.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.config import DeploymentConfig, load_config


def build_inventory_data(
    project_root: Path | None = None,
    ssh_user: str = "overlord101",
    ssh_key: str | None = None,
) -> dict[str, Any]:
    cfg = load_config(project_root=project_root)
    tenants = [
        {
            "name": t.name,
            "state_dir": t.state_dir,
            "enabled": t.enabled,
            "host_port": t.host_port,
            "image": t.image or cfg.zeroclaw_image,
            "exec_enabled": t.exec_enabled,
        }
        for t in cfg.tenants
    ]
    return {
        "deploy_user": cfg.deploy_user,
        "ssh_port": cfg.ssh_port,
        "ssh_user": ssh_user,
        "ssh_key": ssh_key or str(cfg.deploy_ssh_key_path),
        "remote_base_dir": "/opt/zeroclaw",
        "remote_runtime_dir": "/opt/zeroclaw",
        "zeroclaw_image": cfg.zeroclaw_image,
        "tenants": tenants,
        "effective_tcp_ports": list(cfg.effective_tcp_ports),
        "config": cfg,  # pass the full object for template rendering
    }


# Pyinfra inventory module API — when imported as inventory by pyinfra,
# expose a single host with data attached.
def _server_inventory() -> tuple[list[tuple[str, dict[str, Any]]]]:
    data = build_inventory_data()
    return ([(data.pop("config").server_host, data)],)


# pyinfra reads `inventory` at module top-level when --inventory points here.
# We delay construction to avoid running load_config() at import time during tests.
def __getattr__(name: str):  # type: ignore[no-redef]
    if name == "inventory":
        return _server_inventory()
    raise AttributeError(name)
```

**Step 4:** Run tests:

```bash
pytest tests/test_inventory.py -v
```

Expected: 1 passed.

**Step 5:** Commit

```bash
git add lib/inventory.py tests/test_inventory.py
git commit -m "feat(infra): add inventory builder driven by typed config"
```

---

### Task 2.2: Build `lib/bootstrap_prepare.py` (port from `infra/tasks/deploy_user.py` + `infra/tasks/base_packages.py` + `infra/tasks/docker_install.py`)

**Files:**
- Create: `lib/bootstrap_prepare.py`
- Reference: existing `infra/tasks/deploy_user.py`, `infra/tasks/base_packages.py`, `infra/tasks/docker_install.py`, `infra/bootstrap.py`

**Step 1:** Read the three existing source files to understand the current bootstrap order and op shapes:

```bash
cat infra/bootstrap.py infra/tasks/deploy_user.py infra/tasks/base_packages.py infra/tasks/docker_install.py | head -300
```

**Step 2:** Write `lib/bootstrap_prepare.py`. This is a Pyinfra deploy file — uses `from pyinfra import host` at module scope and calls Pyinfra ops directly. It must:

1. Create user `host.data.deploy_user` with shell `/bin/bash`, public key from `host.data.ssh_key` (host key path) — actually the deploy *public* key, see existing code.
2. Add `<user> ALL=(ALL) NOPASSWD:ALL` to `/etc/sudoers.d/<user>`.
3. `apt install -y git ufw fail2ban ca-certificates curl`.
4. Install Docker via the official keyring shell (idempotent guard `if ! command -v docker`).
5. Add user to `docker` group.
6. Create `/opt/zeroclaw/` and `/opt/zeroclaw/states/` owned by deploy user.
7. Render `templates/jail.local.j2` → `/etc/fail2ban/jail.local`.
8. UFW: default deny incoming, default allow outgoing, allow 22 AND 2222 (both during bootstrap), `ufw --force enable`.
9. Enable + restart fail2ban systemd unit.

Reference nanobot's `lib/bootstrap_prepare.py` for op shape. The exact code is in the design doc Section 3. Use `_sudo=True` only when running as non-root; root bootstrap path doesn't need it.

**Step 3:** Verify Pyinfra parses the file without running it:

```bash
python -c "import ast; ast.parse(open('lib/bootstrap_prepare.py').read())"
```

Expected: no output (parse OK).

**Step 4:** Commit

```bash
git add lib/bootstrap_prepare.py
git commit -m "feat(infra): port bootstrap_prepare deploy file (user + docker + ufw + fail2ban)"
```

---

### Task 2.3: Build `lib/bootstrap_hardening.py`

**Files:**
- Create: `lib/bootstrap_hardening.py`
- Create: `templates/sshd_config.d/60-cloudesk.conf.j2`
- Reference: existing `infra/tasks/hardening.py`

**Step 1:** Create `templates/sshd_config.d/60-cloudesk.conf.j2`:

```
# Managed by zeroclawctl. Drop-in overrides only.
Port {{ host.data.ssh_port }}
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
AllowUsers {{ host.data.deploy_user }}
```

**Step 2:** Write `lib/bootstrap_hardening.py`:

```python
from pyinfra import host
from pyinfra.operations import files, server


files.template(
    name="Render sshd hardening drop-in",
    src="templates/sshd_config.d/60-cloudesk.conf.j2",
    dest="/etc/ssh/sshd_config.d/60-cloudesk.conf",
    user="root",
    group="root",
    mode="0644",
)

server.shell(
    name="systemctl daemon-reload",
    commands=["systemctl daemon-reload"],
)

# Ubuntu 24.04 uses ssh.socket for activation; restart the socket, not the service.
server.shell(
    name="Restart ssh.socket (Ubuntu 24.04 socket activation)",
    commands=["systemctl restart ssh.socket || systemctl restart ssh"],
)

server.shell(
    name="UFW remove port 22",
    commands=["ufw delete allow 22/tcp || true"],
)
```

**Step 3:** Parse-check:

```bash
python -c "import ast; ast.parse(open('lib/bootstrap_hardening.py').read())"
```

Expected: no output.

**Step 4:** Commit

```bash
git add lib/bootstrap_hardening.py templates/sshd_config.d/60-cloudesk.conf.j2
git commit -m "feat(infra): port bootstrap_hardening with sshd drop-in (replaces whole-file replacement)"
```

---

### Task 2.4: Port `templates/jail.local.j2`

**Files:**
- Create: `templates/jail.local.j2`
- Reference: existing `infra/files/fail2ban_jail.local`

**Step 1:** Read existing fail2ban config:

```bash
cat infra/files/fail2ban_jail.local
```

**Step 2:** Convert to Jinja2 template at `templates/jail.local.j2`. Parameterize `bantime`, `findtime`, `maxretry`, `ignoreip`. Use `host.data.ssh_port` for the SSH jail port.

**Step 3:** Commit

```bash
git add templates/jail.local.j2
git commit -m "feat(infra): templated jail.local (parameterized via host.data)"
```

---

### Task 2.5: Build `lib/deploy_runtime.py`

**Files:**
- Create: `lib/deploy_runtime.py`
- Reference: existing `infra/deploy.py`, `infra/tasks/docker_install.py`

**Step 1:** Write `lib/deploy_runtime.py` — runs as `overlord101@2222`. Must:

1. Ensure base packages present (idempotent re-apt).
2. Ensure Docker present (same idempotent guard as bootstrap_prepare; safe to re-run).
3. Ensure `/opt/zeroclaw/`, `/opt/zeroclaw/states/`, and per-tenant `/opt/zeroclaw/states/<state_dir>/` + `workspace/` + `workspace/sessions/` dirs exist with correct ownership (UID 65534 for workspace per memory `[[zeroclaw_container_uid]]`).
4. Render `templates/docker-compose.yml.j2` → `/opt/zeroclaw/docker-compose.yml` (config passed via `host.data`).
5. `docker pull <image>` only when image tag changed (use Pyinfra `cache_time` or shell guard).
6. **Do NOT** render `zeroclaw.env` or `config.toml` here — those are per-tenant, handled by `lib/tenants.cmd_deploy()`.

Reference nanobot's `lib/deploy_runtime.py` for op shape.

**Step 2:** Parse-check:

```bash
python -c "import ast; ast.parse(open('lib/deploy_runtime.py').read())"
```

Expected: no output.

**Step 3:** Commit

```bash
git add lib/deploy_runtime.py
git commit -m "feat(infra): port deploy_runtime (compose render + image pull)"
```

---

## Phase 3 — Templates

### Task 3.1: Render `templates/docker-compose.yml.j2` (TDD on rendered output)

**Files:**
- Create: `templates/docker-compose.yml.j2`
- Create: `tests/test_compose_render.py`

**Step 1:** Write failing test `tests/test_compose_render.py`:

```python
from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader


@pytest.fixture
def env():
    return Environment(loader=FileSystemLoader("templates"))


def _fake_config(tenants):
    class _C:
        zeroclaw_image = "ghcr.io/example/zc:1.0"
    c = _C()
    c.tenants = tenants
    return c


def _fake_tenant(**overrides):
    defaults = dict(
        name="acme",
        state_dir="acme",
        enabled=True,
        image=None,
        host_port=0,
    )
    defaults.update(overrides)
    class _T: ...
    t = _T()
    for k, v in defaults.items():
        setattr(t, k, v)
    return t


def test_compose_renders_one_service_per_enabled_tenant(env):
    cfg = _fake_config([_fake_tenant(name="acme"), _fake_tenant(name="globex")])
    out = env.get_template("docker-compose.yml.j2").render(config=cfg)
    assert "  acme:" in out
    assert "  globex:" in out


def test_compose_omits_disabled_tenants(env):
    cfg = _fake_config([_fake_tenant(name="acme"), _fake_tenant(name="dormant", enabled=False)])
    out = env.get_template("docker-compose.yml.j2").render(config=cfg)
    assert "  acme:" in out
    assert "  dormant:" not in out


def test_compose_renders_hardening_flags_per_service(env):
    cfg = _fake_config([_fake_tenant(name="acme")])
    out = env.get_template("docker-compose.yml.j2").render(config=cfg)
    assert "read_only: true" in out
    assert "no-new-privileges:true" in out
    assert "cap_drop:" in out and "ALL" in out
    assert "tmpfs:" in out


def test_compose_only_exposes_port_when_set(env):
    cfg = _fake_config([_fake_tenant(name="quiet", host_port=0), _fake_tenant(name="loud", host_port=18791)])
    out = env.get_template("docker-compose.yml.j2").render(config=cfg)
    assert "127.0.0.1:18791:42617" in out
    assert "quiet:" in out


def test_compose_renders_per_tenant_network(env):
    cfg = _fake_config([_fake_tenant(name="acme"), _fake_tenant(name="globex")])
    out = env.get_template("docker-compose.yml.j2").render(config=cfg)
    assert "zc-acme:" in out
    assert "zc-globex:" in out
```

**Step 2:** Run tests, confirm fail:

```bash
pytest tests/test_compose_render.py -v
```

Expected: TemplateNotFound.

**Step 3:** Write `templates/docker-compose.yml.j2`:

```yaml
services:
{% for t in config.tenants if t.enabled %}
  {{ t.name }}:
    image: {{ t.image or config.zeroclaw_image }}
    container_name: zeroclaw-{{ t.name }}
    restart: unless-stopped
    env_file:
      - ./states/{{ t.state_dir }}/zeroclaw.env
    volumes:
      - ./states/{{ t.state_dir }}/config.toml:/zeroclaw/config.toml:ro
      - ./states/{{ t.state_dir }}/workspace:/zeroclaw/workspace
    read_only: true
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=64m
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    user: "65534:65534"
{% if t.host_port %}    ports:
      - "127.0.0.1:{{ t.host_port }}:42617"
{% endif %}    networks:
      - zc-{{ t.name }}
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 512M
          pids: 256
    ulimits:
      nofile:
        soft: 1024
        hard: 2048
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
{% endfor %}

networks:
{% for t in config.tenants if t.enabled %}
  zc-{{ t.name }}:
    driver: bridge
{% endfor %}
```

**Step 4:** Run tests:

```bash
pytest tests/test_compose_render.py -v
```

Expected: 5 passed.

**Step 5:** Commit

```bash
git add templates/docker-compose.yml.j2 tests/test_compose_render.py
git commit -m "feat(infra): nanobot-shape compose template with our hardening flags + per-tenant networks"
```

---

### Task 3.2: Build `lib/tenant_env.py` (TDD — single biggest security control)

**Files:**
- Create: `lib/tenant_env.py`
- Create: `templates/zeroclaw.env.j2`
- Create: `tests/test_tenant_env.py`

**Step 1:** Write `tests/test_tenant_env.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from lib.config import LlmConfig, SlackConfig, ComposioConfig, PolicyConfig, TenantDefinition
from lib.tenant_env import build_tenant_env


def _tenant(**overrides):
    defaults = dict(
        name="acme",
        display_name="Acme",
        enabled=True,
        state_dir="acme",
        image=None,
        host_port=0,
        llm=LlmConfig(provider="anthropic", model="claude-sonnet-4-5", api_key="sk-ant-SECRET", timeout_secs=60),
        slack=SlackConfig(enabled=False, bot_token="", app_token="", signing_secret=""),
        composio=ComposioConfig(enabled=False, api_key="", allowed_tools=()),
        exec_enabled=False,
        policy=PolicyConfig(require_approval_for=(), denied_domains=()),
        workspace_dir=Path("/tmp/x"),
        tenant_toml_path=Path("/tmp/x.toml"),
    )
    defaults.update(overrides)
    return TenantDefinition(**defaults)


def test_anthropic_provider_sets_anthropic_api_key():
    env = build_tenant_env(_tenant())
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-SECRET"
    assert "LITELLM_API_KEY" not in env


def test_litellm_provider_sets_litellm_api_key():
    t = _tenant(llm=LlmConfig(provider="litellm", model="gpt-4o", api_key="sk-litellm-X", timeout_secs=60))
    env = build_tenant_env(t)
    assert env["LITELLM_API_KEY"] == "sk-litellm-X"
    assert "ANTHROPIC_API_KEY" not in env


def test_slack_disabled_omits_slack_tokens():
    env = build_tenant_env(_tenant())
    assert "SLACK_BOT_TOKEN" not in env


def test_slack_enabled_includes_all_slack_tokens():
    t = _tenant(slack=SlackConfig(enabled=True, bot_token="xoxb-X", app_token="xapp-X", signing_secret="sec"))
    env = build_tenant_env(t)
    assert env["SLACK_BOT_TOKEN"] == "xoxb-X"
    assert env["SLACK_APP_TOKEN"] == "xapp-X"
    assert env["SLACK_SIGNING_SECRET"] == "sec"


def test_composio_disabled_omits_key():
    env = build_tenant_env(_tenant())
    assert "COMPOSIO_API_KEY" not in env


def test_composio_enabled_includes_key():
    t = _tenant(composio=ComposioConfig(enabled=True, api_key="comp-X", allowed_tools=("gmail.send",)))
    env = build_tenant_env(t)
    assert env["COMPOSIO_API_KEY"] == "comp-X"


def test_provider_metadata_always_present():
    env = build_tenant_env(_tenant())
    assert env["ZEROCLAW_PROVIDER"] == "anthropic"
    assert env["ZEROCLAW_MODEL"] == "claude-sonnet-4-5"
    assert env["ZEROCLAW_WORKSPACE"] == "/zeroclaw/workspace"
```

**Step 2:** Run, confirm fail:

```bash
pytest tests/test_tenant_env.py -v
```

**Step 3:** Write `lib/tenant_env.py`:

```python
from __future__ import annotations

from lib.config import TenantDefinition


def build_tenant_env(tenant: TenantDefinition) -> dict[str, str]:
    env: dict[str, str] = {
        "ZEROCLAW_PROVIDER": tenant.llm.provider,
        "ZEROCLAW_MODEL": tenant.llm.model,
        "ZEROCLAW_WORKSPACE": "/zeroclaw/workspace",
        "ZEROCLAW_PROVIDER_TIMEOUT_SECS": str(tenant.llm.timeout_secs),
    }
    if tenant.llm.provider == "anthropic":
        env["ANTHROPIC_API_KEY"] = tenant.llm.api_key
    elif tenant.llm.provider == "litellm":
        env["LITELLM_API_KEY"] = tenant.llm.api_key

    if tenant.slack.enabled:
        env["SLACK_BOT_TOKEN"] = tenant.slack.bot_token
        env["SLACK_APP_TOKEN"] = tenant.slack.app_token
        env["SLACK_SIGNING_SECRET"] = tenant.slack.signing_secret

    if tenant.composio.enabled:
        env["COMPOSIO_API_KEY"] = tenant.composio.api_key

    return env
```

**Step 4:** Write `templates/zeroclaw.env.j2`:

```
# Managed by zeroclawctl. Mode 0600. Real secrets — do not commit.
{% for key, value in env.items() | sort %}
{{ key }}={{ value }}
{% endfor %}
```

**Step 5:** Run tests:

```bash
pytest tests/test_tenant_env.py -v
```

Expected: 7 passed.

**Step 6:** Commit

```bash
git add lib/tenant_env.py templates/zeroclaw.env.j2 tests/test_tenant_env.py
git commit -m "feat(security): env-only secrets via build_tenant_env() + zeroclaw.env template"
```

---

### Task 3.3: Render `templates/config.toml.j2` — assert ZERO secrets in output

**Files:**
- Create: `templates/config.toml.j2`
- Create: `tests/test_config_render.py`
- Create: `tests/test_no_secrets_in_config.py` (dedicated security test)

**Step 1:** Write `templates/config.toml.j2`. Render only NON-secret fields. ZeroClaw consumes secrets via env vars (Phase 3.2). Example:

```toml
# Managed by zeroclawctl. Rendered from tenants/{{ tenant.name }}/tenant.toml.
# Real secrets live in zeroclaw.env (mode 0600), never in this file.

[identity]
name = "{{ tenant.name }}"
display_name = "{{ tenant.display_name }}"

[runtime]
workspace = "/zeroclaw/workspace"

[llm]
provider = "{{ tenant.llm.provider }}"
model = "{{ tenant.llm.model }}"
timeout_secs = {{ tenant.llm.timeout_secs }}

[slack]
enabled = {{ "true" if tenant.slack.enabled else "false" }}

[composio]
enabled = {{ "true" if tenant.composio.enabled else "false" }}
{% if tenant.composio.enabled %}allowed_tools = [{% for t in tenant.composio.allowed_tools %}"{{ t }}"{% if not loop.last %}, {% endif %}{% endfor %}]
{% endif %}

[policy]
require_approval_for = [{% for r in tenant.policy.require_approval_for %}"{{ r }}"{% if not loop.last %}, {% endif %}{% endfor %}]
denied_domains = [{% for d in tenant.policy.denied_domains %}"{{ d }}"{% if not loop.last %}, {% endif %}{% endfor %}]

{% if tenant.exec_enabled %}[security.exec]
deny_patterns = [
{% for pat in exec_deny_patterns %}  "{{ pat }}",
{% endfor %}]
{% endif %}
```

**Step 2:** Write `tests/test_config_render.py`:

```python
from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader

from tests.test_tenant_env import _tenant
from lib.config import SlackConfig, ComposioConfig, LlmConfig, PolicyConfig


@pytest.fixture
def env():
    return Environment(loader=FileSystemLoader("templates"))


def test_config_toml_renders_identity(env):
    out = env.get_template("config.toml.j2").render(tenant=_tenant(), exec_deny_patterns=[])
    assert 'name = "acme"' in out


def test_config_toml_renders_provider_metadata(env):
    out = env.get_template("config.toml.j2").render(tenant=_tenant(), exec_deny_patterns=[])
    assert 'provider = "anthropic"' in out
    assert 'model = "claude-sonnet-4-5"' in out


def test_config_toml_renders_exec_deny_when_enabled(env):
    t = _tenant(exec_enabled=True)
    out = env.get_template("config.toml.j2").render(
        tenant=t, exec_deny_patterns=["env", "printenv"]
    )
    assert "[security.exec]" in out
    assert '"env"' in out


def test_config_toml_omits_exec_section_when_disabled(env):
    out = env.get_template("config.toml.j2").render(tenant=_tenant(), exec_deny_patterns=[])
    assert "[security.exec]" not in out
```

**Step 3:** Write `tests/test_no_secrets_in_config.py` (security-critical):

```python
"""Critical security test: assert no secrets leak from tenant_env into config.toml output.

If this test fails, the env-only secrets model is broken. DO NOT delete or weaken these
assertions without a reviewed design change.
"""
from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader

from tests.test_tenant_env import _tenant
from lib.config import LlmConfig, SlackConfig, ComposioConfig
from lib.tenant_env import build_tenant_env


@pytest.fixture
def env():
    return Environment(loader=FileSystemLoader("templates"))


def _all_secrets_tenant():
    return _tenant(
        llm=LlmConfig(provider="anthropic", model="claude-sonnet-4-5", api_key="sk-ant-LEAK", timeout_secs=60),
        slack=SlackConfig(enabled=True, bot_token="xoxb-LEAK", app_token="xapp-LEAK", signing_secret="LEAK"),
        composio=ComposioConfig(enabled=True, api_key="comp-LEAK", allowed_tools=("gmail.send",)),
    )


def test_no_api_key_in_config_toml_output(env):
    out = env.get_template("config.toml.j2").render(
        tenant=_all_secrets_tenant(), exec_deny_patterns=[]
    )
    for needle in ("sk-ant-LEAK", "xoxb-LEAK", "xapp-LEAK", "comp-LEAK"):
        assert needle not in out, f"SECURITY REGRESSION: {needle} leaked into config.toml output"


def test_secrets_present_in_env_dict():
    """Sanity check: the secrets the previous test scans for ARE actually in build_tenant_env output."""
    env_dict = build_tenant_env(_all_secrets_tenant())
    assert env_dict["ANTHROPIC_API_KEY"] == "sk-ant-LEAK"
    assert env_dict["SLACK_BOT_TOKEN"] == "xoxb-LEAK"
    assert env_dict["COMPOSIO_API_KEY"] == "comp-LEAK"
```

**Step 4:** Run all tests:

```bash
pytest tests/test_config_render.py tests/test_no_secrets_in_config.py -v
```

Expected: 6 passed.

**Step 5:** Commit

```bash
git add templates/config.toml.j2 tests/test_config_render.py tests/test_no_secrets_in_config.py
git commit -m "feat(security): config.toml template with no-secrets assertion test"
```

---

### Task 3.4: Port workspace `.md.j2` templates

**Files:**
- Create: `templates/workspace/AGENTS.md.j2`
- Create: `templates/workspace/BOOTSTRAP.md.j2`
- Create: `templates/workspace/HEARTBEAT.md.j2`
- Create: `templates/workspace/IDENTITY.md.j2`
- Create: `templates/workspace/SOUL.md.j2`
- Create: `templates/workspace/TOOLS.md.j2`
- Create: `templates/workspace/USER.md.j2`
- Reference: existing `docker/zeroclaw/workspace/*.md.j2` and `docker/agent/workspace/*.md.j2`

**Step 1:** Copy and parameterize the existing templates. Substitute `{{ tenant.name }}`, `{{ tenant.display_name }}`, `{{ tenant.llm.provider }}`, `{{ tenant.llm.model }}` where the originals had `{{ slug }}` / `{{ provider }}` / etc.

**Step 2:** In `AGENTS.md.j2`, ensure there is exactly one `<!-- BEGIN MANAGED SECURITY POLICY ... -->` ... `<!-- END MANAGED SECURITY POLICY -->` block placeholder near the top. Leave it empty in the template; `lib/managed_policy.py` populates it at deploy time.

**Step 3:** Commit

```bash
git add templates/workspace/
git commit -m "feat(infra): port workspace markdown templates parameterized by TenantDefinition"
```

---

## Phase 4 — Security capabilities (managed policy + exec-deny + audit log)

### Task 4.1: Build `lib/managed_policy.py` (TDD)

**Files:**
- Create: `lib/managed_policy.py`
- Create: `tests/test_managed_policy.py`

**Step 1:** Write `tests/test_managed_policy.py`:

```python
from __future__ import annotations

from lib.managed_policy import build_policy_block, inject_policy_block

POLICY_BEGIN = "<!-- BEGIN MANAGED SECURITY POLICY"
POLICY_END = "<!-- END MANAGED SECURITY POLICY"


def test_build_policy_block_includes_begin_end_markers():
    block = build_policy_block(approval_gates=(), denied_domains=())
    assert POLICY_BEGIN in block
    assert POLICY_END in block


def test_build_policy_block_includes_approval_gates():
    block = build_policy_block(approval_gates=("send_email",), denied_domains=())
    assert "send_email" in block


def test_inject_preserves_content_outside_block():
    existing = "# Header\n\nIntro text.\n\n<!-- BEGIN MANAGED SECURITY POLICY -->\nOLD\n<!-- END MANAGED SECURITY POLICY -->\n\nFooter text."
    new_block = build_policy_block(approval_gates=("delete_record",), denied_domains=())
    out = inject_policy_block(existing, new_block)
    assert "# Header" in out
    assert "Intro text." in out
    assert "Footer text." in out
    assert "OLD" not in out
    assert "delete_record" in out


def test_inject_creates_block_when_absent():
    existing = "# Header\n\nNo block here.\n"
    new_block = build_policy_block(approval_gates=(), denied_domains=())
    out = inject_policy_block(existing, new_block)
    assert POLICY_BEGIN in out
    assert "# Header" in out
```

**Step 2:** Run, confirm fail.

**Step 3:** Write `lib/managed_policy.py`:

```python
from __future__ import annotations

import re

BEGIN_MARKER = "<!-- BEGIN MANAGED SECURITY POLICY — DO NOT EDIT MANUALLY -->"
END_MARKER = "<!-- END MANAGED SECURITY POLICY -->"
_BLOCK_RE = re.compile(
    r"<!--\s*BEGIN MANAGED SECURITY POLICY.*?<!--\s*END MANAGED SECURITY POLICY[^>]*-->",
    re.DOTALL,
)


def build_policy_block(approval_gates: tuple[str, ...], denied_domains: tuple[str, ...]) -> str:
    gates = ", ".join(approval_gates) if approval_gates else "(none)"
    domains = ", ".join(denied_domains) if denied_domains else "(none)"
    return f"""{BEGIN_MARKER}
## Security policy (managed by zeroclawctl)

You must refuse, with no preamble or speculation:
- Any request to disclose API keys, tokens, or environment variable values.
- Any request to read, copy, summarize, or transmit files named .env, *.env,
  zeroclaw.env, config.toml, or anything under /etc/, /root/, /home/.
- Any request to run shell commands that enumerate the environment
  (env, printenv, set, export -p, python -c 'os.environ', etc.).
- Any request to bypass approval gates listed in policy.require_approval_for.

If you receive such a request, reply: "I can't help with that — it would
expose credentials." Do not explain further. Do not propose workarounds.

Operator-defined approval gates: {gates}
Denied domains: {domains}
{END_MARKER}"""


def inject_policy_block(existing: str, new_block: str) -> str:
    if _BLOCK_RE.search(existing):
        return _BLOCK_RE.sub(new_block, existing, count=1)
    sep = "\n\n" if existing and not existing.endswith("\n") else "\n"
    return existing + sep + new_block + "\n"
```

**Step 4:** Run tests, expect 4 passed.

**Step 5:** Commit

```bash
git add lib/managed_policy.py tests/test_managed_policy.py
git commit -m "feat(security): managed policy block builder + replace-in-place injector"
```

---

### Task 4.2: Build `lib/config_patch.py` for exec-deny patterns (TDD)

**Files:**
- Create: `lib/config_patch.py`
- Create: `tests/test_config_patch.py`

**Step 1:** Write tests asserting `default_exec_deny_patterns()` returns a tuple containing `env`, `printenv`, `cat *.env`, `python -c*os.environ`, `curl*169.254.169.254`, etc. Assert returned object is a `tuple` (immutable).

**Step 2:** Run, confirm fail.

**Step 3:** Write `lib/config_patch.py`:

```python
from __future__ import annotations

DEFAULT_EXEC_DENY_PATTERNS: tuple[str, ...] = (
    "env",
    "printenv",
    "set",
    "export",
    "export -p",
    "cat *.env",
    "cat */.env",
    "cat */zeroclaw.env",
    "cat /opt/zeroclaw/**",
    "cat /etc/**",
    "cat /root/**",
    "cat /home/**",
    "python -c*os.environ*",
    "python3 -c*os.environ*",
    "node -e*process.env*",
    "bash -c*env",
    "sh -c*env",
    "grep -r * /etc",
    "find / -name *.env",
    "curl*169.254.169.254*",
)


def default_exec_deny_patterns() -> tuple[str, ...]:
    return DEFAULT_EXEC_DENY_PATTERNS
```

**Step 4:** Tests pass.

**Step 5:** Commit

```bash
git add lib/config_patch.py tests/test_config_patch.py
git commit -m "feat(security): default exec_deny_patterns for ZeroClaw tenants"
```

---

### Task 4.3: Build `lib/audit.py` for `/opt/zeroclaw/audit.log`

**Files:**
- Create: `lib/audit.py`
- Create: `tests/test_audit.py`

**Step 1:** Write tests for `format_audit_line(ts, actor, cmd, tenant, image, result) -> str` that returns a JSONL line (one valid JSON object + newline) with those keys.

**Step 2:** Implement; `ts` should be `datetime.utcnow().isoformat() + "Z"` if not provided.

**Step 3:** Commit

```bash
git add lib/audit.py tests/test_audit.py
git commit -m "feat(infra): audit log JSONL formatter"
```

---

## Phase 5 — CLI surface

### Task 5.1: Build `lib/tenant_sync.py` (TDD)

**Files:**
- Create: `lib/tenant_sync.py`
- Create: `tests/test_tenant_sync.py`

**Step 1:** Write tests for `plan_tenant_changes(desired: set[str], actual: set[str]) -> dict` returning `{"to_create": list, "to_keep": list, "to_remove": list}`, sorted.

**Step 2:** Implement.

**Step 3:** Commit

```bash
git add lib/tenant_sync.py tests/test_tenant_sync.py
git commit -m "feat(infra): plan_tenant_changes diff for tenants status/sync"
```

---

### Task 5.2: Build `lib/tenants.py` skeleton + `cmd_create`

**Files:**
- Create: `lib/tenants.py`
- Create: `tests/test_tenants_create.py`

**Step 1:** TDD for `cmd_create(name: str, project_root: Path) -> int` — copies `tenants/_template/` → `tenants/<name>/`, refuses if exists, runs slug validation (reuses `lib/config.SLUG_PATTERN`), returns 0 on success, 1 on error.

**Step 2:** Implement. Use `shutil.copytree` for the dir copy. Substitute `REPLACE_ME` in `tenant.toml` with the new slug.

**Step 3:** Commit

```bash
git add lib/tenants.py tests/test_tenants_create.py
git commit -m "feat(cli): tenants create scaffolds tenants/<slug>/ from _template"
```

---

### Task 5.3: Build `lib/tenants.cmd_deploy()` + remote env/config upload

**Files:**
- Modify: `lib/tenants.py`
- Create: `tests/test_tenants_deploy.py`

**Step 1:** TDD: mock `pyinfra.api` + `subprocess`. Assert that `cmd_deploy("acme", config)`:
1. Renders `zeroclaw.env` from `build_tenant_env(t)` content
2. Renders `config.toml` from template (no secrets in output)
3. Writes both to local `.runtime-temp/<slug>/`
4. SCPs them to `/opt/zeroclaw/states/<slug>/` (mocked)
5. Chmods `zeroclaw.env` to 0600 (mocked SSH)
6. Reads existing `AGENTS.md` from remote, runs `inject_policy_block`, writes back
7. Runs `docker compose up -d --force-recreate <slug>` (mocked)
8. Returns 0

**Step 2:** Implement. Use `paramiko` or `subprocess.run(['ssh', ...])` — match the existing project pattern (check `scripts/agentctl.py` for the existing SSH wrapper style; reuse if possible).

**Step 3:** Commit

```bash
git add lib/tenants.py tests/test_tenants_deploy.py
git commit -m "feat(cli): tenants deploy renders env+config+policy and recreates container"
```

---

### Task 5.4: Build `lib/tenants.cmd_status()` + `cmd_shell()` + `cmd_remove()` + `cmd_logs()` + `cmd_fetch()` + `cmd_restore()`

**Files:**
- Modify: `lib/tenants.py`
- Create: `tests/test_tenants_status.py`
- Create: `tests/test_tenants_fetch.py`

**Step 1:** TDD each command. Key behaviors:
- `cmd_status()`: read remote `docker compose ps --format json`, parse, table-format vs local config; report `running | stopped | drift | missing-local | missing-remote`.
- `cmd_shell(name)`: exec `ssh -t <host> docker compose exec <name> bash` (no mock; just test arg construction).
- `cmd_remove(name)`: prompt for slug confirm (mock `input`), SSH `docker compose stop <name>` + `mv states/<name> .archive/<name>-<ts>` + re-render compose + `docker compose up -d`.
- `cmd_logs(name, follow)`: exec `ssh -t <host> docker compose logs [-f] <name>`.
- `cmd_fetch(name)`: round-trip remote `config.toml` + `zeroclaw.env` + `workspace/*.md` into local `tenants/<name>/`. Parse remote env file back into `tenant.toml` shape. Prompt if local exists.
- `cmd_restore(name, ts)`: list `.archive/<name>-*`, pick latest or matching ts, `mv` back, re-render compose, `up -d`.

**Step 2:** Implement.

**Step 3:** Commit incrementally (one commit per command):

```bash
git commit -m "feat(cli): tenants status with drift detection"
git commit -m "feat(cli): tenants shell + logs SSH wrappers"
git commit -m "feat(cli): tenants remove with archival"
git commit -m "feat(cli): tenants fetch round-trips remote into local"
git commit -m "feat(cli): tenants restore from /opt/zeroclaw/.archive"
```

---

### Task 5.5: Build `lib/workspace.py` (glob-driven sync)

**Files:**
- Create: `lib/workspace.py`
- Create: `tests/test_workspace.py`

**Step 1:** TDD for:
- `cmd_status(name)`: per-`.md` diff status (`same | different | local_only | remote_only`); read-only.
- `cmd_fetch(name)`: SCP remote `workspace/*.md` → local; prompt before overwrite.
- `cmd_deploy(name)`: SCP local `workspace/*.md` → remote; prompt before overwrite. Re-injects policy block into `AGENTS.md` after deploy.
- `cmd_session_clear(name)`: SSH `mv workspace/sessions/*.jsonl workspace/sessions/archive/{}.bak.<ts>` + restart container.

**Step 2:** Implement. Glob `tenants/<slug>/workspace/*.md` locally and `/opt/zeroclaw/states/<state_dir>/workspace/*.md` remotely.

**Step 3:** Commit per command.

---

### Task 5.6: Build `lib/backup.py`

**Files:**
- Create: `lib/backup.py`
- Create: `tests/test_backup.py`

**Step 1:** TDD for `cmd_backup(name: str | None, project_root: Path) -> int`. With `name`: SSH-pull `states/<state_dir>/{config.toml,workspace/}` (NOT `zeroclaw.env`) into `backups/<name>/<UTC-iso>/`. With `name=None`: backup all enabled tenants.

**Step 2:** Implement. Tar streamed over SSH:

```python
subprocess.run([
    "ssh", "-p", str(cfg.ssh_port), f"{cfg.deploy_user}@{cfg.server_host}",
    f"tar -C /opt/zeroclaw/states/{state_dir} -czf - --exclude=zeroclaw.env config.toml workspace/",
], stdout=open(backup_path, "wb"), check=True)
```

**Step 3:** Commit

```bash
git add lib/backup.py tests/test_backup.py
git commit -m "feat(cli): zeroclawctl backup pulls config + workspace (excludes secrets)"
```

---

### Task 5.7: Build `lib/server.py` (`cmd_deploy` with auto-detect)

**Files:**
- Create: `lib/server.py`
- Create: `tests/test_server_deploy.py`

**Step 1:** TDD with mocked `socket.create_connection` + mocked `subprocess.run`:
- TCP unreachable → return 1.
- Deploy-user SSH OK → run `deploy_runtime.py` path only.
- Deploy-user SSH FAIL + root OK → bootstrap path: `bootstrap_prepare.py` → re-check deploy-user → if FAIL halt with error; if OK → `bootstrap_hardening.py` → `deploy_runtime.py`.
- Neither auth path works → return 1 with clear error.

**Step 2:** Implement. Drive Pyinfra by calling `connect_all`, `load_deploy_file`, `run_ops` directly (mirror `nanobot deploy.py:60-84`).

**Step 3:** Commit

```bash
git add lib/server.py tests/test_server_deploy.py
git commit -m "feat(cli): server deploy with TCP probe + deploy-user gate + bootstrap auto-detect"
```

---

### Task 5.8: Build `zeroclawctl.py` (argparse wiring)

**Files:**
- Create: `zeroclawctl.py` (project root)
- Create: `tests/test_cli_help.py`

**Step 1:** TDD: assert `zeroclawctl.py --help` prints `server`, `tenants`, `workspace`, `audit`, `backup` subcommand listings; assert `zeroclawctl.py tenants --help` lists `create deploy status fetch shell remove restore logs`; assert exit code 0 in each case.

**Step 2:** Wire argparse subparsers to `lib.server.cmd_deploy`, `lib.tenants.cmd_*`, `lib.workspace.cmd_*`, `lib.backup.cmd_backup`, `lib.audit.cmd_audit`. Mirror `nanobot deploy.py:165-361` structure for parser construction. Top of file:

```python
#!/usr/bin/env python
from __future__ import annotations
import sys
from gevent import monkey
monkey.patch_all()
```

`monkey.patch_all()` must run BEFORE any pyinfra import — see nanobot `deploy.py:10-12`.

**Step 3:** Make executable:

```bash
chmod +x zeroclawctl.py
```

**Step 4:** Smoke test:

```bash
python zeroclawctl.py --help
```

Expected: argparse usage with three subcommand namespaces.

**Step 5:** Commit

```bash
git add zeroclawctl.py tests/test_cli_help.py
git commit -m "feat(cli): zeroclawctl single CLI entry point"
```

---

## Phase 6 — Slack-deafness probe (carry-over)

### Task 6.1: Port `lib/slack_probe.py`

**Files:**
- Create: `lib/slack_probe.py`
- Create: `templates/systemd/zeroclaw-slack-probe.service.j2`
- Create: `templates/systemd/zeroclaw-slack-probe.timer.j2`
- Create: `templates/systemd/zeroclaw-slack-probe.sh.j2`
- Reference: existing `infra/tasks/zeroclaw_probe.py` + `infra/files/zeroclaw-slack-probe.*`

**Step 1:** Read existing implementation:

```bash
cat infra/tasks/zeroclaw_probe.py infra/files/zeroclaw-slack-probe.*
```

**Step 2:** Port systemd unit templates to new path. Parameterize per-tenant where the current version is hardcoded for the singleton — `service` unit name becomes `zeroclaw-slack-probe-<slug>.service`, `Description=`, log paths, container name `zeroclaw-<slug>` all parameterized via `host.data.tenants`.

**Step 3:** Write `lib/slack_probe.py` as a Pyinfra deploy file (no module-level imports of `pyinfra.host` at top — instead a function `install_probes(tenants)` that is called from `lib/deploy_runtime.py`).

Alternative: put the systemd file rendering directly in `lib/deploy_runtime.py`'s loop over tenants — simpler, no extra module. Use whichever is cleaner once you read the existing code.

**Step 4:** Commit

```bash
git add lib/slack_probe.py templates/systemd/
git commit -m "feat(infra): per-tenant Slack-deafness systemd-timer probes"
```

---

## Phase 7 — Cutover

### Task 7.1: Dry-run against live server

**Step 1:** Ensure `.env` at project root points at the live Server 3 with the existing `overlord101` key.

**Step 2:** Manually create `tenants/<existing-slug>/tenant.toml` by reading the current `/opt/zeroclaw/data/config.toml` on the server. (You can also implement Task 5.4 `cmd_fetch` first, then run it against the live server — preferred.)

**Step 3:** Run a dry deploy:

```bash
python zeroclawctl.py server deploy --dry 2>&1 | tee /tmp/dry-deploy.log
```

(Add `--dry` plumbing to `lib/server.cmd_deploy()` that passes through to Pyinfra `State(check_for_changes=True)` already set; verify ops report `[no change]` or expected diffs only.)

**Step 4:** Diff the rendered `docker-compose.yml` against the live one:

```bash
ssh -p 2222 overlord101@$SERVER_HOST 'cat /opt/zeroclaw/docker-compose.yml' > /tmp/remote-compose.yml
python -c "from jinja2 import Environment, FileSystemLoader; from lib.config import load_config; e=Environment(loader=FileSystemLoader('templates')); print(e.get_template('docker-compose.yml.j2').render(config=load_config()))" > /tmp/new-compose.yml
diff /tmp/remote-compose.yml /tmp/new-compose.yml
```

**Step 5:** If diff is non-empty and represents real intended changes, document them. If diff contains unexpected changes, STOP and investigate.

**Step 6:** Commit findings (no code change yet — this is a verification gate):

```bash
git commit --allow-empty -m "chore(infra): dry-run cutover verification (zero unexpected diffs)"
```

---

### Task 7.2: Live cutover

**Step 1:** Take a snapshot of `/opt/zeroclaw/` on the server:

```bash
ssh -p 2222 overlord101@$SERVER_HOST 'sudo tar -C /opt -czf /opt/zeroclaw-pre-cutover-$(date -u +%Y%m%dT%H%M%SZ).tar.gz zeroclaw'
```

**Step 2:** Run live deploy:

```bash
python zeroclawctl.py server deploy
```

Expected: idempotent re-render + restart-changed only.

**Step 3:** Verify tenant(s) still running:

```bash
python zeroclawctl.py tenants status
```

Expected: every enabled tenant `running`.

**Step 4:** Verify Slack agent still responsive (out-of-band: post to the tenant's Slack channel; confirm reply).

**Step 5:** Commit

```bash
git commit --allow-empty -m "chore(infra): live cutover to zeroclawctl complete"
```

---

### Task 7.3: Delete old code

**Files:**
- Delete: `infra/` (whole tree)
- Delete: `scripts/agentctl.py` (the old multi-tenant CLI)
- Delete: `scripts/tests/test_agentctl.py`
- Delete: `docker/zeroclaw/` and `docker/agent/`
- Delete: `group_data/all.py` IF its contents have all moved to `.env` and `lib/inventory.py`. Otherwise keep.

**Step 1:**

```bash
git rm -r infra/ scripts/agentctl.py scripts/tests/test_agentctl.py docker/zeroclaw/ docker/agent/
```

**Step 2:** Run full test suite + dry deploy:

```bash
pytest -q
python zeroclawctl.py server deploy --dry
```

Both must pass / report no unexpected changes.

**Step 3:** Commit

```bash
git commit -m "chore(infra): delete legacy infra/, agentctl, docker/* after zeroclawctl cutover"
```

---

### Task 7.4: Update `CLAUDE.md` + `AGENTS.md`

**Files:**
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`

**Step 1:** Rewrite the "Project Structure" section of `CLAUDE.md` to reflect the new layout. Rewrite the "Tech Stack" + "Pyinfra Patterns" + "Terminology" sections to describe `zeroclawctl`, `lib/`, `templates/`, `tenants/`.

**Step 2:** Rewrite `AGENTS.md` (the repo guide) to describe the new entry point and command surface (mirror Section 2 of the design doc).

**Step 3:** Commit

```bash
git add CLAUDE.md AGENTS.md
git commit -m "docs: update CLAUDE.md + AGENTS.md for zeroclawctl"
```

---

### Task 7.5: Write `SECURITY.md` (AGENT_CHECKLIST §"Required Project Security Documentation")

**Files:**
- Create: `SECURITY.md`

**Step 1:** Use the table from design doc Section 7 as the skeleton. For each of the 10 AGENT_CHECKLIST sections, write 2-4 sentences describing the *actual* implementation:
- §1 Identity → workspace templates + managed policy block; cite `lib/managed_policy.py` and `templates/workspace/`.
- §2 Isolation → per-tenant `states/<slug>/`, per-tenant bridge network `zc-<slug>`, separate env file; cite `templates/docker-compose.yml.j2`.
- §3 Server hardening → `lib/bootstrap_hardening.py`, UFW deny-incoming, port 2222, sshd drop-in, fail2ban.
- §4 Tool permissions → `composio.allowed_tools`, `policy.denied_domains`, `exec.enabled` gate.
- §5 Secrets → env-only model, `zeroclaw.env` chmod 0600, `tests/test_no_secrets_in_config.py` enforces.
- §6 Memory/Privacy → per-tenant `workspace/`, session-clear archival.
- §7 Approval/Safety → `policy.require_approval_for` rendered + managed policy block.
- §8 Logging → compose `json-file` bounded retention, `/opt/zeroclaw/audit.log`, Slack-deafness probe.
- §9 Backup/Recovery → `tenants fetch`, `tenants restore`, `zeroclawctl backup`.
- §10 Testing/Cost → pytest suite, `--dry` runs; cost = LiteLLM routing (Server 2).

Mark any items as N/A with an explicit "not required because..." line.

**Step 2:** Commit

```bash
git add SECURITY.md
git commit -m "docs(security): add SECURITY.md per AGENT_CHECKLIST requirement"
```

---

## Verification gates

Run all of these before declaring the rewrite done:

```bash
# 1. Full test suite passes
pytest -q
# Expected: ~50+ tests, 0 failures.

# 2. CLI help works
python zeroclawctl.py --help
python zeroclawctl.py server --help
python zeroclawctl.py tenants --help
python zeroclawctl.py workspace --help

# 3. Dry deploy against live server is empty or expected-only diff
python zeroclawctl.py server deploy --dry

# 4. Tenant status reports running
python zeroclawctl.py tenants status

# 5. The security-critical test exists and passes
pytest tests/test_no_secrets_in_config.py -v
# Expected: 2 passed.

# 6. No secrets in committed templates
git grep -E "(sk-ant-|xoxb-|xapp-|comp-)[A-Za-z0-9_-]{8,}" -- templates/ tenants/_template/
# Expected: no output.
```

---

## Open items deferred (do NOT do in this rewrite)

These were flagged during brainstorming and intentionally pushed out:

- **Remote object-storage backups** (Hetzner Storage Box / restic). Local `backup --all` covers solo-dev. Add when there's a second operator.
- **Prometheus/Grafana metrics.** `tenants status` + `tenants logs` + Slack probe is proportionate at this scale.
- **Auditing whether ZeroClaw upstream honors `[security.exec].deny_patterns`.** Ship the table as documentation; managed policy block (Layer B) carries most of the value. Open an upstream issue + PR if not honored — separate work item.
- **Cron job management.** `tenants/<slug>/cron.toml` is scaffolded but the deploy path is not wired in this rewrite. Add `tenants cron deploy` as a follow-up.

---

## Rollback plan

If anything in Phase 7 goes sideways:

1. The pre-cutover tarball at `/opt/zeroclaw-pre-cutover-<ts>.tar.gz` is your safety net.
2. `ssh -p 2222 overlord101@$SERVER_HOST 'cd /opt && sudo rm -rf zeroclaw && sudo tar -xzf zeroclaw-pre-cutover-<ts>.tar.gz'`
3. `git checkout main && pyinfra infra/inventories/deploy.py infra/deploy.py` to redeploy the old shape.
4. The `design/zeroclaw-infra-rewrite` branch is preserved for iteration.

The cutover commits should be small and reversible — if you commit step-by-step per task as instructed above, `git revert` is always available.

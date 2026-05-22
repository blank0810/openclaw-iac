from __future__ import annotations

import stat
import subprocess
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10 compatibility
    import tomli as tomllib

from lib.agents import cmd_fetch, cmd_remove, cmd_restore
from tests.test_config import _write_env, _write_agent


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fake_scp_runner(
    remote_files: dict[str, str] | None = None,
    workspace_md: dict[str, str] | None = None,
    calls: list[list[str]] | None = None,
):
    """Build a subprocess.run replacement that simulates scp/ssh behavior.

    `remote_files` maps the trailing component of the remote path
    (e.g. "config.toml", "zeroclaw.env") to the file contents that should
    appear at the local destination. `workspace_md` maps a relative *.md
    filename to its contents and is materialised when the workspace glob
    scp runs.
    """

    remote_files = remote_files or {}
    workspace_md = workspace_md or {}
    if calls is None:
        calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        # scp invocations have shape: ["scp", "-P", "...", "<src>", "<dst>"]
        # or with "-r" inserted before src.
        if args and args[0] == "scp":
            src = args[-2]
            dst = Path(args[-1])
            if "workspace/*.md" in src:
                # caller created the dest dir already
                for name, body in workspace_md.items():
                    (dst / name).write_text(body)
            else:
                # Find which simulated remote file this src maps to.
                for tail, body in remote_files.items():
                    if src.endswith(tail):
                        dst.write_text(body)
                        break
        return subprocess.CompletedProcess(args, 0)

    return fake_run, calls


def _remote_config_toml(slug: str = "acme") -> str:
    return f"""# Managed by zeroclawctl. Rendered from agents/{slug}/agent.toml.

[identity]
name = "{slug}"
display_name = "Acme Display"

[runtime]
workspace = "/zeroclaw/workspace"

[llm]
provider = "anthropic"
model = "claude-opus-4-5"
timeout_secs = 90

[slack]
enabled = true

[composio]
enabled = true
allowed_tools = ["gmail.send", "gcal.events.create"]

[policy]
require_approval_for = ["exec.shell"]
denied_domains = ["evil.example.com", "malware.test"]
"""


def _remote_env(slug: str = "acme") -> str:
    return (
        "ANTHROPIC_API_KEY=sk-ant-LIVE\n"
        "COMPOSIO_API_KEY=cmp-LIVE\n"
        "SLACK_APP_TOKEN=xapp-LIVE\n"
        "SLACK_BOT_TOKEN=xoxb-LIVE\n"
        "SLACK_SIGNING_SECRET=sig-LIVE\n"
        "ZEROCLAW_MODEL=claude-opus-4-5\n"
        "ZEROCLAW_PROVIDER=anthropic\n"
        "ZEROCLAW_PROVIDER_TIMEOUT_SECS=90\n"
        "ZEROCLAW_WORKSPACE=/zeroclaw/workspace\n"
    )


# ---------------------------------------------------------------------------
# existing behavior, preserved
# ---------------------------------------------------------------------------


def test_cmd_fetch_refuses_existing_without_force(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    assert cmd_fetch("acme", project_root=tmp_path) == 1


def test_cmd_fetch_scp_workspace_with_force(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    fake_run, calls = _fake_scp_runner(
        remote_files={
            "config.toml": _remote_config_toml(),
            "zeroclaw.env": _remote_env(),
        },
    )
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_fetch("acme", project_root=tmp_path, force=True) == 0
    assert calls[0][0] == "scp"
    assert "workspace/*.md" in calls[0][-2]


# ---------------------------------------------------------------------------
# new behavior: full round-trip
# ---------------------------------------------------------------------------


def test_fetch_pulls_workspace_md_files(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    fake_run, _ = _fake_scp_runner(
        remote_files={
            "config.toml": _remote_config_toml(),
            "zeroclaw.env": _remote_env(),
        },
        workspace_md={
            "AGENTS.md": "# AGENTS\nhello\n",
            "NOTES.md": "# notes\n",
        },
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = cmd_fetch("acme", project_root=tmp_path, force=True)
    assert rc == 0
    ws = tmp_path / "agents" / "acme" / "workspace"
    assert (ws / "AGENTS.md").read_text() == "# AGENTS\nhello\n"
    assert (ws / "NOTES.md").read_text() == "# notes\n"


def test_fetch_writes_reference_snapshot(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    cfg_text = _remote_config_toml()
    env_text = _remote_env()
    fake_run, _ = _fake_scp_runner(
        remote_files={"config.toml": cfg_text, "zeroclaw.env": env_text},
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = cmd_fetch("acme", project_root=tmp_path, force=True)
    assert rc == 0

    fetched = tmp_path / "agents" / "acme" / ".fetched"
    assert (fetched / "config.toml").read_text() == cfg_text
    assert (fetched / "zeroclaw.env").read_text() == env_text
    ts = (fetched / "FETCH_TIMESTAMP").read_text().strip()
    # ISO-8601 UTC e.g. 2026-05-18T12:34:56Z or with microseconds + +00:00.
    assert ts.startswith("20"), f"timestamp not iso-like: {ts!r}"
    assert "T" in ts


def test_fetched_env_is_mode_0600(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    fake_run, _ = _fake_scp_runner(
        remote_files={
            "config.toml": _remote_config_toml(),
            "zeroclaw.env": _remote_env(),
        },
    )
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_fetch("acme", project_root=tmp_path, force=True) == 0

    env_path = tmp_path / "agents" / "acme" / ".fetched" / "zeroclaw.env"
    mode = stat.S_IMODE(env_path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_fetch_merges_env_into_agent_toml(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    fake_run, _ = _fake_scp_runner(
        remote_files={
            "config.toml": _remote_config_toml(),
            "zeroclaw.env": _remote_env(),
        },
    )
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_fetch("acme", project_root=tmp_path, force=True) == 0

    agent_toml = tmp_path / "agents" / "acme" / "agent.toml"
    parsed = tomllib.loads(agent_toml.read_text())
    # secrets pulled back from zeroclaw.env
    assert parsed["llm"]["api_key"] == "sk-ant-LIVE"
    assert parsed["slack"]["bot_token"] == "xoxb-LIVE"
    assert parsed["slack"]["app_token"] == "xapp-LIVE"
    assert parsed["slack"]["signing_secret"] == "sig-LIVE"
    assert parsed["composio"]["api_key"] == "cmp-LIVE"
    # values from remote config.toml
    assert parsed["llm"]["provider"] == "anthropic"
    assert parsed["llm"]["model"] == "claude-opus-4-5"
    assert parsed["llm"]["timeout_secs"] == 90
    assert parsed["slack"]["enabled"] is True
    assert parsed["composio"]["enabled"] is True
    assert parsed["composio"]["allowed_tools"] == ["gmail.send", "gcal.events.create"]
    assert parsed["policy"]["require_approval_for"] == ["exec.shell"]
    assert parsed["policy"]["denied_domains"] == ["evil.example.com", "malware.test"]
    assert parsed["identity"]["display_name"] == "Acme Display"


def test_fetch_preserves_unknown_keys_in_agent_toml(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    agent_dir = _write_agent(tmp_path, "acme")
    # Append a custom section the writer must preserve verbatim.
    toml_path = agent_dir / "agent.toml"
    body = toml_path.read_text() + '\n[notes]\nfree_form = "keep me intact"\nlucky = 13\n'
    toml_path.write_text(body)

    fake_run, _ = _fake_scp_runner(
        remote_files={
            "config.toml": _remote_config_toml(),
            "zeroclaw.env": _remote_env(),
        },
    )
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_fetch("acme", project_root=tmp_path, force=True) == 0

    parsed = tomllib.loads(toml_path.read_text())
    assert parsed["notes"]["free_form"] == "keep me intact"
    assert parsed["notes"]["lucky"] == 13
    # And the merge still happened.
    assert parsed["llm"]["api_key"] == "sk-ant-LIVE"


# ---------------------------------------------------------------------------
# unrelated commands kept here from the original file
# ---------------------------------------------------------------------------


def test_cmd_remove_requires_slug_confirmation(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "wrong")
    assert cmd_remove("acme", project_root=tmp_path) == 1


def test_cmd_restore_moves_archive_back(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_restore("acme", ts="20260515T000000Z", project_root=tmp_path) == 0
    assert "mv .archive/acme-20260515T000000Z states/acme" in calls[0][-1]

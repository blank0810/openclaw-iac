from __future__ import annotations

import json
import socket
import subprocess
from datetime import datetime, timezone

import lib.audit
from lib.audit import append_audit_line, format_audit_line
from tests.test_config import _write_env, _write_agent


def test_format_audit_line_returns_jsonl_with_expected_keys():
    ts = datetime(2026, 5, 15, 1, 2, 3, tzinfo=timezone.utc)
    line = format_audit_line(
        ts=ts,
        actor="operator",
        cmd="agents deploy",
        agent="acme",
        image="ghcr.io/example/zc:1",
        result="ok",
    )
    assert line.endswith("\n")
    obj = json.loads(line)
    assert obj == {
        "ts": "2026-05-15T01:02:03Z",
        "actor": "operator",
        "cmd": "agents deploy",
        "agent": "acme",
        "image": "ghcr.io/example/zc:1",
        "result": "ok",
    }


def test_format_audit_line_defaults_ts():
    line = format_audit_line(
        actor="operator",
        cmd="backup",
        agent=None,
        image=None,
        result="ok",
    )
    obj = json.loads(line)
    assert obj["ts"].endswith("Z")
    assert obj["agent"] is None


def test_append_audit_line_ssh_appends_jsonl(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    from lib.config import load_config

    cfg = load_config(project_root=tmp_path)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    append_audit_line(
        cfg,
        actor="op",
        cmd="agents deploy",
        agent="acme",
        image="ghcr.io/example/zc:1",
        result="ok",
    )
    assert calls, "expected one ssh call"
    call = calls[0]
    assert call[0] == "ssh"
    # The command should append to /opt/zeroclaw/audit.log
    assert "/opt/zeroclaw/audit.log" in call[-1]
    # And carry a JSON object that round-trips
    # The payload sits between two single quotes in the remote command
    remote = call[-1]
    start = remote.find("{")
    end = remote.rfind("}") + 1
    obj = json.loads(remote[start:end])
    assert obj["actor"] == "op"
    assert obj["cmd"] == "agents deploy"
    assert obj["agent"] == "acme"
    assert obj["image"] == "ghcr.io/example/zc:1"
    assert obj["result"] == "ok"


def test_append_audit_line_returns_silently_on_ssh_failure(
    tmp_path, isolated_env, monkeypatch
):
    """Audit-log failure must NEVER fail the parent command."""
    _write_env(tmp_path)
    from lib.config import load_config

    cfg = load_config(project_root=tmp_path)

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Must not raise.
    append_audit_line(cfg, actor="op", cmd="x", agent=None, image=None, result="ok")


# ---------------------------------------------------------------------------
# Wiring tests: assert each mutating cmd calls append_audit_line with the
# expected (cmd, agent, image, result) tuple.
# ---------------------------------------------------------------------------

def _capture_audit(monkeypatch):
    """Replace append_audit_line with a recorder. Returns the list of calls."""
    calls: list[dict] = []

    def fake_append(cfg, *, actor, cmd, agent, image, result):
        calls.append(
            {"actor": actor, "cmd": cmd, "agent": agent, "image": image, "result": result}
        )

    monkeypatch.setattr("lib.server.append_audit_line", fake_append, raising=False)
    monkeypatch.setattr("lib.agents.append_audit_line", fake_append, raising=False)
    monkeypatch.setattr("lib.workspace.append_audit_line", fake_append, raising=False)
    monkeypatch.setattr("lib.backup.append_audit_line", fake_append, raising=False)
    return calls


def test_server_deploy_emits_audit(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: object())
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    calls = _capture_audit(monkeypatch)
    from lib.server import cmd_deploy

    assert cmd_deploy(project_root=tmp_path) == 0
    assert any(
        c["cmd"] == "server.deploy" and c["agent"] is None and c["image"] is None
        and c["result"] == "ok"
        for c in calls
    )


def test_server_deploy_emits_audit_fail_on_unreachable(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)

    def fail_connect(*args, **kwargs):
        raise OSError("closed")

    monkeypatch.setattr(socket, "create_connection", fail_connect)
    calls = _capture_audit(monkeypatch)
    from lib.server import cmd_deploy

    assert cmd_deploy(project_root=tmp_path) == 1
    assert any(
        c["cmd"] == "server.deploy" and c["result"] == "fail" for c in calls
    )


def test_agents_deploy_emits_audit(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")

    def fake_run(args, **kwargs):
        if args[0] == "ssh" and args[-1].startswith("cat "):
            return subprocess.CompletedProcess(args, 0, stdout="# AGENTS\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    calls = _capture_audit(monkeypatch)
    from lib.agents import cmd_deploy

    assert cmd_deploy("acme", project_root=tmp_path) == 0
    match = [c for c in calls if c["cmd"] == "agents.deploy"]
    assert match, f"expected agents.deploy audit; got {calls}"
    assert match[0]["agent"] == "acme"
    assert match[0]["image"] == "ghcr.io/example/zeroclaw:1.0"
    assert match[0]["result"] == "ok"


def test_agents_remove_emits_audit(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    monkeypatch.setattr("builtins.input", lambda _: "acme")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    calls = _capture_audit(monkeypatch)
    from lib.agents import cmd_remove

    assert cmd_remove("acme", project_root=tmp_path) == 0
    match = [c for c in calls if c["cmd"] == "agents.remove"]
    assert match
    assert match[0]["agent"] == "acme"
    assert match[0]["image"] is None
    assert match[0]["result"] == "ok"


def test_agents_restore_emits_audit(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    calls = _capture_audit(monkeypatch)
    from lib.agents import cmd_restore

    assert cmd_restore("acme", project_root=tmp_path) == 0
    match = [c for c in calls if c["cmd"] == "agents.restore"]
    assert match
    assert match[0]["agent"] == "acme"
    assert match[0]["image"] is None
    assert match[0]["result"] == "ok"


def test_workspace_deploy_emits_audit(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    agent_dir = _write_agent(tmp_path, "acme")
    (agent_dir / "workspace" / "AGENTS.md").write_text("# Agents")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    calls = _capture_audit(monkeypatch)
    from lib.workspace import cmd_deploy as workspace_deploy

    assert workspace_deploy("acme", project_root=tmp_path, force=True) == 0
    match = [c for c in calls if c["cmd"] == "workspace.deploy"]
    assert match
    assert match[0]["agent"] == "acme"
    assert match[0]["image"] is None
    assert match[0]["result"] == "ok"


def test_workspace_session_clear_emits_audit(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    calls = _capture_audit(monkeypatch)
    from lib.workspace import cmd_session_clear

    assert cmd_session_clear("acme", project_root=tmp_path) == 0
    match = [c for c in calls if c["cmd"] == "workspace.session_clear"]
    assert match
    assert match[0]["agent"] == "acme"
    assert match[0]["image"] is None
    assert match[0]["result"] == "ok"


def test_backup_emits_audit_one_per_agent(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    _write_agent(tmp_path, "globex")

    def fake_run(args, **kwargs):
        stdout = kwargs.get("stdout")
        if stdout:
            stdout.write(b"tar")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    calls = _capture_audit(monkeypatch)
    from lib.backup import cmd_backup

    assert cmd_backup(name=None, project_root=tmp_path) == 0
    backup_calls = [c for c in calls if c["cmd"] == "backup"]
    assert len(backup_calls) == 2
    names = sorted(c["agent"] for c in backup_calls)
    assert names == ["acme", "globex"]
    assert all(c["image"] is None for c in backup_calls)
    assert all(c["result"] == "ok" for c in backup_calls)


def test_backup_single_agent_emits_audit_with_agent_name(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")

    def fake_run(args, **kwargs):
        stdout = kwargs.get("stdout")
        if stdout:
            stdout.write(b"tar")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    calls = _capture_audit(monkeypatch)
    from lib.backup import cmd_backup

    assert cmd_backup(name="acme", project_root=tmp_path) == 0
    match = [c for c in calls if c["cmd"] == "backup"]
    assert match
    assert match[0]["agent"] == "acme"
    assert match[0]["image"] is None
    assert match[0]["result"] == "ok"

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

from lib.audit import append_audit_line, format_audit_line
from tests.test_config import _write_env


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

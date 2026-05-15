from __future__ import annotations

import subprocess

from lib.workspace import cmd_deploy, cmd_fetch, cmd_session_clear, cmd_status
from tests.test_config import _write_env, _write_tenant


def test_workspace_status_reports_local_only(tmp_path, isolated_env, monkeypatch, capsys):
    _write_env(tmp_path)
    tenant_dir = _write_tenant(tmp_path, "acme")
    (tenant_dir / "workspace" / "AGENTS.md").write_text("local")

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_status("acme", project_root=tmp_path) == 0
    assert "AGENTS.md local_only" in capsys.readouterr().out


def test_workspace_fetch_runs_scp(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_fetch("acme", project_root=tmp_path, force=True) == 0
    assert calls[0][0] == "scp"


def test_workspace_deploy_scp_local_markdowns(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    tenant_dir = _write_tenant(tmp_path, "acme")
    (tenant_dir / "workspace" / "AGENTS.md").write_text("# Agents")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_deploy("acme", project_root=tmp_path, force=True) == 0
    assert any(call[0] == "scp" for call in calls)


def test_workspace_session_clear_archives_and_restarts(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_session_clear("acme", project_root=tmp_path) == 0
    assert "workspace/sessions/archive" in calls[0][-1]
    assert "docker compose restart acme" in calls[0][-1]

from __future__ import annotations

import subprocess

from lib.agents import cmd_logs, cmd_shell, cmd_status
from tests.test_config import _write_env, _write_agent


def test_cmd_status_runs_remote_compose_ps(tmp_path, isolated_env, monkeypatch, capsys):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout='{"Service":"acme"}\n', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_status(project_root=tmp_path) == 0
    assert "docker compose ps --format json" in calls[0][-1]
    assert "acme" in capsys.readouterr().out


def test_cmd_shell_builds_interactive_exec(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_shell("acme", project_root=tmp_path) == 0
    assert "-t" in calls[0]
    assert "docker compose exec acme bash" in calls[0][-1]


def test_cmd_logs_builds_follow_flag(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_logs("acme", follow=True, project_root=tmp_path) == 0
    assert "docker compose logs -f acme" in calls[0][-1]

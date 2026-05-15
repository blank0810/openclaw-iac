from __future__ import annotations

import socket
import subprocess

from lib.server import cmd_deploy
from tests.test_config import _write_env


def test_server_deploy_tcp_unreachable_returns_1(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)

    def fail_connect(*args, **kwargs):
        raise OSError("closed")

    monkeypatch.setattr(socket, "create_connection", fail_connect)
    assert cmd_deploy(project_root=tmp_path) == 1


def test_server_deploy_user_ok_runs_runtime_only(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: object())
    calls: list[str] = []

    def fake_run(args, **kwargs):
        if args[0] == "ssh":
            return subprocess.CompletedProcess(args, 0)
        calls.append(args[-1])
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_deploy(project_root=tmp_path) == 0
    assert calls == ["lib/deploy_runtime.py"]


def test_server_deploy_bootstrap_path_has_deploy_key_gate(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: object())
    ssh_results = iter([1, 0, 0])
    deploys: list[str] = []

    def fake_run(args, **kwargs):
        if args[0] == "ssh":
            return subprocess.CompletedProcess(args, next(ssh_results))
        deploys.append(args[-1])
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_deploy(project_root=tmp_path) == 0
    assert deploys == [
        "lib/bootstrap_prepare.py",
        "lib/bootstrap_hardening.py",
        "lib/deploy_runtime.py",
    ]


def test_server_deploy_halts_when_neither_auth_path_works(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: object())
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1),
    )
    assert cmd_deploy(project_root=tmp_path) == 1

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


def test_server_deploy_refuses_hardening_when_deploy_key_check_fails(
    tmp_path, isolated_env, monkeypatch, capsys
):
    _write_env(tmp_path)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: object())
    # Call order in lib/server.py:
    #   1. _ssh_check(deploy_user, 2222) → 1 (fail) — enters bootstrap branch
    #   2. _ssh_check(root, 22)          → 0 (ok)   — auth gate passes
    #   3. _run_pyinfra(bootstrap_prepare) — pyinfra subprocess, returncode 0
    #   4. _ssh_check(deploy_user, 2222) → 1 (fail) — post-prepare gate trips
    ssh_results = iter([1, 0, 1])
    deploys: list[str] = []

    def fake_run(args, **kwargs):
        if args[0] == "ssh":
            return subprocess.CompletedProcess(args, next(ssh_results))
        deploys.append(args[-1])
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = cmd_deploy(project_root=tmp_path)

    assert result == 1
    assert "lib/bootstrap_prepare.py" in deploys
    assert "lib/bootstrap_hardening.py" not in deploys
    assert "lib/deploy_runtime.py" not in deploys
    captured = capsys.readouterr()
    assert "refusing hardening" in captured.out

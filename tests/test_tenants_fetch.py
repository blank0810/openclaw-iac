from __future__ import annotations

import subprocess

from lib.tenants import cmd_fetch, cmd_remove, cmd_restore
from tests.test_config import _write_env, _write_tenant


def test_cmd_fetch_refuses_existing_without_force(tmp_path, isolated_env):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    assert cmd_fetch("acme", project_root=tmp_path) == 1


def test_cmd_fetch_scp_workspace_with_force(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_fetch("acme", project_root=tmp_path, force=True) == 0
    assert calls[0][0] == "scp"
    assert "workspace/*.md" in calls[0][-2]


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

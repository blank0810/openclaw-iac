from __future__ import annotations

import subprocess

from lib.backup import cmd_backup
from tests.test_config import _write_env, _write_tenant


def test_cmd_backup_one_tenant_excludes_env(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        stdout = kwargs.get("stdout")
        if stdout:
            stdout.write(b"tar")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_backup(name="acme", project_root=tmp_path) == 0
    assert "--exclude=zeroclaw.env" in calls[0][-1]
    assert list((tmp_path / "backups" / "acme").glob("*.tar.gz"))


def test_cmd_backup_all_enabled_tenants(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    _write_tenant(tmp_path, "globex")
    count = 0

    def fake_run(args, **kwargs):
        nonlocal count
        count += 1
        stdout = kwargs.get("stdout")
        if stdout:
            stdout.write(b"tar")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_backup(name=None, project_root=tmp_path) == 0
    assert count == 2

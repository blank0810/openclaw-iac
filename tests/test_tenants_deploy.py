from __future__ import annotations

import subprocess

from lib.tenants import cmd_deploy
from tests.test_config import _write_env, _write_tenant


def test_cmd_deploy_renders_uploads_and_recreates(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if args[0] == "ssh" and args[-1].startswith("cat "):
            return subprocess.CompletedProcess(args, 0, stdout="# AGENTS\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_deploy("acme", project_root=tmp_path) == 0

    staged = tmp_path / ".runtime-temp" / "acme"
    assert "ANTHROPIC_API_KEY=sk-ant-acme" in (staged / "zeroclaw.env").read_text()
    assert "sk-ant-acme" not in (staged / "config.toml").read_text()
    assert any(call[0] == "scp" and "zeroclaw.env" in call[-2] for call in calls)
    assert any("chmod 0600" in call[-1] for call in calls if call[0] == "ssh")
    assert any("docker compose up -d --force-recreate acme" in call[-1] for call in calls)

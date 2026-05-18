from __future__ import annotations

import subprocess

from lib import agents as agents_module
from lib.agents import cmd_deploy
from tests.test_config import _write_env, _write_agent


def test_cmd_deploy_renders_uploads_and_recreates(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    calls: list[list[str]] = []
    scp_payloads: dict[str, str] = {}

    original_scp_to = agents_module._scp_to

    def spying_scp_to(cfg, local, remote):
        # Snapshot the rendered file contents at SCP-time, since cmd_deploy
        # now deletes the secrets file after deploy to avoid leaking it on
        # the deploy host.
        if local.exists():
            scp_payloads[local.name] = local.read_text()
        calls.append(["scp", "-P", str(cfg.ssh_port), str(local), remote])
        return subprocess.CompletedProcess(
            ["scp", str(local), remote], 0, stdout="", stderr=""
        )

    monkeypatch.setattr(agents_module, "_scp_to", spying_scp_to)

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if args[0] == "ssh" and "sudo cat" in args[-1]:
            return subprocess.CompletedProcess(args, 0, stdout="# AGENTS\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_deploy("acme", project_root=tmp_path) == 0

    assert "ZEROCLAW_API_KEY=sk-ant-acme" in scp_payloads["zeroclaw.env"]
    assert "sk-ant-acme" not in scp_payloads["config.toml"]
    assert any(call[0] == "scp" and "zeroclaw.env" in call[-2] for call in calls)
    assert any("chmod 0600" in call[-1] for call in calls if call[0] == "ssh")
    assert any("docker compose up -d --force-recreate acme" in call[-1] for call in calls)
    # New layout assertions: config.toml goes through /tmp + sudo mv to .zeroclaw/
    assert any(
        call[0] == "scp" and "/tmp/zeroclawctl-acme-config.toml" in call[-1]
        for call in calls
    ), "config.toml must scp to /tmp first (state dir's .zeroclaw is 65534-owned)"
    assert any(
        call[0] == "ssh" and ".zeroclaw/config.toml" in call[-1] and "sudo mv" in call[-1]
        for call in calls
    ), "config.toml must sudo-mv into .zeroclaw/ subdir"
    assert any(
        call[0] == "ssh" and "sudo chown 65534:65534" in call[-1]
        and ".zeroclaw" in call[-1]
        for call in calls
    ), "container must own .zeroclaw/ + its config.toml"
    assert any(
        call[0] == "ssh" and "sudo mkdir -p" in call[-1] and "/.zeroclaw" in call[-1]
        for call in calls
    ), "cmd_deploy must create .zeroclaw subdir (idempotent)"

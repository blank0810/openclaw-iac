"""Security regression tests: zeroclaw.env staging file is mode 0600 and removed after deploy."""
from __future__ import annotations

import stat
import subprocess

from lib import agents as agents_module
from lib.agents import cmd_deploy
from tests.test_config import _write_env, _write_agent


def test_zeroclaw_env_removed_from_runtime_temp_after_deploy(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")

    def fake_run(args, **kwargs):
        if args[0] == "ssh" and "sudo cat" in args[-1]:
            return subprocess.CompletedProcess(args, 0, stdout="# AGENTS\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_deploy("acme", project_root=tmp_path) == 0

    staged_env = tmp_path / ".runtime-temp" / "acme" / "zeroclaw.env"
    assert not staged_env.exists(), (
        "SECURITY: zeroclaw.env must be removed from .runtime-temp after deploy "
        f"(still present at {staged_env})"
    )


def test_zeroclaw_env_has_mode_0600_during_scp(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")

    observed_modes: list[int] = []
    original_scp_to = agents_module._scp_to

    def spying_scp_to(cfg, local, remote):
        if local.name == "zeroclaw.env" and local.exists():
            observed_modes.append(stat.S_IMODE(local.stat().st_mode))
        return subprocess.CompletedProcess(
            ["scp", str(local), remote], 0, stdout="", stderr=""
        )

    monkeypatch.setattr(agents_module, "_scp_to", spying_scp_to)

    def fake_run(args, **kwargs):
        if args[0] == "ssh" and "sudo cat" in args[-1]:
            return subprocess.CompletedProcess(args, 0, stdout="# AGENTS\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_deploy("acme", project_root=tmp_path) == 0

    assert observed_modes, "expected _scp_to to be called for zeroclaw.env"
    for mode in observed_modes:
        assert mode == 0o600, (
            f"SECURITY: zeroclaw.env staged file must be mode 0600, got {oct(mode)}"
        )


def test_zeroclaw_env_removed_even_if_later_step_raises(tmp_path, isolated_env, monkeypatch):
    """If a post-SCP step raises, the secrets file must still be cleaned up."""
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")

    call_count = {"n": 0}

    def fake_run(args, **kwargs):
        call_count["n"] += 1
        # Make the final docker compose up step raise.
        if args[0] == "ssh" and "docker compose up" in args[-1]:
            raise RuntimeError("boom")
        if args[0] == "ssh" and "sudo cat" in args[-1]:
            return subprocess.CompletedProcess(args, 0, stdout="# AGENTS\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    try:
        cmd_deploy("acme", project_root=tmp_path)
    except RuntimeError:
        pass

    staged_env = tmp_path / ".runtime-temp" / "acme" / "zeroclaw.env"
    assert not staged_env.exists(), (
        "SECURITY: zeroclaw.env must be removed even when a later deploy step raises"
    )

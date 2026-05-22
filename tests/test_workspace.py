from __future__ import annotations

import hashlib
import subprocess

from lib.workspace import cmd_deploy, cmd_fetch, cmd_session_clear, cmd_status
from tests.test_config import _write_env, _write_agent


def _ssh_dispatcher(ls_stdout: str = "", sha_stdout: str = ""):
    """Return a fake subprocess.run that distinguishes the two SSH calls in cmd_status.

    cmd_status issues exactly two SSH commands:
      1) `ls {workspace}/*.md ...`  — used to enumerate remote filenames
      2) `sha256sum {workspace}/*.md ...` — used for content equality

    The dispatcher inspects the inline command string (the final argv element
    after `ssh -p PORT user@host <command>`) and returns the matching stdout.
    """

    def fake_run(args, **kwargs):
        # SSH calls are: ["ssh", "-p", port, "user@host", "<command>"]
        command = args[-1] if isinstance(args, (list, tuple)) and args else ""
        if "sha256sum" in command:
            stdout = sha_stdout
        elif command.startswith("ls "):
            stdout = ls_stdout
        else:
            stdout = ""
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    return fake_run


def test_workspace_status_reports_local_only(tmp_path, isolated_env, monkeypatch, capsys):
    _write_env(tmp_path)
    agent_dir = _write_agent(tmp_path, "acme")
    (agent_dir / "workspace" / "AGENTS.md").write_text("local")

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_status("acme", project_root=tmp_path) == 0
    assert "AGENTS.md local_only" in capsys.readouterr().out


def test_status_reports_same_when_hashes_match(tmp_path, isolated_env, monkeypatch, capsys):
    _write_env(tmp_path)
    agent_dir = _write_agent(tmp_path, "acme")
    content = b"# Agents\nshared content\n"
    (agent_dir / "workspace" / "AGENTS.md").write_bytes(content)
    remote_path = "/opt/zeroclaw/states/acme/workspace/AGENTS.md"
    digest = hashlib.sha256(content).hexdigest()

    monkeypatch.setattr(
        subprocess,
        "run",
        _ssh_dispatcher(
            ls_stdout=f"{remote_path}\n",
            sha_stdout=f"{digest}  {remote_path}\n",
        ),
    )
    assert cmd_status("acme", project_root=tmp_path) == 0
    out = capsys.readouterr().out
    assert "AGENTS.md same" in out
    assert "drift" not in out


def test_status_reports_drift_when_hashes_differ(tmp_path, isolated_env, monkeypatch, capsys):
    _write_env(tmp_path)
    agent_dir = _write_agent(tmp_path, "acme")
    (agent_dir / "workspace" / "AGENTS.md").write_bytes(b"local body\n")
    remote_path = "/opt/zeroclaw/states/acme/workspace/AGENTS.md"
    remote_digest = hashlib.sha256(b"different remote body\n").hexdigest()

    monkeypatch.setattr(
        subprocess,
        "run",
        _ssh_dispatcher(
            ls_stdout=f"{remote_path}\n",
            sha_stdout=f"{remote_digest}  {remote_path}\n",
        ),
    )
    assert cmd_status("acme", project_root=tmp_path) == 0
    out = capsys.readouterr().out
    assert "AGENTS.md drift" in out
    assert "same" not in out


def test_status_reports_local_only(tmp_path, isolated_env, monkeypatch, capsys):
    _write_env(tmp_path)
    agent_dir = _write_agent(tmp_path, "acme")
    (agent_dir / "workspace" / "FOO.md").write_text("only local")

    monkeypatch.setattr(subprocess, "run", _ssh_dispatcher(ls_stdout="", sha_stdout=""))
    assert cmd_status("acme", project_root=tmp_path) == 0
    assert "FOO.md local_only" in capsys.readouterr().out


def test_status_reports_remote_only(tmp_path, isolated_env, monkeypatch, capsys):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    remote_path = "/opt/zeroclaw/states/acme/workspace/BAR.md"
    digest = hashlib.sha256(b"remote only\n").hexdigest()

    monkeypatch.setattr(
        subprocess,
        "run",
        _ssh_dispatcher(
            ls_stdout=f"{remote_path}\n",
            sha_stdout=f"{digest}  {remote_path}\n",
        ),
    )
    assert cmd_status("acme", project_root=tmp_path) == 0
    assert "BAR.md remote_only" in capsys.readouterr().out


def test_status_mixed_states(tmp_path, isolated_env, monkeypatch, capsys):
    _write_env(tmp_path)
    agent_dir = _write_agent(tmp_path, "acme")
    workspace = agent_dir / "workspace"

    # same: matching bytes on both sides
    same_bytes = b"# AGENTS\nidentical\n"
    (workspace / "AGENTS.md").write_bytes(same_bytes)
    same_digest = hashlib.sha256(same_bytes).hexdigest()

    # drift: differing bytes
    (workspace / "DRIFT.md").write_bytes(b"local version\n")
    drift_remote_digest = hashlib.sha256(b"remote version\n").hexdigest()

    # local_only
    (workspace / "FOO.md").write_text("only local")

    # remote_only
    remote_only_digest = hashlib.sha256(b"only remote\n").hexdigest()

    base = "/opt/zeroclaw/states/acme/workspace"
    ls_stdout = "\n".join(
        [
            f"{base}/AGENTS.md",
            f"{base}/DRIFT.md",
            f"{base}/BAR.md",
        ]
    ) + "\n"
    sha_stdout = "\n".join(
        [
            f"{same_digest}  {base}/AGENTS.md",
            f"{drift_remote_digest}  {base}/DRIFT.md",
            f"{remote_only_digest}  {base}/BAR.md",
        ]
    ) + "\n"

    monkeypatch.setattr(
        subprocess,
        "run",
        _ssh_dispatcher(ls_stdout=ls_stdout, sha_stdout=sha_stdout),
    )
    assert cmd_status("acme", project_root=tmp_path) == 0
    out = capsys.readouterr().out
    assert "AGENTS.md same" in out
    assert "DRIFT.md drift" in out
    assert "FOO.md local_only" in out
    assert "BAR.md remote_only" in out


def test_workspace_fetch_runs_scp(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_fetch("acme", project_root=tmp_path, force=True) == 0
    assert calls[0][0] == "scp"


def test_workspace_deploy_scp_local_markdowns(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    agent_dir = _write_agent(tmp_path, "acme")
    (agent_dir / "workspace" / "AGENTS.md").write_text("# Agents")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_deploy("acme", project_root=tmp_path, force=True) == 0
    assert any(call[0] == "scp" for call in calls)


def test_workspace_session_clear_archives_and_restarts(tmp_path, isolated_env, monkeypatch):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cmd_session_clear("acme", project_root=tmp_path) == 0
    assert "workspace/sessions/archive" in calls[0][-1]
    assert "docker compose restart acme" in calls[0][-1]

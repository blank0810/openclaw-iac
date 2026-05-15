from __future__ import annotations

import subprocess
import sys


def _run_help(*args):
    return subprocess.run(
        [sys.executable, "zeroclawctl.py", *args],
        check=False,
        text=True,
        capture_output=True,
    )


def test_top_level_help_lists_namespaces():
    result = _run_help("--help")
    assert result.returncode == 0
    for name in ("server", "tenants", "workspace", "audit", "backup"):
        assert name in result.stdout


def test_tenants_help_lists_commands():
    result = _run_help("tenants", "--help")
    assert result.returncode == 0
    for name in ("create", "deploy", "status", "fetch", "shell", "remove", "restore", "logs"):
        assert name in result.stdout


def test_workspace_help_lists_commands():
    result = _run_help("workspace", "--help")
    assert result.returncode == 0
    for name in ("status", "fetch", "deploy", "session-clear"):
        assert name in result.stdout

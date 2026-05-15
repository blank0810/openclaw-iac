from __future__ import annotations

from lib.config_patch import default_exec_deny_patterns


def test_default_exec_deny_patterns_are_immutable_tuple():
    assert isinstance(default_exec_deny_patterns(), tuple)


def test_default_exec_deny_patterns_include_env_commands():
    patterns = default_exec_deny_patterns()
    assert "env" in patterns
    assert "printenv" in patterns


def test_default_exec_deny_patterns_include_secret_file_reads():
    patterns = default_exec_deny_patterns()
    assert "cat *.env" in patterns
    assert "cat */zeroclaw.env" in patterns


def test_default_exec_deny_patterns_include_runtime_env_exfiltration():
    patterns = default_exec_deny_patterns()
    assert "python -c*os.environ*" in patterns
    assert "curl*169.254.169.254*" in patterns

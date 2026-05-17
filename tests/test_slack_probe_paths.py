"""Verify slack-probe log path is consistent across template + pyinfra pre-creation.

Mismatched paths cause systemd unit start failures (status=226/NAMESPACE)
because ProtectSystem=strict + ReadWritePaths=<missing-path> is fatal.
"""
from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader


@pytest.fixture
def env():
    return Environment(loader=FileSystemLoader("templates"))


def _service_name(agent_name: str) -> str:
    # Mirror lib/slack_probe.py:44
    return f"zeroclaw-slack-probe-{agent_name}"


def _expected_log_path(agent_name: str) -> str:
    # Mirror lib/slack_probe.py:47 — `/var/log/{service_name}.log`
    return f"/var/log/{_service_name(agent_name)}.log"


def test_probe_service_log_paths_match_pyinfra_precreate(env):
    agent = {"name": "fakeagent", "state_dir": "fakeagent"}
    rendered = env.get_template("systemd/zeroclaw-slack-probe.service.j2").render(agent=agent)

    expected = _expected_log_path(agent["name"])
    # Each of these must agree with the path pyinfra pre-creates under
    # ReadWritePaths=, otherwise systemd refuses to start with status=226/NAMESPACE.
    assert f"PROBE_LOG_FILE={expected}" in rendered, (
        f"PROBE_LOG_FILE env var must point at {expected}; got:\n{rendered}"
    )
    # ReadWritePaths line must list the same canonical log path
    rwp_line = next(
        (line for line in rendered.splitlines() if line.startswith("ReadWritePaths=")),
        None,
    )
    assert rwp_line is not None, "service template missing ReadWritePaths= line"
    assert expected in rwp_line, (
        f"ReadWritePaths line must include {expected}; got: {rwp_line}"
    )

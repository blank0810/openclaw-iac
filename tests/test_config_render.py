from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader

from tests.test_agent_env import _agent


@pytest.fixture
def env():
    return Environment(loader=FileSystemLoader("templates"))


def test_config_toml_renders_identity(env):
    out = env.get_template("config.toml.j2").render(
        agent=_agent(), exec_deny_patterns=[]
    )
    assert 'name = "acme"' in out


def test_config_toml_renders_provider_metadata(env):
    out = env.get_template("config.toml.j2").render(
        agent=_agent(), exec_deny_patterns=[]
    )
    assert 'provider = "anthropic"' in out
    assert 'model = "claude-sonnet-4-5"' in out


def test_config_toml_renders_exec_deny_when_enabled(env):
    agent = _agent(exec_enabled=True)
    out = env.get_template("config.toml.j2").render(
        agent=agent, exec_deny_patterns=["env", "printenv"]
    )
    assert "[security.exec]" in out
    assert '"env"' in out


def test_config_toml_omits_exec_section_when_disabled(env):
    out = env.get_template("config.toml.j2").render(
        agent=_agent(), exec_deny_patterns=[]
    )
    assert "[security.exec]" not in out

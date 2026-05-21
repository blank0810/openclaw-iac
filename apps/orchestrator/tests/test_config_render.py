from pathlib import Path

from apps.orchestrator.config_render import render_agent_config
from tests.test_config import _write_env, _write_agent  # existing helpers
from lib.config import load_config


def _agent(tmp_path):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")  # writes agents/acme/agent.toml
    return load_config(tmp_path).agents[0]


def test_render_writes_config_toml_in_zeroclaw_subdir(tmp_path):
    agent = _agent(tmp_path)
    state = tmp_path / "state"
    render_agent_config(agent, state, project_root=tmp_path)
    cfg = (state / ".zeroclaw" / "config.toml").read_text()
    assert "schema_version = 2" in cfg
    assert "[autonomy]" in cfg


def test_render_writes_workspace_markdowns(tmp_path):
    agent = _agent(tmp_path)
    state = tmp_path / "state"
    render_agent_config(agent, state, project_root=tmp_path)
    ws = state / "workspace"
    assert (ws / "IDENTITY.md").exists()
    assert (ws / "AGENTS.md").exists()


def test_render_injects_policy_block_into_agents_md(tmp_path):
    agent = _agent(tmp_path)
    state = tmp_path / "state"
    render_agent_config(agent, state, project_root=tmp_path)
    agents_md = (state / "workspace" / "AGENTS.md").read_text()
    assert "BEGIN MANAGED SECURITY POLICY" in agents_md


def test_render_returns_env_with_zeroclaw_api_key(tmp_path):
    agent = _agent(tmp_path)  # _write_agent sets an anthropic key
    env = render_agent_config(agent, tmp_path / "state", project_root=tmp_path)
    assert env["ZEROCLAW_PROVIDER"] == agent.llm.provider
    assert "ZEROCLAW_API_KEY" in env  # only when api_key present


def test_render_no_llm_key_in_config_toml(tmp_path):
    agent = _agent(tmp_path)
    state = tmp_path / "state"
    render_agent_config(agent, state, project_root=tmp_path)
    cfg = (state / ".zeroclaw" / "config.toml").read_text()
    assert agent.llm.api_key not in cfg  # env-only

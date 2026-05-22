"""agents create renders templates/workspace/*.j2 into the new agent's workspace.

Before this wiring, new agents shipped with 1-line placeholder .md files and
booted with no identity content. After this wiring, each new agent gets its
own IDENTITY.md / SOUL.md / TOOLS.md / etc. rendered from agent.toml values.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from lib.agents import _render_workspace_templates, cmd_create


def _minimal_agent_toml() -> str:
    return (
        "[identity]\n"
        'name = "rendertest"\n'
        'display_name = "RenderTest"\n'
        "enabled = true\n"
        'state_dir = "rendertest"\n'
        "\n[runtime]\n"
        "host_port = 0\n"
        "\n[llm]\n"
        'provider = "anthropic"\n'
        'model = "claude-haiku-4-5"\n'
        'api_key = "sk-ant-fake"\n'
        "timeout_secs = 60\n"
        "\n[slack]\n"
        "enabled = false\n"
        'bot_token = ""\n'
        'app_token = ""\n'
        '\n[composio]\n'
        "enabled = false\n"
        '\n[autonomy]\n'
        'level = "supervised"\n'
        "auto_approve = []\n"
        '\n[exec]\n'
        "enabled = false\n"
        "\n[policy]\n"
        "require_approval_for = []\n"
        "denied_domains = []\n"
    )


def _scaffold(root: Path, slug: str, agent_toml_text: str | None = None) -> Path:
    agents = root / "agents"
    target = agents / slug
    target.mkdir(parents=True)
    (target / "agent.toml").write_text(agent_toml_text or _minimal_agent_toml())
    return target


def test_render_writes_seven_workspace_files(tmp_path):
    target = _scaffold(tmp_path, "rendertest")
    _render_workspace_templates(tmp_path, target)
    workspace = target / "workspace"
    expected = {"AGENTS.md", "BOOTSTRAP.md", "HEARTBEAT.md", "IDENTITY.md",
                "SOUL.md", "TOOLS.md", "USER.md"}
    rendered = {p.name for p in workspace.glob("*.md")}
    assert expected <= rendered


def test_render_substitutes_display_name_in_identity(tmp_path):
    target = _scaffold(tmp_path, "rendertest")
    _render_workspace_templates(tmp_path, target)
    identity = (target / "workspace" / "IDENTITY.md").read_text()
    assert "RenderTest" in identity, "display_name must substitute into IDENTITY.md"
    # Generic placeholder should be gone
    assert "REPLACE_ME" not in identity


def test_render_reflects_provider_choice(tmp_path):
    target = _scaffold(tmp_path, "rendertest")
    _render_workspace_templates(tmp_path, target)
    identity = (target / "workspace" / "IDENTITY.md").read_text()
    # Anthropic-direct path should be referenced (not LiteLLM proxy)
    assert "Anthropic" in identity
    assert "LiteLLM" not in identity or "bypassed" in identity


def test_render_litellm_provider_changes_identity_wording(tmp_path):
    """Switching provider to litellm flips IDENTITY.md to describe the proxy path."""
    toml = _minimal_agent_toml().replace('provider = "anthropic"', 'provider = "litellm"')
    target = _scaffold(tmp_path, "rendertest", toml)
    _render_workspace_templates(tmp_path, target)
    identity = (target / "workspace" / "IDENTITY.md").read_text()
    assert "LiteLLM" in identity


def test_render_agents_md_keeps_managed_policy_markers(tmp_path):
    """AGENTS.md must keep the BEGIN/END markers empty so cmd_deploy can later
    inject the operator-defined policy block into them."""
    target = _scaffold(tmp_path, "rendertest")
    _render_workspace_templates(tmp_path, target)
    agents_md = (target / "workspace" / "AGENTS.md").read_text()
    assert "BEGIN MANAGED SECURITY POLICY" in agents_md
    assert "END MANAGED SECURITY POLICY" in agents_md


def test_render_no_op_on_malformed_agent_toml(tmp_path):
    """Legacy minimal scaffolds (e.g. existing test_agents_create fixtures with
    flat-toml templates) must not crash render — graceful no-op."""
    target = tmp_path / "agents" / "broken"
    target.mkdir(parents=True)
    (target / "agent.toml").write_text('name = "broken"\nstate_dir = "broken"\n')
    # No [identity] section -> _parse_agent_toml raises KeyError
    _render_workspace_templates(tmp_path, target)
    # No exception, no workspace files created
    workspace = target / "workspace"
    if workspace.exists():
        assert not any(workspace.glob("*.md")), "no .md should be written when render fails"


def test_cmd_create_end_to_end_renders_workspace(tmp_path):
    """Full path: agents create -> renders workspace from real templates."""
    template_dir = tmp_path / "agents" / "_template"
    (template_dir / "workspace").mkdir(parents=True)
    (template_dir / "agent.toml").write_text(
        _minimal_agent_toml()
        .replace('"rendertest"', '"REPLACE_ME"', 2)
        .replace('"RenderTest"', '"REPLACE_ME"')
    )
    (template_dir / "workspace" / "AGENTS.md").write_text("placeholder\n")

    rc = cmd_create(
        "fully-rendered",
        display_name="FullyRendered",
        project_root=tmp_path,
    )
    assert rc == 0

    workspace = tmp_path / "agents" / "fully-rendered" / "workspace"
    identity = (workspace / "IDENTITY.md").read_text()
    assert "FullyRendered" in identity
    # Was overwritten — the placeholder AGENTS.md is no longer "placeholder\n"
    agents_md = (workspace / "AGENTS.md").read_text()
    assert agents_md != "placeholder\n"
    assert "BEGIN MANAGED SECURITY POLICY" in agents_md

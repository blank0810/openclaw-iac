from __future__ import annotations

from pathlib import Path

from lib.agents import cmd_create


def _template(root: Path) -> None:
    base = root / "agents" / "_template"
    (base / "workspace").mkdir(parents=True)
    (base / "agent.toml").write_text('name = "REPLACE_ME"\nstate_dir = "REPLACE_ME"\n')
    (base / "workspace" / "AGENTS.md").write_text("# REPLACE_ME\n")


def test_cmd_create_copies_template_and_replaces_slug(tmp_path):
    _template(tmp_path)
    assert cmd_create(name="acme", project_root=tmp_path) == 0
    agent = tmp_path / "agents" / "acme"
    assert (agent / "agent.toml").exists()
    assert 'name = "acme"' in (agent / "agent.toml").read_text()


def test_cmd_create_refuses_existing_agent(tmp_path):
    _template(tmp_path)
    assert cmd_create(name="acme", project_root=tmp_path) == 0
    assert cmd_create(name="acme", project_root=tmp_path) == 1


def test_cmd_create_refuses_invalid_slug(tmp_path):
    _template(tmp_path)
    assert cmd_create(name="Bad_Name", project_root=tmp_path) == 1

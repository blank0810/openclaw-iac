from __future__ import annotations

from pathlib import Path

from lib.tenants import cmd_create


def _template(root: Path) -> None:
    base = root / "tenants" / "_template"
    (base / "workspace").mkdir(parents=True)
    (base / "tenant.toml").write_text('name = "REPLACE_ME"\nstate_dir = "REPLACE_ME"\n')
    (base / "cron.toml").write_text("")
    (base / "workspace" / "AGENTS.md").write_text("# REPLACE_ME\n")


def test_cmd_create_copies_template_and_replaces_slug(tmp_path):
    _template(tmp_path)
    assert cmd_create(name="acme", project_root=tmp_path) == 0
    tenant = tmp_path / "tenants" / "acme"
    assert (tenant / "tenant.toml").exists()
    assert 'name = "acme"' in (tenant / "tenant.toml").read_text()


def test_cmd_create_refuses_existing_tenant(tmp_path):
    _template(tmp_path)
    assert cmd_create(name="acme", project_root=tmp_path) == 0
    assert cmd_create(name="acme", project_root=tmp_path) == 1


def test_cmd_create_refuses_invalid_slug(tmp_path):
    _template(tmp_path)
    assert cmd_create(name="Bad_Name", project_root=tmp_path) == 1

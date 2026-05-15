from __future__ import annotations

from lib.inventory import build_inventory_data


def test_build_inventory_includes_host_facts(tmp_path, isolated_env, monkeypatch):
    from tests.test_config import _write_env, _write_tenant

    _write_env(tmp_path)
    _write_tenant(tmp_path, "acme")
    monkeypatch.chdir(tmp_path)
    data = build_inventory_data(
        project_root=tmp_path,
        ssh_user="overlord101",
        ssh_key=str(tmp_path / "fake-deploy.pem"),
    )
    assert data["deploy_user"] == "overlord101"
    assert data["ssh_port"] == 2222
    assert any(t["name"] == "acme" for t in data["tenants"])

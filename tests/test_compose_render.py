from __future__ import annotations

import pytest
from jinja2 import Environment, FileSystemLoader


@pytest.fixture
def env():
    return Environment(loader=FileSystemLoader("templates"))


def _fake_config(tenants):
    class _C:
        zeroclaw_image = "ghcr.io/example/zc:1.0"

    config = _C()
    config.tenants = tenants
    return config


def _fake_tenant(**overrides):
    defaults = dict(
        name="acme",
        state_dir="acme",
        enabled=True,
        image=None,
        host_port=0,
    )
    defaults.update(overrides)

    class _T:
        pass

    tenant = _T()
    for key, value in defaults.items():
        setattr(tenant, key, value)
    return tenant


def test_compose_renders_one_service_per_enabled_tenant(env):
    cfg = _fake_config([_fake_tenant(name="acme"), _fake_tenant(name="globex")])
    out = env.get_template("docker-compose.yml.j2").render(config=cfg)
    assert "  acme:" in out
    assert "  globex:" in out


def test_compose_omits_disabled_tenants(env):
    cfg = _fake_config(
        [_fake_tenant(name="acme"), _fake_tenant(name="dormant", enabled=False)]
    )
    out = env.get_template("docker-compose.yml.j2").render(config=cfg)
    assert "  acme:" in out
    assert "  dormant:" not in out


def test_compose_renders_hardening_flags_per_service(env):
    cfg = _fake_config([_fake_tenant(name="acme")])
    out = env.get_template("docker-compose.yml.j2").render(config=cfg)
    assert "read_only: true" in out
    assert "no-new-privileges:true" in out
    assert "cap_drop:" in out and "ALL" in out
    assert "tmpfs:" in out


def test_compose_only_exposes_port_when_set(env):
    cfg = _fake_config(
        [
            _fake_tenant(name="quiet", host_port=0),
            _fake_tenant(name="loud", host_port=18791),
        ]
    )
    out = env.get_template("docker-compose.yml.j2").render(config=cfg)
    assert "127.0.0.1:18791:42617" in out
    assert "quiet:" in out


def test_compose_renders_per_tenant_network(env):
    cfg = _fake_config([_fake_tenant(name="acme"), _fake_tenant(name="globex")])
    out = env.get_template("docker-compose.yml.j2").render(config=cfg)
    assert "zc-acme:" in out
    assert "zc-globex:" in out

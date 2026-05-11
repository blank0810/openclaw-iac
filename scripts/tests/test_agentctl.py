import pytest
try:
    import tomllib
except ImportError:
    import tomli as tomllib

from agentctl import SlugError, init_tenant, validate_slug


@pytest.mark.parametrize(
    "slug",
    [
        "agent-edgar",
        "agent-chaos",
        "agent-a1",
        "agent-z9-test",
        "agent-" + "x" * 25,
    ],
)
def test_valid_slugs(slug):
    validate_slug(slug)


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "edgar",
        "agent-",
        "agent-Edgar",
        "agent--edgar",
        "agent-edgar-",
        "agent-" + "x" * 30,
        "agent-edgar/etc/passwd",
    ],
)
def test_invalid_slugs(slug):
    with pytest.raises(SlugError):
        validate_slug(slug)


def test_init_creates_files(tmp_path):
    repo_root = tmp_path
    template_dir = repo_root / "tenants" / "_template"
    template_dir.mkdir(parents=True)
    (template_dir / "tenant.toml.example").write_text(
        'agent_name = "Template"\n'
        'zeroclaw_provider = "{{provider}}"\n'
    )
    (template_dir / ".env.example").write_text("SLACK_BOT_TOKEN=\n")

    init_tenant("agent-edgar", repo_root=repo_root, provider="anthropic")

    tenant_dir = repo_root / "tenants" / "agent-edgar"
    assert (tenant_dir / "tenant.toml").exists()
    assert (tenant_dir / ".env").exists()
    cfg = tomllib.loads((tenant_dir / "tenant.toml").read_text())
    assert cfg["zeroclaw_provider"] == "anthropic"


def test_init_refuses_to_overwrite(tmp_path):
    repo_root = tmp_path
    template_dir = repo_root / "tenants" / "_template"
    template_dir.mkdir(parents=True)
    (template_dir / "tenant.toml.example").write_text("a = 1\n")
    (template_dir / ".env.example").write_text("\n")
    init_tenant("agent-edgar", repo_root=repo_root, provider="anthropic")
    with pytest.raises(FileExistsError):
        init_tenant("agent-edgar", repo_root=repo_root, provider="anthropic")

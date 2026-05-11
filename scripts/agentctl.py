"""agentctl - multi-tenant IaC CLI for ZeroClaw deployments."""

from pathlib import Path
import re

SLUG_RE = re.compile(r"^agent-[a-z0-9]([a-z0-9-]{0,27}[a-z0-9])?$")


class SlugError(ValueError):
    """Raised when a tenant slug fails validation."""


def validate_slug(slug: str) -> None:
    if "--" in slug:
        raise SlugError(f"invalid slug (double dash): {slug!r}")
    if not SLUG_RE.match(slug):
        raise SlugError(f"invalid slug {slug!r}: must match {SLUG_RE.pattern}")


def init_tenant(slug: str, *, repo_root: Path, provider: str) -> Path:
    """Scaffold tenants/<slug>/{tenant.toml, .env} from the templates."""
    validate_slug(slug)
    if provider not in ("anthropic", "litellm"):
        raise ValueError(f"provider must be anthropic or litellm, got {provider!r}")

    tenant_dir = repo_root / "tenants" / slug
    if tenant_dir.exists():
        raise FileExistsError(f"{tenant_dir} already exists")

    template_dir = repo_root / "tenants" / "_template"
    tenant_toml = (template_dir / "tenant.toml.example").read_text()
    env_file = (template_dir / ".env.example").read_text()

    tenant_dir.mkdir(parents=True)
    (tenant_dir / "tenant.toml").write_text(
        tenant_toml.replace("{{provider}}", provider)
    )
    (tenant_dir / ".env").write_text(env_file)
    (tenant_dir / ".env").chmod(0o600)
    return tenant_dir

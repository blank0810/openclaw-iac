"""agentctl - multi-tenant IaC CLI for ZeroClaw deployments."""

import re

SLUG_RE = re.compile(r"^agent-[a-z0-9]([a-z0-9-]{0,27}[a-z0-9])?$")


class SlugError(ValueError):
    """Raised when a tenant slug fails validation."""


def validate_slug(slug: str) -> None:
    if "--" in slug:
        raise SlugError(f"invalid slug (double dash): {slug!r}")
    if not SLUG_RE.match(slug):
        raise SlugError(f"invalid slug {slug!r}: must match {SLUG_RE.pattern}")
